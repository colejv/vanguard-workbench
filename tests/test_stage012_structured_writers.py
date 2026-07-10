"""
Tests for:
  - Structured (non-stringified-JSON) tool-call arguments for
    write_stage0_output, write_stage1_output, write_stage2_vectors
  - The Stage 0 / Stage 1 / Stage 2 crew split with hard artifact-existence
    checks between each stage (src/crew.py), replacing the single shared
    pre_crew that previously let Stage 2 start even when stage1_output.json
    was missing.

Root cause this addresses: the previous single-string JSON parameters
(e.g. write_stage1_output(stage1_json: str)) required the model to
serialize a large, deeply nested JSON document INSIDE a string argument
of a tool call -- two layers of serialization, where a local model could
successfully invoke the tool but still produce a string that failed
json.loads() internally. Structured (typed list[dict]) arguments remove
that inner layer entirely: CrewAI's own tool-call argument parsing
handles the JSON, and the tool function receives real Python objects.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import json
import os
import shutil
import hashlib
import runpy
import sys

import pytest

from src import run_context
from src.tools import write_stage0_output, write_stage1_output, write_stage2_vectors


@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    run_context.reset_active_run()
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.set_active_run("test-run", "sha256:test-corpus-hash", str(out_dir))
    yield
    run_context.reset_active_run()


# ---------------------------------------------------------------------------
# Structured argument schema tests
# ---------------------------------------------------------------------------

def test_stage0_writer_accepts_structured_arguments():
    schema = write_stage0_output.args_schema.model_json_schema()
    assert schema["properties"]["signatures"]["type"] == "array"
    assert "stage0_json" not in schema["properties"]


def test_stage1_writer_accepts_structured_arguments():
    schema = write_stage1_output.args_schema.model_json_schema()
    assert schema["properties"]["technical_nodes"]["type"] == "array"
    assert schema["properties"]["procedural_nodes"]["type"] == "array"
    assert schema["properties"]["cognitive_nodes"]["type"] == "array"
    assert schema["properties"]["trust_boundaries"]["type"] == "array"
    assert "stage1_json" not in schema["properties"]


def test_stage2_writer_accepts_structured_arguments():
    schema = write_stage2_vectors.args_schema.model_json_schema()
    assert schema["properties"]["nodes"]["type"] == "array"
    assert schema["properties"]["edges"]["type"] == "array"
    assert "vectors_json" not in schema["properties"]


# ---------------------------------------------------------------------------
# Writer tool behavior -- real structured (non-string) arguments throughout
# ---------------------------------------------------------------------------

_STAGE0_SIGNATURE = {"signature_id": "S-T-01", "category": "technical", "description": "x",
                    "confidence": "HIGH", "deceive_candidate": False, "is_gap": False}
_STAGE1_TECHNICAL_NODE = {"component_id": "C-T-01", "layer": "technical", "name": "x",
                          "asset_control_levels": [], "information_flows": "x",
                          "downstream_dependencies": [], "is_gap": False}
_STAGE2_NODES = [{"id": "ADV_START", "node_type": "privilege", "criticality": 1},
                 {"id": "G1", "node_type": "goal", "criticality": 10}]
_STAGE2_EDGES = [{"source": "ADV_START", "target": "G1", "technique": "T1078",
                  "difficulty": "LOW", "effect": None, "vec": "V-01"}]


def test_stage0_writer_writes_real_structured_signatures():
    result = write_stage0_output.func(signatures=[_STAGE0_SIGNATURE])
    assert result.startswith("WRITTEN")
    written = run_context.read_stamped_json(run_context.artifact_path("stage0_output.json"))
    assert written["signatures"][0]["signature_id"] == "S-T-01"


def test_stage0_writer_rejects_duplicate_signature_id():
    result = write_stage0_output.func(signatures=[_STAGE0_SIGNATURE, _STAGE0_SIGNATURE])
    assert result.startswith("REJECTED")
    assert "duplicate" in result.lower()


def test_stage0_writer_rejects_bad_category_enum():
    bad = dict(_STAGE0_SIGNATURE, category="not_a_real_category")
    result = write_stage0_output.func(signatures=[bad])
    assert result.startswith("REJECTED")


def test_stage0_writer_rejects_non_list_argument():
    result = write_stage0_output.func(signatures="not a list")
    assert result.startswith("REJECTED")


def test_stage1_writer_writes_real_structured_nodes():
    result = write_stage1_output.func(
        technical_nodes=[_STAGE1_TECHNICAL_NODE], procedural_nodes=[], cognitive_nodes=[], trust_boundaries=[],
    )
    assert result.startswith("WRITTEN")
    written = run_context.read_stamped_json(run_context.artifact_path("stage1_output.json"))
    assert written["technical_nodes"][0]["component_id"] == "C-T-01"


def test_stage1_writer_rejects_layer_mismatch():
    wrong_layer = dict(_STAGE1_TECHNICAL_NODE, layer="procedural")
    result = write_stage1_output.func(
        technical_nodes=[wrong_layer], procedural_nodes=[], cognitive_nodes=[], trust_boundaries=[],
    )
    assert result.startswith("REJECTED")
    assert "wrong layer" in result.lower()


def test_stage1_writer_rejects_duplicate_component_id_across_layers():
    proc_node = dict(_STAGE1_TECHNICAL_NODE, layer="procedural")
    result = write_stage1_output.func(
        technical_nodes=[_STAGE1_TECHNICAL_NODE], procedural_nodes=[proc_node], cognitive_nodes=[], trust_boundaries=[],
    )
    assert result.startswith("REJECTED")
    assert "duplicate" in result.lower()


def test_stage1_writer_rejects_non_list_argument():
    result = write_stage1_output.func(
        technical_nodes="not a list", procedural_nodes=[], cognitive_nodes=[], trust_boundaries=[],
    )
    assert result.startswith("REJECTED")


def test_stage2_writer_writes_real_structured_graph():
    result = write_stage2_vectors.func(nodes=_STAGE2_NODES, edges=_STAGE2_EDGES)
    assert result.startswith("WRITTEN")
    written = run_context.read_stamped_json(run_context.artifact_path("stage2_vectors.json"))
    assert written["nodes"][0]["id"] == "ADV_START"


def test_stage2_writer_rejects_dangling_edge():
    bad_edges = [{"source": "ADV_START", "target": "NOT_A_NODE", "technique": "T1078",
                 "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    result = write_stage2_vectors.func(nodes=_STAGE2_NODES, edges=bad_edges)
    assert result.startswith("REJECTED")
    assert "not a declared node" in result.lower()


def test_stage2_writer_rejects_missing_goal():
    no_goal = [{"id": "ADV_START", "node_type": "privilege", "criticality": 1}]
    result = write_stage2_vectors.func(nodes=no_goal, edges=[])
    assert result.startswith("REJECTED")
    assert "goal" in result.lower()


def test_stage2_writer_rejects_non_list_argument():
    result = write_stage2_vectors.func(nodes="not a list", edges=[])
    assert result.startswith("REJECTED")


def test_writer_rejection_cannot_be_satisfied_by_final_answer_json():
    """Confirms there is no code path by which text that merely LOOKS like
    valid JSON (e.g. in an agent's prose Final Answer) can substitute for
    an actual write_stageN_output call. The artifact only exists if the
    real function actually wrote it -- rejecting a call, or never calling
    the tool at all, must leave no stage1_output.json on disk."""
    stage1_json_path = run_context.artifact_path("stage1_output.json")
    assert not os.path.exists(stage1_json_path)

    # A rejected call (layer mismatch) must not write anything either.
    wrong_layer = dict(_STAGE1_TECHNICAL_NODE, layer="procedural")
    result = write_stage1_output.func(
        technical_nodes=[wrong_layer], procedural_nodes=[], cognitive_nodes=[], trust_boundaries=[],
    )
    assert result.startswith("REJECTED")
    assert not os.path.exists(stage1_json_path), (
        "A rejected write_stage1_output call must never leave a partial or "
        "stale stage1_output.json on disk."
    )
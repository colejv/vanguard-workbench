"""
Tests for write_stage0_output / write_stage1_output in src/tools.py.

Run with: pytest tests/test_tools_stage01.py -v
Calls the tools directly via ._run() — no LLM, no CrewAI kickoff, no
pipeline. Each test initializes an isolated run_context so writes follow
the same run-scoped, stamped artifact path the real pipeline uses —
write_stage0_output/write_stage1_output no longer hardcode "outputs/...";
they resolve through run_context.artifact_path() and fail closed with
RuntimeError if no active run has been set, same as every other run-scoped
tool. tmp_path + monkeypatch still keep everything off the real outputs/
directory.

Both tools now take REAL STRUCTURED arguments (e.g. signatures=[...] as
an actual list) rather than a single JSON-string parameter
(stage0_json="..."). This removes the double-serialization layer that
caused a real failure: a local model could successfully invoke the tool
but still produce a malformed nested JSON string, since the outer
tool-call JSON and the inner document JSON had to both be generated
correctly. With structured arguments, CrewAI's own tool-call argument
parsing handles the JSON -- there is no second document to construct or
escape, and the function receives real Python lists/dicts directly.
"""

import json
from pathlib import Path

import pytest

from src import run_context
from src.tools import write_stage0_output, write_stage1_output


@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Give every test its own run-scoped output directory.

    Production tools must never fall back to a shared outputs/ directory,
    so tests initialize the same active-run context that crew.py does.
    """
    monkeypatch.chdir(tmp_path)

    out_dir = tmp_path / "outputs" / "test-run"

    run_context.reset_active_run()
    run_context.set_active_run(
        run_id="test-run",
        corpus_manifest_hash="test-corpus-hash",
        out_dir=str(out_dir),
    )

    yield out_dir

    run_context.reset_active_run()


def _artifact(filename: str) -> Path:
    return Path(run_context.artifact_path(filename))


# ---------- write_stage0_output: valid paths ----------

def test_write_stage0_output_valid_writes_file():
    signatures = [
        {"signature_id": "S-T-01", "category": "technical",
         "description": "Legacy TLS 1.1 endpoint on C2 relay",
         "confidence": "HIGH", "deceive_candidate": False},
    ]
    result = write_stage0_output._run(signatures=signatures)
    stage0_path = _artifact("stage0_output.json")

    assert result.startswith(f"WRITTEN: {stage0_path}")
    assert "1 signature(s)" in result
    assert stage0_path.exists()

    envelope = json.loads(stage0_path.read_text(encoding="utf-8"))
    assert envelope["_meta"]["run_id"] == "test-run"
    assert envelope["_meta"]["corpus_manifest_hash"] == "test-corpus-hash"
    assert len(envelope["data"]["signatures"]) == 1


def test_write_stage0_output_reports_gap_count():
    signatures = [
        {"signature_id": "S-T-01", "category": "technical", "description": "a",
         "confidence": "HIGH", "deceive_candidate": False, "is_gap": False},
        {"signature_id": "S-P-01", "category": "procedural", "description": "[GAP] b",
         "confidence": "LOW", "deceive_candidate": False, "is_gap": True},
    ]
    result = write_stage0_output._run(signatures=signatures)
    assert "1 flagged [GAP]" in result


def test_write_stage0_output_empty_signatures_still_writes():
    result = write_stage0_output._run(signatures=[])
    assert result.startswith("WRITTEN:")
    assert "0 signature(s)" in result


def test_write_stage0_output_rejects_more_than_max_signatures():
    """Defense-in-depth against oversized single-tool-call JSON — this is
    NOT the primary fix for truncated generation (that's task-prompt
    curation), it's a backstop against an agent ignoring that guidance."""
    signatures = [
        {"signature_id": f"S-T-{i:02d}", "category": "technical", "description": f"item {i}",
         "confidence": "LOW", "deceive_candidate": False}
        for i in range(26)  # one over the 25-signature ceiling
    ]
    result = write_stage0_output._run(signatures=signatures)
    assert result.startswith("REJECTED:")
    assert "exceeds the 25 ceiling" in result
    assert not _artifact("stage0_output.json").exists()


def test_write_stage0_output_accepts_exactly_max_signatures():
    """Boundary check: exactly at the ceiling should still succeed."""
    signatures = [
        {"signature_id": f"S-T-{i:02d}", "category": "technical", "description": f"item {i}",
         "confidence": "LOW", "deceive_candidate": False}
        for i in range(25)
    ]
    result = write_stage0_output._run(signatures=signatures)
    assert result.startswith("WRITTEN:")


# ---------- write_stage0_output: rejection paths ----------

def test_write_stage0_output_rejects_non_list_signatures():
    """The old 'malformed JSON string' rejection test no longer applies —
    there is no inner JSON document to parse anymore. The equivalent
    structural-shape check now is: 'signatures' must actually be a list."""
    result = write_stage0_output._run(signatures="not a list")
    assert result.startswith("REJECTED:")
    assert not _artifact("stage0_output.json").exists()


def test_write_stage0_output_rejects_bad_category():
    signatures = [
        {"signature_id": "S-X-01", "category": "financial", "description": "x",
         "confidence": "HIGH", "deceive_candidate": False},
    ]
    result = write_stage0_output._run(signatures=signatures)
    assert result.startswith("REJECTED:")
    assert not _artifact("stage0_output.json").exists()


def test_write_stage0_output_rejects_bad_confidence():
    signatures = [
        {"signature_id": "S-X-01", "category": "technical", "description": "x",
         "confidence": "SORT_OF", "deceive_candidate": False},
    ]
    result = write_stage0_output._run(signatures=signatures)
    assert result.startswith("REJECTED:")


def test_write_stage0_output_rejects_duplicate_signature_id():
    signatures = [
        {"signature_id": "S-T-01", "category": "technical", "description": "a",
         "confidence": "HIGH", "deceive_candidate": False},
        {"signature_id": "S-T-01", "category": "procedural", "description": "b",
         "confidence": "LOW", "deceive_candidate": False},
    ]
    result = write_stage0_output._run(signatures=signatures)
    assert result.startswith("REJECTED:")
    assert "duplicate signature_id" in result
    assert not _artifact("stage0_output.json").exists()


def test_write_stage0_output_rejects_missing_required_field():
    """category present but description missing entirely."""
    signatures = [
        {"signature_id": "S-T-01", "category": "technical",
         "confidence": "HIGH", "deceive_candidate": False},
    ]
    result = write_stage0_output._run(signatures=signatures)
    assert result.startswith("REJECTED:")


def test_write_stage0_output_requires_active_run():
    """Nobody should be able to 'fix' a future failure here by
    reintroducing a fallback to a shared, unscoped outputs/ directory --
    the tool must refuse outright with no active run set."""
    run_context.reset_active_run()
    signatures = [
        {"signature_id": "S-T-01", "category": "technical", "description": "x",
         "confidence": "HIGH", "deceive_candidate": False},
    ]
    with pytest.raises(RuntimeError, match="No active run set"):
        write_stage0_output._run(signatures=signatures)


# ---------- write_stage1_output: valid paths ----------

def _valid_stage1_payload(cog=True):
    return {
        "technical_nodes": [{"component_id": "C-T-01", "layer": "technical", "name": "C2 Relay",
            "asset_control_levels": ["No Access", "API Reach"], "information_flows": "telemetry -> track",
            "downstream_dependencies": []}],
        "procedural_nodes": [{"component_id": "C-P-01", "layer": "procedural", "name": "Patch cycle",
            "asset_control_levels": ["No Access"], "information_flows": "CVE -> queue",
            "downstream_dependencies": []}],
        "cognitive_nodes": [{"component_id": "C-C-01", "hierarchy_stage": "Understanding",
            "feeds": "sensor picture", "corrupts": "false injection", "downstream_effect": "wrong decision",
            "detection_probability": "LOW", "is_center_of_gravity": cog}],
        "trust_boundaries": [{"boundary_id": "TB-01", "from_component": "C-T-01", "to_component": "C-C-01",
            "description": "no re-validation"}],
    }


def test_write_stage1_output_valid_writes_file():
    result = write_stage1_output._run(**_valid_stage1_payload())
    stage1_path = _artifact("stage1_output.json")

    assert result.startswith(f"WRITTEN: {stage1_path}")
    assert "Cognitive-layer candidate touchpoint: C-C-01" in result
    assert stage1_path.exists()

    envelope = json.loads(stage1_path.read_text(encoding="utf-8"))
    assert envelope["_meta"]["run_id"] == "test-run"
    assert envelope["_meta"]["corpus_manifest_hash"] == "test-corpus-hash"
    assert len(envelope["data"]["technical_nodes"]) == 1


def test_write_stage1_output_no_cognitive_nodes_is_valid_with_no_cog():
    """An assessment with zero cognitive nodes writes cleanly — no COG
    flag is ever required, whether cognitive_nodes is empty or just
    unflagged (see the doctrinal tests below)."""
    payload = _valid_stage1_payload()
    payload["cognitive_nodes"] = []
    result = write_stage1_output._run(**payload)
    assert result.startswith("WRITTEN:")
    assert "none flagged" in result


def test_write_stage1_output_rejects_more_than_max_total_nodes():
    """Defense-in-depth against oversized single-tool-call JSON — same
    rationale as the Stage 0 signature ceiling: this backstops an agent
    that ignores the task's curation guidance, it isn't the primary fix
    for truncated generation."""
    payload = {
        "technical_nodes": [
            {"component_id": f"C-T-{i:02d}", "layer": "technical", "name": f"node {i}",
             "asset_control_levels": [], "information_flows": "x", "downstream_dependencies": []}
            for i in range(41)  # one over the 40-node ceiling, all in one layer
        ],
        "procedural_nodes": [],
        "cognitive_nodes": [],
        "trust_boundaries": [],
    }
    result = write_stage1_output._run(**payload)
    assert result.startswith("REJECTED:")
    assert "exceeds the 40 ceiling" in result
    assert not _artifact("stage1_output.json").exists()


def test_write_stage1_output_accepts_exactly_max_total_nodes():
    """Boundary check: exactly at the ceiling, spread across layers, should succeed."""
    payload = {
        "technical_nodes": [
            {"component_id": f"C-T-{i:02d}", "layer": "technical", "name": f"node {i}",
             "asset_control_levels": [], "information_flows": "x", "downstream_dependencies": []}
            for i in range(20)
        ],
        "procedural_nodes": [
            {"component_id": f"C-P-{i:02d}", "layer": "procedural", "name": f"node {i}",
             "asset_control_levels": [], "information_flows": "x", "downstream_dependencies": []}
            for i in range(20)
        ],
        "cognitive_nodes": [],
        "trust_boundaries": [],
    }
    result = write_stage1_output._run(**payload)
    assert result.startswith("WRITTEN:")


# ---------- write_stage1_output: rejection paths ----------

def test_write_stage1_output_rejects_non_list_technical_nodes():
    """The old 'malformed JSON string' rejection test no longer applies —
    there is no inner JSON document to parse anymore. The equivalent
    structural-shape check now is: each of the four arguments must
    actually be a list."""
    payload = _valid_stage1_payload()
    payload["technical_nodes"] = "not a list"
    result = write_stage1_output._run(**payload)
    assert result.startswith("REJECTED:")


def test_write_stage1_output_zero_cognitive_touchpoints_flagged_still_writes():
    """Doctrinally correct: COG (JP 5-0/ADP 3-0) is domain-agnostic, and the
    real, operational COG is computed graph-theoretically in Annex B — it
    may be a Technical-layer chokepoint (e.g. Lockheed Lightning's
    CDL_WRITE: min-cut=1, ~5.5x betweenness) rather than anything in the
    cognitive layer. Zero flagged cognitive touchpoints must NOT be rejected."""
    payload = _valid_stage1_payload(cog=False)
    result = write_stage1_output._run(**payload)
    assert result.startswith("WRITTEN:")
    assert "none flagged" in result


def test_write_stage1_output_multiple_cognitive_touchpoints_flagged_still_writes():
    """Multiple flagged candidates are advisory, not an error — the tool
    reports them but never rejects on count."""
    payload = _valid_stage1_payload(cog=True)
    payload["cognitive_nodes"].append({
        "component_id": "C-C-02", "hierarchy_stage": "Decision",
        "feeds": "x", "corrupts": "x", "downstream_effect": "x",
        "detection_probability": "MEDIUM", "is_center_of_gravity": True,
    })
    result = write_stage1_output._run(**payload)
    assert result.startswith("WRITTEN:")
    assert "multiple flagged" in result
    assert "C-C-01" in result and "C-C-02" in result


def test_write_stage1_output_rejects_technical_node_with_wrong_layer():
    payload = _valid_stage1_payload()
    payload["technical_nodes"][0]["layer"] = "procedural"
    result = write_stage1_output._run(**payload)
    assert result.startswith("REJECTED:")
    assert "wrong layer list" in result
    assert not _artifact("stage1_output.json").exists()


def test_write_stage1_output_rejects_procedural_node_with_wrong_layer():
    payload = _valid_stage1_payload()
    payload["procedural_nodes"][0]["layer"] = "technical"
    result = write_stage1_output._run(**payload)
    assert result.startswith("REJECTED:")
    assert "wrong layer list" in result


def test_write_stage1_output_rejects_duplicate_component_id_across_layers():
    payload = _valid_stage1_payload()
    payload["procedural_nodes"][0]["component_id"] = "C-T-01"  # collides with technical
    result = write_stage1_output._run(**payload)
    assert result.startswith("REJECTED:")
    assert "duplicate component_id" in result
    assert not _artifact("stage1_output.json").exists()


def test_write_stage1_output_rejects_bad_hierarchy_stage():
    payload = _valid_stage1_payload()
    payload["cognitive_nodes"][0]["hierarchy_stage"] = "Vibes"
    result = write_stage1_output._run(**payload)
    assert result.startswith("REJECTED:")


def test_write_stage1_output_missing_trust_boundaries_argument_raises():
    """Under the old single-JSON-string contract, an omitted key was a
    'REJECTED:' string return from this function's own validation. Under
    the new structured-argument contract, trust_boundaries is a required
    parameter of the tool itself -- omitting it is now a hard TypeError
    raised by Python's own call mechanics, before this function's body
    ever runs. Same underlying intent (a malformed/incomplete call must
    never silently succeed), different, earlier failure point."""
    payload = _valid_stage1_payload()
    del payload["trust_boundaries"]
    with pytest.raises(TypeError):
        write_stage1_output._run(**payload)
    assert not _artifact("stage1_output.json").exists()


def test_write_stage1_output_requires_active_run():
    """Same fail-closed contract as Stage 0 -- added for symmetry, not
    explicitly requested, since the exact same bug shape applies equally
    to write_stage1_output and there's no reason to leave it uncovered."""
    run_context.reset_active_run()
    with pytest.raises(RuntimeError, match="No active run set"):
        write_stage1_output._run(**_valid_stage1_payload())
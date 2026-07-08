"""
Tests for write_stage0_output / write_stage1_output in src/tools.py.

Run with: pytest tests/test_tools_stage01.py -v
Calls the tools directly via ._run() — no LLM, no CrewAI kickoff, no
pipeline. Uses tmp_path + monkeypatch to redirect the hardcoded
"outputs/" writes so tests never touch the real outputs/ directory.
"""

import json
import os

import pytest

from src.tools import write_stage0_output, write_stage1_output


@pytest.fixture(autouse=True)
def _isolate_outputs_dir(tmp_path, monkeypatch):
    """write_stage0_output / write_stage1_output hardcode 'outputs/...',
    matching write_stage2_vectors' existing convention. Chdir into a temp
    dir per test so nothing here ever touches the real outputs/ folder."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


# ---------- write_stage0_output: valid paths ----------

def test_write_stage0_output_valid_writes_file():
    payload = {"signatures": [
        {"signature_id": "S-T-01", "category": "technical",
         "description": "Legacy TLS 1.1 endpoint on C2 relay",
         "confidence": "HIGH", "deceive_candidate": False},
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert result.startswith("WRITTEN: outputs/stage0_output.json")
    assert "1 signature(s)" in result
    assert os.path.exists("outputs/stage0_output.json")


def test_write_stage0_output_reports_gap_count():
    payload = {"signatures": [
        {"signature_id": "S-T-01", "category": "technical", "description": "a",
         "confidence": "HIGH", "deceive_candidate": False, "is_gap": False},
        {"signature_id": "S-P-01", "category": "procedural", "description": "[GAP] b",
         "confidence": "LOW", "deceive_candidate": False, "is_gap": True},
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert "1 flagged [GAP]" in result


def test_write_stage0_output_empty_signatures_still_writes():
    result = write_stage0_output._run(stage0_json=json.dumps({"signatures": []}))
    assert result.startswith("WRITTEN:")
    assert "0 signature(s)" in result


def test_write_stage0_output_rejects_more_than_max_signatures():
    """Defense-in-depth against oversized single-tool-call JSON — this is
    NOT the primary fix for truncated generation (that's task-prompt
    curation), it's a backstop against an agent ignoring that guidance."""
    payload = {"signatures": [
        {"signature_id": f"S-T-{i:02d}", "category": "technical", "description": f"item {i}",
         "confidence": "LOW", "deceive_candidate": False}
        for i in range(26)  # one over the 25-signature ceiling
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
    assert "exceeds the 25 ceiling" in result
    assert not os.path.exists("outputs/stage0_output.json")


def test_write_stage0_output_accepts_exactly_max_signatures():
    """Boundary check: exactly at the ceiling should still succeed."""
    payload = {"signatures": [
        {"signature_id": f"S-T-{i:02d}", "category": "technical", "description": f"item {i}",
         "confidence": "LOW", "deceive_candidate": False}
        for i in range(25)
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert result.startswith("WRITTEN:")


# ---------- write_stage0_output: rejection paths ----------

def test_write_stage0_output_rejects_invalid_json():
    result = write_stage0_output._run(stage0_json="{not json")
    assert result.startswith("REJECTED:")
    assert not os.path.exists("outputs/stage0_output.json")


def test_write_stage0_output_rejects_bad_category():
    payload = {"signatures": [
        {"signature_id": "S-X-01", "category": "financial", "description": "x",
         "confidence": "HIGH", "deceive_candidate": False},
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
    assert not os.path.exists("outputs/stage0_output.json")


def test_write_stage0_output_rejects_bad_confidence():
    payload = {"signatures": [
        {"signature_id": "S-X-01", "category": "technical", "description": "x",
         "confidence": "SORT_OF", "deceive_candidate": False},
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert result.startswith("REJECTED:")


def test_write_stage0_output_rejects_duplicate_signature_id():
    payload = {"signatures": [
        {"signature_id": "S-T-01", "category": "technical", "description": "a",
         "confidence": "HIGH", "deceive_candidate": False},
        {"signature_id": "S-T-01", "category": "procedural", "description": "b",
         "confidence": "LOW", "deceive_candidate": False},
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
    assert "duplicate signature_id" in result
    assert not os.path.exists("outputs/stage0_output.json")


def test_write_stage0_output_rejects_missing_required_field():
    """category present but description missing entirely."""
    payload = {"signatures": [
        {"signature_id": "S-T-01", "category": "technical",
         "confidence": "HIGH", "deceive_candidate": False},
    ]}
    result = write_stage0_output._run(stage0_json=json.dumps(payload))
    assert result.startswith("REJECTED:")


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
    result = write_stage1_output._run(stage1_json=json.dumps(_valid_stage1_payload()))
    assert result.startswith("WRITTEN: outputs/stage1_output.json")
    assert "Cognitive-layer candidate touchpoint: C-C-01" in result
    assert os.path.exists("outputs/stage1_output.json")


def test_write_stage1_output_no_cognitive_nodes_is_valid_with_no_cog():
    """An assessment with zero cognitive nodes writes cleanly — no COG
    flag is ever required, whether cognitive_nodes is empty or just
    unflagged (see the doctrinal tests below)."""
    payload = _valid_stage1_payload()
    payload["cognitive_nodes"] = []
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
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
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
    assert "exceeds the 40 ceiling" in result
    assert not os.path.exists("outputs/stage1_output.json")


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
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("WRITTEN:")


# ---------- write_stage1_output: rejection paths ----------

def test_write_stage1_output_rejects_invalid_json():
    result = write_stage1_output._run(stage1_json="{not json")
    assert result.startswith("REJECTED:")


def test_write_stage1_output_zero_cognitive_touchpoints_flagged_still_writes():
    """Doctrinally correct: COG (JP 5-0/ADP 3-0) is domain-agnostic, and the
    real, operational COG is computed graph-theoretically in Annex B — it
    may be a Technical-layer chokepoint (e.g. Lockheed Lightning's
    CDL_WRITE: min-cut=1, ~5.5x betweenness) rather than anything in the
    cognitive layer. Zero flagged cognitive touchpoints must NOT be rejected."""
    payload = _valid_stage1_payload(cog=False)
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
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
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("WRITTEN:")
    assert "multiple flagged" in result
    assert "C-C-01" in result and "C-C-02" in result


def test_write_stage1_output_rejects_technical_node_with_wrong_layer():
    payload = _valid_stage1_payload()
    payload["technical_nodes"][0]["layer"] = "procedural"
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
    assert "wrong layer list" in result
    assert not os.path.exists("outputs/stage1_output.json")


def test_write_stage1_output_rejects_procedural_node_with_wrong_layer():
    payload = _valid_stage1_payload()
    payload["procedural_nodes"][0]["layer"] = "technical"
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
    assert "wrong layer list" in result


def test_write_stage1_output_rejects_duplicate_component_id_across_layers():
    payload = _valid_stage1_payload()
    payload["procedural_nodes"][0]["component_id"] = "C-T-01"  # collides with technical
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
    assert "duplicate component_id" in result
    assert not os.path.exists("outputs/stage1_output.json")


def test_write_stage1_output_rejects_bad_hierarchy_stage():
    payload = _valid_stage1_payload()
    payload["cognitive_nodes"][0]["hierarchy_stage"] = "Vibes"
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("REJECTED:")


def test_write_stage1_output_rejects_missing_trust_boundaries_key():
    payload = _valid_stage1_payload()
    del payload["trust_boundaries"]
    result = write_stage1_output._run(stage1_json=json.dumps(payload))
    assert result.startswith("REJECTED:")
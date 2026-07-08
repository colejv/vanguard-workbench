"""
Verifies the state-management sequence now embedded in crew.py's __main__
block, WITHOUT running CrewAI or any LLM. This replicates, step for step,
the exact calls crew.py makes around pre_crew.kickoff() / verify_stage2_vectors
/ post_crew.kickoff(), using fake artifacts written directly to a temp
outputs/ dir instead of real agent output.

This cannot prove crew.py itself is wired correctly (that requires a real
run) — it proves the state.py call sequence crew.py uses, in the order
crew.py uses it, behaves correctly end to end.

Run with: pytest tests/test_crew_state_integration.py -v
"""

import json
import os

import pytest

from src.schemas import StageStatus
from src.state import (
    new_run_id,
    run_output_dir,
    init_assessment_state,
    save_assessment_state,
    load_assessment_state,
    commit_stage_output,
    set_stage_status,
)


def _write(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def test_full_run_sequence_stage2_pass(tmp_path, monkeypatch):
    """Mirrors crew.py's happy path: Stage 0/1 artifacts present, Stage 2
    vectors present and valid, Stage 3 artifact present at the end."""
    monkeypatch.chdir(tmp_path)

    run_id = new_run_id()
    corpus_manifest_hash = "sha256:fakecorpus123"
    state = init_assessment_state(run_id, corpus_manifest_hash)
    save_assessment_state(state, run_id)

    # --- simulate pre_crew.kickoff() having produced artifacts ---
    _write("outputs/stage0_output.json", json.dumps({"signatures": []}))
    _write("outputs/stage1_output.json", json.dumps({
        "technical_nodes": [], "procedural_nodes": [],
        "cognitive_nodes": [], "trust_boundaries": [],
    }))
    _write("outputs/stage2_vectors.json", json.dumps({
        "nodes": [{"id": "ADV_START", "node_type": "privilege", "criticality": 1},
                  {"id": "G_TEST", "node_type": "goal", "criticality": 10}],
        "edges": [{"source": "ADV_START", "target": "G_TEST", "technique": "T1000",
                    "difficulty": "LOW", "effect": None, "vec": "V-01"}],
    }))

    # --- commit stage0/stage1 exactly as crew.py does ---
    for stage_name, artifact_path in (
        ("stage0", "outputs/stage0_output.json"),
        ("stage1", "outputs/stage1_output.json"),
    ):
        if os.path.exists(artifact_path):
            commit_stage_output(state, stage_name, artifact_path, status=StageStatus.PENDING)
    state.current_stage = "stage2"
    save_assessment_state(state, run_id)

    # --- simulate verify_stage2_vectors() returning PASS ---
    fake_verification = {"is_valid": True, "status": "PASS", "summary": "PASS — all edges verified."}
    if os.path.exists("outputs/stage2_vectors.json"):
        commit_stage_output(state, "stage2", "outputs/stage2_vectors.json", status=StageStatus.PENDING)
    set_stage_status(state, "stage2", StageStatus.PASS if fake_verification["is_valid"] else StageStatus.FAIL)
    save_assessment_state(state, run_id)

    assert fake_verification["is_valid"] is True  # gate would NOT raise here

    # --- simulate post_crew.kickoff() having produced Stage 3 ---
    _write("outputs/stage3.md", "# Stage 3 payload set\n...")
    if os.path.exists("outputs/stage3.md"):
        commit_stage_output(state, "stage3", "outputs/stage3.md", status=StageStatus.PENDING)
    state.current_stage = "complete"
    save_assessment_state(state, run_id)

    # --- verify the final on-disk assessment_state.json ---
    reloaded = load_assessment_state(run_id)
    assert reloaded.run_id == run_id
    assert reloaded.corpus_manifest_hash == corpus_manifest_hash
    assert reloaded.current_stage == "complete"
    assert reloaded.stages["stage0"].status == StageStatus.PENDING
    assert reloaded.stages["stage1"].status == StageStatus.PENDING
    assert reloaded.stages["stage2"].status == StageStatus.PASS
    assert reloaded.stages["stage3"].status == StageStatus.PENDING
    assert reloaded.stages["stage0"].output_hash is not None
    assert reloaded.stages["stage2"].output_hash is not None


def test_full_run_sequence_stage2_fail_halts_before_post_crew(tmp_path, monkeypatch):
    """Mirrors crew.py's failure path: verify_stage2_vectors returns FAIL,
    state records FAIL, and (per crew.py's logic) the RuntimeError would
    fire before post_crew ever runs — so no stage3 commit should occur."""
    monkeypatch.chdir(tmp_path)

    run_id = new_run_id()
    state = init_assessment_state(run_id, "sha256:fakecorpus123")
    save_assessment_state(state, run_id)

    _write("outputs/stage2_vectors.json", json.dumps({
        "nodes": [{"id": "ADV_START", "node_type": "privilege", "criticality": 1}],
        "edges": [{"source": "ADV_START", "target": "MISSING", "technique": "[GAP]",
                    "difficulty": "LOW", "effect": None, "vec": "V-01"}],
    }))

    fake_verification = {"is_valid": False, "status": "FAIL",
                          "summary": "FAIL — 1 edge checked, 0 invalid, 1 gap edge."}

    if os.path.exists("outputs/stage2_vectors.json"):
        commit_stage_output(state, "stage2", "outputs/stage2_vectors.json", status=StageStatus.PENDING)
    set_stage_status(state, "stage2", StageStatus.PASS if fake_verification["is_valid"] else StageStatus.FAIL)
    save_assessment_state(state, run_id)

    reloaded = load_assessment_state(run_id)
    assert reloaded.stages["stage2"].status == StageStatus.FAIL

    # crew.py's actual code raises RuntimeError here and never reaches
    # post_crew.kickoff() or the stage3 commit block — simulate that by
    # simply asserting the gate condition matches what would trigger it.
    assert fake_verification["is_valid"] is False
    with pytest.raises(RuntimeError):
        if not fake_verification["is_valid"]:
            raise RuntimeError(f"Stage 2 verification FAILED: {fake_verification['summary']}")

    # stage3 must NOT have been committed
    assert reloaded.stages["stage3"].status == StageStatus.NOT_STARTED
    assert not os.path.exists("outputs/stage3.md")


def test_missing_stage0_artifact_leaves_it_not_started(tmp_path, monkeypatch):
    """If the Stage 0 agent never calls write_stage0_output, crew.py's
    warning path should leave that stage NOT_STARTED rather than crash."""
    monkeypatch.chdir(tmp_path)

    run_id = new_run_id()
    state = init_assessment_state(run_id, "sha256:fakecorpus123")
    save_assessment_state(state, run_id)

    # stage0_output.json deliberately NOT written
    for stage_name, artifact_path in (
        ("stage0", "outputs/stage0_output.json"),
        ("stage1", "outputs/stage1_output.json"),
    ):
        if os.path.exists(artifact_path):
            commit_stage_output(state, stage_name, artifact_path, status=StageStatus.PENDING)
    save_assessment_state(state, run_id)

    reloaded = load_assessment_state(run_id)
    assert reloaded.stages["stage0"].status == StageStatus.NOT_STARTED
    assert reloaded.stages["stage0"].output_path is None


def test_run_output_dir_created_for_assessment_state(tmp_path, monkeypatch):
    """Confirms the run-scoped directory actually gets created, matching
    crew.py's os.makedirs(out_dir, exist_ok=True) call."""
    monkeypatch.chdir(tmp_path)
    run_id = new_run_id()
    out_dir = run_output_dir(run_id)
    os.makedirs(out_dir, exist_ok=True)
    assert os.path.isdir(out_dir)

    state = init_assessment_state(run_id, "sha256:x")
    path = save_assessment_state(state, run_id)
    assert path == os.path.join(out_dir, "assessment_state.json")
    assert os.path.exists(path)
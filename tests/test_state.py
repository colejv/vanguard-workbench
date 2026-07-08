"""
Standalone tests for src/state.py.

Run with: pytest tests/test_state.py -v
Uses pytest's tmp_path fixture for real (but isolated) file I/O.
No pipeline, no crew, no LLM calls.
"""

from datetime import datetime, timezone

import pytest

from src.schemas import StageStatus
from src.state import (
    new_run_id,
    run_output_dir,
    hash_file,
    init_assessment_state,
    save_assessment_state,
    load_assessment_state,
    commit_stage_output,
    set_stage_status,
    append_gap,
)


# ---------- new_run_id ----------

def test_new_run_id_format():
    fixed = datetime(2026, 7, 2, 14, 30, 12, tzinfo=timezone.utc)
    assert new_run_id(fixed) == "vaf_20260702_143012"


def test_new_run_id_uses_real_time_by_default():
    rid = new_run_id()
    assert rid.startswith("vaf_")
    assert len(rid) == len("vaf_YYYYMMDD_HHMMSS")


# ---------- run_output_dir ----------

def test_run_output_dir_scopes_under_run_id():
    assert run_output_dir("vaf_20260702_143012") == "outputs/vaf_20260702_143012"
    assert run_output_dir("vaf_x", base="custom") == "custom/vaf_x"


# ---------- hash_file ----------

def test_hash_file_is_stable_and_prefixed(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello vanguard")
    h1 = hash_file(str(f))
    h2 = hash_file(str(f))
    assert h1 == h2
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64


def test_hash_file_changes_with_content(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("version 1")
    h1 = hash_file(str(f))
    f.write_text("version 2")
    h2 = hash_file(str(f))
    assert h1 != h2


# ---------- init / save / load round trip ----------

def test_init_assessment_state_basic():
    state = init_assessment_state("vaf_20260702_143012", "sha256:corpusabc")
    assert state.run_id == "vaf_20260702_143012"
    assert state.corpus_manifest_hash == "sha256:corpusabc"
    assert all(s.status == StageStatus.NOT_STARTED for s in state.stages.values())


def test_save_creates_scoped_directory_and_file(tmp_path):
    state = init_assessment_state("vaf_test_run", "sha256:corpusabc")
    path = save_assessment_state(state, "vaf_test_run", base=str(tmp_path))
    assert path == str(tmp_path / "vaf_test_run" / "assessment_state.json")
    assert (tmp_path / "vaf_test_run" / "assessment_state.json").exists()


def test_save_then_load_round_trips(tmp_path):
    state = init_assessment_state("vaf_test_run", "sha256:corpusabc")
    state = append_gap(state, "stage1", "unclear failover path", "decomposer", node_id="N-021")
    save_assessment_state(state, "vaf_test_run", base=str(tmp_path))

    reloaded = load_assessment_state("vaf_test_run", base=str(tmp_path))
    assert reloaded.run_id == "vaf_test_run"
    assert len(reloaded.gap_log) == 1
    assert reloaded.gap_log[0].node_id == "N-021"


def test_save_bumps_updated_at(tmp_path):
    state = init_assessment_state("vaf_test_run", "sha256:corpusabc")
    original_updated = state.updated_at
    save_assessment_state(state, "vaf_test_run", base=str(tmp_path))
    assert state.updated_at >= original_updated  # ISO8601 strings sort chronologically


def test_load_raises_if_no_prior_save(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_assessment_state("never_saved", base=str(tmp_path))


# ---------- commit_stage_output ----------

def test_commit_stage_output_hashes_and_stamps(tmp_path):
    artifact = tmp_path / "stage0.json"
    artifact.write_text('{"scope": "test SUT"}')

    state = init_assessment_state("vaf_test_run", "sha256:corpusabc")
    state = commit_stage_output(state, "stage0", str(artifact))

    rec = state.stages["stage0"]
    assert rec.status == StageStatus.PENDING  # default — gate promotes later
    assert rec.output_path == str(artifact)
    assert rec.output_hash.startswith("sha256:")
    assert rec.committed_at is not None


def test_commit_stage_output_rejects_unknown_stage(tmp_path):
    artifact = tmp_path / "x.json"
    artifact.write_text("{}")
    state = init_assessment_state("r", "sha256:c")
    with pytest.raises(ValueError):
        commit_stage_output(state, "stage99", str(artifact))


def test_commit_stage_output_requires_file_to_exist(tmp_path):
    state = init_assessment_state("r", "sha256:c")
    with pytest.raises(FileNotFoundError):
        commit_stage_output(state, "stage0", str(tmp_path / "does_not_exist.json"))


def test_commit_stage_output_accepts_explicit_status(tmp_path):
    artifact = tmp_path / "stage2_vectors.json"
    artifact.write_text('{"nodes": [], "edges": []}')
    state = init_assessment_state("r", "sha256:c")
    state = commit_stage_output(state, "stage2", str(artifact), status=StageStatus.PASS, gap_count=0)
    assert state.stages["stage2"].status == StageStatus.PASS


# ---------- set_stage_status ----------

def test_set_stage_status_promotes_after_gate(tmp_path):
    artifact = tmp_path / "stage2_vectors.json"
    artifact.write_text('{"nodes": [], "edges": []}')
    state = init_assessment_state("r", "sha256:c")
    state = commit_stage_output(state, "stage2", str(artifact))  # PENDING
    assert state.stages["stage2"].status == StageStatus.PENDING

    state = set_stage_status(state, "stage2", StageStatus.PASS)
    assert state.stages["stage2"].status == StageStatus.PASS


def test_set_stage_status_rejects_unknown_stage():
    state = init_assessment_state("r", "sha256:c")
    with pytest.raises(ValueError):
        set_stage_status(state, "stage99", StageStatus.FAIL)


# ---------- append_gap ----------

def test_append_gap_adds_to_log_and_increments_stage_count():
    state = init_assessment_state("r", "sha256:c")
    state = append_gap(state, "stage1", "ambiguous data flow", "mapper", node_id="N-014")
    assert len(state.gap_log) == 1
    assert state.stages["stage1"].gap_count == 1


def test_append_gap_multiple_increments_correctly():
    state = init_assessment_state("r", "sha256:c")
    state = append_gap(state, "stage1", "gap a", "mapper")
    state = append_gap(state, "stage1", "gap b", "decomposer")
    state = append_gap(state, "stage2", "gap c", "modeler")
    assert state.stages["stage1"].gap_count == 2
    assert state.stages["stage2"].gap_count == 1
    assert len(state.gap_log) == 3


# ---------- end-to-end without any pipeline ----------

def test_full_lifecycle_simulated_without_pipeline(tmp_path):
    """Exercises the exact sequence crew.py will call, using fake artifacts
    instead of a real LLM run — proves the state layer works in total
    isolation from CrewAI."""
    run_id = new_run_id(datetime(2026, 7, 2, 14, 30, 12, tzinfo=timezone.utc))
    base = str(tmp_path)

    state = init_assessment_state(run_id, "sha256:corpusabc")

    stage0_file = tmp_path / "stage0.json"
    stage0_file.write_text('{"scope": "SUT framing"}')
    state = commit_stage_output(state, "stage0", str(stage0_file), status=StageStatus.PASS)

    stage1_file = tmp_path / "stage1.json"
    stage1_file.write_text('{"nodes": ["N-001", "N-002"]}')
    state = commit_stage_output(state, "stage1", str(stage1_file), status=StageStatus.PENDING)
    state = append_gap(state, "stage1", "unconfirmed redundancy path", "decomposer", node_id="N-002")
    state = set_stage_status(state, "stage1", StageStatus.PASS)

    state.current_stage = "stage2"
    save_assessment_state(state, run_id, base=base)

    reloaded = load_assessment_state(run_id, base=base)
    assert reloaded.stages["stage0"].status == StageStatus.PASS
    assert reloaded.stages["stage1"].status == StageStatus.PASS
    assert reloaded.stages["stage1"].gap_count == 1
    assert reloaded.stages["stage2"].status == StageStatus.NOT_STARTED
    assert reloaded.all_stages_passed("stage1") is True
    assert len(reloaded.unresolved_gaps()) == 1
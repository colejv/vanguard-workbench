"""
Stage 4 assessment-state tests.

Covers Commit 1 (Stage 4 state tracking) plus the corrective patch that
followed real-code review:

  - test_assessment_state_contains_stage4
  - test_commit_stage4_output
  - test_stage4_can_transition_pending_to_pass
  - test_stage4_can_transition_pending_to_fail
  - test_run_not_complete_when_stage4_fails
  - test_all_stages_passed_through_stage4
  - test_missing_stage4_artifact_cannot_pass          (new)
  - test_finalized_hash_matches_final_file_content     (new)

test_run_not_complete_when_stage4_fails previously reproduced the intended
state-machine transition locally with a hand-written `is_compliant`
branch, rather than calling the actual production code. That's exactly
why it didn't catch two real bugs that shipped in crew.py: a hash
committed before a corpus-version footer was appended afterward (so the
recorded hash didn't match the final file), and a missing mission-plan
artifact that could still be marked PASS if the safety check happened to
return compliant against empty text. Both tests below now call
finalize_stage4_state() directly -- the same function crew.py calls -- so
a regression in the production code path fails these tests, not just a
simulation of it.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import hashlib
import os

import pytest

from src.schemas import AssessmentState, StageStatus, STAGE_NAMES
from src.state import (
    init_assessment_state,
    commit_stage_output,
    set_stage_status,
    finalize_stage4_state,
    run_output_dir,
)


@pytest.fixture
def fake_artifact(tmp_path):
    """A real file on disk for commit_stage_output to hash -- it requires
    the artifact to actually exist, same as it does in the real pipeline."""
    p = tmp_path / "stage4_mission_plan.md"
    p.write_text("# STAGE 4: MDMP MISSION PLAN\n\nPhase 1: ...\n")
    return str(p)


@pytest.fixture
def run_base(tmp_path):
    """Isolated outputs/ base directory per test, so save_assessment_state
    calls inside finalize_stage4_state don't collide across tests or touch
    a real outputs/ directory."""
    base = tmp_path / "outputs_base"
    base.mkdir()
    return str(base)


def test_assessment_state_contains_stage4():
    """STAGE_NAMES includes stage4, and a fresh AssessmentState pre-populates
    it as NOT_STARTED via the same default_factory used for every other
    stage -- no special-casing required."""
    assert "stage4" in STAGE_NAMES
    state = init_assessment_state("test_run", "sha256:testhash")
    assert "stage4" in state.stages
    assert state.stages["stage4"].status == StageStatus.NOT_STARTED
    assert state.stages["stage4"].output_path is None
    assert state.stages["stage4"].output_hash is None


def test_commit_stage4_output(fake_artifact):
    """commit_stage_output against 'stage4' hashes and records the real
    artifact, same contract as every other stage -- no ValueError from the
    STAGE_NAMES guard now that stage4 is a recognized name."""
    state = init_assessment_state("test_run", "sha256:testhash")
    commit_stage_output(state, "stage4", fake_artifact, status=StageStatus.PENDING)

    record = state.stages["stage4"]
    assert record.status == StageStatus.PENDING
    assert record.output_path == fake_artifact
    assert record.output_hash is not None
    assert record.output_hash.startswith("sha256:")
    assert record.committed_at is not None


def test_stage4_can_transition_pending_to_pass(fake_artifact):
    state = init_assessment_state("test_run", "sha256:testhash")
    commit_stage_output(state, "stage4", fake_artifact, status=StageStatus.PENDING)
    assert state.stages["stage4"].status == StageStatus.PENDING

    set_stage_status(state, "stage4", StageStatus.PASS)
    assert state.stages["stage4"].status == StageStatus.PASS
    assert state.stages["stage4"].output_path == fake_artifact
    assert state.stages["stage4"].output_hash is not None


def test_stage4_can_transition_pending_to_fail(fake_artifact):
    state = init_assessment_state("test_run", "sha256:testhash")
    commit_stage_output(state, "stage4", fake_artifact, status=StageStatus.PENDING)

    set_stage_status(state, "stage4", StageStatus.FAIL)
    assert state.stages["stage4"].status == StageStatus.FAIL
    assert state.stages["stage4"].output_path == fake_artifact
    assert state.stages["stage4"].output_hash is not None


def test_run_not_complete_when_stage4_fails(fake_artifact, run_base):
    """Calls the REAL finalize_stage4_state() -- the same function crew.py
    calls -- for both the failure and success branches, rather than
    reproducing the transition logic locally. A non-compliant result must
    raise, leave stage4=FAIL, and current_stage must land on 'stage4' (not
    'stage2', and never 'complete') so a rejected run is never
    indistinguishable from one that stalled two stages earlier."""
    state = init_assessment_state("test_run", "sha256:testhash")
    state.current_stage = "stage2"  # simulates wherever pre_crew last left it

    with pytest.raises(RuntimeError, match="Phase 0 Safety Gate"):
        finalize_stage4_state(
            state, "test_run",
            stage4_path=fake_artifact,
            is_compliant=False,
            safety_summary="COMPLIANCE GAP: simulated failure",
            base=run_base,
        )

    assert state.stages["stage4"].status == StageStatus.FAIL
    assert state.current_stage == "stage4"
    assert state.current_stage != "complete"

    # ---- Success path, same real function, opposite branch ----
    state2 = init_assessment_state("test_run_2", "sha256:testhash")
    state2.current_stage = "stage2"

    finalize_stage4_state(
        state2, "test_run_2",
        stage4_path=fake_artifact,
        is_compliant=True,
        safety_summary="",
        base=run_base,
    )
    assert state2.stages["stage4"].status == StageStatus.PASS
    assert state2.current_stage == "complete"


def test_missing_stage4_artifact_cannot_pass(run_base):
    """The exact bug this patch closes: a missing stage4_mission_plan.md
    must never be marked PASS, regardless of what a safety check computed
    (a check against empty/absent text could trivially return compliant if
    Stage 3 had no Category 2/3 payloads at all). finalize_stage4_state
    must check file existence BEFORE looking at is_compliant at all."""
    state = init_assessment_state("test_run", "sha256:testhash")
    nonexistent_path = os.path.join(run_base, "does_not_exist_stage4.md")
    assert not os.path.exists(nonexistent_path)

    # is_compliant=True on purpose -- proves the missing-file check takes
    # priority over compliance, not just that failing compliance also fails.
    with pytest.raises(RuntimeError, match="did not produce"):
        finalize_stage4_state(
            state, "test_run",
            stage4_path=nonexistent_path,
            is_compliant=True,
            safety_summary="",
            base=run_base,
        )

    assert state.stages["stage4"].status == StageStatus.FAIL
    assert state.stages["stage4"].output_hash is None
    assert state.stages["stage4"].output_path is None
    assert state.current_stage == "stage4"
    assert state.current_stage != "complete"


def test_finalized_hash_matches_final_file_content(tmp_path, run_base):
    """Regression test for the stale-hash bug: if a file is modified AFTER
    finalize_stage4_state commits it, the stored hash and the actual file
    diverge -- so the caller contract is that stage4_path must already
    contain its FINAL content before this function is ever called. This
    test proves finalize_stage4_state itself is trustworthy (hashes
    exactly what's on disk at call time); crew.py's own responsibility to
    call it only after all file modifications is enforced by the ordering
    fix in crew.py, not by this function, and is covered by the
    integration-level check performed against the real pipeline this
    session (recomputing SHA-256 from the actual final file and comparing
    to assessment_state.json's stored hash)."""
    p = tmp_path / "stage4_mission_plan.md"
    p.write_text("# STAGE 4\n\nPhase 1: ...\n\n---\n*Analysis grounded in Corpus Version v1 (3 files)*")
    final_content_hash = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()

    state = init_assessment_state("test_run", "sha256:testhash")
    finalize_stage4_state(
        state, "test_run",
        stage4_path=str(p),
        is_compliant=True,
        safety_summary="",
        base=run_base,
    )

    assert state.stages["stage4"].output_hash == final_content_hash


def test_all_stages_passed_through_stage4(fake_artifact):
    """AssessmentState.all_stages_passed('stage4') requires every stage
    from stage0 through stage4 to be PASS -- confirms the existing method
    works correctly through the newly-added final stage without any
    changes to its own implementation."""
    state = init_assessment_state("test_run", "sha256:testhash")

    for name in ("stage0", "stage1", "stage2", "stage3"):
        state.stages[name].status = StageStatus.PASS
    assert state.all_stages_passed("stage4") is False

    commit_stage_output(state, "stage4", fake_artifact, status=StageStatus.PENDING)
    set_stage_status(state, "stage4", StageStatus.PASS)
    assert state.all_stages_passed("stage4") is True

    state.stages["stage2"].status = StageStatus.FAIL
    assert state.all_stages_passed("stage4") is False
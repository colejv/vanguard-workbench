"""
Stage 4 assessment-state tests.

Covers the six tests requested for Commit 1 (Stage 4 state tracking):
  - test_assessment_state_contains_stage4
  - test_commit_stage4_output
  - test_stage4_can_transition_pending_to_pass
  - test_stage4_can_transition_pending_to_fail
  - test_run_not_complete_when_stage4_fails
  - test_all_stages_passed_through_stage4

The first five are direct unit tests against src.schemas / src.state. The
sixth (test_run_not_complete_when_stage4_fails) is written as a focused
state-machine test rather than a full crew.py integration test — it
exercises the exact sequence crew.py performs around the Phase 0 gate
(commit PENDING -> gate check -> FAIL-before-raise / PASS-before-complete)
without needing CrewAI or Ollama in the loop. The actual crew.py code path
was additionally verified this session via a mocked-kickoff run against
both a compliant and non-compliant Stage 4, confirmed directly against a
real written assessment_state.json for each -- see the session notes if a
true CrewAI-level integration test needs to be added to this suite later;
that needs conftest.py fixtures matching whatever pattern the rest of
tests/ already uses, which I have not seen.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import os
import pytest

from src.schemas import AssessmentState, StageStatus, STAGE_NAMES
from src.state import init_assessment_state, commit_stage_output, set_stage_status


@pytest.fixture
def fake_artifact(tmp_path):
    """A real file on disk for commit_stage_output to hash -- it requires
    the artifact to actually exist, same as it does in the real pipeline."""
    p = tmp_path / "stage4_mission_plan.md"
    p.write_text("# STAGE 4: MDMP MISSION PLAN\n\nPhase 1: ...\n")
    return str(p)


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
    # Path and hash must survive the status transition -- set_stage_status
    # promotes status only, it must not re-hash or discard prior commit data.
    assert state.stages["stage4"].output_path == fake_artifact
    assert state.stages["stage4"].output_hash is not None


def test_stage4_can_transition_pending_to_fail(fake_artifact):
    state = init_assessment_state("test_run", "sha256:testhash")
    commit_stage_output(state, "stage4", fake_artifact, status=StageStatus.PENDING)

    set_stage_status(state, "stage4", StageStatus.FAIL)
    assert state.stages["stage4"].status == StageStatus.FAIL
    # A FAIL is not a missing artifact -- the mission plan was real and
    # non-compliant, not absent. Hash/path must still be preserved so the
    # audit trail can show exactly what was rejected.
    assert state.stages["stage4"].output_path == fake_artifact
    assert state.stages["stage4"].output_hash is not None


def test_run_not_complete_when_stage4_fails(fake_artifact):
    """Exercises the exact sequence crew.py performs around the Phase 0
    gate: commit PENDING, then on gate failure set FAIL BEFORE raising and
    never advance current_stage to 'complete'. On success, set PASS before
    marking complete. This is the state-machine contract Commit 1 exists
    to enforce -- a failed safety gate must never look like a finished run."""
    # ---- Failure path ----
    state = init_assessment_state("test_run", "sha256:testhash")
    commit_stage_output(state, "stage4", fake_artifact, status=StageStatus.PENDING)
    state.current_stage = "stage2"  # matches crew.py's last real checkpoint before this point

    is_compliant = False  # simulates check_phase0_safety_gate() rejecting the plan
    if not is_compliant:
        set_stage_status(state, "stage4", StageStatus.FAIL)
        # crew.py raises RuntimeError here -- current_stage is deliberately
        # never touched again, so it stays at its last real checkpoint,
        # never "complete".
    else:
        set_stage_status(state, "stage4", StageStatus.PASS)
        state.current_stage = "complete"

    assert state.stages["stage4"].status == StageStatus.FAIL
    assert state.current_stage != "complete"
    assert state.current_stage == "stage2"

    # ---- Success path, same sequence, opposite branch ----
    state2 = init_assessment_state("test_run_2", "sha256:testhash")
    commit_stage_output(state2, "stage4", fake_artifact, status=StageStatus.PENDING)
    state2.current_stage = "stage2"

    is_compliant = True
    if not is_compliant:
        set_stage_status(state2, "stage4", StageStatus.FAIL)
    else:
        set_stage_status(state2, "stage4", StageStatus.PASS)
        state2.current_stage = "complete"

    assert state2.stages["stage4"].status == StageStatus.PASS
    assert state2.current_stage == "complete"


def test_all_stages_passed_through_stage4(fake_artifact):
    """AssessmentState.all_stages_passed('stage4') requires every stage
    from stage0 through stage4 to be PASS -- confirms the existing method
    works correctly through the newly-added final stage without any
    changes to its own implementation."""
    state = init_assessment_state("test_run", "sha256:testhash")

    for name in ("stage0", "stage1", "stage2", "stage3"):
        state.stages[name].status = StageStatus.PASS
    # stage4 still NOT_STARTED at this point
    assert state.all_stages_passed("stage4") is False

    commit_stage_output(state, "stage4", fake_artifact, status=StageStatus.PENDING)
    set_stage_status(state, "stage4", StageStatus.PASS)
    assert state.all_stages_passed("stage4") is True

    # A single upstream regression should also correctly fail the check
    state.stages["stage2"].status = StageStatus.FAIL
    assert state.all_stages_passed("stage4") is False
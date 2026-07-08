"""
Standalone tests for src/schemas.py.

Run with: pytest tests/test_schemas.py -v
No pipeline, no crew, no LLM calls — pure model validation.
"""

import pytest
from pydantic import ValidationError

from src.schemas import (
    AssessmentState,
    GapLogEntry,
    StageRecord,
    StageStatus,
    STAGE_NAMES,
)


# ---------- StageRecord ----------

def test_stage_record_defaults_to_not_started():
    rec = StageRecord()
    assert rec.status == StageStatus.NOT_STARTED
    assert rec.output_path is None
    assert rec.gap_count == 0


def test_stage_record_accepts_valid_pass():
    rec = StageRecord(
        status="PASS",
        output_path="outputs/run123/stage1.json",
        output_hash="sha256:abc123",
        committed_at="2026-07-02T14:38:47Z",
        schema_version="1.0",
        gap_count=2,
    )
    assert rec.status == StageStatus.PASS
    assert rec.gap_count == 2


def test_stage_record_rejects_invalid_status():
    with pytest.raises(ValidationError):
        StageRecord(status="MAYBE")


def test_stage_record_rejects_unknown_field():
    """extra='forbid' should catch typos/drift, e.g. 'stauts' instead of 'status'."""
    with pytest.raises(ValidationError):
        StageRecord(stauts="PASS")


# ---------- GapLogEntry ----------

def test_gap_log_entry_minimal():
    gap = GapLogEntry(
        stage="stage1",
        description="No source material on redundancy failover behavior",
        flagged_by="decomposer",
    )
    assert gap.resolved is False
    assert gap.node_id is None
    assert gap.flagged_at  # auto-populated timestamp


def test_gap_log_entry_node_id_optional_for_stage0():
    """Stage 0 gaps precede node inventory, so node_id must be omittable."""
    gap = GapLogEntry(stage="stage0", description="Scope ambiguous", flagged_by="orchestrator")
    assert gap.node_id is None


def test_gap_log_entry_requires_description():
    with pytest.raises(ValidationError):
        GapLogEntry(stage="stage1", flagged_by="mapper")


# ---------- AssessmentState ----------

def test_assessment_state_initializes_all_four_stages_not_started():
    state = AssessmentState(
        run_id="vaf_20260702_143012",
        corpus_manifest_hash="sha256:8f3a2c",
    )
    assert set(state.stages.keys()) == set(STAGE_NAMES)
    assert all(s.status == StageStatus.NOT_STARTED for s in state.stages.values())
    assert state.gap_log == []
    assert state.current_stage == "stage0"


def test_assessment_state_requires_run_id_and_corpus_hash():
    with pytest.raises(ValidationError):
        AssessmentState(corpus_manifest_hash="sha256:8f3a2c")
    with pytest.raises(ValidationError):
        AssessmentState(run_id="vaf_20260702_143012")


def test_assessment_state_round_trips_through_json():
    """This is the actual on-disk contract: write, reload, must be identical."""
    original = AssessmentState(
        run_id="vaf_20260702_143012",
        corpus_manifest_hash="sha256:8f3a2c",
    )
    original.stages["stage0"] = StageRecord(
        status="PASS",
        output_path="outputs/vaf_20260702_143012/stage0.json",
        output_hash="sha256:1a2b3c",
        committed_at="2026-07-02T14:33:02Z",
        schema_version="1.0",
    )
    original.gap_log.append(
        GapLogEntry(stage="stage1", node_id="N-014",
                     description="Data flow unconfirmed", flagged_by="mapper")
    )

    raw = original.model_dump_json()
    reloaded = AssessmentState.model_validate_json(raw)

    assert reloaded == original
    assert reloaded.stages["stage0"].status == StageStatus.PASS
    assert reloaded.gap_log[0].node_id == "N-014"


# ---------- Helper methods ----------

def test_unresolved_gaps_filters_correctly():
    state = AssessmentState(run_id="r1", corpus_manifest_hash="sha256:x")
    state.gap_log = [
        GapLogEntry(stage="stage1", description="a", flagged_by="mapper", resolved=True),
        GapLogEntry(stage="stage1", description="b", flagged_by="mapper", resolved=False),
        GapLogEntry(stage="stage2", description="c", flagged_by="modeler", resolved=False),
    ]
    unresolved = state.unresolved_gaps()
    assert len(unresolved) == 2
    assert all(not g.resolved for g in unresolved)


def test_all_stages_passed_true_when_all_pass_up_to_point():
    state = AssessmentState(run_id="r1", corpus_manifest_hash="sha256:x")
    state.stages["stage0"].status = StageStatus.PASS
    state.stages["stage1"].status = StageStatus.PASS
    assert state.all_stages_passed("stage1") is True


def test_all_stages_passed_false_if_any_stage_short_of_pass():
    state = AssessmentState(run_id="r1", corpus_manifest_hash="sha256:x")
    state.stages["stage0"].status = StageStatus.PASS
    state.stages["stage1"].status = StageStatus.PENDING
    assert state.all_stages_passed("stage1") is False


def test_all_stages_passed_ignores_later_stages():
    """A FAIL in stage3 shouldn't block a check that only asks through stage1."""
    state = AssessmentState(run_id="r1", corpus_manifest_hash="sha256:x")
    state.stages["stage0"].status = StageStatus.PASS
    state.stages["stage1"].status = StageStatus.PASS
    state.stages["stage3"].status = StageStatus.FAIL
    assert state.all_stages_passed("stage1") is True


def test_all_stages_passed_rejects_unknown_stage_name():
    state = AssessmentState(run_id="r1", corpus_manifest_hash="sha256:x")
    with pytest.raises(ValueError):
        state.all_stages_passed("stage99")
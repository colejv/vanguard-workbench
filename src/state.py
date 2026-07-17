"""
Deterministic, side-effect-explicit functions for the run-level assessment
state / audit trail.

Mirrors the style of src/tools.py's verify_stage2_vectors /
write_stage2_vectors: plain functions, explicit file I/O, no hidden global
state, dict/model return values that crew.py can act on directly.

crew.py is the ONLY place that sequences a run. Functions here are called
by crew.py, not by agents/tools — this is orchestration plumbing, not an
agent-facing tool.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

from src.schemas import (
    AssessmentState,
    GapLogEntry,
    StageRecord,
    StageStatus,
    STAGE_NAMES,
)


def new_run_id(now: Optional[datetime] = None) -> str:
    """
    Generate a run_id of the form vaf_<YYYYMMDD>_<HHMMSS> in UTC.

    `now` is injectable for testing; it defaults to the current UTC time.
    """

    timestamp = now or datetime.now(timezone.utc)
    return f"vaf_{timestamp.strftime('%Y%m%d_%H%M%S')}"


def run_output_dir(
    run_id: str,
    base: str = "outputs",
) -> str:
    """Return the run-scoped output directory."""

    return os.path.join(base, run_id)


def hash_file(path: str) -> str:
    """
    Return the SHA-256 hash of a file's bytes.

    The returned value includes the `sha256:` prefix so artifact identities
    are self-describing in assessment_state.json.
    """

    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)

    return f"sha256:{digest.hexdigest()}"


def canonical_json_sha256(value: object) -> str:
    """
    Return the SHA-256 hash of canonical JSON.

    Sorting keys and using compact separators makes the hash independent of
    dictionary insertion order.
    """

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def init_assessment_state(
    run_id: str,
    corpus_manifest_hash: str,
) -> AssessmentState:
    """
    Create a fresh AssessmentState.

    This function does not write to disk. Call save_assessment_state()
    separately.
    """

    return AssessmentState(
        run_id=run_id,
        corpus_manifest_hash=corpus_manifest_hash,
    )


def save_assessment_state(
    state: AssessmentState,
    run_id: str,
    base: str = "outputs",
) -> str:
    """
    Persist assessment_state.json in the run-scoped output directory.

    Returns the path written.
    """

    state.updated_at = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    out_dir = run_output_dir(run_id, base)
    os.makedirs(out_dir, exist_ok=True)

    path = os.path.join(out_dir, "assessment_state.json")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(state.model_dump_json(indent=2))

    return path


def load_assessment_state(
    run_id: str,
    base: str = "outputs",
) -> AssessmentState:
    """Load assessment_state.json for a run."""

    path = os.path.join(
        run_output_dir(run_id, base),
        "assessment_state.json",
    )

    with open(path, encoding="utf-8") as handle:
        return AssessmentState.model_validate_json(handle.read())


def commit_stage_output(
    state: AssessmentState,
    stage: str,
    output_path: str,
    status: StageStatus = StageStatus.PENDING,
    schema_version: str = "1.0",
    gap_count: int = 0,
) -> AssessmentState:
    """
    Register a stage output in the assessment state.

    The output is hashed, its commit timestamp is recorded, and its initial
    status is set. The caller is responsible for subsequently saving the
    assessment state.
    """

    if stage not in STAGE_NAMES:
        raise ValueError(
            f"unknown stage '{stage}' — must be one of {STAGE_NAMES}"
        )

    if not os.path.exists(output_path):
        raise FileNotFoundError(
            f"cannot commit stage '{stage}': "
            f"{output_path} not found"
        )

    state.stages[stage] = StageRecord(
        status=status,
        output_path=output_path,
        output_hash=hash_file(output_path),
        committed_at=datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        schema_version=schema_version,
        gap_count=gap_count,
    )

    return state


def set_stage_status(
    state: AssessmentState,
    stage: str,
    status: StageStatus,
) -> AssessmentState:
    """
    Change a stage's status after a deterministic gate runs.

    This does not rehash or recommit the stage output.
    """

    if stage not in state.stages:
        raise ValueError(f"unknown stage '{stage}'")

    state.stages[stage].status = status
    return state


def reset_stage_for_retry(
    state: AssessmentState,
    stage: str,
    *,
    reason: str,
    quarantine_manifest: str | None = None,
) -> AssessmentState:
    """
    Clear a failed stage's stale artifact identity before retrying it.

    Previous artifacts remain preserved through the quarantine manifest.
    The previous state record is captured in gate_decisions before the
    stage record is replaced.
    """

    if stage not in STAGE_NAMES:
        raise ValueError(
            f"unknown stage '{stage}' — must be one of {STAGE_NAMES}"
        )

    if stage not in state.stages:
        raise ValueError(
            f"stage '{stage}' is not present in assessment state"
        )

    previous_record = state.stages[stage]

    state.gate_decisions.append(
        {
            "decision_type": "STAGE_RETRY",
            "stage": stage,
            "reason": reason,
            "previous_status": previous_record.status.value,
            "previous_output_path": previous_record.output_path,
            "previous_output_hash": previous_record.output_hash,
            "quarantine_manifest": quarantine_manifest,
            "recorded_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
    )

    # Replace the complete record so no rejected path, hash, timestamp,
    # schema version, or gap count can carry into the new attempt.
    state.stages[stage] = StageRecord(
        status=StageStatus.PENDING,
    )
    state.current_stage = stage

    return state


def append_gap(
    state: AssessmentState,
    stage: str,
    description: str,
    flagged_by: str,
    node_id: Optional[str] = None,
) -> AssessmentState:
    """
    Add a gap to the cross-stage gap log.

    Also increments the corresponding stage's gap count when the stage exists.
    """

    entry = GapLogEntry(
        stage=stage,
        node_id=node_id,
        description=description,
        flagged_by=flagged_by,
    )

    state.gap_log.append(entry)

    if stage in state.stages:
        state.stages[stage].gap_count += 1

    return state


def finalize_stage4_state(
    state: AssessmentState,
    run_id: str,
    stage4_path: str,
    is_compliant: bool,
    safety_summary: str = "",
    base: str = "outputs",
) -> AssessmentState:
    """
    Perform the final Stage 4 state transition.

    The Stage 4 artifact must already contain its final immutable content
    before this function is called.
    """

    state.current_stage = "stage4"

    if not os.path.exists(stage4_path):
        set_stage_status(
            state,
            "stage4",
            StageStatus.FAIL,
        )
        save_assessment_state(
            state,
            run_id,
            base,
        )

        raise RuntimeError(
            f"Stage 4 did not produce {stage4_path} — "
            "the run cannot be finalized. "
            "Run audit trail: "
            f"{run_output_dir(run_id, base)}/assessment_state.json"
        )

    commit_stage_output(
        state,
        "stage4",
        stage4_path,
        status=StageStatus.PENDING,
    )
    save_assessment_state(
        state,
        run_id,
        base,
    )

    if not is_compliant:
        set_stage_status(
            state,
            "stage4",
            StageStatus.FAIL,
        )
        save_assessment_state(
            state,
            run_id,
            base,
        )

        raise RuntimeError(
            "Phase 0 Safety Gate compliance FAILED: "
            f"{safety_summary} "
            "Mission plan NOT finalized. "
            "Run audit trail: "
            f"{run_output_dir(run_id, base)}/assessment_state.json"
        )

    set_stage_status(
        state,
        "stage4",
        StageStatus.PASS,
    )
    state.current_stage = "complete"

    save_assessment_state(
        state,
        run_id,
        base,
    )

    return state


def enforce_stage3_safety_gate(
    state: AssessmentState,
    run_id: str,
    is_compliant: bool,
    summary: str,
    base: str = "outputs",
) -> AssessmentState:
    """
    Apply the Stage 3 prose safety-gate state transition.

    The caller computes and persists the gate report before invoking this
    function.
    """

    if not is_compliant:
        set_stage_status(
            state,
            "stage3",
            StageStatus.FAIL,
        )
        state.current_stage = "stage3"

        save_assessment_state(
            state,
            run_id,
            base,
        )

        raise RuntimeError(
            f"Stage 3 safety gate FAILED: {summary} "
            "Stage 4 was not constructed. "
            "Run audit trail: "
            f"{run_output_dir(run_id, base)}/assessment_state.json"
        )

    set_stage_status(
        state,
        "stage3",
        StageStatus.PASS,
    )
    save_assessment_state(
        state,
        run_id,
        base,
    )

    return state


def enforce_stage3_test_plan_validation(
    state: AssessmentState,
    run_id: str,
    *,
    is_valid: bool,
    summary: str,
    base: str = "outputs",
) -> None:
    """
    Apply the structured Stage 3 test-plan validation transition.

    Success does not mark Stage 3 PASS. The subsequent prose safety gate owns
    that transition.
    """

    if is_valid:
        return

    set_stage_status(
        state,
        "stage3",
        StageStatus.FAIL,
    )
    state.current_stage = "stage3"

    save_assessment_state(
        state,
        run_id,
        base,
    )

    raise RuntimeError(
        "Stage 3 structured test-plan validation FAILED: "
        f"{summary} "
        "Stage 4 was not constructed. "
        "Run audit trail: "
        f"{run_output_dir(run_id, base)}/assessment_state.json"
    )


def enforce_stage4_execution_plan_validation(
    state: AssessmentState,
    run_id: str,
    *,
    is_valid: bool,
    summary: str,
    base: str = "outputs",
) -> None:
    """
    Apply the structured Stage 4 execution-plan validation transition.

    Success does not mark Stage 4 PASS. finalize_stage4_state() owns the final
    PASS transition.
    """

    if is_valid:
        return

    set_stage_status(
        state,
        "stage4",
        StageStatus.FAIL,
    )
    state.current_stage = "stage4"

    save_assessment_state(
        state,
        run_id,
        base,
    )

    raise RuntimeError(
        "Stage 4 structured execution-plan validation FAILED: "
        f"{summary} "
        "Run was not finalized. "
        "Run audit trail: "
        f"{run_output_dir(run_id, base)}/assessment_state.json"
    )
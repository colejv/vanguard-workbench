"""
Deterministic, side-effect-explicit functions for the run-level assessment
state / audit trail.

Mirrors the style of src/tools.py's verify_stage2_vectors / write_stage2_vectors:
plain functions, explicit file I/O, no hidden global state, dict/model
return values that crew.py can act on directly.

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

from src.schemas import AssessmentState, GapLogEntry, StageRecord, StageStatus, STAGE_NAMES


def new_run_id(now: Optional[datetime] = None) -> str:
    """
    Generate a run_id of the form vaf_<YYYYMMDD>_<HHMMSS> (UTC).

    `now` is injectable for testing; defaults to the actual current UTC time.
    """
    ts = now or datetime.now(timezone.utc)
    return f"vaf_{ts.strftime('%Y%m%d_%H%M%S')}"


def run_output_dir(run_id: str, base: str = "outputs") -> str:
    """outputs/<run_id> — the scoping root for every artifact this run produces."""
    return os.path.join(base, run_id)


def hash_file(path: str) -> str:
    """sha256:<hex> of a file's bytes. Matches the format used by snapshot_corpus
    in crew.py, minus the 'sha256:' prefix there — we add it here explicitly
    so output_hash is self-describing in the JSON."""
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return f"sha256:{digest}"


def init_assessment_state(run_id: str, corpus_manifest_hash: str) -> AssessmentState:
    """Create a fresh AssessmentState for a new run. Does not write to disk —
    call save_assessment_state() separately, same two-step pattern as
    write_stage2_vectors + verify_stage2_vectors."""
    return AssessmentState(run_id=run_id, corpus_manifest_hash=corpus_manifest_hash)


def save_assessment_state(state: AssessmentState, run_id: str, base: str = "outputs") -> str:
    """Write assessment_state.json to outputs/<run_id>/. Returns the path written.
    Bumps updated_at as part of the save, since this is the one place that
    always precedes a disk write."""
    state.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = run_output_dir(run_id, base)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "assessment_state.json")
    with open(path, "w") as f:
        f.write(state.model_dump_json(indent=2))
    return path


def load_assessment_state(run_id: str, base: str = "outputs") -> AssessmentState:
    """Read assessment_state.json back from outputs/<run_id>/."""
    path = os.path.join(run_output_dir(run_id, base), "assessment_state.json")
    with open(path) as f:
        return AssessmentState.model_validate_json(f.read())


def commit_stage_output(
    state: AssessmentState,
    stage: str,
    output_path: str,
    status: StageStatus = StageStatus.PENDING,
    schema_version: str = "1.0",
    gap_count: int = 0,
) -> AssessmentState:
    """
    Register a stage's output artifact into the assessment state: hashes the
    file at output_path, stamps committed_at, sets status (default PENDING —
    caller/gate promotes to PASS/FAIL after verification).

    Mutates and returns `state`; caller is responsible for calling
    save_assessment_state() afterward. Kept separate so a caller can batch
    multiple commits before one disk write, same pattern as pre_crew.kickoff()
    running multiple tasks before the single verification gate.
    """
    if stage not in STAGE_NAMES:
        raise ValueError(f"unknown stage '{stage}' — must be one of {STAGE_NAMES}")
    if not os.path.exists(output_path):
        raise FileNotFoundError(f"cannot commit stage '{stage}': {output_path} not found")

    state.stages[stage] = StageRecord(
        status=status,
        output_path=output_path,
        output_hash=hash_file(output_path),
        committed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        schema_version=schema_version,
        gap_count=gap_count,
    )
    return state


def set_stage_status(state: AssessmentState, stage: str, status: StageStatus) -> AssessmentState:
    """Promote/demote a stage's status after a deterministic gate runs
    (e.g. verify_stage2_vectors' PASS/FAIL), without re-hashing the file."""
    if stage not in state.stages:
        raise ValueError(f"unknown stage '{stage}'")
    state.stages[stage].status = status
    return state


def append_gap(
    state: AssessmentState,
    stage: str,
    description: str,
    flagged_by: str,
    node_id: Optional[str] = None,
) -> AssessmentState:
    """Add one gap to the flat, cross-stage gap_log. Also increments that
    stage's gap_count on the StageRecord if it already exists."""
    entry = GapLogEntry(stage=stage, node_id=node_id, description=description, flagged_by=flagged_by)
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
    Single production implementation of the Stage 4 finalize transition.
    crew.py and the test suite both call this function directly, rather
    than crew.py doing its own inline sequencing and tests reproducing that
    sequencing separately -- a real bug (a missing mission-plan artifact
    could still be marked PASS) shipped specifically because the original
    test verified a hand-written simulation of this logic, not this logic.

    Caller contract: by the time this is called, stage4_path must already
    be its FINAL, immutable content -- any post-processing (e.g. appending
    a corpus-version footer) must happen before this call, not after, since
    the committed hash is only meaningful if nothing modifies the file
    afterward.

    Sets current_stage='stage4' immediately, before either outcome, so a
    run that reached Stage 4 and was then rejected is never
    indistinguishable in the audit trail from one that stalled two stages
    earlier.

    Fails closed on a missing artifact: refuses to mark stage4 PASS with no
    file, no hash, no mission plan on disk, regardless of what a safety
    check computed against empty text. Raises RuntimeError in both failure
    paths, after persisting the FAIL status -- state is always saved before
    the exception propagates.
    """
    state.current_stage = "stage4"

    if not os.path.exists(stage4_path):
        set_stage_status(state, "stage4", StageStatus.FAIL)
        save_assessment_state(state, run_id, base)
        raise RuntimeError(
            f"Stage 4 did not produce {stage4_path} — the run cannot be "
            f"finalized. Run audit trail: "
            f"{run_output_dir(run_id, base)}/assessment_state.json"
        )

    commit_stage_output(state, "stage4", stage4_path, status=StageStatus.PENDING)
    save_assessment_state(state, run_id, base)

    if not is_compliant:
        set_stage_status(state, "stage4", StageStatus.FAIL)
        save_assessment_state(state, run_id, base)
        raise RuntimeError(
            f"Phase 0 Safety Gate compliance FAILED: {safety_summary} "
            f"Mission plan NOT finalized. Run audit trail: "
            f"{run_output_dir(run_id, base)}/assessment_state.json"
        )

    set_stage_status(state, "stage4", StageStatus.PASS)
    state.current_stage = "complete"
    save_assessment_state(state, run_id, base)
    return state
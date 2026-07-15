"""
Stage 3 semantic-repair orchestration.

A schema-valid, writer-accepted candidate is NOT yet an authoritative
Stage 3 artifact: it must also pass the deep referential/semantic gate
(validate_stage3_test_plan — real graph nodes, KCAG path membership,
technique IDs, complete safety governance). Previously that deep gate ran
once, AFTER the compiler's own retry loop, so a candidate that was
schema-valid but referentially wrong failed with no chance to self-correct.

This module closes that loop:

    compile candidate (schema-valid, writer-accepted)
    -> deep-validate the candidate
    -> if valid: return
    -> else: archive the rejected candidate + its report,
             delete the authoritative candidate path,
             accumulate the exact validator errors as feedback,
             regenerate

It is a PURE workflow module. It operates only on paths, callables, and
plain data. It does NOT import crew.py, task objects, or agents; it does
NOT generate prose, construct Stage 4, own safety-gate policy, or parse
the CLI. Prose generation lives in stage3_writer.py; referential
validation lives in stage3_validation.py; this module only coordinates
them.

Generation-budget note: the low-level compiler's OWN retries are reserved
for malformed/schema-invalid responses (a candidate that never even
becomes writer-accepted). This module's max_semantic_attempts is the
separate budget for schema-valid-but-referentially-wrong candidates, so
the two budgets don't multiply into an uncontrolled N*M.
"""
import os
from collections.abc import Callable
from typing import Any

from src import run_context


# A callable that runs the deep referential validation against the current
# authoritative candidate on disk and returns the validation report dict
# (with at least "is_valid": bool and error detail). Injected by the caller
# so this module never imports the validator directly.
CandidateValidator = Callable[[], dict]

# A callable that (re)generates the authoritative candidate at artifact_path,
# given accumulated semantic feedback. Injected by the caller.
CandidateCompiler = Callable[..., None]


def _format_semantic_feedback(validation_report: dict) -> str:
    """Turn a deep-validation report into a compact, grouped feedback block
    for the next compile attempt. Groups plan-validation (referential/path)
    errors separately from cross-artifact-consistency errors so the model
    sees the two kinds distinctly."""
    lines = []

    plan_v = validation_report.get("plan_validation", {})
    plan_errors = plan_v.get("errors", []) or []
    if plan_errors:
        lines.append("REFERENTIAL / PATH / SAFETY-REVIEW ERRORS:")
        for err in plan_errors:
            if isinstance(err, dict):
                path = err.get("path", "")
                msg = err.get("message", "")
                lines.append(f"- {path}: {msg}" if path else f"- {msg}")
            else:
                lines.append(f"- {err}")

    consistency = validation_report.get("artifact_consistency", {})
    cons_errors = consistency.get("errors", []) or []
    if cons_errors:
        lines.append("CROSS-ARTIFACT CONSISTENCY ERRORS:")
        for err in cons_errors:
            if isinstance(err, dict):
                lines.append(f"- {err.get('message', err)}")
            else:
                lines.append(f"- {err}")

    return "\n".join(lines)


def _archive_rejected(path: str, attempt: int) -> None:
    """Move a rejected authoritative artifact aside for auditability,
    e.g. stage3_test_plan.json -> stage3_test_plan.json.semantic_rejected_1.
    A no-op if the file doesn't exist."""
    if os.path.exists(path):
        os.replace(path, f"{path}.semantic_rejected_{attempt}")


def compile_stage3_until_valid(
    *,
    compile_candidate: CandidateCompiler,
    validate_candidate: CandidateValidator,
    write_validation_report: Callable[[dict], None],
    read_candidate: Callable[[], dict],
    identity_baseline_path: str,
    read_stamped_json: Callable[[str], dict],
    write_stamped_json: Callable[[str, dict], None],
    artifact_path: str,
    validation_report_path: str,
    max_semantic_attempts: int = 3,
) -> dict:
    """Coordinate candidate generation and semantic repair until the deep
    validator passes, or raise after max_semantic_attempts.

    Parameters (all injected — this module owns none of them):
      compile_candidate(external_feedback: str) -> None
          Generates the authoritative candidate at artifact_path. Raises
          RuntimeError if it cannot even produce a schema-valid,
          writer-accepted candidate (its own internal retries exhausted).
      validate_candidate() -> dict
          Runs the deep referential validation against the candidate now on
          disk; returns the report dict (with "is_valid": bool).
      write_validation_report(report: dict) -> None
          Persists the validation report (hash-bound) to
          validation_report_path.
      read_candidate() -> dict
          Reads the candidate plan now on disk (for the semantic-identity
          check). Injected so this module imports no reader directly.
      artifact_path, validation_report_path
          Authoritative candidate + report paths.

    SEMANTIC IDENTITY: the FIRST compiled candidate establishes a signed
    per-concept identity baseline (technique_ids, vectors, targets,
    categories). If a later repaired candidate MUTATES that identity, repair
    stops with a hard SemanticIdentityMutation error — repair may fix
    structure and fill omissions, but may never change what a concept IS to
    close a KCAG path. That is an analytical failure to be surfaced, not a
    retry to be optimized away.

    Returns the passing validation report on success. Raises RuntimeError,
    fail-closed, if no semantic attempt produces a valid candidate — after
    archiving every rejected candidate and removing the invalid candidate
    from the authoritative path so no downstream/resume logic can mistake
    it for a completed artifact.
    """
    from src.stage3_identity import (
        load_or_capture_baseline, assert_identity_preserved,
    )

    feedback = ""
    identity_baseline = None

    for attempt in range(1, max_semantic_attempts + 1):
        print(f"Stage 3 semantic attempt {attempt}/{max_semantic_attempts}...",
              flush=True)

        # 1. (Re)compile the authoritative candidate. The compiler's own
        #    retries handle malformed/schema-invalid responses; this call
        #    returns only once a schema-valid, writer-accepted candidate is
        #    on disk, or raises if it can't get there.
        compile_candidate(external_feedback=feedback)

        candidate_plan = read_candidate()

        # 1b. Signed semantic-identity baseline. The FIRST compiled candidate
        #     sets it and it is PERSISTED, so a resumed run loads the original
        #     baseline instead of re-capturing from an already-repaired
        #     candidate. Every later candidate must preserve it. A mutation
        #     (e.g. a technique swap to force a KCAG path) is a HARD stop, not
        #     a retry — the candidate is archived and the error surfaced.
        if identity_baseline is None:
            identity_baseline = load_or_capture_baseline(
                plan=candidate_plan,
                baseline_path=identity_baseline_path,
                read_stamped_json=read_stamped_json,
                write_stamped_json=write_stamped_json,
            )
            # A persisted baseline from an earlier process must be enforced
            # against this candidate immediately — otherwise a resume whose
            # first candidate is already mutated would slip through.
            try:
                assert_identity_preserved(identity_baseline, candidate_plan)
            except Exception:
                _archive_rejected(validation_report_path, attempt)
                _archive_rejected(artifact_path, attempt)
                raise
        else:
            try:
                assert_identity_preserved(identity_baseline, candidate_plan)
            except Exception:
                _archive_rejected(validation_report_path, attempt)
                _archive_rejected(artifact_path, attempt)
                raise

        # 2. Deep-validate the candidate now on disk.
        report = validate_candidate()
        write_validation_report(report)

        if report.get("is_valid"):
            print(f"Stage 3 semantic validation PASSED on attempt {attempt}.",
                  flush=True)
            return report

        # 3. Rejected: archive candidate + report, delete authoritative
        #    candidate so it can't be mistaken for done, accumulate feedback.
        print(f"Stage 3 semantic validation FAILED on attempt {attempt}; "
              f"archiving candidate and regenerating.", flush=True)
        _archive_rejected(validation_report_path, attempt)
        _archive_rejected(artifact_path, attempt)

        new_feedback = _format_semantic_feedback(report)
        # Accumulate across attempts rather than replacing, so later attempts
        # keep earlier constraints (same lesson as the schema-feedback loop).
        feedback = (feedback + "\n\n" + new_feedback).strip() if feedback else new_feedback

    raise RuntimeError(
        f"Stage 3 semantic validation failed after {max_semantic_attempts} "
        f"attempt(s). The last candidate was archived; no authoritative "
        f"{os.path.basename(artifact_path)} remains. See the archived "
        f"validation reports for the referential errors."
    )


def stage3_is_semantically_complete(
    *,
    artifact_path: str,
    validation_report_path: str,
    current_candidate_hash: str,
) -> bool:
    """Return True only when Stage 3 is genuinely, semantically complete:
    the candidate exists, the validation report exists and reports both
    plan_validation.is_valid and artifact_consistency.is_consistent, AND
    the report's recorded validated_artifact.sha256 matches the CURRENT
    candidate's hash.

    That last condition is the point: a schema-valid candidate with a stale
    PASSING report from a DIFFERENT candidate must NOT count as done — the
    report must correspond to the candidate actually on disk.

    This function only reads; it never mutates. It is used by resume-state
    detection (Fix 6) so an invalid-but-present candidate is recompiled
    rather than accepted.
    """
    if not os.path.exists(artifact_path):
        return False
    if not os.path.exists(validation_report_path):
        return False

    try:
        report = run_context.read_stamped_json(validation_report_path)
    except Exception:
        return False

    plan_v = report.get("plan_validation", {})
    consistency = report.get("artifact_consistency", {})
    if not (plan_v.get("is_valid") and consistency.get("is_consistent")):
        return False

    recorded = report.get("validated_artifact", {}).get("sha256")
    if not recorded:
        # A report without a bound hash predates hash binding — do not
        # trust it to describe the current candidate.
        return False

    return recorded == current_candidate_hash
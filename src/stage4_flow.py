"""
Stage 4 semantic-repair orchestration.

Directly analogous to src/stage3_flow.py, one stage down. A schema-valid,
writer-accepted Stage 4 candidate is NOT yet authoritative: it must also
pass the deep referential/consistency gate (validate_stage4_execution_plan
+ check_stage4_artifact_consistency — Stage 3 test-ID bindings, inherited
criteria, phase/action structure, Phase 0 gate). This module closes the
loop:

    compile candidate (schema-valid, Phase-0-overlaid, writer-accepted)
    -> deep-validate the candidate
    -> if valid: return
    -> else: archive rejected candidate + report,
             delete the authoritative candidate path,
             accumulate the exact validator errors as feedback,
             regenerate

PURE workflow module. Operates only on paths, callables, and plain data.
Imports nothing from crew.py, tasks, or agents. Does not generate prose,
own release policy, or parse the CLI. Prose generation lives in
stage4_writer.py; validation lives in stage4_validation.py; this module
only coordinates them.

Generation-budget note (same as Stage 3): the compiler's OWN retries are
reserved for malformed/schema-invalid responses; max_semantic_attempts is
the separate budget for schema-valid-but-referentially-wrong candidates.
"""
import os
from collections.abc import Callable

from src import run_context


CandidateValidator = Callable[[], dict]
CandidateCompiler = Callable[..., None]


def _format_semantic_feedback(validation_report: dict) -> str:
    """Group Stage 4 deep-validation errors into a compact feedback block:
    plan-validation (referential/binding/structure) errors separately from
    cross-artifact-consistency (prose vs plan) errors."""
    lines = []

    plan_v = validation_report.get("plan_validation", {})
    plan_errors = plan_v.get("errors", []) or []
    if plan_errors:
        lines.append("REFERENTIAL / BINDING / STRUCTURE ERRORS:")
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
    """Move a rejected authoritative artifact aside for auditability. No-op
    if it doesn't exist."""
    if os.path.exists(path):
        os.replace(path, f"{path}.semantic_rejected_{attempt}")


def compile_stage4_until_valid(
    *,
    compile_candidate: CandidateCompiler,
    validate_candidate: CandidateValidator,
    write_validation_report: Callable[[dict], None],
    artifact_path: str,
    validation_report_path: str,
    max_semantic_attempts: int = 3,
) -> dict:
    """Coordinate Stage 4 candidate generation and semantic repair until the
    deep validator passes, or raise (fail-closed) after
    max_semantic_attempts. Returns the passing validation report.

    Parameters mirror compile_stage3_until_valid:
      compile_candidate(external_feedback: str) -> None
      validate_candidate() -> dict   (report with "is_valid": bool)
      write_validation_report(report: dict) -> None

    On exhaustion, every rejected candidate is archived and the invalid
    candidate is removed from the authoritative path, so no downstream or
    resume logic can mistake it for a completed artifact.
    """
    feedback = ""

    for attempt in range(1, max_semantic_attempts + 1):
        print(f"Stage 4 semantic attempt {attempt}/{max_semantic_attempts}...",
              flush=True)

        compile_candidate(external_feedback=feedback)

        report = validate_candidate()
        write_validation_report(report)

        if report.get("is_valid"):
            print(f"Stage 4 semantic validation PASSED on attempt {attempt}.",
                  flush=True)
            return report

        print(f"Stage 4 semantic validation FAILED on attempt {attempt}; "
              f"archiving candidate and regenerating.", flush=True)
        _archive_rejected(validation_report_path, attempt)
        _archive_rejected(artifact_path, attempt)

        new_feedback = _format_semantic_feedback(report)
        feedback = (feedback + "\n\n" + new_feedback).strip() if feedback else new_feedback

    raise RuntimeError(
        f"Stage 4 semantic validation failed after {max_semantic_attempts} "
        f"attempt(s). The last candidate was archived; no authoritative "
        f"{os.path.basename(artifact_path)} remains. See the archived "
        f"validation reports for the referential errors."
    )


def stage4_is_semantically_complete(
    *,
    artifact_path: str,
    validation_report_path: str,
    current_candidate_hash: str,
) -> bool:
    """Return True only when Stage 4 is genuinely, semantically complete:
    candidate exists, report exists and reports both plan_validation.is_valid
    and artifact_consistency.is_consistent, AND the report's recorded
    source_identity.stage4_execution_plan_sha256 matches the CURRENT
    candidate's hash.

    Reads the Stage 4 report's existing source_identity binding (the shape
    crew.py already wrote), so a schema-valid candidate with a stale passing
    report from a DIFFERENT candidate does NOT count as done. Read-only.
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

    recorded = report.get("source_identity", {}).get("stage4_execution_plan_sha256")
    if not recorded:
        return False

    return recorded == current_candidate_hash
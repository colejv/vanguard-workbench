"""Diagnostics for a missing Stage 2 structured artifact."""

from __future__ import annotations

import os

from src import run_context


def describe_missing_stage2_vectors(
    *,
    vectors_path: str,
    writer_status_path: str,
    audit_path: str,
) -> str:
    """Explain why Stage 2 did not produce its structured artifact."""

    base_message = (
        f"Stage 2 did not produce {vectors_path}. "
        "Annex B and downstream cannot proceed without it."
    )

    if not os.path.exists(writer_status_path):
        return (
            f"{base_message} "
            "`write_stage2_vectors` did not leave a writer-status artifact, "
            "so the tool was likely never called. "
            f"Run audit trail: {audit_path}"
        )

    try:
        status_payload = run_context.read_stamped_json(
            writer_status_path
        )
    except Exception as exc:
        return (
            f"{base_message} "
            f"The writer-status artifact exists but could not be trusted: "
            f"{type(exc).__name__}: {exc}. "
            f"Writer diagnostic: {writer_status_path}. "
            f"Run audit trail: {audit_path}"
        )

    status = str(
        status_payload.get("status", "UNKNOWN")
    ).strip().upper()

    if status == "REJECTED":
        raw_errors = status_payload.get("errors", [])
        errors = (
            [str(error) for error in raw_errors]
            if isinstance(raw_errors, list)
            else [str(raw_errors)]
        )

        visible_errors = errors[:5]
        error_summary = "; ".join(visible_errors)

        if len(errors) > len(visible_errors):
            error_summary += (
                f"; plus {len(errors) - len(visible_errors)} more error(s)"
            )

        if not error_summary:
            error_summary = "No validation details were recorded."

        return (
            f"{base_message} "
            "`write_stage2_vectors` was called, but the payload was "
            f"REJECTED: {error_summary}. "
            f"Writer diagnostic: {writer_status_path}. "
            f"Run audit trail: {audit_path}"
        )

    if status == "WRITTEN":
        artifact_path = status_payload.get("artifact_path")

        return (
            f"{base_message} "
            "`write_stage2_vectors` reported WRITTEN, but the expected "
            "artifact is absent. This is an inconsistent writer state. "
            f"Reported artifact: {artifact_path!r}. "
            f"Writer diagnostic: {writer_status_path}. "
            f"Run audit trail: {audit_path}"
        )

    return (
        f"{base_message} "
        "The writer-status artifact contains an unknown status "
        f"{status!r}. "
        f"Writer diagnostic: {writer_status_path}. "
        f"Run audit trail: {audit_path}"
    )
"""
Stage-transition gate: Annex C must gate Stage 3.

The review found the pipeline "failed open" — Annex C correctly issued a
BLOCKING gap (it refused to fabricate missing Bayesian priors), yet the
workflow proceeded into Stage 3 and Stage 4 anyway. The framework requires
the BBN threat score and phase estimate BEFORE Stage 3. This module makes
that transition condition enforceable in the orchestration layer, so a
blocked Annex C stops Stage 3 by default.

Stage 3 may begin only when Annex C is PASS, or when an authorized waiver
is present AND bound to this exact run/input state (run_id, corpus hash,
and the Annex C artifact hash — so a stale waiver cannot silently authorize
progression after Annex C inputs or findings changed).

This module is deterministic and side-effect-free: it decides, it does not
act. crew.py calls it immediately before Stage 3 and acts on the decision
(recording it in assessment_state.json, refusing to invoke the Stage 3
crew/compiler/writer). It imports nothing from crew, tasks, or agents.
"""
import hashlib
import json
from collections.abc import Mapping


class StageTransitionBlocked(Exception):
    """Raised (via require_allowed) when a required transition precondition
    is not satisfied. Distinct from an analytical stage failure."""


# Fields a waiver must carry to be considered at all.
REQUIRED_WAIVER_FIELDS = (
    "waiver_id",
    "decision",
    "approved_by",
    "approved_at",
    "rationale",
    "scope",
    "source_inputs_missing",
    "run_id",
    "corpus_manifest_hash",
    "annex_c_artifact_hash",
)


class TransitionDecision:
    """The result of a transition evaluation. `allowed` plus a machine and
    human readable reason and a compact audit record."""

    def __init__(self, *, allowed: bool, code: str, reason: str, detail: dict):
        self.allowed = allowed
        self.code = code
        self.reason = reason
        self.detail = detail

    def audit_record(self) -> dict:
        return {
            "gate": "annex_c_to_stage3",
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "detail": self.detail,
        }

    def require_allowed(self) -> None:
        """Raise StageTransitionBlocked if the transition is not allowed."""
        if not self.allowed:
            raise StageTransitionBlocked(f"{self.code}\n{self.reason}")


def _canonical_hash(obj) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def annex_c_artifact_hash(annex_c_report) -> str:
    """Canonical content hash of the Annex C report (its data payload).
    Bound into a waiver so a stale waiver can't authorize progression after
    the Annex C inputs/findings change."""
    if isinstance(annex_c_report, Mapping) and "data" in annex_c_report:
        annex_c_report = annex_c_report["data"]
    return _canonical_hash(annex_c_report)


def _annex_c_status(annex_c_report) -> str:
    """Extract the Annex C status. Absent/unreadable report -> BLOCKED."""
    if not isinstance(annex_c_report, Mapping):
        return "BLOCKED"
    data = annex_c_report.get("data", annex_c_report)
    status = (data.get("status") or data.get("annex_c_status") or "").upper()
    if status in ("PASS", "BLOCKED"):
        return status
    # A report that exists but doesn't clearly say PASS is treated as BLOCKED
    # (fail closed), never assumed to pass.
    return "BLOCKED"


def _validate_waiver(waiver, *, run_id: str, corpus_manifest_hash: str,
                     annex_c_hash: str) -> tuple:
    """Return (is_valid, reason). A waiver must be complete, APPROVED, and
    bound to THIS run, corpus, and Annex C artifact hash."""
    if not isinstance(waiver, Mapping):
        return False, "No waiver provided."

    missing = [f for f in REQUIRED_WAIVER_FIELDS if not waiver.get(f)]
    if missing:
        return False, f"Waiver is incomplete; missing required field(s): {missing}."

    if str(waiver.get("decision")).upper() != "APPROVED":
        return False, f"Waiver decision is {waiver.get('decision')!r}, not APPROVED."

    if waiver.get("run_id") != run_id:
        return False, (f"Waiver run_id {waiver.get('run_id')!r} does not match "
                       f"this run {run_id!r}.")

    if waiver.get("corpus_manifest_hash") != corpus_manifest_hash:
        return False, "Waiver corpus_manifest_hash does not match this run's corpus."

    if waiver.get("annex_c_artifact_hash") != annex_c_hash:
        return False, ("Waiver annex_c_artifact_hash does not match the current "
                       "Annex C artifact — the waiver is stale (Annex C inputs or "
                       "findings changed since it was approved).")

    return True, "Waiver is valid and bound to this run/corpus/Annex C artifact."


def evaluate_stage3_transition(
    *,
    annex_c_report,
    waiver,
    run_id: str,
    corpus_manifest_hash: str,
) -> TransitionDecision:
    """Decide whether Stage 3 may begin. Deterministic; no side effects.

    Allowed iff Annex C status is PASS, or a complete APPROVED waiver bound
    to this exact run_id + corpus_manifest_hash + Annex C artifact hash is
    present. Otherwise blocked.
    """
    status = _annex_c_status(annex_c_report)
    annex_c_hash = annex_c_artifact_hash(annex_c_report) if annex_c_report else None

    if status == "PASS":
        return TransitionDecision(
            allowed=True, code="ANNEX_C_PASS",
            reason="Annex C is PASS; Stage 3 may proceed.",
            detail={"annex_c_status": status, "annex_c_artifact_hash": annex_c_hash},
        )

    # Annex C is not PASS (BLOCKED or missing). Only a valid waiver unblocks.
    waiver_valid, waiver_reason = _validate_waiver(
        waiver, run_id=run_id, corpus_manifest_hash=corpus_manifest_hash,
        annex_c_hash=annex_c_hash,
    )
    if waiver_valid:
        return TransitionDecision(
            allowed=True, code="ANNEX_C_WAIVED",
            reason=f"Annex C is {status}, but a valid waiver authorizes Stage 3. "
                   f"{waiver_reason}",
            detail={
                "annex_c_status": status,
                "annex_c_artifact_hash": annex_c_hash,
                "waiver_id": waiver.get("waiver_id"),
                "approved_by": waiver.get("approved_by"),
                "approved_at": waiver.get("approved_at"),
            },
        )

    return TransitionDecision(
        allowed=False, code="STAGE_TRANSITION_BLOCKED",
        reason=(f"Annex C status is {status}. Stage 3 requires Annex C PASS or an "
                f"authorized waiver. {waiver_reason}"),
        detail={
            "annex_c_status": status,
            "annex_c_artifact_hash": annex_c_hash,
            "waiver_rejection_reason": waiver_reason,
        },
    )
"""
Annex C prior-derivation subsystem.

The analyst runs this pipeline BECAUSE deriving the four BBN priors from the
frozen PAI/OSINT corpus IS the analytical work — they never hand-author
annexc_inputs. But the pipeline must never fabricate a prior to proceed.

This module reconciles the two: an LLM proposes each prior WITH cited,
quote-level corpus evidence; a deterministic validator confirms every quote
actually exists in the frozen normalized text and every citation binds to a
real frozen source hash; a per-prior no-evidence policy decides what happens
when support is absent; and a hash-bound analyst approval gate governs
whether the derived configuration may feed scoring.

This module OWNS derivation only. It does not construct a pgmpy model and it
does not alter the Bayesian topology or mathematics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping

from src.bbn_validation import (
    EXPECTED_DEFENSIVE_CONTROLS,
    validate_bbn_assessment_config,
)
from src.state import canonical_json_sha256


FOUR_PRIORS = (
    "capability_prior",
    "tempo",
    "defensive_posture",
    "geopolitical_trigger_prior",
)

ALLOWED_STATUSES = {
    "SUPPORTED",
    "DEFAULTED",
    "BLOCKED",
}
ALLOWED_SOURCE_MODES = {
    "CORPUS",
    "ASSESSMENT_CONFIG",
    "POLICY_DEFAULT",
    "ANALYST_JUDGMENT",
}
ALLOWED_CONFIDENCE = {
    "LOW",
    "MEDIUM",
    "HIGH",
}
ALLOWED_TEMPO = {
    "LOW",
    "MEDIUM",
    "HIGH",
}

REQUIRED_RECORD_FIELDS = (
    "value",
    "status",
    "source_mode",
    "confidence",
    "reasoning",
    "evidence",
)


class DerivationError(Exception):
    """Raised for structural problems in a derivation."""


class DerivationApprovalBlocked(Exception):
    """Raised when the derivation approval gate is not satisfied."""


def _normalize_text(text: str) -> str:
    """Collapse whitespace without semantic transformation."""

    return " ".join((text or "").split())


def quote_is_present(
    quote: str,
    frozen_text: str,
) -> bool:
    """Return whether a normalized quote occurs verbatim in frozen text."""

    normalized_quote = _normalize_text(quote)

    if not normalized_quote:
        return False

    return normalized_quote in _normalize_text(frozen_text)


def load_derivation_policy(
    policy_path: str,
) -> dict:
    """Load and minimally validate the versioned derivation policy."""

    with open(
        policy_path,
        encoding="utf-8",
    ) as handle:
        policy = json.load(handle)

    if (
        "no_evidence" not in policy
        or "policy_version" not in policy
    ):
        raise DerivationError(
            f"Derivation policy at {policy_path} is missing "
            "no_evidence/policy_version."
        )

    return policy


def apply_no_evidence_policy(
    field: str,
    policy: dict,
) -> dict:
    """Build the policy-defined record for a prior with no evidence."""

    no_evidence = policy["no_evidence"]

    if field == "capability_prior":
        return {
            "field": "adversary.capability_prior",
            "value": list(
                no_evidence["capability_prior"]
            ),
            "status": "DEFAULTED",
            "source_mode": "POLICY_DEFAULT",
            "confidence": "LOW",
            "reasoning": (
                "No corpus evidence resolved adversary capability. "
                "A uniform distribution expresses unresolved uncertainty "
                "without equating 'no evidence' with 'low capability'."
            ),
            "evidence": [
                {
                    "source_type": "POLICY_DEFAULT",
                    "source_file": (
                        "config/annexc_derivation_policy.json"
                    ),
                    "policy_version": policy[
                        "policy_version"
                    ],
                }
            ],
        }

    if field == "geopolitical_trigger_prior":
        specification = no_evidence[
            "geopolitical_trigger_prior"
        ]

        return {
            "field": "geopolitical_trigger_prior",
            "value": float(
                specification["value"]
            ),
            "status": "DEFAULTED",
            "source_mode": "POLICY_DEFAULT",
            "confidence": "LOW",
            "reasoning": (
                "No corpus evidence resolved a geopolitical trigger. "
                "Using the explicit analyst-policy base rate, not an "
                "empirical finding."
            ),
            "evidence": [
                {
                    "source_type": "POLICY_DEFAULT",
                    "source_file": (
                        "config/annexc_derivation_policy.json"
                    ),
                    "policy_version": policy[
                        "policy_version"
                    ],
                }
            ],
        }

    field_path = (
        "adversary.tempo"
        if field == "tempo"
        else "defensive_posture"
    )

    return {
        "field": field_path,
        "value": None,
        "status": "BLOCKED",
        "source_mode": "POLICY_DEFAULT",
        "confidence": "LOW",
        "reasoning": (
            f"No evidence resolved {field_path}, and policy forbids "
            "defaulting it: selecting an existing value would turn "
            "absence of information into a substantive assessment. "
            "Requires quote-supported corpus evidence or an explicit "
            "analyst judgment."
        ),
        "evidence": [
            {
                "source_type": "POLICY_DEFAULT",
                "source_file": (
                    "config/annexc_derivation_policy.json"
                ),
                "policy_version": policy[
                    "policy_version"
                ],
            }
        ],
    }


def _validate_record_shape(
    field: str,
    record: dict,
) -> list:
    errors = []

    for required_field in REQUIRED_RECORD_FIELDS:
        if required_field not in record:
            errors.append(
                {
                    "path": (
                        f"{field}.{required_field}"
                    ),
                    "code": "MISSING_RECORD_FIELD",
                    "message": (
                        "Prior record missing required field "
                        f"{required_field!r}."
                    ),
                }
            )

    if record.get("status") not in ALLOWED_STATUSES:
        errors.append(
            {
                "path": f"{field}.status",
                "code": "INVALID_STATUS",
                "message": (
                    "status must be one of "
                    f"{sorted(ALLOWED_STATUSES)}."
                ),
            }
        )

    if (
        record.get("source_mode")
        not in ALLOWED_SOURCE_MODES
    ):
        errors.append(
            {
                "path": f"{field}.source_mode",
                "code": "INVALID_SOURCE_MODE",
                "message": (
                    "source_mode must be one of "
                    f"{sorted(ALLOWED_SOURCE_MODES)}."
                ),
            }
        )

    if (
        record.get("confidence")
        not in ALLOWED_CONFIDENCE
    ):
        errors.append(
            {
                "path": f"{field}.confidence",
                "code": "INVALID_CONFIDENCE",
                "message": (
                    "confidence must be one of "
                    f"{sorted(ALLOWED_CONFIDENCE)}."
                ),
            }
        )

    if not (
        record.get("reasoning")
        or ""
    ).strip():
        errors.append(
            {
                "path": f"{field}.reasoning",
                "code": "MISSING_REASONING",
                "message": (
                    "Concise reasoning is mandatory."
                ),
            }
        )

    return errors


def _validate_corpus_evidence(
    field: str,
    record: dict,
    frozen_sources: Mapping,
) -> list:
    """Validate quote-level corpus evidence deterministically."""

    errors = []
    evidence = record.get("evidence") or []

    corpus_citations = [
        item
        for item in evidence
        if item.get("source_type") == "CORPUS"
    ]

    if not corpus_citations:
        errors.append(
            {
                "path": f"{field}.evidence",
                "code": "NO_CORPUS_CITATION",
                "message": (
                    "A CORPUS-derived value requires at least "
                    "one corpus citation."
                ),
            }
        )
        return errors

    any_verified = False

    for index, citation in enumerate(
        corpus_citations
    ):
        path = f"{field}.evidence[{index}]"
        source_file = citation.get(
            "source_file"
        )
        source_hash = citation.get(
            "source_sha256"
        )
        quote = citation.get("quote")

        if (
            not quote
            or not _normalize_text(quote)
        ):
            errors.append(
                {
                    "path": path,
                    "code": "MISSING_QUOTE",
                    "message": (
                        "Each corpus citation must contain "
                        "a quote."
                    ),
                }
            )
            continue

        if not source_file:
            errors.append(
                {
                    "path": path,
                    "code": "MISSING_SOURCE_FILE",
                    "message": (
                        "Citation must identify the frozen "
                        "source item."
                    ),
                }
            )
            continue

        frozen_source = frozen_sources.get(
            source_file
        )

        if frozen_source is None:
            errors.append(
                {
                    "path": path,
                    "code": "UNKNOWN_SOURCE_FILE",
                    "message": (
                        f"Cited source {source_file!r} is not "
                        "in the frozen corpus."
                    ),
                }
            )
            continue

        if (
            source_hash is not None
            and frozen_source.get("sha256")
            not in (source_hash, None)
        ):
            if (
                frozen_source.get("sha256")
                != source_hash
            ):
                errors.append(
                    {
                        "path": path,
                        "code": (
                            "SOURCE_HASH_MISMATCH"
                        ),
                        "message": (
                            "Citation source_sha256 does not "
                            "match the frozen source hash."
                        ),
                    }
                )
                continue

        if not quote_is_present(
            quote,
            frozen_source.get("text", ""),
        ):
            errors.append(
                {
                    "path": path,
                    "code": "QUOTE_NOT_FOUND",
                    "message": (
                        "Cited quote was not found in the "
                        "frozen normalized source text."
                    ),
                }
            )
            continue

        any_verified = True

    if not any_verified and not errors:
        errors.append(
            {
                "path": f"{field}.evidence",
                "code": "NO_VERIFIED_CITATION",
                "message": (
                    "No citation could be verified against "
                    "the frozen corpus."
                ),
            }
        )

    return errors


def _validate_assessment_config_evidence(
    field: str,
    record: dict,
) -> list:
    """Validate assessment-owned evidence."""

    errors = []
    evidence = record.get("evidence") or []

    assessment_evidence = [
        item
        for item in evidence
        if item.get("source_type")
        == "ASSESSMENT_CONFIG"
    ]

    if not assessment_evidence:
        errors.append(
            {
                "path": f"{field}.evidence",
                "code": (
                    "NO_ASSESSMENT_CONFIG_EVIDENCE"
                ),
                "message": (
                    "An assessment-owned value must cite "
                    "ASSESSMENT_CONFIG evidence."
                ),
            }
        )
        return errors

    for index, item in enumerate(
        assessment_evidence
    ):
        if (
            not item.get("config_field")
            and not item.get("source_file")
        ):
            errors.append(
                {
                    "path": (
                        f"{field}.evidence[{index}]"
                    ),
                    "code": (
                        "UNBOUND_ASSESSMENT_EVIDENCE"
                    ),
                    "message": (
                        "ASSESSMENT_CONFIG evidence must name "
                        "a config_field or artifact."
                    ),
                }
            )

    return errors


def validate_derivation(
    derivation: dict,
    *,
    frozen_sources: Mapping,
    policy: dict,
) -> dict:
    """Deterministically validate all four prior records."""

    del policy

    errors = []
    priors = derivation.get("priors") or {}
    resolved = {}

    for field in FOUR_PRIORS:
        record = priors.get(field)

        if record is None:
            errors.append(
                {
                    "path": field,
                    "code": "MISSING_PRIOR",
                    "message": (
                        "Derivation is missing prior "
                        f"{field!r}."
                    ),
                }
            )
            resolved[field] = "MISSING"
            continue

        shape_errors = _validate_record_shape(
            field,
            record,
        )
        errors.extend(shape_errors)

        if shape_errors:
            resolved[field] = "INVALID"
            continue

        status = record["status"]
        source_mode = record["source_mode"]

        if status == "SUPPORTED":
            if source_mode == "CORPUS":
                evidence_errors = (
                    _validate_corpus_evidence(
                        field,
                        record,
                        frozen_sources,
                    )
                )
            elif (
                source_mode
                == "ASSESSMENT_CONFIG"
            ):
                evidence_errors = (
                    _validate_assessment_config_evidence(
                        field,
                        record,
                    )
                )
            elif (
                source_mode
                == "ANALYST_JUDGMENT"
            ):
                evidence_errors = []

                if not (
                    record.get("reasoning")
                    or ""
                ).strip():
                    evidence_errors.append(
                        {
                            "path": (
                                f"{field}.reasoning"
                            ),
                            "code": (
                                "MISSING_RATIONALE"
                            ),
                            "message": (
                                "Analyst judgment requires "
                                "a rationale."
                            ),
                        }
                    )
            else:
                evidence_errors = [
                    {
                        "path": (
                            f"{field}.source_mode"
                        ),
                        "code": (
                            "SUPPORTED_REQUIRES_"
                            "EVIDENCE_MODE"
                        ),
                        "message": (
                            "A SUPPORTED value cannot have "
                            "source_mode POLICY_DEFAULT."
                        ),
                    }
                ]

            if evidence_errors:
                errors.extend(evidence_errors)
                resolved[field] = "BLOCKED"
            else:
                resolved[field] = "SUPPORTED"

        elif status == "DEFAULTED":
            if field not in (
                "capability_prior",
                "geopolitical_trigger_prior",
            ):
                errors.append(
                    {
                        "path": (
                            f"{field}.status"
                        ),
                        "code": (
                            "DEFAULT_NOT_ALLOWED"
                        ),
                        "message": (
                            f"{field} may not be DEFAULTED; "
                            "policy requires BLOCK."
                        ),
                    }
                )
                resolved[field] = "BLOCKED"
            else:
                resolved[field] = "DEFAULTED"

        else:
            resolved[field] = "BLOCKED"

    return {
        "is_valid": not errors,
        "errors": errors,
        "priors": resolved,
    }


def compile_bbn_assessment_config(
    derivation: dict,
) -> dict:
    """Compile derivation values into the existing BBN validator shape."""

    priors = derivation.get("priors") or {}

    def value(field: str):
        record = priors.get(field) or {}
        return record.get("value")

    return {
        "adversary": {
            "capability_prior": value(
                "capability_prior"
            ),
            "tempo": value("tempo"),
        },
        "defensive_posture": value(
            "defensive_posture"
        ),
        "geopolitical_trigger_prior": value(
            "geopolitical_trigger_prior"
        ),
    }


def annexc_derivation_hash(
    derivation: dict,
    *,
    corpus_manifest_hash: str,
) -> str:
    """Hash only the analytically meaningful review subject."""

    subject = {
        "schema_version": derivation.get(
            "schema_version",
            "1.0",
        ),
        "policy_version": derivation.get(
            "policy_version"
        ),
        "corpus_manifest_hash": (
            corpus_manifest_hash
        ),
        "priors": derivation.get(
            "priors",
            {},
        ),
        "compiled_config": derivation.get(
            "compiled_config",
            {},
        ),
    }

    return canonical_json_sha256(subject)


REQUIRED_APPROVAL_FIELDS = (
    "approval_id",
    "decision",
    "approved_by",
    "reviewer_role",
    "approved_at",
    "rationale",
    "run_id",
    "corpus_manifest_hash",
    "policy_version",
    "review_subject_hash",
)


class DerivationGateDecision:
    """Result of deterministic derivation-approval evaluation."""

    def __init__(
        self,
        *,
        allowed: bool,
        code: str,
        reason: str,
        detail: dict,
    ):
        self.allowed = allowed
        self.code = code
        self.reason = reason
        self.detail = detail

    def audit_record(self) -> dict:
        return {
            "gate": (
                "annexc_derivation_approval"
            ),
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "detail": self.detail,
        }

    def require_allowed(self) -> None:
        if not self.allowed:
            raise DerivationApprovalBlocked(
                f"{self.code}\n{self.reason}"
            )


def evaluate_derivation_approval(
    *,
    derivation: dict,
    derivation_validation: dict,
    config_validation: dict,
    approval: dict | None,
    run_id: str,
    corpus_manifest_hash: str,
    policy_version: str,
) -> DerivationGateDecision:
    """Evaluate the hash-bound analyst approval gate."""

    resolved = derivation_validation.get(
        "priors",
        {},
    )

    bad_priors = {
        field: status
        for field, status in resolved.items()
        if status
        not in (
            "SUPPORTED",
            "DEFAULTED",
        )
    }

    if (
        not derivation_validation.get(
            "is_valid"
        )
        or bad_priors
    ):
        return DerivationGateDecision(
            allowed=False,
            code="DERIVATION_NOT_RESOLVED",
            reason=(
                "Derivation has unresolved priors or validation "
                f"errors (non-passing: {bad_priors or 'see errors'}). "
                "Annex C is blocked."
            ),
            detail={
                "priors": resolved,
            },
        )

    if not config_validation.get("is_valid"):
        return DerivationGateDecision(
            allowed=False,
            code="CONFIG_INVALID",
            reason=(
                "Compiled BBN assessment config failed "
                "validate_bbn_assessment_config()."
            ),
            detail={
                "config_errors": (
                    config_validation.get(
                        "errors"
                    )
                )
            },
        )

    if not isinstance(approval, Mapping):
        return DerivationGateDecision(
            allowed=False,
            code="NO_APPROVAL",
            reason=(
                "No analyst approval record present; Annex C "
                "requires an approved derivation."
            ),
            detail={},
        )

    missing_fields = [
        field
        for field in REQUIRED_APPROVAL_FIELDS
        if not approval.get(field)
    ]

    if missing_fields:
        return DerivationGateDecision(
            allowed=False,
            code="APPROVAL_INCOMPLETE",
            reason=(
                "Approval missing required field(s): "
                f"{missing_fields}."
            ),
            detail={},
        )

    decision = str(
        approval.get("decision")
    ).upper()

    if decision == "REJECTED":
        return DerivationGateDecision(
            allowed=False,
            code="APPROVAL_REJECTED",
            reason=(
                "Analyst REJECTED the derivation; "
                "Annex C is blocked."
            ),
            detail={},
        )

    if decision != "APPROVED":
        return DerivationGateDecision(
            allowed=False,
            code="APPROVAL_NOT_APPROVED",
            reason=(
                "Approval decision is "
                f"{approval.get('decision')!r}, "
                "not APPROVED."
            ),
            detail={},
        )

    if approval.get("run_id") != run_id:
        return DerivationGateDecision(
            allowed=False,
            code="APPROVAL_RUN_MISMATCH",
            reason=(
                "Approval run_id does not match "
                "the active run."
            ),
            detail={},
        )

    if (
        approval.get(
            "corpus_manifest_hash"
        )
        != corpus_manifest_hash
    ):
        return DerivationGateDecision(
            allowed=False,
            code="APPROVAL_CORPUS_MISMATCH",
            reason=(
                "Approval corpus_manifest_hash does not "
                "match the active corpus."
            ),
            detail={},
        )

    if (
        approval.get("policy_version")
        != policy_version
    ):
        return DerivationGateDecision(
            allowed=False,
            code="APPROVAL_POLICY_MISMATCH",
            reason=(
                "Approval policy_version does not match "
                "the derivation policy."
            ),
            detail={},
        )

    current_subject_hash = (
        annexc_derivation_hash(
            derivation,
            corpus_manifest_hash=(
                corpus_manifest_hash
            ),
        )
    )

    if (
        approval.get("review_subject_hash")
        != current_subject_hash
    ):
        return DerivationGateDecision(
            allowed=False,
            code="APPROVAL_STALE",
            reason=(
                "Approval review_subject_hash does not match "
                "the current derivation — the derivation "
                "changed since it was approved."
            ),
            detail={
                "expected": current_subject_hash,
                "approval": approval.get(
                    "review_subject_hash"
                ),
            },
        )

    return DerivationGateDecision(
        allowed=True,
        code="DERIVATION_APPROVED",
        reason=(
            "Derivation is fully resolved, config-valid, "
            "and approved for this run."
        ),
        detail={
            "approval_id": approval.get(
                "approval_id"
            ),
            "review_subject_hash": (
                current_subject_hash
            ),
        },
    )


def require_approved_derivation(
    **kwargs,
) -> DerivationGateDecision:
    """Evaluate the approval and raise unless allowed."""

    decision = evaluate_derivation_approval(
        **kwargs
    )
    decision.require_allowed()
    return decision


def derive_annexc_inputs(
    *,
    corpus_sources: Mapping,
    policy: dict,
    propose_priors: Callable[
        [Mapping],
        dict,
    ],
    assessment_config: Mapping | None = None,
) -> dict:
    """Orchestrate proposal and per-prior no-evidence policy."""

    del assessment_config

    proposed = (
        propose_priors(corpus_sources)
        or {}
    )
    priors = {}

    for field in FOUR_PRIORS:
        record = proposed.get(field)

        if record is None:
            priors[field] = (
                apply_no_evidence_policy(
                    field,
                    policy,
                )
            )
        else:
            priors[field] = record

    derivation = {
        "schema_version": "1.0",
        "policy_version": policy[
            "policy_version"
        ],
        "priors": priors,
    }

    derivation["compiled_config"] = (
        compile_bbn_assessment_config(
            derivation
        )
    )

    return derivation


def load_frozen_corpus_sources(
    out_dir: str,
    *,
    source_dir: str = "sources",
    lock_manifest_path: str = (
        "sources/corpus_manifest.md"
    ),
) -> dict:
    """
    Load the exact corpus bound by the frozen corpus-lock manifest.

    Each source file is rehashed against the frozen manifest before its
    normalized text is loaded through read_corpus_file(), the same reader
    used by Stage 0.

    Missing manifests, malformed manifests, missing files, hash drift,
    extraction failures, empty source text, and zero-source results all
    fail closed.
    """

    del out_dir

    from src.tools import read_corpus_file

    if not os.path.isfile(
        lock_manifest_path
    ):
        raise DerivationError(
            "Cannot load the frozen Annex C corpus: "
            f"{lock_manifest_path} does not exist."
        )

    try:
        with open(
            lock_manifest_path,
            encoding="utf-8",
        ) as handle:
            manifest_text = handle.read()
    except OSError as exc:
        raise DerivationError(
            "Cannot read the frozen Annex C corpus manifest "
            f"{lock_manifest_path}: {exc}"
        ) from exc

    manifest_match = re.search(
        r"```json\s*(\{.*\})\s*```",
        manifest_text,
        re.DOTALL,
    )

    if manifest_match is None:
        raise DerivationError(
            "Cannot load the frozen Annex C corpus: "
            f"{lock_manifest_path} has no embedded JSON object."
        )

    try:
        manifest = json.loads(
            manifest_match.group(1)
        )
    except json.JSONDecodeError as exc:
        raise DerivationError(
            "Cannot load the frozen Annex C corpus: "
            f"{lock_manifest_path} contains invalid JSON: {exc}"
        ) from exc

    entries = manifest.get("files")

    if (
        not isinstance(entries, list)
        or not entries
    ):
        raise DerivationError(
            "Cannot load the frozen Annex C corpus: "
            f"{lock_manifest_path} has no non-empty files list."
        )

    frozen_sources: dict[
        str,
        dict[str, str],
    ] = {}
    errors: list[str] = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(
                f"manifest files[{index}] is not an object"
            )
            continue

        source_file = entry.get("file")
        expected_hash = entry.get("sha256")

        if (
            not isinstance(source_file, str)
            or not source_file.strip()
        ):
            errors.append(
                f"manifest files[{index}] has no valid file name"
            )
            continue

        source_file = source_file.strip()

        if (
            not isinstance(expected_hash, str)
            or not expected_hash.strip()
        ):
            errors.append(
                f"{source_file}: frozen SHA-256 is missing"
            )
            continue

        expected_hash = expected_hash.strip()

        if expected_hash.startswith(
            "sha256:"
        ):
            expected_hex = (
                expected_hash.removeprefix(
                    "sha256:"
                )
            )
        else:
            expected_hex = expected_hash

        if not re.fullmatch(
            r"[0-9a-fA-F]{64}",
            expected_hex,
        ):
            errors.append(
                f"{source_file}: frozen SHA-256 is malformed: "
                f"{expected_hash!r}"
            )
            continue

        expected_hex = expected_hex.lower()

        source_path = os.path.join(
            source_dir,
            source_file,
        )

        if not os.path.isfile(source_path):
            errors.append(
                f"{source_file}: frozen source file is missing at "
                f"{source_path}"
            )
            continue

        try:
            digest = hashlib.sha256()

            with open(
                source_path,
                "rb",
            ) as handle:
                for block in iter(
                    lambda: handle.read(
                        1024 * 1024
                    ),
                    b"",
                ):
                    digest.update(block)

            actual_hex = digest.hexdigest()
        except OSError as exc:
            errors.append(
                f"{source_file}: could not hash source file: "
                f"{exc}"
            )
            continue

        if actual_hex != expected_hex:
            errors.append(
                f"{source_file}: SHA-256 mismatch "
                f"(expected {expected_hex}, got {actual_hex})"
            )
            continue

        try:
            source_text = read_corpus_file(
                source_path
            )
        except Exception as exc:
            errors.append(
                f"{source_file}: text extraction failed: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        if (
            not isinstance(source_text, str)
            or not source_text.strip()
        ):
            errors.append(
                f"{source_file}: text extraction produced no content"
            )
            continue

        frozen_sources[source_file] = {
            "sha256": (
                f"sha256:{actual_hex}"
            ),
            "text": source_text,
        }

    if errors:
        formatted_errors = "\n  - ".join(
            errors
        )

        raise DerivationError(
            "Frozen Annex C corpus loading failed. "
            "No model calls were made.\n"
            f"  - {formatted_errors}"
        )

    if not frozen_sources:
        raise DerivationError(
            "Frozen Annex C corpus loading produced zero sources. "
            "Refusing to start a zero-chunk proposer scan."
        )

    return frozen_sources


def make_prior_proposer(
    frozen_sources: Mapping,
    llm,
    live: bool = True,
    diagnostics_out_dir: str | None = None,
) -> Callable[[Mapping], dict]:
    """Return the live or stub prior proposer."""

    del frozen_sources

    if not live or llm is None:

        def propose_stub(
            corpus_sources: Mapping,
        ) -> dict:
            del corpus_sources
            return {}

        return propose_stub

    def propose_live(
        corpus_sources: Mapping,
    ) -> dict:
        from src.annexc_proposer import (
            propose_priors_from_corpus,
        )

        return propose_priors_from_corpus(
            frozen_sources=corpus_sources,
            llm=llm,
            diagnostics_out_dir=(
                diagnostics_out_dir
            ),
        )

    return propose_live


def run_annexc_derivation_gate(
    *,
    state,
    run_id,
    out_dir,
    corpus_manifest_hash,
    run_context,
    set_stage_status,
    save_assessment_state,
    StageStatus,
    policy_path=(
        "config/annexc_derivation_policy.json"
    ),
):
    """Run the two-phase Annex C derivation and approval gate."""

    del set_stage_status
    del StageStatus

    derivation_path = (
        run_context.artifact_path(
            "annexc_derivation.json"
        )
    )
    config_path = (
        run_context.artifact_path(
            "annexc_assessment_config.json"
        )
    )
    approval_path = (
        run_context.artifact_path(
            "annexc_derivation_approval.json"
        )
    )

    policy = load_derivation_policy(
        policy_path
    )
    frozen_sources = (
        load_frozen_corpus_sources(
            out_dir
        )
    )

    if not os.path.exists(
        derivation_path
    ):
        try:
            from config.llm import reason_llm
        except Exception:
            reason_llm = None

        derivation = derive_annexc_inputs(
            corpus_sources=frozen_sources,
            policy=policy,
            propose_priors=make_prior_proposer(
                frozen_sources,
                reason_llm,
                diagnostics_out_dir=out_dir,
            ),
        )

        config = (
            compile_bbn_assessment_config(
                derivation
            )
        )
        config_validation = (
            validate_bbn_assessment_config(
                config
            )
        )

        derivation[
            "config_validation"
        ] = config_validation
        derivation[
            "review_subject_hash"
        ] = annexc_derivation_hash(
            derivation,
            corpus_manifest_hash=(
                corpus_manifest_hash
            ),
        )

        run_context.write_stamped_json(
            derivation_path,
            derivation,
        )
        run_context.write_stamped_json(
            config_path,
            config,
        )

        state.current_stage = (
            "annexc_derivation"
        )
        save_assessment_state(
            state,
            run_id,
        )

        raise DerivationApprovalBlocked(
            "ANNEXC_DERIVATION_AWAITING_APPROVAL\n"
            "Annex C priors were derived and written to "
            f"{derivation_path}. An analyst must review the "
            "derivation and evidence, then write "
            f"{approval_path} (decision APPROVED/REJECTED) "
            "before Annex C can score. Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    derivation = (
        run_context.read_stamped_json(
            derivation_path
        )
    )
    derivation_validation = (
        validate_derivation(
            derivation,
            frozen_sources=frozen_sources,
            policy=policy,
        )
    )

    config = (
        run_context.read_stamped_json(
            config_path
        )
    )
    config_validation = (
        validate_bbn_assessment_config(
            config
        )
    )

    approval = None

    if os.path.exists(approval_path):
        try:
            approval = (
                run_context.read_stamped_json(
                    approval_path
                )
            )
        except Exception:
            approval = None

    decision = (
        evaluate_derivation_approval(
            derivation=derivation,
            derivation_validation=(
                derivation_validation
            ),
            config_validation=(
                config_validation
            ),
            approval=approval,
            run_id=run_id,
            corpus_manifest_hash=(
                corpus_manifest_hash
            ),
            policy_version=policy[
                "policy_version"
            ],
        )
    )

    if isinstance(
        getattr(
            state,
            "gate_decisions",
            None,
        ),
        list,
    ):
        state.gate_decisions.append(
            decision.audit_record()
        )

    if not decision.allowed:
        state.current_stage = (
            "annexc_derivation"
        )
        save_assessment_state(
            state,
            run_id,
        )

        raise DerivationApprovalBlocked(
            f"{decision.code}\n"
            f"{decision.reason}\n"
            "Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    return decision
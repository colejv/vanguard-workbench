from __future__ import annotations

"""
Fast Annex C derivation from prior-stage assessment artifacts.

This replaces the full-corpus Annex C extraction scan. The four BBN priors
are derived from Stage 0, Stage 1, Stage 2, and Annex B artifacts using one
structured model call, with at most one repair call.

Every supported prior must cite an exact quote from a hash-bound artifact.
Missing evidence still follows the existing versioned no-evidence policy.
"""


import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.annexc_derivation import (
    FOUR_PRIORS,
    DerivationApprovalBlocked,
    annexc_derivation_hash,
    apply_no_evidence_policy,
    compile_bbn_assessment_config,
    evaluate_derivation_approval,
    load_derivation_policy,
    quote_is_present,
)
from src.bbn_validation import (
    EXPECTED_DEFENSIVE_CONTROLS,
    validate_bbn_assessment_config,
)
from src.structured_output import generate_structured_json


ARTIFACT_SOURCE_MODE = "ASSESSMENT_ARTIFACT"

_REQUIRED_JSON_ARTIFACTS = (
    "stage0_output.json",
    "stage1_output.json",
    "stage2_vectors.json",
    "kcag_report.json",
)

_FIELD_PATHS = {
    "capability_prior": "adversary.capability_prior",
    "tempo": "adversary.tempo",
    "defensive_posture": "defensive_posture",
    "geopolitical_trigger_prior": "geopolitical_trigger_prior",
}

_ALLOWED_CONFIDENCE = {
    "LOW",
    "MEDIUM",
    "HIGH",
}


def _resolve_repository_path(
    path_value: str | os.PathLike[str],
) -> Path:
    """
    Resolve configuration paths independently of the process working
    directory.

    Pytest integration tests and production launchers may change cwd, while
    repository configuration remains anchored beside the src directory.
    """

    path = Path(path_value).expanduser()

    if path.is_absolute():
        return path

    repository_root = Path(__file__).resolve().parents[1]
    return repository_root / path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return f"sha256:{digest.hexdigest()}"


def load_prior_stage_artifacts(
    *,
    out_dir: str,
    run_context,
) -> dict[str, dict[str, Any]]:
    """
    Load the Stage 0/1/2 and Annex B structured artifacts.

    Stamped reads enforce active-run and corpus identity. The returned text
    is the exact compact JSON supplied to the derivation model and used for
    deterministic quote verification.
    """

    sources: dict[str, dict[str, Any]] = {}

    for artifact_name in _REQUIRED_JSON_ARTIFACTS:
        path = Path(out_dir) / artifact_name

        if not path.is_file():
            raise FileNotFoundError(
                "Annex C artifact derivation requires "
                f"{path}, but it does not exist."
            )

        payload = run_context.read_stamped_json(
            str(path)
        )

        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

        sources[artifact_name] = {
            "path": str(path),
            "sha256": _file_sha256(path),
            "text": text,
        }

    return sources


def _evidence_schema(
    artifact_names: list[str],
) -> dict:
    return {
        "type": "object",
        "properties": {
            "artifact_name": {
                "type": "string",
                "enum": artifact_names,
            },
            "quote": {
                "type": "string",
            },
        },
        "required": [
            "artifact_name",
            "quote",
        ],
        "additionalProperties": False,
    }


def _record_schema(
    *,
    value_schema: dict,
    artifact_names: list[str],
) -> dict:
    return {
        "type": "object",
        "properties": {
            "value": value_schema,
            "confidence": {
                "type": "string",
                "enum": [
                    "LOW",
                    "MEDIUM",
                    "HIGH",
                ],
            },
            "reasoning": {
                "type": "string",
            },
            "evidence": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": _evidence_schema(
                    artifact_names
                ),
            },
        },
        "required": [
            "value",
            "confidence",
            "reasoning",
            "evidence",
        ],
        "additionalProperties": False,
    }


def _proposal_schema(
    artifact_names: list[str],
) -> dict:
    controls = sorted(
        EXPECTED_DEFENSIVE_CONTROLS
    )

    defensive_value_schema = {
        "type": "object",
        "properties": {
            control: {
                "type": "boolean",
            }
            for control in controls
        },
        "required": controls,
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "capability_prior": {
                "type": "array",
                "maxItems": 1,
                "items": _record_schema(
                    artifact_names=artifact_names,
                    value_schema={
                        "type": "array",
                        "items": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "minItems": 3,
                        "maxItems": 3,
                    },
                ),
            },
            "tempo": {
                "type": "array",
                "maxItems": 1,
                "items": _record_schema(
                    artifact_names=artifact_names,
                    value_schema={
                        "type": "string",
                        "enum": [
                            "LOW",
                            "MEDIUM",
                            "HIGH",
                        ],
                    },
                ),
            },
            "defensive_posture": {
                "type": "array",
                "maxItems": 1,
                "items": _record_schema(
                    artifact_names=artifact_names,
                    value_schema=(
                        defensive_value_schema
                    ),
                ),
            },
            "geopolitical_trigger_prior": {
                "type": "array",
                "maxItems": 1,
                "items": _record_schema(
                    artifact_names=artifact_names,
                    value_schema={
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                ),
            },
        },
        "required": list(FOUR_PRIORS),
        "additionalProperties": False,
    }


_SYSTEM_PROMPT = """
You derive four Annex C BBN priors from completed assessment artifacts.

Use only the supplied Stage 0, Stage 1, Stage 2, and Annex B artifacts.
Do not rescan or reason from the original corpus. Do not use outside
knowledge.

Every top-level prior field must be an array. Return either an empty array
or an array containing exactly one proposal object. Never return a proposal
object directly as the top-level field value.

Return an empty array for a prior when the artifacts do not provide enough
evidence to support a value. Never invent a value merely to complete the
assessment.

For every proposed prior:

1. Cite one or more exact, contiguous quotes copied from the named artifact.
2. Use artifact_name exactly as supplied.
3. Include a non-empty reasoning string explaining the inference concisely.
4. Include confidence as exactly LOW, MEDIUM, or HIGH.
5. Treat KCAG values as assessment heuristics, not calibrated empirical
   probabilities.
6. For defensive_posture, mark a control true or false only when the
   assessment artifacts substantively support that conclusion.
7. For defensive_posture, value must be one JSON object mapping every required control to an unquoted JSON boolean. Do not return defensive_posture.value as an array.\nReturn only the schema-constrained JSON object.
""".strip()


def _render_prompt(
    sources: Mapping[str, Mapping[str, Any]],
) -> str:
    sections = []

    for artifact_name, source in sources.items():
        sections.append(
            f"=== ARTIFACT {artifact_name} ===\n"
            f"SHA256: {source['sha256']}\n"
            f"{source['text']}\n"
            f"=== END ARTIFACT {artifact_name} ==="
        )

    return (
        "Derive these priors:\n"
        "- capability_prior: a three-element probability vector ordered "
        "[hacktivist, criminal, nation_state], summing to 1.\n"
        "- tempo: LOW, MEDIUM, or HIGH.\n"
        "- defensive_posture: booleans for every required defensive control.\n"
        "- geopolitical_trigger_prior: a number from 0 through 1.\n\n"
        "Use an empty array when the supplied assessment artifacts cannot "
        "support a prior.\n\n"
        + "\n\n".join(sections)
    )



def _normalize_boolean_value(
    value: Any,
    *,
    path: str,
) -> bool:
    """Normalize only unambiguous boolean representations."""

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized == "true":
            return True

        if normalized == "false":
            return False

    raise ValueError(
        f"{path} must be a boolean"
    )


def _normalize_defensive_posture_value(
    value: Any,
) -> dict[str, bool]:
    """
    Normalize equivalent defensive-posture representations.

    Accepted forms:

    1. A direct control-to-boolean object.
    2. A one-element array containing that object.
    3. An array of {"control": name, "enabled": bool} records.
    4. An array of {"name": name, "value": bool} records.

    Missing, duplicate, or unknown controls still fail closed.
    """

    expected = set(
        EXPECTED_DEFENSIVE_CONTROLS
    )

    raw_mapping: dict[str, Any]

    if isinstance(value, Mapping):
        raw_mapping = dict(value)

    elif (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], Mapping)
        and set(value[0]) == expected
    ):
        raw_mapping = dict(value[0])

    elif isinstance(value, list):
        raw_mapping = {}

        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise ValueError(
                    "defensive_posture array items "
                    "must be objects"
                )

            control = item.get("control")

            if control is None:
                control = item.get("name")

            if not isinstance(control, str):
                raise ValueError(
                    "defensive_posture array item "
                    f"{index} must identify a control"
                )

            control = control.strip()

            if control not in expected:
                raise ValueError(
                    "defensive_posture contains unknown "
                    f"control {control!r}"
                )

            if control in raw_mapping:
                raise ValueError(
                    "defensive_posture contains duplicate "
                    f"control {control!r}"
                )

            if "enabled" in item:
                control_value = item["enabled"]
            elif "value" in item:
                control_value = item["value"]
            else:
                raise ValueError(
                    "defensive_posture array item "
                    f"{index} must contain enabled or value"
                )

            raw_mapping[control] = control_value

    else:
        raise ValueError(
            "defensive_posture must be an object "
            "or an equivalent control array"
        )

    actual = set(raw_mapping)

    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)

        raise ValueError(
            "defensive_posture must contain exactly "
            f"{sorted(expected)}; missing={missing}; "
            f"unexpected={unexpected}"
        )

    return {
        control: _normalize_boolean_value(
            raw_mapping[control],
            path=f"defensive_posture.{control}",
        )
        for control in sorted(expected)
    }


def _validate_value(
    field: str,
    value: Any,
) -> Any:
    if field == "capability_prior":
        if (
            not isinstance(value, list)
            or len(value) != 3
        ):
            raise ValueError(
                "capability_prior must contain exactly "
                "three probabilities"
            )

        normalized = []

        for item in value:
            if (
                isinstance(item, bool)
                or not isinstance(
                    item,
                    (int, float),
                )
            ):
                raise ValueError(
                    "capability_prior values must be numeric"
                )

            number = float(item)

            if number < 0 or number > 1:
                raise ValueError(
                    "capability_prior values must be "
                    "between 0 and 1"
                )

            normalized.append(number)

        if abs(sum(normalized) - 1.0) > 1e-6:
            raise ValueError(
                "capability_prior must sum to 1"
            )

        return normalized

    if field == "tempo":
        if value not in {
            "LOW",
            "MEDIUM",
            "HIGH",
        }:
            raise ValueError(
                "tempo must be LOW, MEDIUM, or HIGH"
            )

        return value

    if field == "defensive_posture":
        return _normalize_defensive_posture_value(
            value
        )

    if field == "geopolitical_trigger_prior":
        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                (int, float),
            )
        ):
            raise ValueError(
                "geopolitical_trigger_prior must "
                "be numeric"
            )

        number = float(value)

        if number < 0 or number > 1:
            raise ValueError(
                "geopolitical_trigger_prior must "
                "be between 0 and 1"
            )

        return number

    raise ValueError(
        f"Unknown Annex C prior: {field}"
    )


def _normalize_prior_records(
    field: str,
    value: Any,
) -> list:
    """
    Normalize an unambiguous single proposal object to the schema's
    one-element array representation.

    Ollama occasionally returns:

        "defensive_posture": {...}

    despite the supplied schema requiring:

        "defensive_posture": [{...}]

    Missing or null values mean no proposal. Scalars and other malformed
    structures continue to fail closed.
    """

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, Mapping):
        return [dict(value)]

    raise ValueError(
        f"{field} must be an array or a single proposal object"
    )


def _normalize_proposal_record(
    field: str,
    candidate: Any,
) -> dict:
    """
    Normalize harmless structured-output inconsistencies without changing
    the proposed analytical value.

    A missing explanation is replaced only when the proposal contains cited
    evidence. Missing evidence still fails closed during validation.
    """

    if not isinstance(candidate, Mapping):
        raise ValueError(
            f"{field}[0] must be an object"
        )

    normalized = dict(candidate)

    evidence = normalized.get("evidence")

    if isinstance(evidence, Mapping):
        normalized["evidence"] = [
            dict(evidence)
        ]

    confidence = normalized.get(
        "confidence"
    )

    if (
        confidence is None
        or (
            isinstance(confidence, str)
            and not confidence.strip()
        )
    ):
        normalized["confidence"] = "LOW"

    reasoning = normalized.get(
        "reasoning"
    )
    evidence_items = normalized.get(
        "evidence"
    )

    if (
        (
            not isinstance(reasoning, str)
            or not reasoning.strip()
        )
        and isinstance(evidence_items, list)
        and evidence_items
    ):
        normalized["reasoning"] = (
            "Derived from the cited prior-stage "
            f"assessment artifact evidence for {field}."
        )

    return normalized


def _validate_model_payload(
    payload: Any,
    *,
    sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict]:
    if not isinstance(payload, Mapping):
        raise ValueError(
            "Annex C proposal must be a JSON object"
        )

    proposals: dict[str, dict] = {}

    for field in FOUR_PRIORS:
        records = _normalize_prior_records(
            field,
            payload.get(field),
        )

        if len(records) > 1:
            raise ValueError(
                f"{field} may contain at most one proposal"
            )

        if not records:
            continue

        candidate = _normalize_proposal_record(
            field,
            records[0],
        )

        confidence = candidate.get(
            "confidence"
        )

        if confidence not in _ALLOWED_CONFIDENCE:
            raise ValueError(
                f"{field}.confidence must be LOW, "
                "MEDIUM, or HIGH"
            )

        reasoning = candidate.get(
            "reasoning"
        )

        if (
            not isinstance(reasoning, str)
            or not reasoning.strip()
        ):
            raise ValueError(
                f"{field}.reasoning is required"
            )

        value = _validate_value(
            field,
            candidate.get("value"),
        )

        evidence_items = candidate.get(
            "evidence"
        )

        if (
            not isinstance(evidence_items, list)
            or not evidence_items
        ):
            raise ValueError(
                f"{field}.evidence must contain "
                "at least one citation"
            )

        evidence = []

        for index, citation in enumerate(
            evidence_items
        ):
            if not isinstance(
                citation,
                Mapping,
            ):
                raise ValueError(
                    f"{field}.evidence[{index}] "
                    "must be an object"
                )

            artifact_name = citation.get(
                "artifact_name"
            )
            quote = citation.get("quote")

            if artifact_name not in sources:
                raise ValueError(
                    f"{field}.evidence[{index}] "
                    "references an unknown artifact"
                )

            if (
                not isinstance(quote, str)
                or not quote.strip()
            ):
                raise ValueError(
                    f"{field}.evidence[{index}].quote "
                    "is required"
                )

            source = sources[artifact_name]

            if not quote_is_present(
                quote,
                source["text"],
            ):
                raise ValueError(
                    f"{field}.evidence[{index}] quote "
                    f"was not found in {artifact_name}"
                )

            evidence.append(
                {
                    "source_type": (
                        "ASSESSMENT_ARTIFACT"
                    ),
                    "source_file": (
                        artifact_name
                    ),
                    "source_sha256": (
                        source["sha256"]
                    ),
                    "quote": quote,
                }
            )

        proposals[field] = {
            "field": _FIELD_PATHS[field],
            "value": value,
            "status": "SUPPORTED",
            "source_mode": (
                ARTIFACT_SOURCE_MODE
            ),
            "confidence": confidence,
            "reasoning": reasoning.strip(),
            "evidence": evidence,
        }

    return proposals


def _propose_from_artifacts(
    *,
    sources: Mapping[str, Mapping[str, Any]],
    llm,
    timeout_seconds: int = 180,
) -> dict[str, dict]:
    base_prompt = _render_prompt(
        sources
    )
    schema = _proposal_schema(
        sorted(sources)
    )

    last_error: Exception | None = None

    for attempt in range(2):
        prompt = base_prompt

        if last_error is not None:
            prompt += (
                "\n\nPREVIOUS RESPONSE REJECTED:\n"
                f"{type(last_error).__name__}: "
                f"{last_error}\n\n"
                "Repair the response. Use an empty array "
                "for any prior that cannot be supported. "
                "Every quote must be copied exactly from "
                "the named artifact."
            )

        try:
            raw = generate_structured_json(
                llm=llm,
                schema=schema,
                prompt=prompt,
                system_message=_SYSTEM_PROMPT,
                num_predict=4096,
                timeout_seconds=(
                    timeout_seconds
                ),
            )

            parsed = json.loads(raw)

            return _validate_model_payload(
                parsed,
                sources=sources,
            )

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        "Annex C artifact derivation failed after "
        f"two attempts: {last_error}"
    )


def derive_annexc_from_prior_artifacts(
    *,
    sources: Mapping[str, Mapping[str, Any]],
    policy: dict,
    llm,
    timeout_seconds: int = 180,
) -> dict:
    """
    Perform one artifact-based derivation call and apply policy fallbacks.
    """

    proposed = _propose_from_artifacts(
        sources=sources,
        llm=llm,
        timeout_seconds=timeout_seconds,
    )

    priors = {}

    for field in FOUR_PRIORS:
        record = proposed.get(field)

        if record is None:
            record = apply_no_evidence_policy(
                field,
                policy,
            )

        priors[field] = record

    derivation = {
        "schema_version": "1.0",
        "policy_version": policy[
            "policy_version"
        ],
        "derivation_method": (
            "PRIOR_STAGE_ARTIFACTS_SINGLE_CALL"
        ),
        "source_artifacts": {
            name: {
                "path": source["path"],
                "sha256": source["sha256"],
            }
            for name, source in sources.items()
        },
        "priors": priors,
    }

    derivation["compiled_config"] = (
        compile_bbn_assessment_config(
            derivation
        )
    )

    return derivation


def _validate_artifact_evidence(
    *,
    field: str,
    record: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
) -> list[dict]:
    errors = []
    evidence = record.get("evidence")

    if (
        not isinstance(evidence, list)
        or not evidence
    ):
        return [
            {
                "path": f"{field}.evidence",
                "code": (
                    "NO_ASSESSMENT_ARTIFACT_EVIDENCE"
                ),
                "message": (
                    "A supported artifact-derived prior "
                    "requires evidence."
                ),
            }
        ]

    for index, citation in enumerate(evidence):
        path = f"{field}.evidence[{index}]"

        if not isinstance(citation, Mapping):
            errors.append(
                {
                    "path": path,
                    "code": (
                        "INVALID_EVIDENCE_SHAPE"
                    ),
                    "message": (
                        "Evidence must be an object."
                    ),
                }
            )
            continue

        source_file = citation.get(
            "source_file"
        )
        source_hash = citation.get(
            "source_sha256"
        )
        quote = citation.get("quote")

        source = sources.get(source_file)

        if source is None:
            errors.append(
                {
                    "path": path,
                    "code": (
                        "UNKNOWN_ASSESSMENT_ARTIFACT"
                    ),
                    "message": (
                        f"Unknown artifact {source_file!r}."
                    ),
                }
            )
            continue

        if source_hash != source["sha256"]:
            errors.append(
                {
                    "path": path,
                    "code": (
                        "ARTIFACT_HASH_MISMATCH"
                    ),
                    "message": (
                        "Evidence hash does not match "
                        "the current artifact."
                    ),
                }
            )
            continue

        if (
            not isinstance(quote, str)
            or not quote_is_present(
                quote,
                source["text"],
            )
        ):
            errors.append(
                {
                    "path": path,
                    "code": (
                        "ARTIFACT_QUOTE_NOT_FOUND"
                    ),
                    "message": (
                        "Evidence quote was not found "
                        "in the current artifact."
                    ),
                }
            )

    return errors


def validate_artifact_derivation(
    derivation: dict,
    *,
    sources: Mapping[str, Mapping[str, Any]],
    policy: dict,
) -> dict:
    """
    Validate derivation shape, values, and artifact-bound evidence.
    """

    del policy

    errors = []
    resolved = {}
    priors = derivation.get("priors")

    if not isinstance(priors, Mapping):
        return {
            "is_valid": False,
            "errors": [
                {
                    "path": "priors",
                    "code": "MISSING_PRIORS",
                    "message": (
                        "Derivation has no priors object."
                    ),
                }
            ],
            "priors": {
                field: "MISSING"
                for field in FOUR_PRIORS
            },
        }

    for field in FOUR_PRIORS:
        record = priors.get(field)

        if not isinstance(record, Mapping):
            errors.append(
                {
                    "path": field,
                    "code": "MISSING_PRIOR",
                    "message": (
                        f"Missing prior {field}."
                    ),
                }
            )
            resolved[field] = "MISSING"
            continue

        status = record.get("status")
        source_mode = record.get(
            "source_mode"
        )
        reasoning = record.get(
            "reasoning"
        )
        confidence = record.get(
            "confidence"
        )

        if (
            not isinstance(reasoning, str)
            or not reasoning.strip()
        ):
            errors.append(
                {
                    "path": (
                        f"{field}.reasoning"
                    ),
                    "code": "MISSING_REASONING",
                    "message": (
                        "Reasoning is required."
                    ),
                }
            )

        if confidence not in _ALLOWED_CONFIDENCE:
            errors.append(
                {
                    "path": (
                        f"{field}.confidence"
                    ),
                    "code": (
                        "INVALID_CONFIDENCE"
                    ),
                    "message": (
                        "Confidence must be LOW, "
                        "MEDIUM, or HIGH."
                    ),
                }
            )

        if status == "SUPPORTED":
            try:
                _validate_value(
                    field,
                    record.get("value"),
                )
            except ValueError as exc:
                errors.append(
                    {
                        "path": (
                            f"{field}.value"
                        ),
                        "code": (
                            "INVALID_PRIOR_VALUE"
                        ),
                        "message": str(exc),
                    }
                )

            if (
                source_mode
                == ARTIFACT_SOURCE_MODE
            ):
                evidence_errors = (
                    _validate_artifact_evidence(
                        field=field,
                        record=record,
                        sources=sources,
                    )
                )
                errors.extend(
                    evidence_errors
                )

                resolved[field] = (
                    "BLOCKED"
                    if evidence_errors
                    else "SUPPORTED"
                )

            elif source_mode in {
                "ANALYST_JUDGMENT",
                "ASSESSMENT_CONFIG",
            }:
                resolved[field] = "SUPPORTED"

            else:
                errors.append(
                    {
                        "path": (
                            f"{field}.source_mode"
                        ),
                        "code": (
                            "INVALID_SUPPORTED_SOURCE"
                        ),
                        "message": (
                            "Supported priors must come "
                            "from assessment artifacts, "
                            "analyst judgment, or an "
                            "assessment configuration."
                        ),
                    }
                )
                resolved[field] = "BLOCKED"

        elif status == "DEFAULTED":
            if field not in {
                "capability_prior",
                "geopolitical_trigger_prior",
            }:
                errors.append(
                    {
                        "path": (
                            f"{field}.status"
                        ),
                        "code": (
                            "DEFAULT_NOT_ALLOWED"
                        ),
                        "message": (
                            f"{field} may not be "
                            "defaulted."
                        ),
                    }
                )
                resolved[field] = "BLOCKED"
            else:
                try:
                    _validate_value(
                        field,
                        record.get("value"),
                    )
                except ValueError as exc:
                    errors.append(
                        {
                            "path": (
                                f"{field}.value"
                            ),
                            "code": (
                                "INVALID_DEFAULT_VALUE"
                            ),
                            "message": str(exc),
                        }
                    )

                resolved[field] = "DEFAULTED"

        elif status == "BLOCKED":
            resolved[field] = "BLOCKED"

        else:
            errors.append(
                {
                    "path": (
                        f"{field}.status"
                    ),
                    "code": "INVALID_STATUS",
                    "message": (
                        "Status must be SUPPORTED, "
                        "DEFAULTED, or BLOCKED."
                    ),
                }
            )
            resolved[field] = "INVALID"

    return {
        "is_valid": not errors,
        "errors": errors,
        "priors": resolved,
    }


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
    """
    Two-phase artifact-based derivation and analyst-approval gate.
    """

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
    context_path = (
        run_context.artifact_path(
            "annexc_artifact_context.json"
        )
    )
    approval_path = (
        run_context.artifact_path(
            "annexc_derivation_approval.json"
        )
    )

    resolved_policy_path = _resolve_repository_path(
        policy_path
    )

    policy = load_derivation_policy(
        str(resolved_policy_path)
    )

    sources = load_prior_stage_artifacts(
        out_dir=out_dir,
        run_context=run_context,
    )

    run_context.write_stamped_json(
        context_path,
        {
            "derivation_method": (
                "PRIOR_STAGE_ARTIFACTS_SINGLE_CALL"
            ),
            "artifacts": {
                name: {
                    "path": source["path"],
                    "sha256": source["sha256"],
                    "characters": len(
                        source["text"]
                    ),
                }
                for name, source in sources.items()
            },
        },
    )

    if not os.path.exists(derivation_path):
        from config.llm import reason_llm

        print(
            "[Annex C] Deriving priors from "
            "Stage 0/1/2 and Annex B artifacts "
            "using one structured model call.",
            flush=True,
        )

        derivation = (
            derive_annexc_from_prior_artifacts(
                sources=sources,
                policy=policy,
                llm=reason_llm,
            )
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
            "Annex C priors were derived from prior-stage "
            f"artifacts and written to {derivation_path}. "
            "Review the derivation and write "
            f"{approval_path} before Annex C scoring. "
            "Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    derivation = (
        run_context.read_stamped_json(
            derivation_path
        )
    )
    config = (
        run_context.read_stamped_json(
            config_path
        )
    )

    derivation_validation = (
        validate_artifact_derivation(
            derivation,
            sources=sources,
            policy=policy,
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

    decision = evaluate_derivation_approval(
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

    # The approved derivation resolves the Annex C transition gate.
    # Persist PASS so Stage 3 does not continue seeing the earlier BLOCKED
    # status from the unresolved derivation attempt.    return decision

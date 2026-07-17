from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import run_context
from src.annexc_artifact_gate import (
    load_prior_stage_artifacts,
    validate_artifact_derivation,
)
from src.annexc_derivation import (
    annexc_derivation_hash,
    compile_bbn_assessment_config,
    load_derivation_policy,
)
from src.bbn_validation import (
    EXPECTED_DEFENSIVE_CONTROLS,
    validate_bbn_assessment_config,
)


RUN_ID = os.environ.get(
    "RUN",
    "vaf_20260714_155844",
)

RUN_DIR = Path("outputs") / RUN_ID
INPUT_PATH = RUN_DIR / "annexc_analyst_input.json"
DERIVATION_PATH = RUN_DIR / "annexc_derivation.json"
CONFIG_PATH = RUN_DIR / "annexc_assessment_config.json"
APPROVAL_PATH = RUN_DIR / "annexc_derivation_approval.json"
RESOLUTION_PATH = RUN_DIR / "annexc_analyst_resolution.json"
POLICY_PATH = Path(
    "config/annexc_derivation_policy.json"
).resolve()

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

STATE_TO_BOOLEAN = {
    "DEPLOYED": True,
    "NOT_DEPLOYED": False,
}

UNRESOLVED_STATES = {
    "PARTIALLY_DEPLOYED",
    "UNKNOWN",
}

CONSERVATIVE_POLICY = "CONSERVATIVE_FALSE"


def fail(message: str) -> None:
    raise SystemExit(
        f"\nERROR: {message}\n"
    )


def required_string(
    value: Any,
    *,
    path: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        fail(
            f"{path} must be a non-empty string."
        )

    return value.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return (
        f"sha256:{digest.hexdigest()}"
    )


def unwrap_json_document(
    document: Any,
    *,
    expected_run_id: str,
    expected_corpus_hash: str,
) -> dict:
    if not isinstance(document, dict):
        fail(
            "annexc_analyst_input.json must "
            "contain a JSON object."
        )

    if (
        "_meta" not in document
        and "data" not in document
    ):
        return document

    meta = document.get("_meta")
    data = document.get("data")

    if not isinstance(meta, dict):
        fail(
            "Stamped analyst input has no "
            "valid _meta object."
        )

    if not isinstance(data, dict):
        fail(
            "Stamped analyst input has no "
            "valid data object."
        )

    if (
        meta.get("run_id")
        != expected_run_id
    ):
        fail(
            "Analyst input belongs to a "
            "different run."
        )

    if (
        meta.get("corpus_manifest_hash")
        != expected_corpus_hash
    ):
        fail(
            "Analyst input corpus hash does "
            "not match the active run."
        )

    return data


def validation_passed(
    result: Any,
) -> bool:
    if isinstance(result, bool):
        return result

    if isinstance(result, dict):
        return bool(
            result.get("is_valid")
        )

    return False


for required_path in (
    INPUT_PATH,
    DERIVATION_PATH,
    POLICY_PATH,
):
    if not required_path.is_file():
        fail(
            "Required file does not exist: "
            f"{required_path}"
        )


derivation_envelope = json.loads(
    DERIVATION_PATH.read_text(
        encoding="utf-8"
    )
)

meta = derivation_envelope.get(
    "_meta"
)

if not isinstance(meta, dict):
    fail(
        "annexc_derivation.json has no "
        "stamped _meta object."
    )

if meta.get("run_id") != RUN_ID:
    fail(
        "Derivation run ID does not "
        f"match RUN={RUN_ID}."
    )

corpus_hash = required_string(
    meta.get(
        "corpus_manifest_hash"
    ),
    path=(
        "annexc_derivation._meta."
        "corpus_manifest_hash"
    ),
)

run_context.set_active_run(
    run_id=RUN_ID,
    corpus_manifest_hash=corpus_hash,
    out_dir=str(RUN_DIR),
)

derivation = (
    run_context.read_stamped_json(
        str(DERIVATION_PATH)
    )
)

raw_input = json.loads(
    INPUT_PATH.read_text(
        encoding="utf-8"
    )
)

analyst_input = unwrap_json_document(
    raw_input,
    expected_run_id=RUN_ID,
    expected_corpus_hash=corpus_hash,
)

review = analyst_input.get(
    "review"
)

if not isinstance(review, dict):
    fail(
        "review must be a JSON object."
    )

analyst_name = required_string(
    review.get("analyst_name"),
    path="review.analyst_name",
)

analyst_role = required_string(
    review.get("analyst_role"),
    path="review.analyst_role",
)

review_notes = review.get(
    "review_notes",
    "",
)

if not isinstance(
    review_notes,
    str,
):
    fail(
        "review.review_notes must "
        "be a string."
    )

review_notes = review_notes.strip()


tempo_input = analyst_input.get(
    "tempo"
)

if not isinstance(
    tempo_input,
    dict,
):
    fail(
        "tempo must be a JSON object."
    )

tempo_value = str(
    tempo_input.get(
        "value",
        "",
    )
).strip().upper()

if tempo_value not in ALLOWED_TEMPO:
    fail(
        "tempo.value must be LOW, "
        "MEDIUM, or HIGH."
    )

tempo_confidence = str(
    tempo_input.get(
        "confidence",
        "",
    )
).strip().upper()

if (
    tempo_confidence
    not in ALLOWED_CONFIDENCE
):
    fail(
        "tempo.confidence must be LOW, "
        "MEDIUM, or HIGH."
    )

tempo_reasoning = required_string(
    tempo_input.get(
        "reasoning"
    ),
    path="tempo.reasoning",
)


compilation = analyst_input.get(
    "compilation",
    {},
)

if not isinstance(
    compilation,
    dict,
):
    fail(
        "compilation must be "
        "a JSON object."
    )

unresolved_policy = str(
    compilation.get(
        "unresolved_control_policy",
        "",
    )
).strip().upper()

acknowledgement = str(
    compilation.get(
        "acknowledgement",
        "",
    )
).strip()


posture_input = analyst_input.get(
    "defensive_posture"
)

if not isinstance(
    posture_input,
    dict,
):
    fail(
        "defensive_posture must "
        "be a JSON object."
    )

expected_controls = set(
    EXPECTED_DEFENSIVE_CONTROLS
)

actual_controls = set(
    posture_input
)

missing_controls = sorted(
    expected_controls
    - actual_controls
)

unexpected_controls = sorted(
    actual_controls
    - expected_controls
)

if (
    missing_controls
    or unexpected_controls
):
    fail(
        "defensive_posture control set "
        "is incorrect. "
        f"Missing={missing_controls}; "
        f"unexpected={unexpected_controls}"
    )


compiled_posture: dict[
    str,
    bool,
] = {}

normalized_controls: dict[
    str,
    dict[str, Any],
] = {}

conservatively_compiled: list[
    str
] = []


for control in sorted(
    expected_controls
):
    entry = posture_input[
        control
    ]

    if not isinstance(
        entry,
        dict,
    ):
        fail(
            "defensive_posture."
            f"{control} must be "
            "a JSON object."
        )

    state = str(
        entry.get(
            "deployment_state",
            "",
        )
    ).strip().upper()

    confidence = str(
        entry.get(
            "confidence",
            "",
        )
    ).strip().upper()

    if (
        confidence
        not in ALLOWED_CONFIDENCE
    ):
        fail(
            "defensive_posture."
            f"{control}.confidence "
            "must be LOW, MEDIUM, "
            "or HIGH."
        )

    reasoning = required_string(
        entry.get(
            "reasoning"
        ),
        path=(
            "defensive_posture."
            f"{control}.reasoning"
        ),
    )

    normalized_entry = {
        **entry,
        "deployment_state": state,
        "confidence": confidence,
        "reasoning": reasoning,
    }

    if state in STATE_TO_BOOLEAN:
        compiled_value = (
            STATE_TO_BOOLEAN[state]
        )

        normalized_entry[
            "compiled_value"
        ] = compiled_value

        normalized_entry[
            "compilation_basis"
        ] = (
            "DIRECT_DEPLOYMENT_STATE"
        )

    elif state in UNRESOLVED_STATES:
        if (
            unresolved_policy
            != CONSERVATIVE_POLICY
        ):
            fail(
                f"{control}={state} requires "
                "compilation."
                "unresolved_control_policy="
                "CONSERVATIVE_FALSE."
            )

        if not acknowledgement:
            fail(
                "compilation.acknowledgement "
                "is required when using "
                "CONSERVATIVE_FALSE."
            )

        compiled_value = False

        normalized_entry[
            "compiled_value"
        ] = False

        normalized_entry[
            "compilation_basis"
        ] = (
            CONSERVATIVE_POLICY
        )

        normalized_entry[
            "compilation_note"
        ] = acknowledgement

        conservatively_compiled.append(
            f"{control}={state}"
        )

    else:
        fail(
            "defensive_posture."
            f"{control}.deployment_state "
            "must be DEPLOYED, "
            "NOT_DEPLOYED, "
            "PARTIALLY_DEPLOYED, "
            f"or UNKNOWN; got {state!r}."
        )

    compiled_posture[
        control
    ] = compiled_value

    normalized_controls[
        control
    ] = normalized_entry


input_hash = sha256_file(
    INPUT_PATH
)

analyst_evidence = {
    "source_type": (
        "ANALYST_JUDGMENT"
    ),
    "source_file": (
        INPUT_PATH.name
    ),
    "source_sha256": (
        input_hash
    ),
    "approved_by": (
        analyst_name
    ),
    "reviewer_role": (
        analyst_role
    ),
}


derivation["priors"][
    "tempo"
] = {
    "field": (
        "adversary.tempo"
    ),
    "value": tempo_value,
    "status": "SUPPORTED",
    "source_mode": (
        "ANALYST_JUDGMENT"
    ),
    "confidence": (
        tempo_confidence
    ),
    "reasoning": (
        tempo_reasoning
    ),
    "evidence": [
        {
            **analyst_evidence,
            "config_field": (
                "adversary.tempo"
            ),
        }
    ],
}


confirmed_deployed = sorted(
    control
    for control, entry
    in normalized_controls.items()
    if (
        entry[
            "deployment_state"
        ]
        == "DEPLOYED"
    )
)

confirmed_not_deployed = sorted(
    control
    for control, entry
    in normalized_controls.items()
    if (
        entry[
            "deployment_state"
        ]
        == "NOT_DEPLOYED"
    )
)

partially_deployed = sorted(
    control
    for control, entry
    in normalized_controls.items()
    if (
        entry[
            "deployment_state"
        ]
        == "PARTIALLY_DEPLOYED"
    )
)

unknown_controls = sorted(
    control
    for control, entry
    in normalized_controls.items()
    if (
        entry[
            "deployment_state"
        ]
        == "UNKNOWN"
    )
)

posture_confidences = {
    entry["confidence"]
    for entry
    in normalized_controls.values()
}

if posture_confidences == {
    "HIGH"
}:
    posture_confidence = "HIGH"
elif "LOW" in posture_confidences:
    posture_confidence = "LOW"
else:
    posture_confidence = "MEDIUM"

posture_reasoning = (
    "Explicit analyst assessment from "
    "annexc_analyst_input.json. "
    "Confirmed deployed: "
    f"{confirmed_deployed or ['none']}. "
    "Confirmed not deployed: "
    f"{confirmed_not_deployed or ['none']}. "
    "Partially deployed controls compiled "
    "conservatively as false: "
    f"{partially_deployed or ['none']}. "
    "Unknown controls compiled "
    "conservatively as false: "
    f"{unknown_controls or ['none']}."
)

derivation["priors"][
    "defensive_posture"
] = {
    "field": (
        "defensive_posture"
    ),
    "value": compiled_posture,
    "status": "SUPPORTED",
    "source_mode": (
        "ANALYST_JUDGMENT"
    ),
    "confidence": (
        posture_confidence
    ),
    "reasoning": (
        posture_reasoning
    ),
    "evidence": [
        {
            **analyst_evidence,
            "config_field": (
                "defensive_posture"
            ),
            "assessment_states": {
                control: entry[
                    "deployment_state"
                ]
                for control, entry
                in normalized_controls.items()
            },
            "compilation_policy": (
                unresolved_policy
                or "DIRECT_ONLY"
            ),
        }
    ],
}


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

if not validation_passed(
    config_validation
):
    print(
        json.dumps(
            config_validation,
            indent=2,
        )
    )

    fail(
        "Compiled BBN assessment "
        "configuration failed validation. "
        "Nothing was written."
    )


sources = (
    load_prior_stage_artifacts(
        out_dir=str(RUN_DIR),
        run_context=run_context,
    )
)

policy = (
    load_derivation_policy(
        str(POLICY_PATH)
    )
)

derivation[
    "compiled_config"
] = config

derivation[
    "config_validation"
] = config_validation

derivation.pop(
    "review_subject_hash",
    None,
)

derivation_validation = (
    validate_artifact_derivation(
        derivation,
        sources=sources,
        policy=policy,
    )
)

bad_priors = {
    field: status
    for field, status
    in derivation_validation.get(
        "priors",
        {},
    ).items()
    if status not in {
        "SUPPORTED",
        "DEFAULTED",
    }
}

if (
    not derivation_validation.get(
        "is_valid"
    )
    or bad_priors
):
    print(
        json.dumps(
            derivation_validation,
            indent=2,
        )
    )

    fail(
        "Revised derivation is not fully "
        "resolved. Nothing was written."
    )


review_hash = (
    annexc_derivation_hash(
        derivation,
        corpus_manifest_hash=(
            corpus_hash
        ),
    )
)

derivation[
    "review_subject_hash"
] = review_hash


now = datetime.now(
    timezone.utc
)

approved_at = now.strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)

timestamp = now.strftime(
    "%Y%m%dT%H%M%SZ"
)

approval = {
    "approval_id": (
        f"ADC-{timestamp}"
    ),
    "decision": "APPROVED",
    "approved_by": analyst_name,
    "reviewer_role": analyst_role,
    "approved_at": approved_at,
    "rationale": (
        review_notes
        or (
            "Reviewed the Annex C priors "
            "and approved conservative "
            "compilation of partial or "
            "unknown defensive controls."
        )
    ),
    "run_id": RUN_ID,
    "corpus_manifest_hash": (
        corpus_hash
    ),
    "policy_version": (
        derivation[
            "policy_version"
        ]
    ),
    "review_subject_hash": (
        review_hash
    ),
}


resolution = {
    "schema_version": "1.0",
    "analyst_input": {
        "source_file": (
            INPUT_PATH.name
        ),
        "source_sha256": (
            input_hash
        ),
    },
    "analyst": {
        "name": analyst_name,
        "role": analyst_role,
    },
    "tempo": {
        "value": tempo_value,
        "confidence": (
            tempo_confidence
        ),
        "reasoning": (
            tempo_reasoning
        ),
    },
    "defensive_posture": (
        normalized_controls
    ),
    "compiled_defensive_posture": (
        compiled_posture
    ),
    "compilation": {
        "policy": (
            unresolved_policy
            or "DIRECT_ONLY"
        ),
        "acknowledgement": (
            acknowledgement
        ),
        "conservatively_compiled": (
            conservatively_compiled
        ),
    },
    "derivation_validation": (
        derivation_validation
    ),
    "config_validation": (
        config_validation
    ),
    "review_subject_hash": (
        review_hash
    ),
    "approved_at": approved_at,
}


backup_dir = (
    RUN_DIR
    / "quarantine"
    / "annexc-analyst-resolution"
    / timestamp
)

backup_dir.mkdir(
    parents=True,
    exist_ok=True,
)

for path in (
    INPUT_PATH,
    DERIVATION_PATH,
    CONFIG_PATH,
    APPROVAL_PATH,
    RESOLUTION_PATH,
):
    if path.exists():
        shutil.copy2(
            path,
            backup_dir / path.name,
        )


run_context.write_stamped_json(
    str(DERIVATION_PATH),
    derivation,
)

run_context.write_stamped_json(
    str(CONFIG_PATH),
    config,
)

run_context.write_stamped_json(
    str(RESOLUTION_PATH),
    resolution,
)

run_context.write_stamped_json(
    str(APPROVAL_PATH),
    approval,
)


print()
print(
    "Annex C analyst input applied successfully."
)
print(
    f"Run: {RUN_ID}"
)
print(
    f"Tempo: {tempo_value}"
)
print(
    "Compiled defensive posture:"
)
print(
    json.dumps(
        compiled_posture,
        indent=2,
    )
)
print(
    "Conservatively compiled:"
)
print(
    json.dumps(
        conservatively_compiled,
        indent=2,
    )
)
print(
    f"Review hash: {review_hash}"
)
print(
    f"Approval: {APPROVAL_PATH}"
)
print(
    f"Backup: {backup_dir}"
)

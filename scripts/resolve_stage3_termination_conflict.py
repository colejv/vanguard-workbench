from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src import run_context
from src.stage3_schema import Stage3TestPlan
from src.stage3_validation import (
    build_stage3_validation_report,
    check_stage3_artifact_consistency,
    validate_stage3_test_plan,
)


RUN_ID = os.environ.get(
    "RUN",
    "vaf_20260714_155844",
)

RUN_DIR = REPOSITORY_ROOT / "outputs" / RUN_ID

STAGE3_PROSE_PATH = RUN_DIR / "stage3.md"
STAGE3_PLAN_PATH = RUN_DIR / "stage3_test_plan.json"
STAGE3_VALIDATION_PATH = (
    RUN_DIR / "stage3_test_plan_validation.json"
)
STAGE2_PATH = RUN_DIR / "stage2_vectors.json"
KCAG_PATH = RUN_DIR / "kcag_report.json"
TECHNIQUE_INDEX_PATH = (
    REPOSITORY_ROOT
    / "corpus-index"
    / "technique_index.json"
)

STAGE4_ARTIFACTS = (
    "stage4_mission_plan.md",
    "stage4_execution_plan.json",
    "stage4_execution_plan_validation.json",
    "stage4_safety_contract.json",
    "stage4_identity_baseline.json",
)


def unwrap(document: Any) -> Any:
    if (
        isinstance(document, dict)
        and "_meta" in document
        and "data" in document
    ):
        return document["data"]

    return document


def validation_passed(result: Any) -> bool:
    if isinstance(result, bool):
        return result

    if not isinstance(result, dict):
        return False

    if "is_valid" in result:
        return bool(result["is_valid"])

    return result.get("status") == "PASS"


def patch_termination_fields(
    value: Any,
    *,
    path: str = "",
) -> list[str]:
    """
    Set existing maximum-termination fields to 15 seconds.

    The function does not add guessed schema fields. It changes only existing
    keys whose names explicitly identify a termination duration or limit.
    """

    patched: list[str] = []

    if isinstance(value, dict):
        for key in list(value):
            child_path = (
                f"{path}.{key}"
                if path
                else key
            )
            normalized_key = (
                key.lower()
                .replace("-", "_")
                .replace(" ", "_")
            )

            is_termination_limit = (
                "termination" in normalized_key
                and any(
                    marker in normalized_key
                    for marker in (
                        "second",
                        "time",
                        "duration",
                        "maximum",
                        "max",
                        "limit",
                    )
                )
            )

            if is_termination_limit:
                current = value[key]

                if isinstance(current, bool):
                    continue

                if isinstance(current, (int, float)):
                    value[key] = 15
                    patched.append(child_path)
                    continue

                if isinstance(current, str):
                    value[key] = "15 seconds"
                    patched.append(child_path)
                    continue

            patched.extend(
                patch_termination_fields(
                    value[key],
                    path=child_path,
                )
            )

    elif isinstance(value, list):
        for index, item in enumerate(value):
            patched.extend(
                patch_termination_fields(
                    item,
                    path=f"{path}[{index}]",
                )
            )

    return patched


for required_path in (
    STAGE3_PROSE_PATH,
    STAGE3_PLAN_PATH,
    STAGE2_PATH,
    KCAG_PATH,
    TECHNIQUE_INDEX_PATH,
):
    if not required_path.is_file():
        raise SystemExit(
            f"Missing required file: {required_path}"
        )


plan_envelope = json.loads(
    STAGE3_PLAN_PATH.read_text(
        encoding="utf-8"
    )
)

metadata = plan_envelope.get("_meta")

if not isinstance(metadata, dict):
    raise SystemExit(
        "stage3_test_plan.json has no stamped _meta object."
    )

corpus_hash = metadata.get(
    "corpus_manifest_hash"
)

if not isinstance(corpus_hash, str) or not corpus_hash:
    raise SystemExit(
        "stage3_test_plan.json has no corpus hash."
    )

run_context.set_active_run(
    run_id=RUN_ID,
    corpus_manifest_hash=corpus_hash,
    out_dir=str(RUN_DIR),
)

stage3_prose = run_context.read_stamped_prose(
    str(STAGE3_PROSE_PATH)
)

stage3_plan = run_context.read_stamped_json(
    str(STAGE3_PLAN_PATH)
)

stage2_vectors = run_context.read_stamped_json(
    str(STAGE2_PATH)
)

kcag_report = run_context.read_stamped_json(
    str(KCAG_PATH)
)

technique_index_document = json.loads(
    TECHNIQUE_INDEX_PATH.read_text(
        encoding="utf-8"
    )
)

technique_index = unwrap(
    technique_index_document
)


# Replace every authoritative Stage 3 "Maximum termination time" value.
termination_line = re.compile(
    r"(?im)"
    r"(?P<prefix>"
    r"(?:\*\*)?"
    r"Maximum termination time"
    r"(?:\*\*)?"
    r"\s*:\s*"
    r")"
    r"<?\s*"
    r"\d+(?:\.\d+)?"
    r"\s*"
    r"(?:seconds?|minutes?|hours?)"
    r"\s*>?"
)

updated_prose, prose_replacements = (
    termination_line.subn(
        lambda match: (
            match.group("prefix")
            + "15 seconds"
        ),
        stage3_prose,
    )
)

if prose_replacements == 0:
    raise SystemExit(
        "No 'Maximum termination time' field was found "
        "in stage3.md. Nothing was changed."
    )


patched_json_paths = patch_termination_fields(
    stage3_plan
)

if not patched_json_paths:
    raise SystemExit(
        "No existing maximum-termination field was found "
        "in stage3_test_plan.json. Nothing was changed."
    )


validated_model = Stage3TestPlan.model_validate(
    stage3_plan
)

normalized_plan = validated_model.model_dump(
    mode="json"
)

plan_validation = validate_stage3_test_plan(
    plan=normalized_plan,
    stage2_vectors=stage2_vectors,
    kcag_report=kcag_report,
    technique_index=technique_index,
)

consistency = check_stage3_artifact_consistency(
    stage3_text=updated_prose,
    test_plan=normalized_plan,
)

validation_report = build_stage3_validation_report(
    plan=normalized_plan,
    plan_validation=plan_validation,
    consistency=consistency,
    artifact_path=str(STAGE3_PLAN_PATH),
)

print("Stage 3 prose replacements:", prose_replacements)
print(
    "Stage 3 JSON fields updated:",
    json.dumps(
        patched_json_paths,
        indent=2,
    ),
)
print(
    "Plan validation:",
    json.dumps(
        plan_validation,
        indent=2,
    ),
)
print(
    "Artifact consistency:",
    json.dumps(
        consistency,
        indent=2,
    ),
)

if not validation_passed(plan_validation):
    raise SystemExit(
        "\nUpdated Stage 3 plan failed semantic validation. "
        "No authoritative files were changed."
    )

if not validation_passed(consistency):
    raise SystemExit(
        "\nUpdated Stage 3 artifacts failed consistency validation. "
        "No authoritative files were changed."
    )

if not validation_report.get("is_valid"):
    raise SystemExit(
        "\nUpdated Stage 3 validation report is not valid. "
        "No authoritative files were changed."
    )


timestamp = datetime.now(
    timezone.utc
).strftime("%Y%m%dT%H%M%SZ")

backup_dir = (
    RUN_DIR
    / "quarantine"
    / "stage3-termination-resolution"
    / timestamp
)

backup_dir.mkdir(
    parents=True,
    exist_ok=True,
)

for artifact_path in (
    STAGE3_PROSE_PATH,
    STAGE3_PLAN_PATH,
    STAGE3_VALIDATION_PATH,
):
    if artifact_path.exists():
        shutil.copy2(
            artifact_path,
            backup_dir / artifact_path.name,
        )

for artifact_name in STAGE4_ARTIFACTS:
    artifact_path = RUN_DIR / artifact_name

    if artifact_path.exists():
        shutil.move(
            str(artifact_path),
            str(backup_dir / artifact_name),
        )


# Write and restamp Stage 3 prose.
STAGE3_PROSE_PATH.write_text(
    updated_prose.rstrip() + "\n",
    encoding="utf-8",
)

run_context.stamp_prose_file(
    str(STAGE3_PROSE_PATH)
)

run_context.write_stamped_json(
    str(STAGE3_PLAN_PATH),
    normalized_plan,
)

run_context.write_stamped_json(
    str(STAGE3_VALIDATION_PATH),
    validation_report,
)


print()
print("Stage 3 termination conflict resolved.")
print("Maximum termination time: 15 seconds")
print("Updated:", STAGE3_PROSE_PATH)
print("Updated:", STAGE3_PLAN_PATH)
print("Updated:", STAGE3_VALIDATION_PATH)
print("Stage 4 artifacts quarantined:", backup_dir)

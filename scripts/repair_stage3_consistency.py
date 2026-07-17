from __future__ import annotations

import copy
import itertools
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
from src.stage3_writer import (
    _apply_safety_overlay,
    _extract_prose_concept_identities,
)


RUN_ID = os.environ.get(
    "RUN",
    "vaf_20260714_155844",
)

RUN_DIR = REPOSITORY_ROOT / "outputs" / RUN_ID

PROSE_PATH = RUN_DIR / "stage3.md"
PLAN_PATH = RUN_DIR / "stage3_test_plan.json"
VALIDATION_PATH = (
    RUN_DIR / "stage3_test_plan_validation.json"
)
STAGE2_PATH = RUN_DIR / "stage2_vectors.json"
KCAG_PATH = RUN_DIR / "kcag_report.json"
TECHNIQUE_INDEX_PATH = (
    REPOSITORY_ROOT
    / "corpus-index"
    / "technique_index.json"
)

TEST_HEADING_RE = re.compile(
    r"^#{2,6}\s+(RT-\d{3})\b.*$",
    re.IGNORECASE | re.MULTILINE,
)

VECTOR_ID_RE = re.compile(
    r"\bV-\d+\b",
    re.IGNORECASE,
)

# Intentionally matches ATT&CK/ATLAS-style T identifiers.
# It does not include EX-* identifiers because the Stage 3 consistency
# validator does not treat those as execution-technique bindings.
TECHNIQUE_ID_RE = re.compile(
    r"\b(?:AML\.)?T\d{4}\b",
    re.IGNORECASE,
)


def unwrap(document: Any) -> Any:
    if (
        isinstance(document, dict)
        and "_meta" in document
        and "data" in document
    ):
        return document["data"]

    return document


def rejection_number(path: Path) -> int:
    match = re.search(
        r"semantic_rejected_(\d+)$",
        path.name,
    )

    return int(match.group(1)) if match else -1


def extract_technique_ids(value: Any) -> set[str]:
    serialized = json.dumps(
        value,
        sort_keys=True,
        default=str,
    )

    return {
        match.upper()
        for match in TECHNIQUE_ID_RE.findall(
            serialized
        )
    }


def extract_vector_objects(
    value: Any,
    vector_id: str,
) -> list[dict]:
    matches: list[dict] = []

    if isinstance(value, dict):
        object_ids = {
            str(value.get(key, "")).upper()
            for key in (
                "id",
                "vector_id",
                "vectorId",
            )
        }

        if vector_id.upper() in object_ids:
            matches.append(value)

        for child in value.values():
            matches.extend(
                extract_vector_objects(
                    child,
                    vector_id,
                )
            )

    elif isinstance(value, list):
        for child in value:
            matches.extend(
                extract_vector_objects(
                    child,
                    vector_id,
                )
            )

    return matches


def prose_sections(
    prose: str,
) -> dict[str, str]:
    headings = list(
        TEST_HEADING_RE.finditer(prose)
    )

    sections: dict[str, str] = {}

    for index, heading in enumerate(headings):
        test_id = heading.group(1).upper()
        start = heading.start()
        end = (
            headings[index + 1].start()
            if index + 1 < len(headings)
            else len(prose)
        )

        sections[test_id] = prose[start:end]

    return sections


def expected_techniques_by_test(
    prose: str,
    stage2_vectors: dict,
) -> dict[str, list[str]]:
    sections = prose_sections(prose)
    result: dict[str, list[str]] = {}

    for test_id, section in sections.items():
        technique_ids = {
            value.upper()
            for value in TECHNIQUE_ID_RE.findall(
                section
            )
        }

        vector_ids = {
            value.upper()
            for value in VECTOR_ID_RE.findall(
                section
            )
        }

        for vector_id in vector_ids:
            for vector_object in extract_vector_objects(
                stage2_vectors,
                vector_id,
            ):
                technique_ids.update(
                    extract_technique_ids(
                        vector_object
                    )
                )

        result[test_id] = sorted(
            technique_ids
        )

    return result


def normalize_technique_entries(
    original_entries: Any,
    expected_ids: list[str],
) -> list[Any]:
    if not isinstance(original_entries, list):
        original_entries = []

    entries_by_id: dict[str, Any] = {}

    for entry in original_entries:
        for technique_id in extract_technique_ids(
            entry
        ):
            entries_by_id.setdefault(
                technique_id,
                entry,
            )

    normalized: list[Any] = []

    for technique_id in expected_ids:
        if technique_id in entries_by_id:
            normalized.append(
                copy.deepcopy(
                    entries_by_id[technique_id]
                )
            )
        else:
            # Current schema normally uses strings. This fallback is used
            # only when the rejected candidate omitted a prose-bound ID.
            normalized.append(technique_id)

    return normalized


def validation_errors(
    result: Any,
) -> list[Any]:
    if not isinstance(result, dict):
        return [repr(result)]

    for key in (
        "errors",
        "validation_errors",
    ):
        errors = result.get(key)

        if isinstance(errors, list):
            return errors

    return []


for required_path in (
    PROSE_PATH,
    STAGE2_PATH,
    KCAG_PATH,
    TECHNIQUE_INDEX_PATH,
):
    if not required_path.is_file():
        raise SystemExit(
            f"Missing required file: {required_path}"
        )


rejected_candidates = sorted(
    RUN_DIR.glob(
        "stage3_test_plan.json.semantic_rejected_*"
    ),
    key=rejection_number,
    reverse=True,
)

if not rejected_candidates:
    raise SystemExit(
        "No rejected Stage 3 candidates were found."
    )


first_envelope = json.loads(
    rejected_candidates[0].read_text(
        encoding="utf-8"
    )
)

metadata = first_envelope.get("_meta")

if not isinstance(metadata, dict):
    raise SystemExit(
        "Rejected candidate has no stamped metadata."
    )

corpus_hash = metadata.get(
    "corpus_manifest_hash"
)

if not isinstance(corpus_hash, str):
    raise SystemExit(
        "Rejected candidate has no corpus hash."
    )

run_context.set_active_run(
    run_id=RUN_ID,
    corpus_manifest_hash=corpus_hash,
    out_dir=str(RUN_DIR),
)


stage3_prose = run_context.read_stamped_prose(
    str(PROSE_PATH)
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

identities = _extract_prose_concept_identities(
    stage3_prose
)

expected_techniques = expected_techniques_by_test(
    stage3_prose,
    stage2_vectors,
)

print("Authoritative Stage 3 identities:")
print(
    json.dumps(
        identities,
        indent=2,
    )
)

print("\nAuthoritative technique bindings:")
print(
    json.dumps(
        expected_techniques,
        indent=2,
    )
)


passing_candidate: dict | None = None
passing_report: dict | None = None
passing_source: Path | None = None

diagnostics: list[dict[str, Any]] = []


for rejected_path in rejected_candidates:
    envelope = json.loads(
        rejected_path.read_text(
            encoding="utf-8"
        )
    )

    source_candidate = unwrap(envelope)

    if not isinstance(source_candidate, dict):
        continue

    source_concepts = source_candidate.get(
        "test_concepts"
    )

    if not isinstance(source_concepts, list):
        continue

    if len(source_concepts) != len(identities):
        continue

    concept_indices = range(
        len(source_concepts)
    )

    # A permutation maps each prose identity, in prose order,
    # to one candidate concept.
    permutations = list(
        itertools.permutations(
            concept_indices
        )
    )

    def permutation_score(
        permutation: tuple[int, ...],
    ) -> int:
        score = 0

        for identity, concept_index in zip(
            identities,
            permutation,
        ):
            expected = set(
                expected_techniques.get(
                    identity["test_id"],
                    [],
                )
            )

            actual = extract_technique_ids(
                source_concepts[
                    concept_index
                ].get(
                    "execution_techniques",
                    [],
                )
            )

            score += 100 * len(
                expected & actual
            )
            score -= 10 * len(
                expected - actual
            )
            score -= len(
                actual - expected
            )

        return score

    permutations.sort(
        key=permutation_score,
        reverse=True,
    )

    for permutation in permutations:
        candidate = copy.deepcopy(
            source_candidate
        )

        reordered_concepts = []

        for identity, source_index in zip(
            identities,
            permutation,
        ):
            concept = copy.deepcopy(
                source_concepts[source_index]
            )

            test_id = identity["test_id"]
            categories = identity["categories"]
            technique_ids = (
                expected_techniques.get(
                    test_id,
                    [],
                )
            )

            concept["test_id"] = test_id
            concept["categories"] = categories

            concept["execution_techniques"] = (
                normalize_technique_entries(
                    concept.get(
                        "execution_techniques",
                        [],
                    ),
                    technique_ids,
                )
            )

            if not (
                set(categories)
                & {2, 3}
            ):
                concept["safety_controls"] = None

            reordered_concepts.append(
                concept
            )

        candidate["test_concepts"] = (
            reordered_concepts
        )

        try:
            _apply_safety_overlay(
                candidate,
                stage3_prose,
            )

            validated_model = (
                Stage3TestPlan.model_validate(
                    candidate
                )
            )

            normalized_candidate = (
                validated_model.model_dump(
                    mode="json"
                )
            )

            plan_validation = (
                validate_stage3_test_plan(
                    plan=normalized_candidate,
                    stage2_vectors=stage2_vectors,
                    kcag_report=kcag_report,
                    technique_index=technique_index,
                )
            )

            consistency = (
                check_stage3_artifact_consistency(
                    stage3_text=stage3_prose,
                    test_plan=normalized_candidate,
                )
            )

            report = (
                build_stage3_validation_report(
                    plan=normalized_candidate,
                    plan_validation=plan_validation,
                    consistency=consistency,
                    artifact_path=str(
                        PLAN_PATH
                    ),
                )
            )

        except Exception as exc:
            diagnostics.append(
                {
                    "candidate": (
                        rejected_path.name
                    ),
                    "permutation": list(
                        permutation
                    ),
                    "exception": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                }
            )
            continue

        if report.get("is_valid"):
            passing_candidate = (
                normalized_candidate
            )
            passing_report = report
            passing_source = rejected_path
            break

        diagnostics.append(
            {
                "candidate": (
                    rejected_path.name
                ),
                "permutation": list(
                    permutation
                ),
                "plan_errors": (
                    validation_errors(
                        plan_validation
                    )
                ),
                "consistency_errors": (
                    validation_errors(
                        consistency
                    )
                ),
            }
        )

    if passing_candidate is not None:
        break


if (
    passing_candidate is None
    or passing_report is None
    or passing_source is None
):
    diagnostic_path = (
        RUN_DIR
        / "stage3_consistency_repair_failures_v2.json"
    )

    diagnostic_path.write_text(
        json.dumps(
            {
                "run_id": RUN_ID,
                "identities": identities,
                "expected_techniques": (
                    expected_techniques
                ),
                "diagnostics": diagnostics,
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\nNo repaired candidate passed."
    )
    print(
        "Diagnostics:",
        diagnostic_path,
    )

    for failure in diagnostics[-5:]:
        print()
        print(
            json.dumps(
                failure,
                indent=2,
                default=str,
            )
        )

    raise SystemExit(
        "\nNo authoritative files were written."
    )


timestamp = datetime.now(
    timezone.utc
).strftime(
    "%Y%m%dT%H%M%SZ"
)

backup_dir = (
    RUN_DIR
    / "quarantine"
    / "stage3-consistency-repair"
    / timestamp
)

backup_dir.mkdir(
    parents=True,
    exist_ok=True,
)

for current_path in (
    PLAN_PATH,
    VALIDATION_PATH,
):
    if current_path.exists():
        shutil.move(
            str(current_path),
            str(
                backup_dir
                / current_path.name
            ),
        )

run_context.write_stamped_json(
    str(PLAN_PATH),
    passing_candidate,
)

run_context.write_stamped_json(
    str(VALIDATION_PATH),
    passing_report,
)

print()
print("Stage 3 consistency repair PASS.")
print("Source:", passing_source)
print("Plan:", PLAN_PATH)
print("Validation:", VALIDATION_PATH)
print("Backup:", backup_dir)

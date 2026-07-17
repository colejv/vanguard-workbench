"""
Comprehensive final-assessment report generation.

This module consumes only completed, run-stamped assessment artifacts. It
does not read the original corpus, rerun prior stages, recalculate KCAG/BBN
results, create new test concepts, or grant execution authorization.

Pipeline:

    verified artifacts
        -> deterministic canonical context
        -> one structured narrative-synthesis call
        -> deterministic Markdown rendering
        -> deterministic completeness/provenance validation
        -> assessment completion record
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src import run_context
from src.structured_output import generate_structured_json


FINAL_REPORT_SCHEMA_VERSION = "1.0"

FINAL_JSON_NAME = "final_assessment_report.json"
FINAL_MARKDOWN_NAME = "final_assessment_report.md"
FINAL_VALIDATION_NAME = "final_report_validation.json"
FINAL_CONTEXT_NAME = "final_report_context.json"
ARTIFACT_INVENTORY_NAME = "artifact_inventory.json"
COMPLETION_NAME = "assessment_completion.json"

FINAL_ARTIFACT_NAMES = (
    FINAL_CONTEXT_NAME,
    ARTIFACT_INVENTORY_NAME,
    FINAL_JSON_NAME,
    FINAL_MARKDOWN_NAME,
    FINAL_VALIDATION_NAME,
    COMPLETION_NAME,
)

REPORT_ID_RE = re.compile(r"^FR-\d{3}$")
FINDING_ID_RE = re.compile(r"^FR-F-\d{3}$")
RECOMMENDATION_ID_RE = re.compile(r"^FR-R-\d{3}$")
ITEM_ID_RE = re.compile(r"^FR-(?:L|U)-\d{3}$")

REQUIRED_STAMPED_JSON = (
    "stage0_output.json",
    "stage1_output.json",
    "stage2_vectors.json",
    "kcag_validation.json",
    "kcag_report.json",
    "annexc_derivation.json",
    "annexc_assessment_config.json",
    "annexc_derivation_approval.json",
    "annexc_analyst_resolution.json",
    "bbn_report.json",
    "bbn_sensitivity.json",
    "stage3_test_plan.json",
    "stage3_test_plan_validation.json",
    "stage4_execution_plan.json",
    "stage4_execution_plan_validation.json",
)

REQUIRED_STAMPED_PROSE = (
    "stage0.md",
    "stage1.md",
    "stage2.md",
    "model_assumptions.md",
    "annexB_kcag.md",
    "annexC_bbn.md",
    "stage3.md",
    "stage4_mission_plan.md",
)

OPTIONAL_STAMPED_PROSE = (
    "stage2_verification.md",
    "corpus_lock_confirmation.md",
)

VALIDATION_ARTIFACTS = {
    "kcag_validation.json",
    "stage3_test_plan_validation.json",
    "stage4_execution_plan_validation.json",
}

PROSE_CHARACTER_LIMIT = 7_000

STAGE_NARRATIVE_KEYS = (
    "stage0",
    "stage1",
    "stage2",
    "annex_b",
    "annex_c",
    "stage3",
    "stage4",
)

SYSTEM_PROMPT = """
You are the final assessment-report synthesizer.

You receive only completed, verified assessment artifacts from one Vanguard
Workbench run. Produce a concise but comprehensive cross-stage narrative.

Hard requirements:

1. Use only supplied artifacts and authoritative facts.
2. Do not read or infer from the original source corpus.
3. Do not recalculate or alter KCAG or Bayesian values.
4. Do not invent components, nodes, goals, vector IDs, framework IDs,
   RT-NNN test concepts, PHASE-NN phases, ACT-NNN actions, roles, evidence,
   approvals, or authorization.
5. KCAG traversal scores are configured heuristics for relative ranking,
   not calibrated empirical probabilities.
6. Bayesian results depend on configured/defaulted priors and analyst
   judgments. Disclose that dependency.
7. Preserve partial, unknown, defaulted, and conservatively compiled states.
8. Stage 4 is a planning artifact. Execution authorization remains
   NOT_GRANTED.
9. Every finding, recommendation, limitation, and unresolved item must cite
   one or more supplied artifact filenames.
10. Return only the schema-constrained JSON object.
""".strip()


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return "sha256:" + digest.hexdigest()


def _final_report_output_paths(
    out_dir: str | Path,
) -> dict[str, str]:
    root = Path(out_dir)

    return {
        "context": str(
            root / FINAL_CONTEXT_NAME
        ),
        "inventory": str(
            root / ARTIFACT_INVENTORY_NAME
        ),
        "report_json": str(
            root / FINAL_JSON_NAME
        ),
        "report_markdown": str(
            root / FINAL_MARKDOWN_NAME
        ),
        "validation": str(
            root / FINAL_VALIDATION_NAME
        ),
        "completion": str(
            root / COMPLETION_NAME
        ),
    }


def validate_existing_final_report(
    out_dir: str | Path,
) -> dict[str, Any]:
    """
    Verify that an existing final-report package is complete, stamped,
    hash-bound, validated, and associated with the active run.

    This is the resume gate used by crew.py. Presence alone never counts as
    completion.
    """

    root = Path(out_dir)
    active = run_context.get_active_run()
    errors: list[str] = []

    paths = {
        name: root / name
        for name in FINAL_ARTIFACT_NAMES
    }

    missing = sorted(
        name
        for name, path in paths.items()
        if not path.is_file()
    )

    if missing:
        return {
            "is_valid": False,
            "status": "INCOMPLETE",
            "errors": [
                "Missing final-report artifacts: "
                + ", ".join(missing)
            ],
            "outputs": _final_report_output_paths(
                root
            ),
        }

    try:
        context = run_context.read_stamped_json(
            str(paths[FINAL_CONTEXT_NAME])
        )
        inventory = run_context.read_stamped_json(
            str(paths[ARTIFACT_INVENTORY_NAME])
        )
        report = run_context.read_stamped_json(
            str(paths[FINAL_JSON_NAME])
        )
        run_context.read_stamped_prose(
            str(paths[FINAL_MARKDOWN_NAME])
        )
        validation = run_context.read_stamped_json(
            str(paths[FINAL_VALIDATION_NAME])
        )
        completion = run_context.read_stamped_json(
            str(paths[COMPLETION_NAME])
        )
    except Exception as exc:
        return {
            "is_valid": False,
            "status": "UNTRUSTED",
            "errors": [
                f"{type(exc).__name__}: {exc}"
            ],
            "outputs": _final_report_output_paths(
                root
            ),
        }

    if completion.get("status") != "COMPLETE":
        errors.append(
            "assessment_completion.json status "
            "is not COMPLETE."
        )

    if completion.get("run_id") != active.run_id:
        errors.append(
            "Completion run_id does not match "
            "the active run."
        )

    if (
        completion.get(
            "corpus_manifest_hash"
        )
        != active.corpus_manifest_hash
    ):
        errors.append(
            "Completion corpus hash does not match "
            "the active run."
        )

    if (
        completion.get(
            "execution_authorization"
        )
        != "NOT_GRANTED"
    ):
        errors.append(
            "Completion artifact does not preserve "
            "execution authorization as NOT_GRANTED."
        )

    if (
        completion.get(
            "final_report_validation_status"
        )
        != "PASS"
    ):
        errors.append(
            "Completion artifact does not record "
            "final-report validation as PASS."
        )

    if (
        validation.get("status") != "PASS"
        or validation.get("is_valid") is not True
    ):
        errors.append(
            "final_report_validation.json is not PASS."
        )

    context_identity = context.get(
        "assessment_identity",
        {},
    )

    if (
        context_identity.get("run_id")
        != active.run_id
    ):
        errors.append(
            "Final-report context run_id mismatch."
        )

    if (
        context_identity.get(
            "corpus_manifest_hash"
        )
        != active.corpus_manifest_hash
    ):
        errors.append(
            "Final-report context corpus hash mismatch."
        )

    report_identity = report.get(
        "assessment_identity",
        {},
    )

    if (
        report_identity.get("run_id")
        != active.run_id
    ):
        errors.append(
            "Final report run_id mismatch."
        )

    if (
        report_identity.get(
            "corpus_manifest_hash"
        )
        != active.corpus_manifest_hash
    ):
        errors.append(
            "Final report corpus hash mismatch."
        )

    if inventory.get("run_id") != active.run_id:
        errors.append(
            "Artifact inventory run_id mismatch."
        )

    if (
        inventory.get(
            "corpus_manifest_hash"
        )
        != active.corpus_manifest_hash
    ):
        errors.append(
            "Artifact inventory corpus hash mismatch."
        )

    context_hash = context.get(
        "context_hash"
    )

    if not isinstance(context_hash, str):
        errors.append(
            "Final-report context has no context hash."
        )

    if report.get("context_hash") != context_hash:
        errors.append(
            "Final report context hash mismatch."
        )

    if (
        completion.get("context_hash")
        != context_hash
    ):
        errors.append(
            "Completion context hash mismatch."
        )

    if (
        report.get(
            "required_disclosures",
            {},
        ).get(
            "execution_authorization"
        )
        != "NOT_GRANTED"
    ):
        errors.append(
            "Final report does not preserve "
            "execution authorization as NOT_GRANTED."
        )

    expected_json_hash = completion.get(
        "final_report_json_sha256"
    )
    actual_json_hash = sha256_file(
        paths[FINAL_JSON_NAME]
    )

    if expected_json_hash != actual_json_hash:
        errors.append(
            "Final-report JSON hash mismatch."
        )

    expected_markdown_hash = completion.get(
        "final_report_markdown_sha256"
    )
    actual_markdown_hash = sha256_file(
        paths[FINAL_MARKDOWN_NAME]
    )

    if (
        expected_markdown_hash
        != actual_markdown_hash
    ):
        errors.append(
            "Final-report Markdown hash mismatch."
        )

    return {
        "is_valid": not errors,
        "status": (
            "PASS"
            if not errors
            else "FAIL"
        ),
        "errors": errors,
        "outputs": _final_report_output_paths(
            root
        ),
    }


def quarantine_existing_final_report_artifacts(
    out_dir: str | Path,
    *,
    label: str = "automatic-final-report-regeneration",
) -> str | None:
    """
    Move existing final-report artifacts out of the authoritative run root
    before regeneration.
    """

    root = Path(out_dir)

    existing = [
        root / name
        for name in FINAL_ARTIFACT_NAMES
        if (root / name).exists()
    ]

    if not existing:
        return None

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S%fZ")

    destination = (
        root
        / "quarantine"
        / label
        / timestamp
    )

    destination.mkdir(
        parents=True,
        exist_ok=False,
    )

    for path in existing:
        shutil.move(
            str(path),
            str(destination / path.name),
        )

    return str(destination)


def generate_or_reuse_final_report(
    *,
    out_dir: str,
    llm: Any,
    timeout_seconds: int = 600,
    force: bool = False,
) -> dict[str, Any]:
    """
    Reuse a valid final report, or regenerate it from verified artifacts.

    Invalid or partial prior outputs are quarantined before regeneration.
    """

    existing = validate_existing_final_report(
        out_dir
    )

    if existing["is_valid"] and not force:
        return {
            "reused": True,
            "quarantine": None,
            "outputs": existing["outputs"],
        }

    quarantine_path = (
        quarantine_existing_final_report_artifacts(
            out_dir
        )
    )

    outputs = generate_and_validate_final_report(
        out_dir=out_dir,
        llm=llm,
        timeout_seconds=timeout_seconds,
    )

    completed = validate_existing_final_report(
        out_dir
    )

    if not completed["is_valid"]:
        raise RuntimeError(
            "Generated final-report package failed "
            "completion verification: "
            + "; ".join(
                completed["errors"]
            )
        )

    return {
        "reused": False,
        "quarantine": quarantine_path,
        "outputs": outputs,
    }


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return "sha256:" + hashlib.sha256(
        encoded
    ).hexdigest()


def _compact_prose(
    text: str,
    *,
    limit: int = PROSE_CHARACTER_LIMIT,
) -> str:
    if len(text) <= limit:
        return text

    tail_length = min(2_000, limit // 4)
    head_length = limit - tail_length

    return (
        text[:head_length]
        + "\n\n[... deterministic context compaction ...]\n\n"
        + text[-tail_length:]
    )


def _recursive_ids(
    value: Any,
    pattern: re.Pattern[str],
) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(child, str):
                    if pattern.fullmatch(child):
                        found.add(child.upper())

                    for match in pattern.findall(child):
                        if isinstance(match, str):
                            found.add(match.upper())

                visit(child)

        elif isinstance(item, list):
            for child in item:
                visit(child)

        elif isinstance(item, str):
            if pattern.fullmatch(item):
                found.add(item.upper())

            for match in pattern.findall(item):
                if isinstance(match, str):
                    found.add(match.upper())

    visit(value)

    return sorted(found)


def _validation_status(
    artifact_name: str,
    payload: Mapping[str, Any],
) -> str:
    if artifact_name in VALIDATION_ARTIFACTS:
        if payload.get("is_valid") is True:
            return "PASS"

        if payload.get("is_consistent") is True:
            return "PASS"

        if payload.get("status") == "PASS":
            return "PASS"

        return "FAIL"

    if artifact_name == "bbn_report.json":
        status = (
            payload.get("status")
            or payload.get("annex_c_status")
        )

        return "PASS" if status == "PASS" else "FAIL"

    if artifact_name == "bbn_sensitivity.json":
        return (
            "PASS"
            if payload.get("status") == "PASS"
            else "FAIL"
        )

    if artifact_name == "stage4_execution_plan.json":
        return (
            "PASS"
            if payload.get("execution_authorization")
            == "NOT_GRANTED"
            else "FAIL"
        )

    return "VERIFIED"


def _state_summary(
    state_document: Mapping[str, Any],
) -> dict[str, Any]:
    stages = state_document.get("stages", {})
    statuses: dict[str, Any] = {}

    if isinstance(stages, Mapping):
        for stage_name, record in stages.items():
            if isinstance(record, Mapping):
                statuses[str(stage_name)] = record.get(
                    "status"
                )

    return {
        "current_stage": state_document.get(
            "current_stage"
        ),
        "stage_statuses": statuses,
        "gap_count": len(
            state_document.get("gap_log", [])
            if isinstance(
                state_document.get("gap_log", []),
                list,
            )
            else []
        ),
        "gate_decision_count": len(
            state_document.get(
                "gate_decisions",
                [],
            )
            if isinstance(
                state_document.get(
                    "gate_decisions",
                    [],
                ),
                list,
            )
            else []
        ),
    }


def _build_authoritative_facts(
    *,
    structured: Mapping[str, Mapping[str, Any]],
    state_document: Mapping[str, Any],
) -> dict[str, Any]:
    stage2 = structured["stage2_vectors.json"]
    kcag = structured["kcag_report.json"]
    annex_c_config = structured[
        "annexc_assessment_config.json"
    ]
    annex_c_derivation = structured[
        "annexc_derivation.json"
    ]
    analyst_resolution = structured[
        "annexc_analyst_resolution.json"
    ]
    bbn = structured["bbn_report.json"]
    sensitivity = structured[
        "bbn_sensitivity.json"
    ]
    stage3 = structured[
        "stage3_test_plan.json"
    ]
    stage4 = structured[
        "stage4_execution_plan.json"
    ]

    node_pattern = re.compile(r"(?:C-[A-Z]-\d+|ADV_START|G_[A-Z0-9_]+)")
    vector_pattern = re.compile(r"V-\d+")
    technique_pattern = re.compile(
        r"(?:AML\.)?T\d{4}(?:\.\d{3})?"
    )

    stage2_node_ids = _recursive_ids(
        stage2,
        node_pattern,
    )
    stage2_goal_ids = sorted(
        node_id
        for node_id in stage2_node_ids
        if node_id.startswith("G_")
    )
    stage2_vector_ids = _recursive_ids(
        stage2,
        vector_pattern,
    )
    technique_ids = _recursive_ids(
        stage2,
        technique_pattern,
    )

    test_concepts = stage3.get(
        "test_concepts",
        [],
    )
    stage3_test_ids = sorted(
        str(concept.get("test_id"))
        for concept in test_concepts
        if isinstance(concept, Mapping)
        and concept.get("test_id")
    )

    stage3_categories = {
        str(concept.get("test_id")): sorted(
            concept.get("categories", [])
        )
        for concept in test_concepts
        if isinstance(concept, Mapping)
        and concept.get("test_id")
    }

    stage4_phases = stage4.get(
        "phases",
        [],
    )

    phase_ids: list[str] = []
    action_ids: list[str] = []
    action_bindings: dict[str, str] = {}

    for phase in stage4_phases:
        if not isinstance(phase, Mapping):
            continue

        phase_id = phase.get("phase_id")

        if phase_id:
            phase_ids.append(str(phase_id))

        for action in phase.get("actions", []):
            if not isinstance(action, Mapping):
                continue

            action_id = action.get("action_id")
            test_id = action.get("test_id")

            if action_id:
                action_ids.append(str(action_id))

                if test_id:
                    action_bindings[
                        str(action_id)
                    ] = str(test_id)

    priors = annex_c_derivation.get(
        "priors",
        {},
    )

    prior_statuses = {
        str(name): (
            record.get("status")
            if isinstance(record, Mapping)
            else None
        )
        for name, record in (
            priors.items()
            if isinstance(priors, Mapping)
            else []
        )
    }

    source_modes = {
        str(name): (
            record.get("source_mode")
            if isinstance(record, Mapping)
            else None
        )
        for name, record in (
            priors.items()
            if isinstance(priors, Mapping)
            else []
        )
    }

    return {
        "state": _state_summary(
            state_document
        ),
        "stage2": {
            "graph_stats": kcag.get(
                "graph_stats",
                {},
            ),
            "node_ids": stage2_node_ids,
            "goal_ids": stage2_goal_ids,
            "vector_ids": stage2_vector_ids,
            "technique_ids": technique_ids,
        },
        "annex_b": {
            "scoring_model": kcag.get(
                "scoring_model",
                {},
            ),
            "minimum_cut": kcag.get(
                "minimum_cut",
                {},
            ),
            "priority_path": kcag.get(
                "priority_path",
                {},
            ),
            "top_paths": kcag.get(
                "top_paths",
                [],
            ),
        },
        "annex_c": {
            "assessment_config": annex_c_config,
            "prior_statuses": prior_statuses,
            "prior_source_modes": source_modes,
            "threat_score": bbn.get(
                "threat_score"
            ),
            "bbn_status": (
                bbn.get("status")
                or bbn.get(
                    "annex_c_status"
                )
            ),
            "sensitivity_status": sensitivity.get(
                "status"
            ),
            "analyst_resolution": {
                "tempo": analyst_resolution.get(
                    "tempo"
                ),
                "defensive_posture": analyst_resolution.get(
                    "defensive_posture"
                ),
                "compiled_defensive_posture": (
                    analyst_resolution.get(
                        "compiled_defensive_posture"
                    )
                ),
                "compilation": analyst_resolution.get(
                    "compilation"
                ),
            },
        },
        "stage3": {
            "test_ids": stage3_test_ids,
            "categories_by_test_id": (
                stage3_categories
            ),
            "safety_review": stage3.get(
                "assessment_safety_review",
                {},
            ),
        },
        "stage4": {
            "plan_id": stage4.get(
                "plan_id"
            ),
            "phase_ids": sorted(
                phase_ids
            ),
            "action_ids": sorted(
                action_ids
            ),
            "action_test_bindings": (
                action_bindings
            ),
            "execution_authorization": (
                stage4.get(
                    "execution_authorization"
                )
            ),
            "artifact_role": stage4.get(
                "artifact_role"
            ),
            "phase0_safety_gate": (
                stage4.get(
                    "phase0_safety_gate",
                    {},
                )
            ),
        },
        "validation_statuses": {
            name: _validation_status(
                name,
                structured[name],
            )
            for name in (
                "kcag_validation.json",
                "bbn_report.json",
                "bbn_sensitivity.json",
                "stage3_test_plan_validation.json",
                "stage4_execution_plan_validation.json",
            )
        },
    }


def build_final_report_context(
    out_dir: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Read, verify, inventory, and compact all final-report inputs.

    Every structured or prose artifact passes through run_context's stamped
    readers. assessment_state.json is the one existing run-level state file
    that is not stamped, so its embedded run and corpus identities are checked
    directly.
    """

    active = run_context.get_active_run()
    root = Path(out_dir)

    state_path = root / "assessment_state.json"

    if not state_path.is_file():
        raise FileNotFoundError(
            f"Missing assessment state: {state_path}"
        )

    state_document = json.loads(
        state_path.read_text(
            encoding="utf-8"
        )
    )

    if state_document.get("run_id") != active.run_id:
        raise ValueError(
            "assessment_state.json run_id does not "
            "match the active run."
        )

    if (
        state_document.get(
            "corpus_manifest_hash"
        )
        != active.corpus_manifest_hash
    ):
        raise ValueError(
            "assessment_state.json corpus hash does "
            "not match the active run."
        )

    structured: dict[str, dict[str, Any]] = {}
    narratives: dict[str, str] = {}
    inventory_entries: list[dict[str, Any]] = []

    inventory_entries.append(
        {
            "artifact": "assessment_state.json",
            "path": str(state_path),
            "kind": "RUN_STATE",
            "sha256": sha256_file(
                state_path
            ),
            "validation_status": "VERIFIED",
            "included_in_report": True,
        }
    )

    for artifact_name in REQUIRED_STAMPED_JSON:
        path = root / artifact_name
        payload = run_context.read_stamped_json(
            str(path)
        )

        if not isinstance(payload, dict):
            raise ValueError(
                f"{artifact_name} data must be a JSON object."
            )

        structured[artifact_name] = payload

        inventory_entries.append(
            {
                "artifact": artifact_name,
                "path": str(path),
                "kind": "STAMPED_JSON",
                "sha256": sha256_file(path),
                "validation_status": (
                    _validation_status(
                        artifact_name,
                        payload,
                    )
                ),
                "included_in_report": True,
            }
        )

    for artifact_name in REQUIRED_STAMPED_PROSE:
        path = root / artifact_name
        body = run_context.read_stamped_prose(
            str(path)
        )

        narratives[artifact_name] = (
            _compact_prose(body)
        )

        inventory_entries.append(
            {
                "artifact": artifact_name,
                "path": str(path),
                "kind": "STAMPED_PROSE",
                "sha256": sha256_file(path),
                "validation_status": "VERIFIED",
                "included_in_report": True,
            }
        )

    for artifact_name in OPTIONAL_STAMPED_PROSE:
        path = root / artifact_name

        if not path.is_file():
            continue

        try:
            body = run_context.read_stamped_prose(
                str(path)
            )
        except ValueError as exc:
            # Optional artifacts must never weaken run isolation. An existing
            # but unstamped optional file is recorded for audit purposes and
            # excluded from the canonical report context.
            inventory_entries.append(
                {
                    "artifact": artifact_name,
                    "path": str(path),
                    "kind": "OPTIONAL_PROSE",
                    "sha256": sha256_file(path),
                    "validation_status": "EXCLUDED_UNTRUSTED",
                    "included_in_report": False,
                    "exclusion_reason": str(exc),
                }
            )
            continue

        narratives[artifact_name] = (
            _compact_prose(body)
        )

        inventory_entries.append(
            {
                "artifact": artifact_name,
                "path": str(path),
                "kind": "STAMPED_PROSE",
                "sha256": sha256_file(path),
                "validation_status": "VERIFIED",
                "included_in_report": True,
            }
        )

    failed_inputs = [
        entry["artifact"]
        for entry in inventory_entries
        if entry["validation_status"] == "FAIL"
    ]

    if failed_inputs:
        raise RuntimeError(
            "Final report cannot be built from failed "
            f"artifacts: {failed_inputs}"
        )

    authoritative_facts = (
        _build_authoritative_facts(
            structured=structured,
            state_document=state_document,
        )
    )

    if (
        authoritative_facts["stage4"][
            "execution_authorization"
        ]
        != "NOT_GRANTED"
    ):
        raise RuntimeError(
            "Stage 4 execution authorization must be "
            "exactly NOT_GRANTED."
        )

    inventory = {
        "schema_version": (
            FINAL_REPORT_SCHEMA_VERSION
        ),
        "run_id": active.run_id,
        "corpus_manifest_hash": (
            active.corpus_manifest_hash
        ),
        "artifact_count": len(
            inventory_entries
        ),
        "artifacts": sorted(
            inventory_entries,
            key=lambda entry: entry[
                "artifact"
            ],
        ),
    }

    context = {
        "schema_version": (
            FINAL_REPORT_SCHEMA_VERSION
        ),
        "assessment_identity": {
            "run_id": active.run_id,
            "corpus_manifest_hash": (
                active.corpus_manifest_hash
            ),
            "generated_at": utc_now(),
        },
        "authoritative_facts": (
            authoritative_facts
        ),
        "structured_artifacts": structured,
        "narrative_sources": narratives,
        "source_artifact_names": sorted(
            entry["artifact"]
            for entry in inventory_entries
            if entry["included_in_report"]
        ),
    }

    context["context_hash"] = (
        canonical_json_sha256(context)
    )

    run_context.write_stamped_json(
        str(root / ARTIFACT_INVENTORY_NAME),
        inventory,
    )
    run_context.write_stamped_json(
        str(root / FINAL_CONTEXT_NAME),
        context,
    )

    return context, inventory


def _source_reference_schema(
    artifact_names: list[str],
) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {
            "type": "string",
            "enum": artifact_names,
        },
    }


def final_report_synthesis_schema(
    artifact_names: list[str],
) -> dict[str, Any]:
    references = _source_reference_schema(
        artifact_names
    )

    finding = {
        "type": "object",
        "properties": {
            "finding_id": {
                "type": "string",
            },
            "title": {
                "type": "string",
            },
            "severity": {
                "type": "string",
                "enum": [
                    "LOW",
                    "MODERATE",
                    "HIGH",
                    "CRITICAL",
                ],
            },
            "confidence": {
                "type": "string",
                "enum": [
                    "LOW",
                    "MEDIUM",
                    "HIGH",
                    "UNSPECIFIED",
                ],
            },
            "statement": {
                "type": "string",
            },
            "implications": {
                "type": "string",
            },
            "source_artifacts": references,
        },
        "required": [
            "finding_id",
            "title",
            "severity",
            "confidence",
            "statement",
            "implications",
            "source_artifacts",
        ],
        "additionalProperties": False,
    }

    recommendation = {
        "type": "object",
        "properties": {
            "recommendation_id": {
                "type": "string",
            },
            "priority": {
                "type": "string",
                "enum": [
                    "IMMEDIATE",
                    "NEAR_TERM",
                    "MID_TERM",
                    "LONG_TERM",
                    "UNSPECIFIED",
                ],
            },
            "title": {
                "type": "string",
            },
            "action": {
                "type": "string",
            },
            "rationale": {
                "type": "string",
            },
            "source_artifacts": references,
        },
        "required": [
            "recommendation_id",
            "priority",
            "title",
            "action",
            "rationale",
            "source_artifacts",
        ],
        "additionalProperties": False,
    }

    issue = {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
            },
            "statement": {
                "type": "string",
            },
            "source_artifacts": references,
        },
        "required": [
            "item_id",
            "statement",
            "source_artifacts",
        ],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "report_id": {
                "type": "string",
            },
            "title": {
                "type": "string",
            },
            "executive_summary": {
                "type": "string",
            },
            "overall_assessment": {
                "type": "object",
                "properties": {
                    "risk_level": {
                        "type": "string",
                        "enum": [
                            "LOW",
                            "MODERATE",
                            "HIGH",
                            "CRITICAL",
                            "NOT_RATED",
                        ],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": [
                            "LOW",
                            "MEDIUM",
                            "HIGH",
                            "UNSPECIFIED",
                        ],
                    },
                    "rationale": {
                        "type": "string",
                    },
                },
                "required": [
                    "risk_level",
                    "confidence",
                    "rationale",
                ],
                "additionalProperties": False,
            },
            "scope_and_methodology": {
                "type": "string",
            },
            "stage_narratives": {
                "type": "object",
                "properties": {
                    key: {
                        "type": "string",
                    }
                    for key in STAGE_NARRATIVE_KEYS
                },
                "required": list(
                    STAGE_NARRATIVE_KEYS
                ),
                "additionalProperties": False,
            },
            "key_findings": {
                "type": "array",
                "minItems": 3,
                "maxItems": 15,
                "items": finding,
            },
            "recommendations": {
                "type": "array",
                "minItems": 3,
                "maxItems": 15,
                "items": recommendation,
            },
            "limitations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 15,
                "items": issue,
            },
            "unresolved_items": {
                "type": "array",
                "maxItems": 15,
                "items": issue,
            },
        },
        "required": [
            "report_id",
            "title",
            "executive_summary",
            "overall_assessment",
            "scope_and_methodology",
            "stage_narratives",
            "key_findings",
            "recommendations",
            "limitations",
            "unresolved_items",
        ],
        "additionalProperties": False,
    }


def _required_text(
    value: Any,
    *,
    path: str,
) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{path} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{path} must not be empty"
        )

    return normalized


def _normalize_source_artifacts(
    value: Any,
    *,
    path: str,
    allowed: set[str],
) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise ValueError(
            f"{path} must be an array"
        )

    normalized: list[str] = []

    for item in values:
        if not isinstance(item, str):
            raise ValueError(
                f"{path} entries must be strings"
            )

        artifact = item.strip()

        if artifact not in allowed:
            raise ValueError(
                f"{path} references unknown artifact "
                f"{artifact!r}"
            )

        if artifact not in normalized:
            normalized.append(artifact)

    if not normalized:
        raise ValueError(
            f"{path} requires at least one artifact"
        )

    return normalized


def _normalize_model_text(
    value: Any,
) -> str:
    """
    Normalize common local-model text wrappers.

    Some local models return schema string fields as objects such as
    {"text": "..."} or as arrays of paragraph strings. This function unwraps
    those representations without inventing substantive narrative content.
    """

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, Mapping):
        preferred_keys = (
            "text",
            "value",
            "content",
            "title",
            "summary",
            "statement",
            "rationale",
            "action",
            "implications",
            "description",
        )

        for key in preferred_keys:
            if key not in value:
                continue

            normalized = _normalize_model_text(
                value[key]
            )

            if normalized:
                return normalized

        if len(value) == 1:
            normalized = _normalize_model_text(
                next(iter(value.values()))
            )

            if normalized:
                return normalized

        return ""

    if isinstance(value, list):
        paragraphs = [
            _normalize_model_text(item)
            for item in value
        ]

        return "\n\n".join(
            paragraph
            for paragraph in paragraphs
            if paragraph
        )

    return ""


def _normalize_model_enum(
    value: Any,
    *,
    allowed: set[str],
    aliases: Mapping[str, str] | None = None,
    fallback: str,
) -> str:
    """
    Normalize model-generated categorical values without inventing ratings.

    Invalid, missing, wrapped, or unexpected values resolve to an explicit
    non-rated fallback rather than causing repeated synthesis failures.
    """

    raw = _normalize_model_text(value)

    normalized = re.sub(
        r"[^A-Z0-9]+",
        "_",
        raw.upper(),
    ).strip("_")

    alias_map = dict(aliases or {})

    if normalized in alias_map:
        normalized = alias_map[normalized]

    if normalized in allowed:
        return normalized

    # Accept phrases such as "HIGH RISK" or "MEDIUM CONFIDENCE".
    for candidate in allowed:
        if candidate in {
            "NOT_RATED",
            "UNSPECIFIED",
        }:
            continue

        if re.search(
            rf"(?:^|_){re.escape(candidate)}(?:_|$)",
            normalized,
        ):
            return candidate

    return fallback


def _fallback_narrative_excerpt(
    value: Any,
    *,
    limit: int = 1800,
) -> str:
    """Create a compact deterministic excerpt from verified prose."""

    text = _normalize_model_text(value)

    if not text:
        return ""

    text = re.sub(
        r"(?m)^#{1,6}\s+",
        "",
        text,
    )
    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    ).strip()

    if len(text) <= limit:
        return text

    return text[:limit].rstrip() + "..."


def _build_deterministic_narrative_fallbacks(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Build required narrative fallbacks from verified context only.

    These values are used only when the local model omits a required text
    field. No new quantitative values or authorization decisions are created.
    """

    identity = context.get(
        "assessment_identity",
        {},
    )
    facts = context.get(
        "authoritative_facts",
        {},
    )

    stage2 = facts.get(
        "stage2",
        {},
    )
    annex_c = facts.get(
        "annex_c",
        {},
    )
    stage3 = facts.get(
        "stage3",
        {},
    )
    stage4 = facts.get(
        "stage4",
        {},
    )

    graph_stats = stage2.get(
        "graph_stats",
        {},
    )

    run_id = identity.get(
        "run_id",
        "unknown",
    )
    threat_score = annex_c.get(
        "threat_score"
    )

    nodes = graph_stats.get("nodes")
    edges = graph_stats.get("edges")
    goals = len(
        stage2.get(
            "goal_ids",
            [],
        )
    )
    tests = len(
        stage3.get(
            "test_ids",
            [],
        )
    )
    actions = len(
        stage4.get(
            "action_ids",
            [],
        )
    )

    summary_parts = [
        (
            f"Assessment run {run_id} completed the "
            "verified Stage 0 through Stage 4 workflow."
        ),
        (
            f"Stage 2 modeled {nodes} nodes, {edges} edges, "
            f"and {goals} assessment goals."
        ),
    ]

    if threat_score is not None:
        summary_parts.append(
            "Annex C produced a verified threat score of "
            f"{threat_score}."
        )

    summary_parts.extend(
        [
            (
                f"Stage 3 defined {tests} approved test "
                f"concepts, and Stage 4 defined {actions} "
                "mission-plan actions."
            ),
            (
                "Execution authorization remains "
                "NOT_GRANTED."
            ),
        ]
    )

    source_names = {
        "stage0": "stage0.md",
        "stage1": "stage1.md",
        "stage2": "stage2.md",
        "annex_b": "annexB_kcag.md",
        "annex_c": "annexC_bbn.md",
        "stage3": "stage3.md",
        "stage4": "stage4_mission_plan.md",
    }

    narrative_sources = context.get(
        "narrative_sources",
        {},
    )

    stage_narratives: dict[str, str] = {}

    for stage_key, artifact_name in source_names.items():
        source_text = ""

        if isinstance(
            narrative_sources,
            Mapping,
        ):
            source_text = (
                _fallback_narrative_excerpt(
                    narrative_sources.get(
                        artifact_name
                    )
                )
            )

        if not source_text:
            source_text = (
                f"The verified {artifact_name} artifact "
                "is the authoritative source for this "
                "section."
            )

        stage_narratives[stage_key] = source_text

    return {
        "executive_summary": " ".join(
            summary_parts
        ),
        "scope_and_methodology": (
            "This comprehensive report consolidates "
            "verified, run-scoped Stage 0 through Stage 4 "
            "and Annex B/Annex C artifacts. It does not "
            "reread the original corpus, recalculate KCAG "
            "or Bayesian results, create new test concepts, "
            "or grant execution authorization."
        ),
        "overall_rationale": (
            "The overall assessment is based on the "
            "verified cross-stage findings, quantitative "
            "outputs, analyst resolutions, test strategy, "
            "and mission-plan artifacts included in this "
            "run."
        ),
        "stage_narratives": stage_narratives,
    }


def _available_report_sources(
    context: Mapping[str, Any],
    *candidates: str,
) -> list[str]:
    """Return valid source artifacts from the canonical context."""

    available = [
        str(name)
        for name in context.get(
            "source_artifact_names",
            [],
        )
        if isinstance(name, str)
    ]
    available_set = set(available)

    selected = [
        candidate
        for candidate in candidates
        if candidate in available_set
    ]

    if selected:
        return selected

    if available:
        return [available[0]]

    raise ValueError(
        "Final-report context contains no source artifacts."
    )


def _build_deterministic_collection_fallbacks(
    context: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """
    Build report findings, recommendations, and limitations from verified
    authoritative facts.

    These items are used when the local model omits or malforms required
    collections. No new quantitative values or execution authorization are
    introduced.
    """

    facts = context.get(
        "authoritative_facts",
        {},
    )

    stage2 = facts.get(
        "stage2",
        {},
    )
    annex_b = facts.get(
        "annex_b",
        {},
    )
    annex_c = facts.get(
        "annex_c",
        {},
    )
    stage3 = facts.get(
        "stage3",
        {},
    )
    stage4 = facts.get(
        "stage4",
        {},
    )

    graph_stats = stage2.get(
        "graph_stats",
        {},
    )

    nodes = graph_stats.get("nodes")
    edges = graph_stats.get("edges")
    goal_ids = stage2.get(
        "goal_ids",
        [],
    )
    vector_ids = stage2.get(
        "vector_ids",
        [],
    )

    priority_path_record = annex_b.get(
        "priority_path",
        {},
    )

    priority_path = priority_path_record.get(
        "path",
        [],
    )
    priority_score = priority_path_record.get(
        "score"
    )

    threat_score = annex_c.get(
        "threat_score"
    )

    test_ids = stage3.get(
        "test_ids",
        [],
    )
    action_ids = stage4.get(
        "action_ids",
        [],
    )

    execution_authorization = stage4.get(
        "execution_authorization",
        "NOT_GRANTED",
    )

    stage2_sources = _available_report_sources(
        context,
        "stage2_vectors.json",
        "kcag_report.json",
        "stage2.md",
        "annexB_kcag.md",
    )

    annex_b_sources = _available_report_sources(
        context,
        "kcag_report.json",
        "kcag_validation.json",
        "annexB_kcag.md",
        "stage2.md",
    )

    annex_c_sources = _available_report_sources(
        context,
        "bbn_report.json",
        "bbn_sensitivity.json",
        "annexc_assessment_config.json",
        "annexc_analyst_resolution.json",
        "annexC_bbn.md",
    )

    planning_sources = _available_report_sources(
        context,
        "stage3_test_plan.json",
        "stage3_test_plan_validation.json",
        "stage4_execution_plan.json",
        "stage4_execution_plan_validation.json",
        "stage3.md",
        "stage4_mission_plan.md",
    )

    priority_path_text = (
        " -> ".join(
            str(item)
            for item in priority_path
        )
        if priority_path
        else "the validated Annex B priority path"
    )

    findings = [
        {
            "finding_id": "FR-F-001",
            "title": "Validated attack-surface model",
            "severity": "NOT_RATED",
            "confidence": "HIGH",
            "statement": (
                f"Stage 2 modeled {nodes} nodes, {edges} edges, "
                f"{len(goal_ids)} goal nodes, and "
                f"{len(vector_ids)} attack vectors."
            ),
            "implications": (
                "The validated graph provides the traceable "
                "foundation for quantitative path analysis, "
                "test design, and mission planning."
            ),
            "source_artifacts": stage2_sources,
        },
        {
            "finding_id": "FR-F-002",
            "title": "Prioritized adversary path",
            "severity": "NOT_RATED",
            "confidence": "HIGH",
            "statement": (
                f"Annex B identified {priority_path_text} as the "
                f"priority path with heuristic score "
                f"{priority_score}."
            ),
            "implications": (
                "The path should guide defensive review and "
                "test prioritization, while remaining a relative "
                "heuristic ranking rather than an empirical "
                "probability."
            ),
            "source_artifacts": annex_b_sources,
        },
        {
            "finding_id": "FR-F-003",
            "title": "Verified Bayesian threat assessment",
            "severity": "NOT_RATED",
            "confidence": "HIGH",
            "statement": (
                "Annex C produced a verified threat score of "
                f"{threat_score} using the approved assessment "
                "configuration and analyst control resolution."
            ),
            "implications": (
                "The result depends on configured priors, policy "
                "defaults, and analyst judgments and should be "
                "interpreted with those dependencies visible."
            ),
            "source_artifacts": annex_c_sources,
        },
        {
            "finding_id": "FR-F-004",
            "title": "Validated test and mission planning",
            "severity": "NOT_RATED",
            "confidence": "HIGH",
            "statement": (
                f"Stage 3 defined {len(test_ids)} test concepts and "
                f"Stage 4 defined {len(action_ids)} mission-plan "
                f"actions. Execution authorization remains "
                f"{execution_authorization}."
            ),
            "implications": (
                "The completed artifacts support human review and "
                "future authorization decisions but do not authorize "
                "execution."
            ),
            "source_artifacts": planning_sources,
        },
    ]

    recommendations = [
        {
            "recommendation_id": "FR-R-001",
            "priority": "NEAR_TERM",
            "title": "Review the priority attack path",
            "action": (
                "Review the validated priority path, minimum-cut "
                "results, and central nodes against current defensive "
                "controls and planned mitigations."
            ),
            "rationale": (
                "Concentrating defensive review on validated "
                "high-leverage graph elements provides a traceable "
                "basis for reducing modeled attack-path viability."
            ),
            "source_artifacts": annex_b_sources,
        },
        {
            "recommendation_id": "FR-R-002",
            "priority": "NEAR_TERM",
            "title": "Resolve defensive-control uncertainty",
            "action": (
                "Confirm controls recorded as partial, unknown, "
                "defaulted, or conservatively compiled and rerun the "
                "Annex C assessment when authoritative deployment "
                "evidence becomes available."
            ),
            "rationale": (
                "Reducing uncertainty in defensive-control states "
                "improves the interpretability of the Bayesian "
                "assessment without concealing prior assumptions."
            ),
            "source_artifacts": annex_c_sources,
        },
        {
            "recommendation_id": "FR-R-003",
            "priority": "IMMEDIATE",
            "title": "Preserve authorization and safety gates",
            "action": (
                "Require human approval, validated telemetry, abort "
                "criteria, termination limits, rollback capability, "
                "and release conditions before any Stage 3 or Stage 4 "
                "activity is authorized."
            ),
            "rationale": (
                "The completed workflow is a planning product and "
                "explicitly retains execution authorization as "
                "NOT_GRANTED."
            ),
            "source_artifacts": planning_sources,
        },
    ]

    limitations = [
        {
            "item_id": "FR-L-001",
            "statement": (
                "KCAG traversal scores are configured heuristics for "
                "relative ranking and are not calibrated empirical "
                "probabilities."
            ),
            "source_artifacts": annex_b_sources,
        },
        {
            "item_id": "FR-L-002",
            "statement": (
                "The Annex C threat score depends on configured "
                "priors, explicit defaults, analyst judgments, and "
                "the conservative compilation policy recorded in the "
                "assessment artifacts."
            ),
            "source_artifacts": annex_c_sources,
        },
        {
            "item_id": "FR-L-003",
            "statement": (
                "Stage 4 is a human-reviewed mission-plan draft and "
                "does not grant execution authorization."
            ),
            "source_artifacts": planning_sources,
        },
    ]

    return {
        "key_findings": findings,
        "recommendations": recommendations,
        "limitations": limitations,
        "unresolved_items": [],
    }


def normalize_synthesis_identifiers(
    payload: Any,
    *,
    context: Mapping[str, Any] | None = None,
) -> Any:
    """
    Normalize model response structure and assign deterministic identifiers.

    Workflow identifiers and the report title are bookkeeping fields, not
    narrative synthesis. Model-provided values for those fields are ignored.
    """

    if not isinstance(payload, Mapping):
        return payload

    normalized = dict(payload)

    normalized["report_id"] = "FR-001"
    normalized["title"] = (
        "Comprehensive Final Assessment Report"
    )

    for field_name in (
        "executive_summary",
        "scope_and_methodology",
    ):
        normalized[field_name] = (
            _normalize_model_text(
                normalized.get(field_name)
            )
        )

    raw_overall = normalized.get(
        "overall_assessment"
    )

    overall_mapping: dict[str, Any] = {}

    if isinstance(raw_overall, Mapping):
        overall_mapping = dict(
            raw_overall
        )

    elif isinstance(raw_overall, list):
        # Some local models wrap an object in a one-element array.
        for candidate in raw_overall:
            if isinstance(candidate, Mapping):
                overall_mapping = dict(
                    candidate
                )
                break

        if not overall_mapping:
            overall_mapping[
                "rationale"
            ] = _normalize_model_text(
                raw_overall
            )

    else:
        overall_mapping[
            "rationale"
        ] = _normalize_model_text(
            raw_overall
        )

    normalized["overall_assessment"] = {
        "risk_level": _normalize_model_enum(
            overall_mapping.get(
                "risk_level"
            ),
            allowed={
                "LOW",
                "MODERATE",
                "HIGH",
                "CRITICAL",
                "NOT_RATED",
            },
            aliases={
                "MEDIUM": "MODERATE",
                "MEDIUM_RISK": "MODERATE",
            },
            fallback="NOT_RATED",
        ),
        "confidence": _normalize_model_enum(
            overall_mapping.get(
                "confidence"
            ),
            allowed={
                "LOW",
                "MEDIUM",
                "HIGH",
                "UNSPECIFIED",
            },
            aliases={
                "MODERATE": "MEDIUM",
                "MODERATE_CONFIDENCE": "MEDIUM",
            },
            fallback="UNSPECIFIED",
        ),
        "rationale": _normalize_model_text(
            overall_mapping.get(
                "rationale"
            )
        ),
    }

    narratives = normalized.get(
        "stage_narratives"
    )

    if isinstance(narratives, Mapping):
        normalized["stage_narratives"] = {
            key: _normalize_model_text(
                narratives.get(key)
            )
            for key in STAGE_NARRATIVE_KEYS
        }

    collections = (
        (
            "key_findings",
            "finding_id",
            "FR-F-",
            (
                "title",
                "severity",
                "confidence",
                "statement",
                "implications",
            ),
        ),
        (
            "recommendations",
            "recommendation_id",
            "FR-R-",
            (
                "priority",
                "title",
                "action",
                "rationale",
            ),
        ),
        (
            "limitations",
            "item_id",
            "FR-L-",
            (
                "statement",
            ),
        ),
        (
            "unresolved_items",
            "item_id",
            "FR-U-",
            (
                "statement",
            ),
        ),
    )

    for (
        collection_name,
        id_key,
        prefix,
        text_fields,
    ) in collections:
        items = normalized.get(
            collection_name
        )

        if not isinstance(items, list):
            continue

        normalized_items: list[Any] = []

        for index, item in enumerate(
            items,
            start=1,
        ):
            if not isinstance(item, Mapping):
                normalized_items.append(item)
                continue

            normalized_item = dict(item)
            normalized_item[id_key] = (
                f"{prefix}{index:03d}"
            )

            for field_name in text_fields:
                normalized_item[field_name] = (
                    _normalize_model_text(
                        normalized_item.get(
                            field_name
                        )
                    )
                )

            if collection_name == "key_findings":
                normalized_item["severity"] = (
                    _normalize_model_enum(
                        normalized_item.get("severity"),
                        allowed={
                            "LOW",
                            "MODERATE",
                            "HIGH",
                            "CRITICAL",
                            "NOT_RATED",
                        },
                        aliases={
                            "MEDIUM": "MODERATE",
                            "MEDIUM_RISK": "MODERATE",
                        },
                        fallback="NOT_RATED",
                    )
                )

                normalized_item["confidence"] = (
                    _normalize_model_enum(
                        normalized_item.get("confidence"),
                        allowed={
                            "LOW",
                            "MEDIUM",
                            "HIGH",
                            "UNSPECIFIED",
                        },
                        aliases={
                            "MODERATE": "MEDIUM",
                            "MODERATE_CONFIDENCE": "MEDIUM",
                        },
                        fallback="UNSPECIFIED",
                    )
                )

            elif collection_name == "recommendations":
                normalized_item["priority"] = (
                    _normalize_model_enum(
                        normalized_item.get("priority"),
                        allowed={
                            "IMMEDIATE",
                            "NEAR_TERM",
                            "MID_TERM",
                            "LONG_TERM",
                            "UNSPECIFIED",
                        },
                        aliases={
                            "NEAR": "NEAR_TERM",
                            "MID": "MID_TERM",
                            "LONG": "LONG_TERM",
                        },
                        fallback="UNSPECIFIED",
                    )
                )

            sources = normalized_item.get(
                "source_artifacts"
            )

            if isinstance(sources, Mapping):
                sources = (
                    sources.get("artifacts")
                    or sources.get("sources")
                    or sources.get("items")
                    or sources.get("value")
                )

            if isinstance(sources, str):
                sources = [sources]

            normalized_item[
                "source_artifacts"
            ] = sources

            normalized_items.append(
                normalized_item
            )

        normalized[collection_name] = (
            normalized_items
        )


    if context is not None:
        collection_fallbacks = (
            _build_deterministic_collection_fallbacks(
                context
            )
        )

        allowed_sources = set(
            context.get(
                "source_artifact_names",
                [],
            )
        )

        collection_rules = {
            "key_findings": {
                "minimum": 3,
                "id_key": "finding_id",
                "prefix": "FR-F-",
                "required_text": (
                    "title",
                    "statement",
                    "implications",
                ),
            },
            "recommendations": {
                "minimum": 3,
                "id_key": "recommendation_id",
                "prefix": "FR-R-",
                "required_text": (
                    "title",
                    "action",
                    "rationale",
                ),
            },
            "limitations": {
                "minimum": 1,
                "id_key": "item_id",
                "prefix": "FR-L-",
                "required_text": (
                    "statement",
                ),
            },
            "unresolved_items": {
                "minimum": 0,
                "id_key": "item_id",
                "prefix": "FR-U-",
                "required_text": (
                    "statement",
                ),
            },
        }

        for (
            collection_name,
            rule,
        ) in collection_rules.items():
            raw_items = normalized.get(
                collection_name
            )

            usable_items: list[dict[str, Any]] = []

            if isinstance(raw_items, list):
                for raw_item in raw_items:
                    if not isinstance(
                        raw_item,
                        Mapping,
                    ):
                        continue

                    item = dict(raw_item)

                    if not all(
                        _normalize_model_text(
                            item.get(field_name)
                        )
                        for field_name in rule[
                            "required_text"
                        ]
                    ):
                        continue

                    sources = item.get(
                        "source_artifacts"
                    )

                    if not isinstance(
                        sources,
                        list,
                    ):
                        continue

                    valid_sources = [
                        source
                        for source in sources
                        if (
                            isinstance(source, str)
                            and source in allowed_sources
                        )
                    ]

                    if not valid_sources:
                        continue

                    item[
                        "source_artifacts"
                    ] = list(
                        dict.fromkeys(
                            valid_sources
                        )
                    )

                    usable_items.append(item)

            for fallback_item in (
                collection_fallbacks[
                    collection_name
                ]
            ):
                if len(usable_items) >= rule[
                    "minimum"
                ]:
                    break

                usable_items.append(
                    dict(fallback_item)
                )

            if (
                len(usable_items)
                < rule["minimum"]
            ):
                raise ValueError(
                    f"Unable to construct the required "
                    f"{collection_name} collection from "
                    "verified artifacts."
                )

            usable_items = usable_items[:15]

            for index, item in enumerate(
                usable_items,
                start=1,
            ):
                item[
                    rule["id_key"]
                ] = (
                    f"{rule['prefix']}{index:03d}"
                )

            normalized[
                collection_name
            ] = usable_items

        fallbacks = (
            _build_deterministic_narrative_fallbacks(
                context
            )
        )

        if not _normalize_model_text(
            normalized.get(
                "executive_summary"
            )
        ):
            normalized[
                "executive_summary"
            ] = fallbacks[
                "executive_summary"
            ]

        if not _normalize_model_text(
            normalized.get(
                "scope_and_methodology"
            )
        ):
            normalized[
                "scope_and_methodology"
            ] = fallbacks[
                "scope_and_methodology"
            ]

        overall = normalized.get(
            "overall_assessment"
        )

        if isinstance(overall, Mapping):
            normalized_overall = dict(
                overall
            )
        else:
            normalized_overall = {}

        if not _normalize_model_text(
            normalized_overall.get(
                "rationale"
            )
        ):
            normalized_overall[
                "rationale"
            ] = fallbacks[
                "overall_rationale"
            ]

        normalized[
            "overall_assessment"
        ] = normalized_overall

        narratives = normalized.get(
            "stage_narratives"
        )

        if isinstance(narratives, Mapping):
            normalized_narratives = dict(
                narratives
            )
        else:
            normalized_narratives = {}

        for stage_key in STAGE_NARRATIVE_KEYS:
            if not _normalize_model_text(
                normalized_narratives.get(
                    stage_key
                )
            ):
                normalized_narratives[
                    stage_key
                ] = fallbacks[
                    "stage_narratives"
                ][stage_key]

        normalized[
            "stage_narratives"
        ] = normalized_narratives

    return normalized


def validate_synthesis_payload(
    payload: Any,
    *,
    artifact_names: list[str],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(
            "Final-report synthesis must be a JSON object."
        )

    normalized = dict(payload)
    allowed = set(artifact_names)

    report_id = _required_text(
        normalized.get("report_id"),
        path="report_id",
    ).upper()

    if not REPORT_ID_RE.fullmatch(
        report_id
    ):
        raise ValueError(
            "report_id must match FR-NNN"
        )

    normalized["report_id"] = report_id
    normalized["title"] = _required_text(
        normalized.get("title"),
        path="title",
    )
    normalized["executive_summary"] = (
        _required_text(
            normalized.get(
                "executive_summary"
            ),
            path="executive_summary",
        )
    )
    normalized["scope_and_methodology"] = (
        _required_text(
            normalized.get(
                "scope_and_methodology"
            ),
            path="scope_and_methodology",
        )
    )

    overall = normalized.get(
        "overall_assessment"
    )

    if not isinstance(overall, Mapping):
        raise ValueError(
            "overall_assessment must be an object"
        )

    risk_level = _normalize_model_enum(
        overall.get(
            "risk_level"
        ),
        allowed={
            "LOW",
            "MODERATE",
            "HIGH",
            "CRITICAL",
            "NOT_RATED",
        },
        aliases={
            "MEDIUM": "MODERATE",
            "MEDIUM_RISK": "MODERATE",
        },
        fallback="NOT_RATED",
    )

    confidence = _normalize_model_enum(
        overall.get(
            "confidence"
        ),
        allowed={
            "LOW",
            "MEDIUM",
            "HIGH",
            "UNSPECIFIED",
        },
        aliases={
            "MODERATE": "MEDIUM",
            "MODERATE_CONFIDENCE": "MEDIUM",
        },
        fallback="UNSPECIFIED",
    )

    normalized["overall_assessment"] = {
        "risk_level": risk_level,
        "confidence": confidence,
        "rationale": _required_text(
            overall.get("rationale"),
            path=(
                "overall_assessment.rationale"
            ),
        ),
    }

    narratives = normalized.get(
        "stage_narratives"
    )

    if not isinstance(narratives, Mapping):
        raise ValueError(
            "stage_narratives must be an object"
        )

    normalized["stage_narratives"] = {
        key: _required_text(
            narratives.get(key),
            path=f"stage_narratives.{key}",
        )
        for key in STAGE_NARRATIVE_KEYS
    }

    findings = normalized.get(
        "key_findings"
    )

    if (
        not isinstance(findings, list)
        or len(findings) < 3
    ):
        raise ValueError(
            "key_findings requires at least three items"
        )

    normalized_findings: list[dict[str, Any]] = []
    seen_findings: set[str] = set()

    for index, finding in enumerate(
        findings
    ):
        if not isinstance(finding, Mapping):
            raise ValueError(
                f"key_findings[{index}] must be an object"
            )

        finding_id = _required_text(
            finding.get("finding_id"),
            path=(
                f"key_findings[{index}].finding_id"
            ),
        ).upper()

        if not FINDING_ID_RE.fullmatch(
            finding_id
        ):
            raise ValueError(
                f"{finding_id} must match FR-F-NNN"
            )

        if finding_id in seen_findings:
            raise ValueError(
                f"Duplicate finding_id {finding_id}"
            )

        seen_findings.add(finding_id)

        severity = str(
            finding.get("severity", "")
        ).strip().upper()
        finding_confidence = str(
            finding.get("confidence", "")
        ).strip().upper()

        if severity not in {
            "LOW",
            "MODERATE",
            "HIGH",
            "CRITICAL",
            "NOT_RATED",
        }:
            raise ValueError(
                f"{finding_id} severity is invalid"
            )

        if finding_confidence not in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "UNSPECIFIED",
        }:
            raise ValueError(
                f"{finding_id} confidence is invalid"
            )

        normalized_findings.append(
            {
                "finding_id": finding_id,
                "title": _required_text(
                    finding.get("title"),
                    path=f"{finding_id}.title",
                ),
                "severity": severity,
                "confidence": finding_confidence,
                "statement": _required_text(
                    finding.get("statement"),
                    path=f"{finding_id}.statement",
                ),
                "implications": _required_text(
                    finding.get("implications"),
                    path=f"{finding_id}.implications",
                ),
                "source_artifacts": (
                    _normalize_source_artifacts(
                        finding.get(
                            "source_artifacts"
                        ),
                        path=(
                            f"{finding_id}."
                            "source_artifacts"
                        ),
                        allowed=allowed,
                    )
                ),
            }
        )

    normalized["key_findings"] = (
        normalized_findings
    )

    recommendations = normalized.get(
        "recommendations"
    )

    if (
        not isinstance(
            recommendations,
            list,
        )
        or len(recommendations) < 3
    ):
        raise ValueError(
            "recommendations requires at least "
            "three items"
        )

    normalized_recommendations: list[
        dict[str, Any]
    ] = []
    seen_recommendations: set[str] = set()

    for index, recommendation in enumerate(
        recommendations
    ):
        if not isinstance(
            recommendation,
            Mapping,
        ):
            raise ValueError(
                f"recommendations[{index}] "
                "must be an object"
            )

        recommendation_id = _required_text(
            recommendation.get(
                "recommendation_id"
            ),
            path=(
                f"recommendations[{index}]."
                "recommendation_id"
            ),
        ).upper()

        if not RECOMMENDATION_ID_RE.fullmatch(
            recommendation_id
        ):
            raise ValueError(
                f"{recommendation_id} must match "
                "FR-R-NNN"
            )

        if (
            recommendation_id
            in seen_recommendations
        ):
            raise ValueError(
                "Duplicate recommendation_id "
                f"{recommendation_id}"
            )

        seen_recommendations.add(
            recommendation_id
        )

        priority = str(
            recommendation.get(
                "priority",
                "",
            )
        ).strip().upper()

        if priority not in {
            "IMMEDIATE",
            "NEAR_TERM",
            "MID_TERM",
            "LONG_TERM",
            "UNSPECIFIED",
        }:
            raise ValueError(
                f"{recommendation_id} priority "
                "is invalid"
            )

        normalized_recommendations.append(
            {
                "recommendation_id": (
                    recommendation_id
                ),
                "priority": priority,
                "title": _required_text(
                    recommendation.get(
                        "title"
                    ),
                    path=(
                        f"{recommendation_id}.title"
                    ),
                ),
                "action": _required_text(
                    recommendation.get(
                        "action"
                    ),
                    path=(
                        f"{recommendation_id}.action"
                    ),
                ),
                "rationale": _required_text(
                    recommendation.get(
                        "rationale"
                    ),
                    path=(
                        f"{recommendation_id}.rationale"
                    ),
                ),
                "source_artifacts": (
                    _normalize_source_artifacts(
                        recommendation.get(
                            "source_artifacts"
                        ),
                        path=(
                            f"{recommendation_id}."
                            "source_artifacts"
                        ),
                        allowed=allowed,
                    )
                ),
            }
        )

    normalized["recommendations"] = (
        normalized_recommendations
    )

    for collection_name, prefix in (
        ("limitations", "FR-L-"),
        ("unresolved_items", "FR-U-"),
    ):
        items = normalized.get(
            collection_name
        )

        if not isinstance(items, list):
            raise ValueError(
                f"{collection_name} must be an array"
            )

        if (
            collection_name == "limitations"
            and not items
        ):
            raise ValueError(
                "limitations requires at least one item"
            )

        normalized_items: list[
            dict[str, Any]
        ] = []
        seen_items: set[str] = set()

        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise ValueError(
                    f"{collection_name}[{index}] "
                    "must be an object"
                )

            item_id = _required_text(
                item.get("item_id"),
                path=(
                    f"{collection_name}[{index}]."
                    "item_id"
                ),
            ).upper()

            if (
                not ITEM_ID_RE.fullmatch(
                    item_id
                )
                or not item_id.startswith(
                    prefix
                )
            ):
                raise ValueError(
                    f"{item_id} has the wrong "
                    f"identifier format for "
                    f"{collection_name}"
                )

            if item_id in seen_items:
                raise ValueError(
                    f"Duplicate item_id {item_id}"
                )

            seen_items.add(item_id)

            normalized_items.append(
                {
                    "item_id": item_id,
                    "statement": _required_text(
                        item.get("statement"),
                        path=(
                            f"{item_id}.statement"
                        ),
                    ),
                    "source_artifacts": (
                        _normalize_source_artifacts(
                            item.get(
                                "source_artifacts"
                            ),
                            path=(
                                f"{item_id}."
                                "source_artifacts"
                            ),
                            allowed=allowed,
                        )
                    ),
                }
            )

        normalized[collection_name] = (
            normalized_items
        )

    return normalized


def synthesize_final_report(
    *,
    context: Mapping[str, Any],
    llm: Any,
    timeout_seconds: int = 180,
    retries: int = 1,
) -> dict[str, Any]:
    artifact_names = list(
        context["source_artifact_names"]
    )

    schema = final_report_synthesis_schema(
        artifact_names
    )

    # Send only the material required for narrative synthesis. The complete
    # structured artifacts remain in final_report_context.json for audit and
    # deterministic validation, but sending them again substantially increases
    # model latency without improving the report.
    model_context = {
        "assessment_identity": context[
            "assessment_identity"
        ],
        "context_hash": context[
            "context_hash"
        ],
        "authoritative_facts": context[
            "authoritative_facts"
        ],
        "narrative_sources": context[
            "narrative_sources"
        ],
        "source_artifact_names": context[
            "source_artifact_names"
        ],
    }

    prompt = (
        "Create the comprehensive final assessment "
        "narrative from this verified canonical context.\n\n"
        "The authoritative_facts object is deterministic. "
        "Do not copy it into your response and do not alter "
        "its values. It will be attached after synthesis.\n\n"
        "VERIFIED FINAL-REPORT CONTEXT:\n"
        + json.dumps(
            model_context,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )

    last_error: Exception | None = None

    for attempt in range(
        retries + 1
    ):
        request_prompt = prompt

        if last_error is not None:
            request_prompt += (
                "\n\nPREVIOUS RESPONSE REJECTED:\n"
                f"{type(last_error).__name__}: "
                f"{last_error}\n\n"
                "Repair the response. Use only supplied "
                "artifact filenames and preserve all "
                "required identifier formats."
            )

        try:
            raw = generate_structured_json(
                llm=llm,
                schema=schema,
                prompt=request_prompt,
                system_message=SYSTEM_PROMPT,
                num_predict=4096,
                timeout_seconds=timeout_seconds,
            )

            parsed = json.loads(raw)

            parsed = normalize_synthesis_identifiers(
                parsed,
                context=context,
            )

            synthesis = validate_synthesis_payload(
                parsed,
                artifact_names=artifact_names,
            )

            synthesis[
                "schema_version"
            ] = FINAL_REPORT_SCHEMA_VERSION

            synthesis[
                "assessment_identity"
            ] = copy.deepcopy(
                context[
                    "assessment_identity"
                ]
            )

            synthesis[
                "context_hash"
            ] = context["context_hash"]

            # Keep the synthesized report structurally independent from the
            # canonical context. Otherwise, modifying the report also mutates
            # the validation source and defeats tamper detection.
            synthesis[
                "authoritative_facts"
            ] = copy.deepcopy(
                context[
                    "authoritative_facts"
                ]
            )

            facts = context[
                "authoritative_facts"
            ]

            synthesis["coverage"] = {
                "stage2_goal_ids": copy.deepcopy(
                    facts["stage2"]["goal_ids"]
                ),
                "stage2_vector_ids": copy.deepcopy(
                    facts["stage2"]["vector_ids"]
                ),
                "stage3_test_ids": copy.deepcopy(
                    facts["stage3"]["test_ids"]
                ),
                "stage4_phase_ids": copy.deepcopy(
                    facts["stage4"]["phase_ids"]
                ),
                "stage4_action_ids": copy.deepcopy(
                    facts["stage4"]["action_ids"]
                ),
            }

            synthesis[
                "required_disclosures"
            ] = {
                "kcag_scores_are_heuristic": True,
                "bbn_depends_on_configured_priors": True,
                "defaulted_or_analyst_judgment_priors_disclosed": True,
                "partial_or_unknown_controls_disclosed": True,
                "execution_authorization": "NOT_GRANTED",
            }

            synthesis[
                "artifact_references"
            ] = list(artifact_names)

            return synthesis

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        "Final-report synthesis failed after "
        f"{retries + 1} attempt(s): {last_error}"
    )


def _validation_error(
    path: str,
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "path": path,
        "code": code,
        "message": message,
    }


def validate_final_report(
    *,
    report: Mapping[str, Any],
    context: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if report.get("schema_version") != (
        FINAL_REPORT_SCHEMA_VERSION
    ):
        errors.append(
            _validation_error(
                "schema_version",
                "SCHEMA_VERSION_MISMATCH",
                "Final-report schema version is invalid.",
            )
        )

    if (
        report.get("assessment_identity")
        != context.get(
            "assessment_identity"
        )
    ):
        errors.append(
            _validation_error(
                "assessment_identity",
                "ASSESSMENT_IDENTITY_MISMATCH",
                "Report identity does not match the "
                "verified final-report context.",
            )
        )

    if (
        report.get("context_hash")
        != context.get("context_hash")
    ):
        errors.append(
            _validation_error(
                "context_hash",
                "CONTEXT_HASH_MISMATCH",
                "Report is not bound to the current "
                "canonical context.",
            )
        )

    if (
        report.get("authoritative_facts")
        != context.get(
            "authoritative_facts"
        )
    ):
        errors.append(
            _validation_error(
                "authoritative_facts",
                "AUTHORITATIVE_FACT_MISMATCH",
                "Report facts differ from verified "
                "source artifacts.",
            )
        )

    facts = context[
        "authoritative_facts"
    ]

    expected_coverage = {
        "stage2_goal_ids": facts[
            "stage2"
        ]["goal_ids"],
        "stage2_vector_ids": facts[
            "stage2"
        ]["vector_ids"],
        "stage3_test_ids": facts[
            "stage3"
        ]["test_ids"],
        "stage4_phase_ids": facts[
            "stage4"
        ]["phase_ids"],
        "stage4_action_ids": facts[
            "stage4"
        ]["action_ids"],
    }

    if (
        report.get("coverage")
        != expected_coverage
    ):
        errors.append(
            _validation_error(
                "coverage",
                "CROSS_STAGE_COVERAGE_MISMATCH",
                "Final-report cross-stage coverage "
                "does not exactly match the verified "
                "artifacts.",
            )
        )

    disclosures = report.get(
        "required_disclosures",
        {},
    )

    expected_disclosures = {
        "kcag_scores_are_heuristic": True,
        "bbn_depends_on_configured_priors": True,
        "defaulted_or_analyst_judgment_priors_disclosed": True,
        "partial_or_unknown_controls_disclosed": True,
        "execution_authorization": "NOT_GRANTED",
    }

    if disclosures != expected_disclosures:
        errors.append(
            _validation_error(
                "required_disclosures",
                "REQUIRED_DISCLOSURE_MISMATCH",
                "Mandatory methodology and "
                "authorization disclosures are missing.",
            )
        )

    if (
        facts["stage4"][
            "execution_authorization"
        ]
        != "NOT_GRANTED"
    ):
        errors.append(
            _validation_error(
                "authoritative_facts.stage4."
                "execution_authorization",
                "EXECUTION_AUTHORIZATION_INVALID",
                "Final report must not grant execution "
                "authorization.",
            )
        )

    serialized_narrative = json.dumps(
        {
            "executive_summary": report.get(
                "executive_summary"
            ),
            "overall_assessment": report.get(
                "overall_assessment"
            ),
            "stage_narratives": report.get(
                "stage_narratives"
            ),
            "key_findings": report.get(
                "key_findings"
            ),
            "recommendations": report.get(
                "recommendations"
            ),
        },
        ensure_ascii=False,
    ).lower()

    prohibited_authorization_patterns = (
        "execution authorization is granted",
        "execution is authorized",
        "authorized to execute",
        '"execution_authorization": "granted"',
    )

    for phrase in prohibited_authorization_patterns:
        if phrase in serialized_narrative:
            errors.append(
                _validation_error(
                    "$",
                    "EXECUTION_AUTHORIZATION_CONTRADICTION",
                    "Narrative contains language that "
                    "could be interpreted as granting "
                    "execution authorization.",
                )
            )
            break

    inventory_names = {
        entry["artifact"]
        for entry in inventory.get(
            "artifacts",
            [],
        )
        if isinstance(entry, Mapping)
        and entry.get(
            "included_in_report"
        )
    }

    expected_references = set(
        context[
            "source_artifact_names"
        ]
    )

    if set(
        report.get(
            "artifact_references",
            [],
        )
    ) != expected_references:
        errors.append(
            _validation_error(
                "artifact_references",
                "ARTIFACT_INVENTORY_MISMATCH",
                "Report artifact references do not "
                "match the canonical context.",
            )
        )

    referenced: set[str] = set()

    for collection_name in (
        "key_findings",
        "recommendations",
        "limitations",
        "unresolved_items",
    ):
        collection = report.get(
            collection_name,
            [],
        )

        if not isinstance(collection, list):
            errors.append(
                _validation_error(
                    collection_name,
                    "INVALID_COLLECTION",
                    f"{collection_name} must be an array.",
                )
            )
            continue

        for index, item in enumerate(
            collection
        ):
            if not isinstance(item, Mapping):
                continue

            sources = item.get(
                "source_artifacts",
                [],
            )

            if not sources:
                errors.append(
                    _validation_error(
                        f"{collection_name}[{index}]."
                        "source_artifacts",
                        "MISSING_SOURCE_ARTIFACT",
                        "Every narrative item requires "
                        "source artifacts.",
                    )
                )

            for artifact_name in sources:
                referenced.add(
                    artifact_name
                )

                if artifact_name not in inventory_names:
                    errors.append(
                        _validation_error(
                            f"{collection_name}[{index}]."
                            "source_artifacts",
                            "UNKNOWN_SOURCE_ARTIFACT",
                            "Narrative references unknown "
                            f"artifact {artifact_name!r}.",
                        )
                    )

    if not referenced:
        errors.append(
            _validation_error(
                "$",
                "NO_PROVENANCE_REFERENCES",
                "Final report contains no provenance "
                "references.",
            )
        )

    stage_narratives = report.get(
        "stage_narratives",
        {},
    )

    if not isinstance(
        stage_narratives,
        Mapping,
    ):
        errors.append(
            _validation_error(
                "stage_narratives",
                "MISSING_STAGE_NARRATIVES",
                "Stage narratives are missing.",
            )
        )
    else:
        for key in STAGE_NARRATIVE_KEYS:
            value = stage_narratives.get(key)

            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                errors.append(
                    _validation_error(
                        f"stage_narratives.{key}",
                        "EMPTY_STAGE_NARRATIVE",
                        f"Missing narrative for {key}.",
                    )
                )

    validation_statuses = facts[
        "validation_statuses"
    ]

    for artifact_name, status in (
        validation_statuses.items()
    ):
        if status != "PASS":
            errors.append(
                _validation_error(
                    "authoritative_facts."
                    "validation_statuses."
                    f"{artifact_name}",
                    "UPSTREAM_VALIDATION_NOT_PASS",
                    f"{artifact_name} status is "
                    f"{status!r}, not PASS.",
                )
            )

    is_valid = not errors

    return {
        "schema_version": (
            FINAL_REPORT_SCHEMA_VERSION
        ),
        "is_valid": is_valid,
        "status": (
            "PASS"
            if is_valid
            else "FAIL"
        ),
        "checked_source_artifacts": len(
            inventory_names
        ),
        "checked_references": len(
            referenced
        ),
        "coverage": {
            "stage2_goals": len(
                expected_coverage[
                    "stage2_goal_ids"
                ]
            ),
            "stage2_vectors": len(
                expected_coverage[
                    "stage2_vector_ids"
                ]
            ),
            "stage3_tests": len(
                expected_coverage[
                    "stage3_test_ids"
                ]
            ),
            "stage4_phases": len(
                expected_coverage[
                    "stage4_phase_ids"
                ]
            ),
            "stage4_actions": len(
                expected_coverage[
                    "stage4_action_ids"
                ]
            ),
        },
        "errors": errors,
        "warnings": warnings,
        "summary": (
            "Final report validation "
            f"{'PASS' if is_valid else 'FAIL'}: "
            f"{len(errors)} error(s), "
            f"{len(warnings)} warning(s)."
        ),
    }


def _artifact_suffix(
    artifacts: list[str],
) -> str:
    return (
        "  \nSources: "
        + ", ".join(
            f"`{artifact}`"
            for artifact in artifacts
        )
    )


def render_final_report_markdown(
    report: Mapping[str, Any],
    *,
    validation_status: str = "PENDING",
) -> str:
    facts = report[
        "authoritative_facts"
    ]
    annex_b = facts["annex_b"]
    annex_c = facts["annex_c"]
    stage2 = facts["stage2"]
    stage3 = facts["stage3"]
    stage4 = facts["stage4"]

    lines: list[str] = [
        f"# {report['title']}",
        "",
        f"**Report ID:** `{report['report_id']}`  ",
        "**Run ID:** "
        f"`{report['assessment_identity']['run_id']}`  ",
        "**Corpus manifest:** "
        f"`{report['assessment_identity']['corpus_manifest_hash']}`  ",
        "**Execution authorization:** `NOT_GRANTED`",
        "",
        "> This report is an assessment and planning product. "
        "It does not authorize execution.",
        "",
        "## Executive Summary",
        "",
        report["executive_summary"],
        "",
        "## Overall Assessment",
        "",
        f"**Risk level:** {report['overall_assessment']['risk_level']}  ",
        f"**Confidence:** {report['overall_assessment']['confidence']}",
        "",
        report["overall_assessment"]["rationale"],
        "",
        "## Scope and Methodology",
        "",
        report["scope_and_methodology"],
        "",
        "KCAG traversal scores are configured heuristics for relative "
        "ranking and are not calibrated empirical probabilities. "
        "The Bayesian result depends on configured priors, explicit "
        "policy defaults, and analyst judgments. Partial or unknown "
        "defensive controls compiled conservatively for scoring remain "
        "partial or unknown in the assessment record.",
        "",
        "## Stage 0 — Intelligence Findings",
        "",
        report["stage_narratives"]["stage0"],
        "",
        "## Stage 1 — System Characterization",
        "",
        report["stage_narratives"]["stage1"],
        "",
        "## Stage 2 — Attack Surface and Kill Chains",
        "",
        report["stage_narratives"]["stage2"],
        "",
        f"- Graph nodes: `{stage2['graph_stats'].get('nodes')}`",
        f"- Graph edges: `{stage2['graph_stats'].get('edges')}`",
        f"- Goal nodes: `{', '.join(stage2['goal_ids'])}`",
        f"- Stage 2 vectors: `{', '.join(stage2['vector_ids'])}`",
        "",
        "## Annex B — Quantitative KCAG Analysis",
        "",
        report["stage_narratives"]["annex_b"],
        "",
        "**Priority path:** "
        f"`{' -> '.join(annex_b.get('priority_path', {}).get('path', []))}`  ",
        "**Priority-path heuristic score:** "
        f"`{annex_b.get('priority_path', {}).get('score')}`",
        "",
        "## Annex C — Bayesian Threat Analysis",
        "",
        report["stage_narratives"]["annex_c"],
        "",
        f"**Threat score:** `{annex_c.get('threat_score')}`  ",
        "**BBN status:** "
        f"`{annex_c.get('bbn_status')}`  ",
        "**Sensitivity status:** "
        f"`{annex_c.get('sensitivity_status')}`",
        "",
        "### Approved Assessment Configuration",
        "",
        "```json",
        json.dumps(
            annex_c.get(
                "assessment_config"
            ),
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "### Analyst Defensive-Control Resolution",
        "",
        "```json",
        json.dumps(
            annex_c.get(
                "analyst_resolution"
            ),
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Stage 3 — Test Strategy",
        "",
        report["stage_narratives"]["stage3"],
        "",
        f"**Approved test concepts:** "
        f"`{', '.join(stage3['test_ids'])}`",
        "",
        "## Stage 4 — Mission Plan",
        "",
        report["stage_narratives"]["stage4"],
        "",
        f"**Plan ID:** `{stage4.get('plan_id')}`  ",
        f"**Phases:** `{', '.join(stage4['phase_ids'])}`  ",
        f"**Actions:** `{', '.join(stage4['action_ids'])}`  ",
        "**Execution authorization:** `NOT_GRANTED`",
        "",
        "## Key Findings",
        "",
    ]

    for finding in report["key_findings"]:
        lines.extend(
            [
                f"### {finding['finding_id']} — {finding['title']}",
                "",
                f"**Severity:** {finding['severity']}  ",
                f"**Confidence:** {finding['confidence']}",
                "",
                finding["statement"],
                "",
                f"**Implications:** {finding['implications']}",
                "",
                _artifact_suffix(
                    finding[
                        "source_artifacts"
                    ]
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Prioritized Recommendations",
            "",
        ]
    )

    for recommendation in report[
        "recommendations"
    ]:
        lines.extend(
            [
                "### "
                f"{recommendation['recommendation_id']} — "
                f"{recommendation['title']}",
                "",
                f"**Priority:** {recommendation['priority']}",
                "",
                recommendation["action"],
                "",
                f"**Rationale:** {recommendation['rationale']}",
                "",
                _artifact_suffix(
                    recommendation[
                        "source_artifacts"
                    ]
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Limitations",
            "",
        ]
    )

    for item in report["limitations"]:
        lines.extend(
            [
                f"- **{item['item_id']}** — "
                f"{item['statement']}"
                + _artifact_suffix(
                    item[
                        "source_artifacts"
                    ]
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Unresolved Items",
            "",
        ]
    )

    if report["unresolved_items"]:
        for item in report[
            "unresolved_items"
        ]:
            lines.extend(
                [
                    f"- **{item['item_id']}** — "
                    f"{item['statement']}"
                    + _artifact_suffix(
                        item[
                            "source_artifacts"
                        ]
                    ),
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "No additional unresolved items were "
                "introduced by the final-report stage.",
                "",
            ]
        )

    lines.extend(
        [
            "## Safety and Authorization Constraints",
            "",
            "Execution authorization remains "
            "**NOT_GRANTED**. Category 2/3 safety "
            "requirements, approving roles, abort "
            "criteria, termination limits, rollback "
            "requirements, and release conditions remain "
            "binding exactly as defined in the verified "
            "Stage 3 and Stage 4 artifacts.",
            "",
            "## Validation and Provenance",
            "",
            "This report was generated from verified, "
            "run-scoped artifacts only. Authoritative "
            "numeric values, identifiers, coverage lists, "
            "prior states, and authorization status were "
            "attached deterministically rather than "
            "generated by the language model.",
            "",
            "### Included Artifacts",
            "",
        ]
    )

    for artifact in report[
        "artifact_references"
    ]:
        lines.append(f"- `{artifact}`")

    lines.extend(
        [
            "",
            "## Final Disposition",
            "",
            "**Assessment workflow:** COMPLETE  ",
            f"**Final-report validation:** "
            f"{validation_status}  ",
            "**Execution authorization:** NOT_GRANTED",
            "",
        ]
    )

    return "\n".join(lines)


def generate_and_validate_final_report(
    *,
    out_dir: str,
    llm: Any,
    timeout_seconds: int = 180,
) -> dict[str, str]:
    root = Path(out_dir)

    print(
        "Final report: verifying and collecting artifacts...",
        flush=True,
    )

    context, inventory = (
        build_final_report_context(
            out_dir
        )
    )

    print(
        "Final report: context ready; starting Ollama synthesis...",
        flush=True,
    )

    report = synthesize_final_report(
        context=context,
        llm=llm,
        timeout_seconds=timeout_seconds,
    )

    print(
        "Final report: synthesis complete; running validation...",
        flush=True,
    )

    validation = validate_final_report(
        report=report,
        context=context,
        inventory=inventory,
    )

    report_path = root / FINAL_JSON_NAME
    markdown_path = root / FINAL_MARKDOWN_NAME
    validation_path = (
        root / FINAL_VALIDATION_NAME
    )
    completion_path = root / COMPLETION_NAME

    run_context.write_stamped_json(
        str(report_path),
        report,
    )

    markdown = render_final_report_markdown(
        report,
        validation_status=validation["status"],
    )

    markdown_path.write_text(
        markdown.rstrip() + "\n",
        encoding="utf-8",
    )
    run_context.stamp_prose_file(
        str(markdown_path)
    )

    run_context.write_stamped_json(
        str(validation_path),
        validation,
    )

    if not validation["is_valid"]:
        raise RuntimeError(
            "Final report failed deterministic "
            f"validation. See {validation_path}."
        )

    print(
        "Final report: validation PASS; writing completion record...",
        flush=True,
    )

    completion = {
        "schema_version": (
            FINAL_REPORT_SCHEMA_VERSION
        ),
        "status": "COMPLETE",
        "run_id": run_context.get_active_run().run_id,
        "corpus_manifest_hash": (
            run_context.get_active_run()
            .corpus_manifest_hash
        ),
        "completed_at": utc_now(),
        "final_report_json": (
            report_path.name
        ),
        "final_report_json_sha256": (
            sha256_file(report_path)
        ),
        "final_report_markdown": (
            markdown_path.name
        ),
        "final_report_markdown_sha256": (
            sha256_file(markdown_path)
        ),
        "final_report_validation": (
            validation_path.name
        ),
        "final_report_validation_status": (
            "PASS"
        ),
        "context_hash": context[
            "context_hash"
        ],
        "execution_authorization": (
            "NOT_GRANTED"
        ),
    }

    run_context.write_stamped_json(
        str(completion_path),
        completion,
    )

    return {
        "context": str(
            root / FINAL_CONTEXT_NAME
        ),
        "inventory": str(
            root / ARTIFACT_INVENTORY_NAME
        ),
        "report_json": str(
            report_path
        ),
        "report_markdown": str(
            markdown_path
        ),
        "validation": str(
            validation_path
        ),
        "completion": str(
            completion_path
        ),
    }

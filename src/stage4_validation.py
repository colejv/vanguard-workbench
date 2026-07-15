"""
Deterministic validation for the structured Stage 4 execution plan
(stage4_execution_plan.json) against the verified Stage 3 test plan,
plus cross-artifact consistency checking against the human-reviewed
Stage 4 prose (stage4_mission_plan.md).

A Stage 4 action may implement one or more Stage 3 test concepts through
Stage4Action.test_ids.

A Stage4TestBinding remains singular: one binding per Stage 3 test concept,
with assigned_action_ids listing all Stage 4 actions that implement it.

The validator confirms that multi-test prose references are preserved
exactly and that a test ID is never silently dropped from a structured
action.
"""

import hashlib
import json
import re
from typing import Any

from pydantic import ValidationError

from src.stage4_schema import (
    Stage4ExecutionPlan,
)
from src.tools import (
    STAGE3_INVALID_VALUES,
    STAGE3_NO_GATE_REQUIRED,
    _strip_markdown_emphasis,
)


PLAN_ID_PATTERN = re.compile(
    r"^MP-\d{3}$"
)
PHASE_ID_PATTERN = re.compile(
    r"^PHASE-\d{2}$"
)
ACTION_ID_PATTERN = re.compile(
    r"^ACT-\d{3}$"
)
TEST_ID_PATTERN = re.compile(
    r"^RT-\d{3}$"
)


# Supports:
#
#   ## PHASE-01 — Preparation
#   ### PHASE 1: Reconnaissance (PHASE-01)
#   Phase ID: PHASE-01
#
# Applied after Markdown emphasis stripping.
STAGE4_PHASE_HEADING = re.compile(
    r"^\s*"
    r"(?:"
    r"#{1,6}\s+.*?\b"
    r"|"
    r"(?:[-*+]\s*)?"
    r"Phase\s+ID\s*:\s*"
    r")"
    r"(PHASE-\d{2})\b.*$",
    re.IGNORECASE | re.MULTILINE,
)


# Supports:
#
#   ### ACT-001 — RT-001
#   ### ACT-001: RT-001, RT-003
#   ### Action ACT-001: Description
#   ACT-001: Description
#
# Applied after Markdown emphasis stripping.
STAGE4_ACTION_HEADING = re.compile(
    r"^\s*"
    r"(?:#{1,6}\s+)?"
    r"(?:[-*+]\s*)?"
    r"(?:Action\s+)?"
    r"(ACT-\d{3})\s*"
    r"(?::|[-–—])\s*"
    r"(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# Captures the full payload after the reference label.
STAGE4_TEST_REFERENCE = re.compile(
    r"^\s*"
    r"(?:[-*+]\s*)?"
    r"(?:Test\s+Concept(?:\s+Reference)?|Test\s+ID)"
    r"\s*:\s*"
    r"(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


RT_ID_PATTERN = re.compile(
    r"\bRT-\d{3}\b",
    re.IGNORECASE,
)


_INHERITED_FIELDS = (
    (
        "success_criteria",
        "MISSING_INHERITED_SUCCESS_CRITERION",
    ),
    (
        "abort_criteria",
        "MISSING_INHERITED_ABORT_CRITERION",
    ),
    (
        "rollback_or_recovery_steps",
        "MISSING_INHERITED_RECOVERY_STEP",
    ),
    (
        "telemetry_requirements",
        "MISSING_INHERITED_TELEMETRY",
    ),
    (
        "preconditions",
        "MISSING_INHERITED_PRECONDITION",
    ),
)


def _err(
    path: str,
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "path": path,
        "code": code,
        "message": message,
    }


def _unwrap_stamped_data(
    value: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    data = value.get("data")

    if isinstance(data, dict):
        return data

    return value


def stage4_candidate_hash(
    plan: dict,
) -> str:
    payload = json.dumps(
        plan,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return (
        "sha256:"
        + hashlib.sha256(
            payload
        ).hexdigest()
    )


def build_stage4_validation_report(
    *,
    plan: dict,
    stage3_test_plan: dict,
    plan_validation: dict,
    consistency: dict,
) -> dict:
    return {
        "is_valid": (
            plan_validation["is_valid"]
            and consistency["is_consistent"]
        ),
        "source_identity": {
            "stage4_execution_plan_sha256": (
                stage4_candidate_hash(plan)
            ),
            "stage3_test_plan_sha256": (
                stage4_candidate_hash(
                    stage3_test_plan
                )
            ),
        },
        "plan_validation": plan_validation,
        "artifact_consistency": consistency,
    }


def _is_placeholder(
    value: str | None,
) -> bool:
    return (
        (value or "")
        .strip()
        .lower()
        in STAGE3_INVALID_VALUES
    )


def _normalize(
    value: str | None,
) -> str:
    return " ".join(
        (value or "")
        .lower()
        .split()
    )


def _extract_rt_ids(
    text: str,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for match in RT_ID_PATTERN.finditer(
        text or ""
    ):
        test_id = match.group(0).upper()

        if test_id not in seen:
            seen.add(test_id)
            result.append(test_id)

    return result


def _extract_prose_phase_ids(
    stage4_text: str,
) -> list[str]:
    return [
        match.group(1).upper()
        for match
        in STAGE4_PHASE_HEADING.finditer(
            stage4_text
        )
    ]


def _extract_prose_action_blocks(
    stage4_text: str,
) -> dict[str, dict[str, str]]:
    matches = list(
        STAGE4_ACTION_HEADING.finditer(
            stage4_text
        )
    )

    blocks: dict[
        str,
        dict[str, str],
    ] = {}

    for index, match in enumerate(
        matches
    ):
        action_id = (
            match.group(1).upper()
        )

        if action_id in blocks:
            raise ValueError(
                "Duplicate Stage 4 prose action "
                f"heading: {action_id}"
            )

        block_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(stage4_text)
        )

        blocks[action_id] = {
            "heading": (
                match.group(0).strip()
            ),
            "block": stage4_text[
                match.start():block_end
            ],
        }

    return blocks


def _extract_action_test_references(
    *,
    heading: str,
    block: str,
) -> list[str] | None:
    """
    Resolve the complete explicit RT-NNN set for one prose action.

    A labeled Test Concept Reference/Test ID line is authoritative when
    present. If the heading also contains RT-NNN IDs, both sets must agree.
    """
    heading_ids = _extract_rt_ids(
        heading
    )

    reference_lines = list(
        STAGE4_TEST_REFERENCE.finditer(
            block
        )
    )

    if len(reference_lines) > 1:
        raise ValueError(
            "Action block contains multiple "
            "Test Concept Reference/Test ID lines."
        )

    labeled_ids: list[str] = []

    if reference_lines:
        labeled_ids = _extract_rt_ids(
            reference_lines[0].group(1)
        )

        if not labeled_ids:
            raise ValueError(
                "Test Concept Reference/Test ID line "
                "contains no valid RT-NNN identifier."
            )

    if heading_ids and labeled_ids:
        if set(heading_ids) != set(labeled_ids):
            raise ValueError(
                "Action heading and labeled test "
                "references disagree."
            )

        return labeled_ids

    if labeled_ids:
        return labeled_ids

    if heading_ids:
        return heading_ids

    return None


def validate_stage4_execution_plan(
    *,
    plan: dict,
    stage3_test_plan: dict,
) -> dict:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    plan_data = _unwrap_stamped_data(
        plan
    )
    stage3_data = _unwrap_stamped_data(
        stage3_test_plan
    )

    try:
        parsed = (
            Stage4ExecutionPlan
            .model_validate(plan_data)
        )
    except ValidationError as exc:
        return {
            "is_valid": False,
            "status": "FAIL",
            "checked_phases": 0,
            "checked_actions": 0,
            "errors": [
                _err(
                    "$",
                    "SCHEMA_INVALID",
                    str(exc),
                )
            ],
            "warnings": [],
            "summary": (
                "Stage 4 execution plan failed "
                "schema re-validation."
            ),
        }

    stage3_by_id = {
        concept["test_id"]
        .strip()
        .upper(): concept
        for concept
        in stage3_data.get(
            "test_concepts",
            [],
        )
    }

    stage3_review = (
        stage3_data.get(
            "assessment_safety_review",
            {},
        )
        or {}
    )

    if not PLAN_ID_PATTERN.match(
        parsed.plan_id
    ):
        errors.append(
            _err(
                "plan_id",
                "INVALID_PLAN_ID_FORMAT",
                f"'{parsed.plan_id}' does not "
                "match MP-NNN.",
            )
        )

    phase_ids = [
        phase.phase_id
        for phase in parsed.phases
    ]

    if len(phase_ids) != len(
        set(phase_ids)
    ):
        duplicates = sorted({
            phase_id
            for phase_id in phase_ids
            if phase_ids.count(
                phase_id
            ) > 1
        })

        errors.append(
            _err(
                "phases",
                "DUPLICATE_PHASE_ID",
                f"Duplicate phase_id(s): "
                f"{duplicates}.",
            )
        )

    sequences = [
        phase.sequence
        for phase in parsed.phases
    ]

    if len(sequences) != len(
        set(sequences)
    ):
        errors.append(
            _err(
                "phases",
                "DUPLICATE_PHASE_SEQUENCE",
                "Phase sequence values "
                "must be unique.",
            )
        )
    elif sorted(sequences) != list(
        range(
            1,
            len(sequences) + 1,
        )
    ):
        errors.append(
            _err(
                "phases",
                "NON_CONTIGUOUS_PHASE_SEQUENCE",
                "Phase sequence must be "
                "contiguous starting at 1; "
                f"got {sorted(sequences)}.",
            )
        )

    all_action_ids: list[str] = []

    for phase in parsed.phases:
        phase_path = (
            f"phases[{phase.phase_id}]"
        )

        if not PHASE_ID_PATTERN.match(
            phase.phase_id
        ):
            errors.append(
                _err(
                    f"{phase_path}.phase_id",
                    "INVALID_PHASE_ID_FORMAT",
                    f"'{phase.phase_id}' does not "
                    "match PHASE-NN.",
                )
            )

        if not phase.actions:
            errors.append(
                _err(
                    f"{phase_path}.actions",
                    "EMPTY_PHASE",
                    "Every phase requires at "
                    "least one action.",
                )
            )

        for action in phase.actions:
            all_action_ids.append(
                action.action_id
            )

            action_path = (
                f"{phase_path}.actions"
                f"[{action.action_id}]"
            )

            if not ACTION_ID_PATTERN.match(
                action.action_id
            ):
                errors.append(
                    _err(
                        f"{action_path}.action_id",
                        "INVALID_ACTION_ID_FORMAT",
                        f"'{action.action_id}' does "
                        "not match ACT-NNN.",
                    )
                )

            if not action.test_ids:
                errors.append(
                    _err(
                        f"{action_path}.test_ids",
                        "MISSING_TEST_IDS",
                        "Every action requires at "
                        "least one test ID.",
                    )
                )

            if len(action.test_ids) != len(
                set(action.test_ids)
            ):
                errors.append(
                    _err(
                        f"{action_path}.test_ids",
                        "DUPLICATE_ACTION_TEST_ID",
                        "Action test_ids must "
                        "be unique.",
                    )
                )

            for test_id in action.test_ids:
                if not TEST_ID_PATTERN.match(
                    test_id
                ):
                    errors.append(
                        _err(
                            f"{action_path}.test_ids",
                            "INVALID_TEST_ID_FORMAT",
                            f"'{test_id}' does not "
                            "match RT-NNN.",
                        )
                    )

            if not action.responsible_roles:
                errors.append(
                    _err(
                        f"{action_path}"
                        ".responsible_roles",
                        "MISSING_RESPONSIBLE_ROLE",
                        "At least one responsible "
                        "role is required.",
                    )
                )

            if not action.alert_triggers:
                errors.append(
                    _err(
                        f"{action_path}"
                        ".alert_triggers",
                        "MISSING_ALERT_TRIGGER",
                        "At least one alert trigger "
                        "is required.",
                    )
                )

            if not action.opsec_measures:
                errors.append(
                    _err(
                        f"{action_path}"
                        ".opsec_measures",
                        "MISSING_OPSEC_MEASURE",
                        "At least one OPSEC measure "
                        "is required.",
                    )
                )

            if _is_placeholder(
                action.action_summary
            ):
                errors.append(
                    _err(
                        f"{action_path}"
                        ".action_summary",
                        "PLACEHOLDER_VALUE",
                        f"'{action.action_summary}' "
                        "is a placeholder value.",
                    )
                )

    if len(all_action_ids) != len(
        set(all_action_ids)
    ):
        duplicates = sorted({
            action_id
            for action_id
            in all_action_ids
            if all_action_ids.count(
                action_id
            ) > 1
        })

        errors.append(
            _err(
                "phases",
                "DUPLICATE_ACTION_ID",
                "Duplicate action_id(s) "
                f"across the plan: {duplicates}.",
            )
        )

    json_source_ids = set(
        parsed.source_stage3_test_ids
    )
    stage3_ids = set(stage3_by_id)

    if json_source_ids != stage3_ids:
        missing = (
            stage3_ids - json_source_ids
        )
        extra = (
            json_source_ids - stage3_ids
        )

        if missing:
            errors.append(
                _err(
                    "source_stage3_test_ids",
                    "MISSING_STAGE3_TEST_ID",
                    "source_stage3_test_ids "
                    "is missing Stage 3 concept(s): "
                    f"{sorted(missing)}.",
                )
            )

        if extra:
            errors.append(
                _err(
                    "source_stage3_test_ids",
                    "UNKNOWN_STAGE3_TEST_ID",
                    "source_stage3_test_ids "
                    "references nonexistent "
                    "Stage 3 concept(s): "
                    f"{sorted(extra)}.",
                )
            )

    binding_test_ids = [
        binding.test_id
        for binding
        in parsed.test_bindings
    ]

    if len(binding_test_ids) != len(
        set(binding_test_ids)
    ):
        duplicates = sorted({
            test_id
            for test_id
            in binding_test_ids
            if binding_test_ids.count(
                test_id
            ) > 1
        })

        errors.append(
            _err(
                "test_bindings",
                "DUPLICATE_BINDING",
                f"Duplicate test binding(s): "
                f"{duplicates}.",
            )
        )

    bound_ids = set(
        binding_test_ids
    )

    if bound_ids != stage3_ids:
        missing = (
            stage3_ids - bound_ids
        )
        extra = (
            bound_ids - stage3_ids
        )

        if missing:
            errors.append(
                _err(
                    "test_bindings",
                    "MISSING_STAGE3_TEST_ID",
                    "No binding for Stage 3 "
                    f"concept(s): {sorted(missing)}.",
                )
            )

        if extra:
            errors.append(
                _err(
                    "test_bindings",
                    "UNKNOWN_STAGE3_TEST_ID",
                    "Binding references nonexistent "
                    "Stage 3 concept(s): "
                    f"{sorted(extra)}.",
                )
            )

    actions_by_test_id: dict[
        str,
        list[Any],
    ] = {}

    for phase in parsed.phases:
        for action in phase.actions:
            for test_id in action.test_ids:
                actions_by_test_id.setdefault(
                    test_id,
                    [],
                ).append(action)

                if test_id not in stage3_by_id:
                    errors.append(
                        _err(
                            (
                                f"phases[{phase.phase_id}]"
                                f".actions"
                                f"[{action.action_id}]"
                                ".test_ids"
                            ),
                            "UNKNOWN_STAGE3_TEST_ID",
                            "Action references "
                            "nonexistent Stage 3 "
                            f"concept '{test_id}'.",
                        )
                    )

    for binding in parsed.test_bindings:
        binding_path = (
            f"test_bindings"
            f"[{binding.test_id}]"
        )

        stage3_concept = (
            stage3_by_id.get(
                binding.test_id
            )
        )

        if stage3_concept is None:
            continue

        if set(binding.categories) != set(
            stage3_concept[
                "categories"
            ]
        ):
            errors.append(
                _err(
                    f"{binding_path}.categories",
                    "CATEGORY_MISMATCH",
                    "Binding categories do not "
                    "match Stage 3 categories.",
                )
            )

        if set(
            binding.stage2_vector_ids
        ) != set(
            stage3_concept[
                "stage2_vector_ids"
            ]
        ):
            errors.append(
                _err(
                    f"{binding_path}"
                    ".stage2_vector_ids",
                    "STAGE2_VECTOR_MISMATCH",
                    "Binding stage2_vector_ids "
                    "do not match Stage 3.",
                )
            )

        if (
            binding.kcag_path
            != stage3_concept["kcag_path"]
        ):
            errors.append(
                _err(
                    f"{binding_path}.kcag_path",
                    "KCAG_PATH_MISMATCH",
                    "Binding kcag_path does "
                    "not match Stage 3; order "
                    "is significant.",
                )
            )

        stage3_technique_ids = {
            reference["technique_id"]
            for reference
            in stage3_concept.get(
                "execution_techniques",
                [],
            )
        }

        if set(
            binding.technique_ids
        ) != stage3_technique_ids:
            errors.append(
                _err(
                    f"{binding_path}"
                    ".technique_ids",
                    "TECHNIQUE_ID_MISMATCH",
                    "Binding technique_ids do "
                    "not match Stage 3.",
                )
            )

        assigned = set(
            binding.assigned_action_ids
        )

        actual = {
            action.action_id
            for action
            in actions_by_test_id.get(
                binding.test_id,
                [],
            )
        }

        if assigned != actual:
            missing = actual - assigned
            extra = assigned - actual

            if missing:
                errors.append(
                    _err(
                        f"{binding_path}"
                        ".assigned_action_ids",
                        "ASSIGNED_ACTIONS_MISSING",
                        "assigned_action_ids is "
                        "missing real action(s): "
                        f"{sorted(missing)}.",
                    )
                )

            if extra:
                errors.append(
                    _err(
                        f"{binding_path}"
                        ".assigned_action_ids",
                        "ASSIGNED_ACTIONS_STALE",
                        "assigned_action_ids "
                        "references nonexistent "
                        f"action(s): {sorted(extra)}.",
                    )
                )

        if not actual:
            errors.append(
                _err(
                    binding_path,
                    "TEST_HAS_NO_ACTION",
                    f"Stage 3 concept "
                    f"'{binding.test_id}' has no "
                    "assigned Stage 4 action.",
                )
            )

        matching_actions = (
            actions_by_test_id.get(
                binding.test_id,
                [],
            )
        )

        for (
            field_name,
            error_code,
        ) in _INHERITED_FIELDS:
            stage3_values = {
                _normalize(value)
                for value
                in stage3_concept.get(
                    field_name,
                    [],
                )
            }

            stage4_union = {
                _normalize(value)
                for action
                in matching_actions
                for value
                in getattr(
                    action,
                    field_name,
                )
            }

            missing_values = (
                stage3_values
                - stage4_union
            )

            if missing_values:
                errors.append(
                    _err(
                        f"{binding_path}"
                        f".{field_name}",
                        error_code,
                        "Stage 4 actions for "
                        f"'{binding.test_id}' do "
                        "not collectively cover "
                        f"Stage 3 {field_name}: "
                        f"{sorted(missing_values)}.",
                    )
                )

    category_2_3_ids = {
        test_id
        for test_id, concept
        in stage3_by_id.items()
        if {2, 3}
        & set(concept["categories"])
    }

    gate = parsed.phase0_safety_gate
    gate_path = (
        "phase0_safety_gate"
    )

    if category_2_3_ids:
        if not gate.required:
            errors.append(
                _err(
                    f"{gate_path}.required",
                    "SAFETY_GATE_FLAG_MISMATCH",
                    "required must be true when "
                    "any Stage 3 concept carries "
                    "Category 2/3.",
                )
            )

        covered = set(
            gate.covered_test_ids
        )

        if covered != category_2_3_ids:
            missing = (
                category_2_3_ids - covered
            )
            extra = (
                covered - category_2_3_ids
            )

            if missing:
                errors.append(
                    _err(
                        f"{gate_path}"
                        ".covered_test_ids",
                        "MISSING_COVERED_TEST_ID",
                        "covered_test_ids is "
                        f"missing: {sorted(missing)}.",
                    )
                )

            if extra:
                errors.append(
                    _err(
                        f"{gate_path}"
                        ".covered_test_ids",
                        "EXTRA_COVERED_TEST_ID",
                        "covered_test_ids includes "
                        "non-Category-2/3 test(s): "
                        f"{sorted(extra)}.",
                    )
                )

        if (
            gate.execution_release
            != "BLOCKED_PENDING_SIGNOFF"
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".execution_release",
                    "INVALID_EXECUTION_RELEASE",
                    "execution_release must be "
                    "BLOCKED_PENDING_SIGNOFF when "
                    "Category 2/3 exists.",
                )
            )

        if gate.not_required_statement:
            errors.append(
                _err(
                    f"{gate_path}"
                    ".not_required_statement",
                    "CONTRADICTORY_NOT_REQUIRED_STATEMENT",
                    "not_required_statement must "
                    "be null when Category 2/3 "
                    "concepts exist.",
                )
            )

        if not gate.required_approving_roles:
            errors.append(
                _err(
                    f"{gate_path}"
                    ".required_approving_roles",
                    "EMPTY_APPROVING_ROLES",
                    "At least one approving role "
                    "is required.",
                )
            )

        if (
            not gate.safety_authority
            or _is_placeholder(
                gate.safety_authority
            )
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".safety_authority",
                    "PLACEHOLDER_OR_MISSING",
                    "safety_authority is required.",
                )
            )

        if (
            not gate.abort_authority
            or _is_placeholder(
                gate.abort_authority
            )
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".abort_authority",
                    "PLACEHOLDER_OR_MISSING",
                    "abort_authority is required.",
                )
            )

        if not gate.abort_criteria:
            errors.append(
                _err(
                    f"{gate_path}"
                    ".abort_criteria",
                    "EMPTY_ABORT_CRITERIA",
                    "At least one entry is required.",
                )
            )

        if (
            not gate.maximum_termination_seconds
            or gate.maximum_termination_seconds
            <= 0
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".maximum_termination_seconds",
                    "INVALID_TERMINATION_TIME",
                    "maximum_termination_seconds "
                    "must be positive.",
                )
            )

        if (
            not gate
            .rollback_or_recovery_procedure
            or _is_placeholder(
                gate
                .rollback_or_recovery_procedure
            )
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".rollback_or_recovery_procedure",
                    "PLACEHOLDER_OR_MISSING",
                    "rollback_or_recovery_procedure "
                    "is required.",
                )
            )

        if not gate.release_condition:
            errors.append(
                _err(
                    f"{gate_path}"
                    ".release_condition",
                    "MISSING_RELEASE_CONDITION",
                    "release_condition is required.",
                )
            )
        else:
            lowered = (
                gate.release_condition.lower()
            )

            if not any(
                phrase in lowered
                for phrase in (
                    "may not begin",
                    "must not begin",
                    "shall not begin",
                )
            ):
                errors.append(
                    _err(
                        f"{gate_path}"
                        ".release_condition",
                        "WEAK_RELEASE_CONDITION",
                        "release_condition must "
                        "contain blocking language.",
                    )
                )

        stage3_seconds = (
            stage3_review.get(
                "maximum_termination_seconds"
            )
        )

        if (
            stage3_seconds is not None
            and gate
            .maximum_termination_seconds
            is not None
            and gate
            .maximum_termination_seconds
            > stage3_seconds
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".maximum_termination_seconds",
                    "TERMINATION_TIME_WEAKENED",
                    "Stage 4 termination time "
                    "exceeds Stage 3's approved "
                    "maximum.",
                )
            )

        stage3_roles = {
            _normalize(role)
            for role
            in stage3_review.get(
                "required_approving_roles",
                [],
            )
        }

        stage4_roles = {
            _normalize(role)
            for role
            in gate.required_approving_roles
        }

        missing_roles = (
            stage3_roles - stage4_roles
        )

        if missing_roles:
            errors.append(
                _err(
                    f"{gate_path}"
                    ".required_approving_roles",
                    "MISSING_STAGE3_APPROVING_ROLE",
                    "Stage 4 drops Stage 3 "
                    "approving role(s): "
                    f"{sorted(missing_roles)}.",
                )
            )

        stage3_abort = {
            _normalize(criterion)
            for criterion
            in stage3_review.get(
                "abort_criteria",
                [],
            )
        }

        stage4_abort = {
            _normalize(criterion)
            for criterion
            in gate.abort_criteria
        }

        missing_abort = (
            stage3_abort - stage4_abort
        )

        if missing_abort:
            errors.append(
                _err(
                    f"{gate_path}"
                    ".abort_criteria",
                    "MISSING_STAGE3_ABORT_CRITERION",
                    "Stage 4 drops Stage 3 "
                    "assessment-level abort "
                    f"criteria: {sorted(missing_abort)}.",
                )
            )

    else:
        if gate.required:
            errors.append(
                _err(
                    f"{gate_path}.required",
                    "SAFETY_GATE_FLAG_MISMATCH",
                    "required must be false when "
                    "no Stage 3 concept carries "
                    "Category 2/3.",
                )
            )

        if gate.covered_test_ids:
            errors.append(
                _err(
                    f"{gate_path}"
                    ".covered_test_ids",
                    "UNEXPECTED_COVERED_TEST_ID",
                    "covered_test_ids must be "
                    "empty when no Category 2/3 "
                    "concepts exist.",
                )
            )

        if (
            gate.execution_release
            != "NOT_APPLICABLE"
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".execution_release",
                    "INVALID_EXECUTION_RELEASE",
                    "execution_release must be "
                    "NOT_APPLICABLE when no "
                    "Category 2/3 concepts exist.",
                )
            )

        if (
            gate.not_required_statement
            or ""
        ).strip() != (
            STAGE3_NO_GATE_REQUIRED
        ):
            errors.append(
                _err(
                    f"{gate_path}"
                    ".not_required_statement",
                    "MISSING_NOT_REQUIRED_STATEMENT",
                    "not_required_statement must "
                    f"be exactly "
                    f"'{STAGE3_NO_GATE_REQUIRED}'.",
                )
            )

    is_valid = not errors

    return {
        "is_valid": is_valid,
        "status": (
            "PASS"
            if is_valid
            else "FAIL"
        ),
        "checked_phases": len(
            parsed.phases
        ),
        "checked_actions": len(
            all_action_ids
        ),
        "errors": errors,
        "warnings": warnings,
        "summary": (
            "Stage 4 execution-plan validation "
            f"{'PASS' if is_valid else 'FAIL'}: "
            f"{len(parsed.phases)} phase(s), "
            f"{len(all_action_ids)} action(s) checked, "
            f"{len(errors)} error(s)."
        ),
    }


def check_stage4_artifact_consistency(
    *,
    stage4_text: str,
    execution_plan: dict,
) -> dict:
    """
    Confirm that the Stage 4 prose and structured plan contain the same
    phases, actions, complete action-to-test mappings, and Phase 0
    disposition.
    """
    errors: list[dict[str, str]] = []

    stripped = _strip_markdown_emphasis(
        stage4_text or ""
    )

    plan_data = _unwrap_stamped_data(
        execution_plan
    )

    prose_phase_id_list = (
        _extract_prose_phase_ids(
            stripped
        )
    )
    prose_phase_ids = set(
        prose_phase_id_list
    )

    duplicate_prose_phases = sorted({
        phase_id
        for phase_id
        in prose_phase_id_list
        if prose_phase_id_list.count(
            phase_id
        ) > 1
    })

    if duplicate_prose_phases:
        errors.append(
            _err(
                "stage4_mission_plan.md",
                "DUPLICATE_PROSE_PHASE_HEADING",
                "Stage 4 prose contains "
                "duplicate phase heading(s): "
                f"{duplicate_prose_phases}.",
            )
        )

    json_phase_ids = {
        phase["phase_id"].upper()
        for phase
        in plan_data.get(
            "phases",
            [],
        )
        if isinstance(phase, dict)
        and isinstance(
            phase.get("phase_id"),
            str,
        )
    }

    missing_phase_from_prose = (
        json_phase_ids
        - prose_phase_ids
    )

    missing_phase_from_json = (
        prose_phase_ids
        - json_phase_ids
    )

    if missing_phase_from_prose:
        errors.append(
            _err(
                "phases",
                "PHASE_MISSING_FROM_PROSE",
                "Structured phase(s) have no "
                "matching prose phase: "
                f"{sorted(missing_phase_from_prose)}.",
            )
        )

    if missing_phase_from_json:
        errors.append(
            _err(
                "stage4_mission_plan.md",
                "PHASE_MISSING_FROM_JSON",
                "Prose phase(s) have no "
                "matching structured phase: "
                f"{sorted(missing_phase_from_json)}.",
            )
        )

    try:
        prose_action_blocks = (
            _extract_prose_action_blocks(
                stripped
            )
        )
    except ValueError as exc:
        errors.append(
            _err(
                "stage4_mission_plan.md",
                "DUPLICATE_PROSE_ACTION_HEADING",
                str(exc),
            )
        )
        prose_action_blocks = {}

    prose_action_ids = set(
        prose_action_blocks
    )

    json_actions: list[
        tuple[str, set[str]]
    ] = []

    for phase in plan_data.get(
        "phases",
        [],
    ):
        if not isinstance(phase, dict):
            continue

        for action in phase.get(
            "actions",
            [],
        ):
            if not isinstance(action, dict):
                continue

            action_id = action.get(
                "action_id"
            )

            raw_test_ids = action.get(
                "test_ids"
            )

            # Compatibility with pre-migration fixtures and interrupted artifacts.
            # Canonical Stage 4 output remains plural-only.
            if (
                raw_test_ids is None
                and isinstance(
                    action.get("test_id"),
                    str,
                )
            ):
                raw_test_ids = [
                    action["test_id"]
                ]

            if (
                isinstance(action_id, str)
                and isinstance(
                    raw_test_ids,
                    list,
                )
                and raw_test_ids
                and all(
                    isinstance(test_id, str)
                    and test_id.strip()
                    for test_id in raw_test_ids
                )
            ):
                json_actions.append((
                    action_id.upper(),
                    {
                        test_id.strip().upper()
                        for test_id in raw_test_ids
                    },
                ))

    json_action_ids = {
        action_id
        for action_id, _
        in json_actions
    }

    missing_action_from_prose = (
        json_action_ids
        - prose_action_ids
    )

    missing_action_from_json = (
        prose_action_ids
        - json_action_ids
    )

    if missing_action_from_prose:
        errors.append(
            _err(
                "phases",
                "ACTION_MISSING_FROM_PROSE",
                "Structured action(s) have no "
                "matching prose action: "
                f"{sorted(missing_action_from_prose)}.",
            )
        )

    if missing_action_from_json:
        errors.append(
            _err(
                "stage4_mission_plan.md",
                "ACTION_MISSING_FROM_JSON",
                "Prose action(s) have no "
                "matching structured action: "
                f"{sorted(missing_action_from_json)}.",
            )
        )

    for (
        action_id,
        structured_test_ids,
    ) in json_actions:
        prose_entry = (
            prose_action_blocks.get(
                action_id
            )
        )

        if prose_entry is None:
            continue

        try:
            prose_test_ids = (
                _extract_action_test_references(
                    heading=(
                        prose_entry["heading"]
                    ),
                    block=(
                        prose_entry["block"]
                    ),
                )
            )
        except ValueError as exc:
            errors.append(
                _err(
                    f"stage4_mission_plan.md"
                    f"[{action_id}]",
                    "ACTION_TEST_REFERENCE_INVALID",
                    str(exc),
                )
            )
            continue

        if prose_test_ids is None:
            errors.append(
                _err(
                    f"phases[...].actions"
                    f"[{action_id}]",
                    "ACTION_HEADING_MISSING_TEST_ID",
                    f"Prose action {action_id} "
                    "does not contain an explicit "
                    "RT-NNN reference.",
                )
            )
            continue

        prose_test_id_set = set(
            prose_test_ids
        )

        if (
            prose_test_id_set
            != structured_test_ids
        ):
            errors.append(
                _err(
                    f"phases[...].actions"
                    f"[{action_id}].test_ids",
                    "ACTION_TEST_ID_MISMATCH",
                    f"Structured action {action_id} "
                    f"references "
                    f"{sorted(structured_test_ids)}, "
                    "but its approved prose "
                    f"references "
                    f"{sorted(prose_test_id_set)}.",
                )
            )

    json_gate_required = bool(
        (
            plan_data.get(
                "phase0_safety_gate"
            )
            or {}
        ).get("required")
    )

    no_gate_statement_present = (
        STAGE3_NO_GATE_REQUIRED.lower()
        in stripped.lower()
    )

    if (
        json_gate_required
        and no_gate_statement_present
    ):
        errors.append(
            _err(
                "stage4_mission_plan.md",
                "PROSE_NO_GATE_CONTRADICTS_JSON",
                "JSON declares the Phase 0 "
                "safety gate required, but prose "
                "contains the no-gate statement.",
            )
        )

    if (
        not json_gate_required
        and not no_gate_statement_present
    ):
        errors.append(
            _err(
                "stage4_mission_plan.md",
                "PROSE_MISSING_NOT_REQUIRED_STATEMENT",
                "JSON declares the Phase 0 "
                "safety gate not required, but "
                "the exact no-gate statement "
                "is absent from prose.",
            )
        )

    is_consistent = not errors

    return {
        "is_consistent": is_consistent,
        "status": (
            "PASS"
            if is_consistent
            else "FAIL"
        ),
        "errors": errors,
        "summary": (
            "Stage 4 cross-artifact consistency "
            f"{'PASS' if is_consistent else 'FAIL'}: "
            f"{len(errors)} error(s)."
        ),
    }
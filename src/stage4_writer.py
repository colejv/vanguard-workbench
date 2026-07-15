"""
Direct Stage 4 structured-output compiler.

Stage 4 requests schema-constrained structured output through Ollama's
native /api/chat endpoint, applies deterministic overlays, validates the
candidate against Stage4ExecutionPlan, and passes the validated JSON
string to the deterministic writer tool.

Interface parity with Stage 3: write_stage4_execution_plan takes one
execution_plan_json STRING and re-validates it internally.

DETERMINISTIC CONTROLS

1. PHASE 0 SAFETY GATE

   Derived from the validated Stage 3 test plan's
   assessment_safety_review. The model is not trusted to transcribe
   safety-governance data.

2. APPROVED ACTION CONTRACT

   Every ACT-NNN action explicitly present in the approved Stage 4 prose
   must appear exactly once in the structured plan with the same complete
   set of RT-NNN test assignments.

   A single action may implement multiple test concepts. Candidates that
   omit, combine, rename, invent, remap, or silently drop test references
   are rejected before writer invocation.

3. INHERITED STAGE 3 REQUIREMENTS

   Stage 3 success criteria, abort criteria, recovery steps, telemetry
   requirements, and preconditions are authoritative.

   Missing inherited values are copied deterministically into the first
   Stage 4 action, in approved phase/action order, assigned to the
   applicable Stage 3 test concept. Existing Stage 4 values are preserved.

4. TEST BINDINGS

   Categories, Stage 2 vectors, KCAG paths, and technique IDs are copied
   from the validated Stage 3 plan.

   assigned_action_ids are derived from the verified Stage 4 action set.
   A multi-test action is assigned to every binding identified by its
   test_ids list.

MIGRATION COMPATIBILITY

Older candidates and tests may still emit:

    "test_id": "RT-001"

The compiler canonicalizes that input to:

    "test_ids": ["RT-001"]

before action-contract enforcement. Newly generated and written artifacts
remain plural-only.

This module owns Stage-4-specific prompt construction, deterministic
overlays, schema-feedback retries, writer invocation, and artifact
read-back. Generic Ollama HTTP mechanics live in
src/structured_output.py. The outer semantic repair loop lives in
src/stage4_flow.py.
"""

from collections import defaultdict
import json
import os
import re
from typing import Any

from src import run_context
from src.structured_output import generate_structured_json
from src.tools import _strip_markdown_emphasis


STAGE4_WRITE_MAX_RETRIES = 3


# Applied after Markdown emphasis has been stripped.
#
# Supports:
#
#   ### ACT-001 — RT-001
#   ### ACT-001: RT-001, RT-003
#   ### Action ACT-001: Description
#   ACT-001: Description
#   ACT-001 — Description
#
# Group 1 is ACT-NNN.
# Group 2 is the remainder of the heading.
_STAGE4_ACTION_HEADING_RE = re.compile(
    r"^\s*"
    r"(?:#{1,6}\s+)?"
    r"(?:[-*+]\s*)?"
    r"(?:Action\s+)?"
    r"(ACT-\d{3})\s*"
    r"(?::|[-–—])\s*"
    r"(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# Applied after Markdown emphasis has been stripped.
#
# Captures the entire reference payload so every RT-NNN can be extracted:
#
#   Test Concept Reference: RT-001, RT-003
#   Test Concept: RT-001 / RT-003
#   Test ID: RT-001
_STAGE4_TEST_REFERENCE_RE = re.compile(
    r"^\s*"
    r"(?:[-*+]\s*)?"
    r"(?:Test\s+Concept(?:\s+Reference)?|Test\s+ID)"
    r"\s*:\s*"
    r"(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


_RT_ID_RE = re.compile(
    r"\bRT-\d{3}\b",
    re.IGNORECASE,
)


_STAGE3_INHERITED_ACTION_FIELDS = (
    "success_criteria",
    "abort_criteria",
    "rollback_or_recovery_steps",
    "telemetry_requirements",
    "preconditions",
)


def _unwrap_stamped_data(
    value: dict[str, Any],
) -> dict[str, Any]:
    """
    Return the data body from either a stamped artifact or an already
    unwrapped artifact dictionary.
    """
    if not isinstance(value, dict):
        return {}

    data = value.get("data")

    if isinstance(data, dict):
        return data

    return value


def _normalize_test_ids(
    values: Any,
    *,
    context: str,
) -> list[str]:
    """
    Validate and normalize a canonical action.test_ids list.
    """
    if not isinstance(values, list) or not values:
        raise ValueError(
            f"{context} requires a non-empty test_ids list."
        )

    normalized: list[str] = []

    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{context}.test_ids[{index}] must be a "
                "non-empty string."
            )

        normalized_value = value.strip().upper()

        if not re.fullmatch(
            r"RT-\d{3}",
            normalized_value,
        ):
            raise ValueError(
                f"{context}.test_ids[{index}] must match "
                f"RT-NNN; got {value!r}."
            )

        normalized.append(normalized_value)

    if len(normalized) != len(set(normalized)):
        raise ValueError(
            f"{context}.test_ids contains duplicate values."
        )

    return normalized


def _canonicalize_action_test_ids(
    action: dict[str, Any],
    *,
    context: str,
) -> list[str]:
    """
    Canonicalize one action's test references in place.

    Accepted inputs:

        {"test_id": "RT-001"}

        {"test_ids": ["RT-001"]}

        {"test_ids": ["RT-001", "RT-003"]}

    When both test_id and test_ids are present, they must describe the
    same singular assignment. A legacy singular value cannot coexist
    with a true multi-test list because that would be ambiguous.

    Returns the normalized plural list and writes it back to action.
    """
    if not isinstance(action, dict):
        raise ValueError(
            f"{context} must be an object."
        )

    has_plural = "test_ids" in action
    has_singular = "test_id" in action

    if not has_plural and not has_singular:
        raise ValueError(
            f"{context} requires a non-empty test_ids list."
        )

    if has_singular:
        legacy_value = action.get("test_id")

        if (
            not isinstance(legacy_value, str)
            or not legacy_value.strip()
        ):
            raise ValueError(
                f"{context}.test_id must be a non-empty string."
            )

        normalized_legacy = legacy_value.strip().upper()

        if not re.fullmatch(
            r"RT-\d{3}",
            normalized_legacy,
        ):
            raise ValueError(
                f"{context}.test_id must match RT-NNN; "
                f"got {legacy_value!r}."
            )

        if not has_plural:
            action["test_ids"] = [
                normalized_legacy
            ]
        else:
            plural_values = _normalize_test_ids(
                action.get("test_ids"),
                context=context,
            )

            if plural_values != [
                normalized_legacy
            ]:
                raise ValueError(
                    f"{context}.test_id and test_ids disagree."
                )

            action["test_ids"] = plural_values

        action.pop("test_id", None)

    normalized = _normalize_test_ids(
        action.get("test_ids"),
        context=context,
    )

    action["test_ids"] = normalized

    return normalized


def _extract_rt_ids(
    text: str,
) -> list[str]:
    """
    Extract unique RT-NNN identifiers in first-occurrence order.
    """
    result: list[str] = []
    seen: set[str] = set()

    for match in _RT_ID_RE.finditer(
        text or ""
    ):
        test_id = match.group(0).upper()

        if test_id not in seen:
            seen.add(test_id)
            result.append(test_id)

    return result


def _normalize_requirement(
    value: str,
) -> str:
    """
    Normalize an inherited requirement for deterministic equality checks.

    The original Stage 3 text is retained when copied into Stage 4.
    Normalization is used only to identify requirements already present
    despite case or whitespace differences.
    """
    return " ".join(
        value.strip().lower().split()
    )


def build_stage4_phase0_gate(
    stage3_test_plan: dict[str, Any],
) -> dict[str, Any]:
    """
    Derive phase0_safety_gate deterministically from the validated
    Stage 3 assessment_safety_review.

    Governance values are copied verbatim. The overlay never invents
    replacements. Incomplete required governance remains the deep
    validator's responsibility.
    """
    plan = _unwrap_stamped_data(
        stage3_test_plan
    )

    review = plan.get(
        "assessment_safety_review"
    )

    if not isinstance(review, dict):
        raise ValueError(
            "Stage 3 plan is missing assessment_safety_review."
        )

    required = bool(
        review.get("category_2_3_present")
    )

    if not required:
        return {
            "required": False,
            "covered_test_ids": list(
                review.get(
                    "covered_test_ids",
                    [],
                )
                or []
            ),
            "required_approving_roles": [],
            "safety_authority": None,
            "abort_authority": None,
            "abort_criteria": [],
            "maximum_termination_seconds": None,
            "rollback_or_recovery_procedure": None,
            "release_condition": None,
            "execution_release": "NOT_APPLICABLE",
            "not_required_statement": review.get(
                "not_required_statement"
            ),
        }

    return {
        "required": True,
        "covered_test_ids": list(
            review.get(
                "covered_test_ids",
                [],
            )
            or []
        ),
        "required_approving_roles": list(
            review.get(
                "required_approving_roles",
                [],
            )
            or []
        ),
        "safety_authority": review.get(
            "safety_authority"
        ),
        "abort_authority": review.get(
            "abort_authority"
        ),
        "abort_criteria": list(
            review.get(
                "abort_criteria",
                [],
            )
            or []
        ),
        "maximum_termination_seconds": review.get(
            "maximum_termination_seconds"
        ),
        "rollback_or_recovery_procedure": review.get(
            "rollback_or_recovery_procedure"
        ),
        "release_condition": review.get(
            "release_condition"
        ),
        "execution_release": "BLOCKED_PENDING_SIGNOFF",
        "not_required_statement": None,
    }


def extract_stage4_action_contract(
    stage4_prose: str,
) -> dict[str, list[str]]:
    """
    Extract the approved action_id -> test_ids contract from Stage 4 prose.

    Supports:

        ### ACT-001 — RT-001

        ### Action ACT-001: Description
        * Test Concept Reference: RT-001, RT-003

    Markdown emphasis is stripped before parsing.

    The function never infers assignments from descriptive prose. Every
    action must have explicit RT-NNN references either on its heading or
    on exactly one labeled Test Concept Reference/Test ID line.

    If both the heading and labeled line contain references, their sets
    must agree.
    """
    if (
        not isinstance(stage4_prose, str)
        or not stage4_prose.strip()
    ):
        raise ValueError(
            "Approved Stage 4 prose is empty."
        )

    stripped = _strip_markdown_emphasis(
        stage4_prose
    )

    matches = list(
        _STAGE4_ACTION_HEADING_RE.finditer(
            stripped
        )
    )

    if not matches:
        candidate_lines = [
            line.strip()
            for line in stripped.splitlines()
            if re.search(
                r"\bACT-\d{3}\b",
                line,
                re.IGNORECASE,
            )
        ]

        if candidate_lines:
            raise ValueError(
                "Approved Stage 4 prose contains ACT-NNN "
                "references, but none matched the supported "
                "action-heading formats. Candidate lines: "
                f"{candidate_lines[:10]}"
            )

        raise ValueError(
            "Approved Stage 4 prose contains no "
            "ACT-NNN action headings."
        )

    contract: dict[str, list[str]] = {}

    for index, match in enumerate(
        matches
    ):
        action_id = match.group(1).upper()

        if action_id in contract:
            raise ValueError(
                "Duplicate action heading in Stage 4 prose: "
                f"{action_id}"
            )

        block_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(stripped)
        )

        heading = match.group(0)

        block = stripped[
            match.start():block_end
        ]

        heading_ids = _extract_rt_ids(
            heading
        )

        reference_lines = list(
            _STAGE4_TEST_REFERENCE_RE.finditer(
                block
            )
        )

        if len(reference_lines) > 1:
            raise ValueError(
                f"Approved Stage 4 prose action {action_id} "
                "contains multiple Test Concept Reference/Test ID "
                "lines. Use one explicit reference line per action."
            )

        labeled_ids: list[str] = []

        if reference_lines:
            labeled_ids = _extract_rt_ids(
                reference_lines[0].group(1)
            )

            if not labeled_ids:
                raise ValueError(
                    f"Approved Stage 4 prose action {action_id} "
                    "has a Test Concept Reference line but no "
                    "valid RT-NNN identifiers."
                )

        if heading_ids and labeled_ids:
            if set(heading_ids) != set(
                labeled_ids
            ):
                raise ValueError(
                    f"Approved Stage 4 prose action {action_id} "
                    "has conflicting heading and labeled test "
                    f"references: heading={heading_ids}, "
                    f"labeled={labeled_ids}."
                )

            test_ids = labeled_ids
        elif labeled_ids:
            test_ids = labeled_ids
        elif heading_ids:
            test_ids = heading_ids
        else:
            raise ValueError(
                f"Approved Stage 4 prose action {action_id} "
                "has no explicit RT-NNN reference on its heading "
                "and no Test Concept Reference/Test ID field."
            )

        contract[action_id] = test_ids

    return contract


def enforce_stage4_action_contract(
    *,
    stage4_prose: str,
    stage4_candidate: dict[str, Any],
) -> None:
    """
    Require the structured candidate to preserve the approved prose action
    contract exactly.

    Every approved action must appear exactly once and retain the complete
    set of explicit RT-NNN assignments. Unexpected actions are rejected.

    Legacy singular action.test_id values are canonicalized before
    comparison.
    """
    expected = extract_stage4_action_contract(
        stage4_prose
    )

    phases = stage4_candidate.get(
        "phases"
    )

    if not isinstance(phases, list):
        raise ValueError(
            "Stage 4 candidate phases must be a list."
        )

    actual: dict[str, list[str]] = {}

    for phase_index, phase in enumerate(
        phases
    ):
        if not isinstance(phase, dict):
            raise ValueError(
                f"Stage 4 phases[{phase_index}] "
                "must be an object."
            )

        actions = phase.get(
            "actions"
        )

        if not isinstance(actions, list):
            raise ValueError(
                f"Stage 4 phases[{phase_index}].actions "
                "must be a list."
            )

        for action_index, action in enumerate(
            actions
        ):
            if not isinstance(action, dict):
                raise ValueError(
                    f"Stage 4 phases[{phase_index}]"
                    f".actions[{action_index}] "
                    "must be an object."
                )

            action_id = action.get(
                "action_id"
            )

            if (
                not isinstance(action_id, str)
                or not action_id.strip()
            ):
                raise ValueError(
                    f"Stage 4 phases[{phase_index}]"
                    f".actions[{action_index}] "
                    "has no valid action_id."
                )

            normalized_action_id = (
                action_id.strip().upper()
            )

            action["action_id"] = (
                normalized_action_id
            )

            if normalized_action_id in actual:
                raise ValueError(
                    "Duplicate structured Stage 4 action: "
                    f"{normalized_action_id}"
                )

            actual[normalized_action_id] = (
                _canonicalize_action_test_ids(
                    action,
                    context=(
                        "Stage 4 action "
                        f"{normalized_action_id}"
                    ),
                )
            )

    missing = sorted(
        set(expected) - set(actual)
    )

    unexpected = sorted(
        set(actual) - set(expected)
    )

    mismatched = sorted(
        action_id
        for action_id
        in set(expected) & set(actual)
        if set(expected[action_id])
        != set(actual[action_id])
    )

    problems: list[str] = []

    if missing:
        problems.append(
            "missing approved action(s): "
            + ", ".join(missing)
        )

    if unexpected:
        problems.append(
            "unexpected action(s): "
            + ", ".join(unexpected)
        )

    for action_id in mismatched:
        problems.append(
            f"{action_id} must reference "
            f"{sorted(expected[action_id])}, not "
            f"{sorted(actual[action_id])}"
        )

    if problems:
        raise ValueError(
            "Stage 4 candidate violates the approved "
            "action contract: "
            + "; ".join(problems)
        )


def overlay_stage3_inherited_requirements(
    *,
    stage3_test_plan: dict[str, Any],
    stage4_candidate: dict[str, Any],
) -> None:
    """
    Ensure Stage 4 collectively carries every required Stage 3 action
    field.

    For each Stage 3 test concept, all Stage 4 actions whose test_ids
    contain that concept form the applicable action group.

    Existing Stage 4 values are preserved. Any missing authoritative
    Stage 3 values are appended to the first matching action in approved
    phase/action order.

    This implementation is assessment-independent:

      - no action IDs are hardcoded;
      - no test IDs are hardcoded;
      - no action count is assumed;
      - multi-test actions are supported;
      - original Stage 3 requirement text is copied verbatim.

    The Stage 4 validator checks inherited requirements collectively
    across every action assigned to a test concept. Therefore, placing
    each missing requirement onto the first matching action satisfies the
    deterministic contract without duplicating it across all actions.
    """
    stage3_plan = _unwrap_stamped_data(
        stage3_test_plan
    )

    concepts = stage3_plan.get(
        "test_concepts"
    )

    if (
        not isinstance(concepts, list)
        or not concepts
    ):
        raise ValueError(
            "Validated Stage 3 plan contains no test_concepts."
        )

    phases = stage4_candidate.get(
        "phases"
    )

    if (
        not isinstance(phases, list)
        or not phases
    ):
        raise ValueError(
            "Stage 4 candidate phases must be a non-empty list "
            "before inherited requirements can be overlaid."
        )

    actions_in_order: list[
        tuple[str, dict[str, Any], list[str]]
    ] = []

    seen_action_ids: set[str] = set()

    for phase_index, phase in enumerate(
        phases
    ):
        if not isinstance(phase, dict):
            raise ValueError(
                f"Stage 4 phases[{phase_index}] "
                "must be an object."
            )

        actions = phase.get(
            "actions"
        )

        if not isinstance(actions, list):
            raise ValueError(
                f"Stage 4 phases[{phase_index}].actions "
                "must be a list."
            )

        for action_index, action in enumerate(
            actions
        ):
            if not isinstance(action, dict):
                raise ValueError(
                    f"Stage 4 phases[{phase_index}]"
                    f".actions[{action_index}] "
                    "must be an object."
                )

            action_id = action.get(
                "action_id"
            )

            if (
                not isinstance(action_id, str)
                or not action_id.strip()
            ):
                raise ValueError(
                    f"Stage 4 phases[{phase_index}]"
                    f".actions[{action_index}] "
                    "has no valid action_id."
                )

            normalized_action_id = (
                action_id.strip().upper()
            )

            if normalized_action_id in seen_action_ids:
                raise ValueError(
                    "Duplicate Stage 4 action_id while applying "
                    "Stage 3 inheritance: "
                    f"{normalized_action_id}"
                )

            seen_action_ids.add(
                normalized_action_id
            )

            action["action_id"] = (
                normalized_action_id
            )

            test_ids = (
                _canonicalize_action_test_ids(
                    action,
                    context=(
                        "Stage 4 action "
                        f"{normalized_action_id}"
                    ),
                )
            )

            actions_in_order.append((
                normalized_action_id,
                action,
                test_ids,
            ))

    for concept_index, concept in enumerate(
        concepts
    ):
        if not isinstance(concept, dict):
            raise ValueError(
                f"Stage 3 test_concepts[{concept_index}] "
                "must be an object."
            )

        raw_test_id = concept.get(
            "test_id"
        )

        if (
            not isinstance(raw_test_id, str)
            or not raw_test_id.strip()
        ):
            raise ValueError(
                f"Stage 3 test_concepts[{concept_index}] "
                "has no valid test_id."
            )

        test_id = raw_test_id.strip().upper()

        matching_actions = [
            (
                action_id,
                action,
            )
            for (
                action_id,
                action,
                action_test_ids,
            ) in actions_in_order
            if test_id in action_test_ids
        ]

        if not matching_actions:
            raise ValueError(
                f"Stage 3 test concept {test_id} has no assigned "
                "Stage 4 action for inherited-requirement overlay."
            )

        target_action_id, target_action = (
            matching_actions[0]
        )

        for field_name in (
            _STAGE3_INHERITED_ACTION_FIELDS
        ):
            source_values = concept.get(
                field_name,
                [],
            )

            if source_values is None:
                source_values = []

            if not isinstance(source_values, list):
                raise ValueError(
                    f"Stage 3 test concept {test_id}.{field_name} "
                    "must be a list."
                )

            existing_values: set[str] = set()

            for (
                matching_action_id,
                matching_action,
            ) in matching_actions:
                action_values = matching_action.get(
                    field_name
                )

                if action_values is None:
                    action_values = []
                    matching_action[field_name] = (
                        action_values
                    )

                if not isinstance(action_values, list):
                    raise ValueError(
                        f"Stage 4 action "
                        f"{matching_action_id}.{field_name} "
                        "must be a list."
                    )

                for value_index, value in enumerate(
                    action_values
                ):
                    if (
                        not isinstance(value, str)
                        or not value.strip()
                    ):
                        raise ValueError(
                            f"Stage 4 action "
                            f"{matching_action_id}."
                            f"{field_name}[{value_index}] must be "
                            "a non-empty string."
                        )

                    existing_values.add(
                        _normalize_requirement(
                            value
                        )
                    )

            target_values = target_action.get(
                field_name
            )

            if target_values is None:
                target_values = []
                target_action[field_name] = (
                    target_values
                )

            if not isinstance(target_values, list):
                raise ValueError(
                    f"Stage 4 action {target_action_id}."
                    f"{field_name} must be a list."
                )

            for value_index, source_value in enumerate(
                source_values
            ):
                if (
                    not isinstance(source_value, str)
                    or not source_value.strip()
                ):
                    raise ValueError(
                        f"Stage 3 test concept {test_id}."
                        f"{field_name}[{value_index}] must be "
                        "a non-empty string."
                    )

                normalized_source = (
                    _normalize_requirement(
                        source_value
                    )
                )

                if normalized_source in existing_values:
                    continue

                target_values.append(
                    source_value
                )

                existing_values.add(
                    normalized_source
                )


def build_stage4_test_bindings(
    *,
    stage3_test_plan: dict[str, Any],
    stage4_candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build Stage4ExecutionPlan.test_bindings deterministically.

    Authoritative fields copied from validated Stage 3:

      - test_id
      - categories
      - stage2_vector_ids
      - kcag_path
      - technique_ids

    Stage 4 contributes:

      - assigned_action_ids

    assigned_action_ids are derived from:

        phases[].actions[].action_id
        phases[].actions[].test_ids[]

    A multi-test action is included in every referenced test binding.
    """
    stage3_plan = _unwrap_stamped_data(
        stage3_test_plan
    )

    concepts = stage3_plan.get(
        "test_concepts"
    )

    if (
        not isinstance(concepts, list)
        or not concepts
    ):
        raise ValueError(
            "Validated Stage 3 plan contains no "
            "test_concepts."
        )

    concepts_by_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for concept_index, concept in enumerate(
        concepts
    ):
        if not isinstance(concept, dict):
            raise ValueError(
                f"Stage 3 test_concepts"
                f"[{concept_index}] must be an object."
            )

        test_id = concept.get(
            "test_id"
        )

        if (
            not isinstance(test_id, str)
            or not test_id.strip()
        ):
            raise ValueError(
                f"Stage 3 test_concepts"
                f"[{concept_index}] has no valid test_id."
            )

        normalized_test_id = (
            test_id.strip().upper()
        )

        if normalized_test_id in concepts_by_id:
            raise ValueError(
                "Duplicate Stage 3 test_id: "
                f"{normalized_test_id}"
            )

        concepts_by_id[
            normalized_test_id
        ] = concept

    phases = stage4_candidate.get(
        "phases"
    )

    if (
        not isinstance(phases, list)
        or not phases
    ):
        raise ValueError(
            "Stage 4 candidate phases must be a "
            "non-empty list before test_bindings "
            "can be constructed."
        )

    actions_by_test: dict[
        str,
        list[str],
    ] = defaultdict(list)

    seen_action_ids: set[str] = set()

    for phase_index, phase in enumerate(
        phases
    ):
        if not isinstance(phase, dict):
            raise ValueError(
                f"Stage 4 phases[{phase_index}] "
                "must be an object."
            )

        actions = phase.get(
            "actions"
        )

        if not isinstance(actions, list):
            raise ValueError(
                f"Stage 4 phases[{phase_index}]"
                ".actions must be a list."
            )

        for action_index, action in enumerate(
            actions
        ):
            if not isinstance(action, dict):
                raise ValueError(
                    f"Stage 4 phases[{phase_index}]"
                    f".actions[{action_index}] "
                    "must be an object."
                )

            action_id = action.get(
                "action_id"
            )

            if (
                not isinstance(action_id, str)
                or not action_id.strip()
            ):
                raise ValueError(
                    f"Stage 4 phases[{phase_index}]"
                    f".actions[{action_index}] requires "
                    "a non-empty action_id."
                )

            normalized_action_id = (
                action_id.strip().upper()
            )

            action["action_id"] = (
                normalized_action_id
            )

            if normalized_action_id in seen_action_ids:
                raise ValueError(
                    "Duplicate Stage 4 action_id: "
                    f"{normalized_action_id}"
                )

            seen_action_ids.add(
                normalized_action_id
            )

            test_ids = (
                _canonicalize_action_test_ids(
                    action,
                    context=(
                        "Stage 4 action "
                        f"{normalized_action_id}"
                    ),
                )
            )

            for test_id in test_ids:
                if test_id not in concepts_by_id:
                    raise ValueError(
                        f"Stage 4 action "
                        f"{normalized_action_id} references "
                        f"unknown Stage 3 test_id {test_id}."
                    )

                actions_by_test[test_id].append(
                    normalized_action_id
                )

    bindings: list[dict[str, Any]] = []

    for concept in concepts:
        test_id = (
            concept["test_id"]
            .strip()
            .upper()
        )

        assigned_action_ids = (
            actions_by_test.get(
                test_id,
                [],
            )
        )

        if not assigned_action_ids:
            raise ValueError(
                f"Stage 3 test concept {test_id} "
                "has no assigned Stage 4 action."
            )

        categories = concept.get(
            "categories"
        )

        if (
            not isinstance(categories, list)
            or not categories
        ):
            raise ValueError(
                f"Stage 3 test concept {test_id} "
                "has no categories."
            )

        stage2_vector_ids = concept.get(
            "stage2_vector_ids"
        )

        if (
            not isinstance(
                stage2_vector_ids,
                list,
            )
            or not stage2_vector_ids
        ):
            raise ValueError(
                f"Stage 3 test concept {test_id} "
                "has no stage2_vector_ids."
            )

        kcag_path = concept.get(
            "kcag_path"
        )

        if (
            not isinstance(kcag_path, list)
            or not kcag_path
        ):
            raise ValueError(
                f"Stage 3 test concept {test_id} "
                "has no kcag_path."
            )

        execution_techniques = concept.get(
            "execution_techniques"
        )

        if (
            not isinstance(
                execution_techniques,
                list,
            )
            or not execution_techniques
        ):
            raise ValueError(
                f"Stage 3 test concept {test_id} "
                "has no execution_techniques."
            )

        technique_ids: set[str] = set()

        for technique_index, technique in enumerate(
            execution_techniques
        ):
            if not isinstance(technique, dict):
                raise ValueError(
                    f"Stage 3 test concept {test_id} "
                    f"execution_techniques"
                    f"[{technique_index}] "
                    "must be an object."
                )

            technique_id = technique.get(
                "technique_id"
            )

            if (
                not isinstance(technique_id, str)
                or not technique_id.strip()
            ):
                raise ValueError(
                    f"Stage 3 test concept {test_id} "
                    f"execution_techniques"
                    f"[{technique_index}] "
                    "has no valid technique_id."
                )

            technique_ids.add(
                technique_id.strip()
            )

        bindings.append({
            "test_id": test_id,
            "categories": list(
                categories
            ),
            "stage2_vector_ids": list(
                stage2_vector_ids
            ),
            "kcag_path": list(
                kcag_path
            ),
            "technique_ids": sorted(
                technique_ids
            ),
            "assigned_action_ids": sorted(
                assigned_action_ids
            ),
        })

    return bindings


def _apply_phase0_overlay(
    parsed: dict[str, Any],
    stage3_test_plan: dict[str, Any],
) -> None:
    """
    Replace model-generated Phase 0 data with validated Stage 3 data.
    """
    parsed["phase0_safety_gate"] = (
        build_stage4_phase0_gate(
            stage3_test_plan
        )
    )


def _apply_inherited_requirements_overlay(
    parsed: dict[str, Any],
    stage3_test_plan: dict[str, Any],
) -> None:
    """
    Deterministically carry authoritative Stage 3 action requirements
    into the Stage 4 action groups implementing each test concept.
    """
    overlay_stage3_inherited_requirements(
        stage3_test_plan=stage3_test_plan,
        stage4_candidate=parsed,
    )


def _apply_test_bindings_overlay(
    parsed: dict[str, Any],
    stage3_test_plan: dict[str, Any],
) -> None:
    """
    Replace model-generated test bindings with deterministic bindings.
    """
    parsed["test_bindings"] = (
        build_stage4_test_bindings(
            stage3_test_plan=stage3_test_plan,
            stage4_candidate=parsed,
        )
    )


STAGE4_WRITE_SYSTEM = (
    "Return exactly one JSON object matching the supplied schema. "
    "The root object must contain schema_version, plan_id, plan_title, "
    "artifact_role, execution_authorization, source_stage3_test_ids, "
    "phase0_safety_gate, test_bindings, phases, global_opsec_measures, "
    "assumptions, and limitations. "
    "Do not wrap the object in execution_plan, plan, data, result, "
    "output, or any other container. "
    "Do not emit prose or a tool call."
)


STAGE4_WRITE_PROMPT_TEMPLATE = (
    "Translate the approved Stage 4 mission-plan prose below into one "
    "JSON document matching the supplied schema. Use only the test IDs, "
    "vector IDs, KCAG paths, and technique IDs already established by "
    "the Stage 3 plan and referential context. Do not invent new ones.\n\n"

    "ROOT SHAPE — REQUIRED:\n"
    "- The JSON root itself IS the Stage4ExecutionPlan object.\n"
    "- Required root keys: schema_version, plan_id, plan_title, "
    "artifact_role, execution_authorization, source_stage3_test_ids, "
    "phase0_safety_gate, test_bindings, phases, global_opsec_measures, "
    "assumptions, limitations.\n"
    "- Use schema_version as integer 1, not the stage number.\n"
    '- Do not return {{"execution_plan": {{...}}}} or any wrapper.\n\n'

    "STRICT SCHEMA CONSTANTS:\n"
    "- schema_version MUST be integer 1.\n"
    "- artifact_role MUST be exactly "
    "'HUMAN_REVIEWED_MISSION_PLAN_DRAFT'.\n"
    "- execution_authorization MUST be exactly 'NOT_GRANTED'.\n"
    "- Each phase REQUIRES: phase_id, sequence (integer), name, purpose, "
    "entry_criteria (list), exit_criteria (list), actions (list).\n"
    "- Each action REQUIRES: action_id, test_ids (a non-empty list of "
    "every RT-NNN explicitly referenced by that action), action_summary, "
    "responsible_roles (list), preconditions (list), success_criteria "
    "(list), abort_criteria (list), rollback_or_recovery_steps (list; "
    "use this exact field name), telemetry_requirements (list), "
    "alert_triggers (list), and opsec_measures (list).\n"
    "- Do not emit action.test_id. The canonical action field is "
    "test_ids and is always a list, even when it contains one item.\n"
    "- Each test_binding uses singular test_id because each binding "
    "represents one Stage 3 concept.\n"
    "- global_opsec_measures, assumptions, and limitations are required "
    "root-level lists.\n\n"

    "ACTION PRESERVATION:\n"
    "- Every approved ACT-NNN action must appear exactly once.\n"
    "- Do not combine two approved actions into one action.\n"
    "- Do not omit, rename, renumber, invent, or remap actions.\n"
    "- Preserve the complete set of RT-NNN references for every action.\n"
    "- A single action may contain multiple test_ids.\n"
    "- Never drop the second or later RT-NNN reference from an action.\n"
    "- Preserve all approved preconditions, success criteria, abort "
    "criteria, rollback/recovery steps, telemetry requirements, alert "
    "triggers, responsible roles, and OPSEC measures.\n\n"

    "DETERMINISTIC FIELDS:\n"
    "- Emit phase0_safety_gate as an empty object {{}}. Its values are "
    "injected from the validated Stage 3 safety review.\n"
    "- Emit test_bindings as an empty list []. Its values are constructed "
    "from the validated Stage 3 concepts and verified action test_ids.\n"
    "- Missing Stage 3 success criteria, abort criteria, recovery steps, "
    "telemetry requirements, and preconditions are injected "
    "deterministically after generation.\n"
    "- Every action MUST still include its correct action_id and complete "
    "test_ids list.\n\n"

    "REFERENTIAL CONTEXT:\n"
    "{referential_context}\n\n"

    "APPROVED STAGE 4 MISSION-PLAN PROSE:\n\n"
    "{stage4_prose}"
)


def _record_validation_feedback(
    feedback_by_path: dict[str, str],
    exc: Any,
) -> None:
    """
    Accumulate Pydantic validation errors keyed by field path.
    """
    for error in exc.errors():
        path = ".".join(
            str(part)
            for part in error["loc"]
        )

        feedback_by_path[path] = (
            error["msg"]
        )


def _render_feedback(
    feedback_by_path: dict[str, str],
    writer_feedback: list[str],
) -> str:
    parts: list[str] = []

    if feedback_by_path:
        parts.append(
            "\n".join(
                f"- {path}: {message}"
                for path, message
                in sorted(
                    feedback_by_path.items()
                )
            )
        )

    if writer_feedback:
        parts.append(
            "WRITER OR GENERATION REJECTIONS:\n"
            + "\n".join(
                f"- {message}"
                for message in writer_feedback
            )
        )

    return "\n\n".join(parts)


def _generate_stage4_plan_json(
    *,
    stage4_prose: str,
    referential_context: str,
    stage3_test_plan: dict[str, Any],
    llm: Any,
    correction_feedback: str = "",
    timeout_seconds: int = 600,
) -> str:
    """
    Request one Stage 4 candidate, enforce the approved multi-test action
    contract, apply deterministic overlays, validate against
    Stage4ExecutionPlan, and return canonical JSON.
    """
    from src.stage4_schema import (
        Stage4ExecutionPlan,
    )

    schema = (
        Stage4ExecutionPlan
        .model_json_schema()
    )

    action_contract = (
        extract_stage4_action_contract(
            stage4_prose
        )
    )

    prompt = (
        STAGE4_WRITE_PROMPT_TEMPLATE.format(
            referential_context=(
                referential_context
            ),
            stage4_prose=stage4_prose,
        )
    )

    prompt += (
        "\n\nAPPROVED ACTION CONTRACT — REQUIRED:\n"
        + json.dumps(
            action_contract,
            indent=2,
            sort_keys=True,
        )
        + "\nEvery listed action_id MUST appear exactly once in "
        "phases[].actions[]. Preserve the complete associated test_ids "
        "list. Do not omit, combine, rename, renumber, invent, remap, "
        "or silently drop any test reference."
    )

    if correction_feedback:
        prompt += (
            "\n\nPREVIOUS OUTPUT WAS REJECTED BY DETERMINISTIC "
            "VALIDATION. Correct every applicable error below. "
            "Previously corrected fields must remain corrected:\n"
            f"{correction_feedback}"
        )

    normalized_content = (
        generate_structured_json(
            llm=llm,
            schema=schema,
            prompt=prompt,
            system_message=(
                STAGE4_WRITE_SYSTEM
            ),
            timeout_seconds=(
                timeout_seconds
            ),
        )
    )

    parsed = json.loads(
        normalized_content
    )

    if (
        isinstance(parsed, dict)
        and set(parsed.keys())
        == {"execution_plan"}
        and isinstance(
            parsed["execution_plan"],
            dict,
        )
    ):
        parsed = parsed[
            "execution_plan"
        ]

    if not isinstance(parsed, dict):
        raise ValueError(
            "Stage 4 structured output root "
            "must be a JSON object."
        )

    # Stage 3-authoritative safety data.
    _apply_phase0_overlay(
        parsed,
        stage3_test_plan,
    )

    # Enforce the complete approved action set and canonicalize legacy
    # action.test_id values to action.test_ids.
    enforce_stage4_action_contract(
        stage4_prose=stage4_prose,
        stage4_candidate=parsed,
    )

    # Stage 3 action-level requirements are authoritative. Do not rely on
    # probabilistic model transcription for success criteria, abort
    # criteria, recovery steps, telemetry requirements, or preconditions.
    _apply_inherited_requirements_overlay(
        parsed,
        stage3_test_plan,
    )

    # Stage 3-authoritative references plus assignments derived from the
    # verified complete action set.
    _apply_test_bindings_overlay(
        parsed,
        stage3_test_plan,
    )

    validated = (
        Stage4ExecutionPlan
        .model_validate(parsed)
    )

    return validated.model_dump_json()


def compile_stage4_structured_output(
    *,
    stage4_prose: str,
    referential_context: str,
    stage3_test_plan: dict[str, Any],
    llm: Any,
    writer_tool: Any,
    artifact_path: str,
    max_retries: int = STAGE4_WRITE_MAX_RETRIES,
    external_feedback: str = "",
) -> None:
    """
    Generate a schema-valid Stage 4 execution plan and invoke the
    deterministic writer.

    external_feedback carries semantic-repair feedback from
    stage4_flow.py.
    """
    from pydantic import ValidationError

    feedback_by_path: dict[str, str] = {}
    writer_feedback: list[str] = []

    for attempt in range(
        1,
        max_retries + 1,
    ):
        print(
            f"Stage 4 structured write: attempt "
            f"{attempt}/{max_retries} "
            "(Ollama structured output, not native tool call)...",
            flush=True,
        )

        correction_feedback = (
            _render_feedback(
                feedback_by_path,
                writer_feedback,
            )
        )

        if external_feedback:
            semantic_prefix = (
                "DEEP STAGE 4 VALIDATION REJECTED A PREVIOUS "
                "CANDIDATE. Correct every referential, consistency, "
                "inheritance, action-contract, or execution-plan "
                "error below:\n"
                f"{external_feedback}"
            )

            correction_feedback = (
                semantic_prefix
                + "\n\n"
                + correction_feedback
                if correction_feedback
                else semantic_prefix
            )

        try:
            plan_json = (
                _generate_stage4_plan_json(
                    stage4_prose=(
                        stage4_prose
                    ),
                    referential_context=(
                        referential_context
                    ),
                    stage3_test_plan=(
                        stage3_test_plan
                    ),
                    llm=llm,
                    correction_feedback=(
                        correction_feedback
                    ),
                )
            )
        except ValidationError as exc:
            _record_validation_feedback(
                feedback_by_path,
                exc,
            )

            print(
                "  Structured generation/validation failed: "
                f"ValidationError: {exc}",
                flush=True,
            )
            continue
        except Exception as exc:
            feedback_text = (
                f"{type(exc).__name__}: {exc}"
            )[:4000]

            writer_feedback.append(
                feedback_text
            )

            print(
                "  Structured generation failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue

        try:
            write_result = writer_tool.func(
                execution_plan_json=plan_json
            )
        except Exception as exc:
            feedback_text = (
                f"{type(exc).__name__}: {exc}"
            )[:4000]

            writer_feedback.append(
                feedback_text
            )

            print(
                "  Writer invocation raised "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue

        write_result_text = (
            write_result
            if isinstance(
                write_result,
                str,
            )
            else repr(write_result)
        )

        print(
            "  Writer result: "
            f"{write_result_text[:120]}",
            flush=True,
        )

        if write_result_text.startswith(
            "WRITTEN"
        ):
            if not os.path.exists(
                artifact_path
            ):
                message = (
                    "Writer returned WRITTEN but "
                    f"{artifact_path} does not exist."
                )

                writer_feedback.append(
                    message
                )

                print(
                    f"  {message}",
                    flush=True,
                )
                continue

            try:
                run_context.read_stamped_json(
                    artifact_path
                )
            except Exception as exc:
                message = (
                    "Written artifact failed stamped "
                    "read-back: "
                    f"{type(exc).__name__}: {exc}"
                )

                writer_feedback.append(
                    message[:4000]
                )

                print(
                    f"  {message}",
                    flush=True,
                )
                continue

            print(
                "  Stage 4 structured write "
                "SUCCEEDED on attempt "
                f"{attempt}.",
                flush=True,
            )
            return

        print(
            "  REJECTED by validator: "
            f"{write_result_text[:200]}",
            flush=True,
        )

        writer_feedback.append(
            write_result_text[:4000]
        )

    raise RuntimeError(
        "Stage 4 structured write failed "
        f"after {max_retries} attempts. "
        "See terminal output above for "
        "per-attempt details."
    )
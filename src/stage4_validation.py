"""
Deterministic validation for the structured Stage 4 execution plan
(stage4_execution_plan.json) against the real, already-verified Stage 3
test plan -- plus a cross-artifact consistency check against the
human-reviewed prose (stage4_mission_plan.md).

Runs AFTER the Stage 4 human-input prompt (both Stage 4 artifacts are
products of that task and cannot exist before it), but BEFORE the
existing final Phase 0 prose check and BEFORE finalize_stage4_state().
It cannot intercept the human review itself, but it must prevent final
completion of a plan that silently dropped, altered, or invented a test
concept, weakened an inherited abort/recovery/telemetry requirement, or
weakened the approved Category 2/3 termination time.

write_stage4_execution_plan() (the writer tool) only performs shallow,
writer-time checks (schema shape, size, duplicate IDs, placeholders).
This module owns every referential and cross-artifact check, exactly
mirroring the Stage 3 split between write_stage3_test_plan() and
src/stage3_validation.py.

The structured Category 2/3 gate here is intentionally duplicated with
the existing prose-based check_phase0_safety_gate(): this module
validates the STRUCTURED artifact; check_phase0_safety_gate() remains an
independent defense-in-depth check over the human-readable prose, and
continues to run and gate finalize_stage4_state() on its own, after this
module's checks pass.
"""
import re
from typing import Any

from pydantic import ValidationError

from src.stage4_schema import Stage4ExecutionPlan
from src.tools import _strip_markdown_emphasis, STAGE3_NO_GATE_REQUIRED, STAGE3_INVALID_VALUES

PLAN_ID_PATTERN = re.compile(r"^MP-\d{3}$")
PHASE_ID_PATTERN = re.compile(r"^PHASE-\d{2}$")
ACTION_ID_PATTERN = re.compile(r"^ACT-\d{3}$")

STAGE4_PHASE_HEADING = re.compile(r"^#{2,6}\s+(PHASE-\d{2})\b.*$", re.IGNORECASE | re.MULTILINE)
STAGE4_ACTION_HEADING = re.compile(r"^#{2,6}\s+(ACT-\d{3})\b.*$", re.IGNORECASE | re.MULTILINE)

_INHERITED_FIELDS = (
    ("success_criteria", "MISSING_INHERITED_SUCCESS_CRITERION"),
    ("abort_criteria", "MISSING_INHERITED_ABORT_CRITERION"),
    ("rollback_or_recovery_steps", "MISSING_INHERITED_RECOVERY_STEP"),
    ("telemetry_requirements", "MISSING_INHERITED_TELEMETRY"),
    ("preconditions", "MISSING_INHERITED_PRECONDITION"),
)


def _err(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message}


def _is_placeholder(value: str) -> bool:
    return (value or "").strip().lower() in STAGE3_INVALID_VALUES


def _normalize(value: str) -> str:
    return " ".join((value or "").lower().split())


def validate_stage4_execution_plan(*, plan: dict, stage3_test_plan: dict) -> dict:
    """Validate the structured Stage 4 execution plan against the real,
    already-verified Stage 3 test plan. Does not mutate either input."""
    errors: list = []
    warnings: list = []

    try:
        parsed = Stage4ExecutionPlan.model_validate(plan)
    except ValidationError as exc:
        return {
            "is_valid": False, "status": "FAIL", "checked_phases": 0, "checked_actions": 0,
            "errors": [_err("$", "SCHEMA_INVALID", str(exc))], "warnings": [],
            "summary": "Stage 4 execution plan failed schema re-validation.",
        }

    stage3_by_id = {c["test_id"]: c for c in stage3_test_plan.get("test_concepts", [])}
    stage3_review = stage3_test_plan.get("assessment_safety_review", {}) or {}

    # ---- Plan-level structural checks ----
    if not PLAN_ID_PATTERN.match(parsed.plan_id):
        errors.append(_err("plan_id", "INVALID_PLAN_ID_FORMAT",
                           f"'{parsed.plan_id}' does not match the required MP-NNN format."))

    phase_ids = [p.phase_id for p in parsed.phases]
    if len(phase_ids) != len(set(phase_ids)):
        dupes = sorted({p for p in phase_ids if phase_ids.count(p) > 1})
        errors.append(_err("phases", "DUPLICATE_PHASE_ID", f"Duplicate phase_id(s): {dupes}."))

    sequences = [p.sequence for p in parsed.phases]
    if len(sequences) != len(set(sequences)):
        errors.append(_err("phases", "DUPLICATE_PHASE_SEQUENCE", "Phase sequence values must be unique."))
    elif sorted(sequences) != list(range(1, len(sequences) + 1)):
        errors.append(_err("phases", "NON_CONTIGUOUS_PHASE_SEQUENCE",
                           f"Phase sequence must be contiguous starting at 1; got {sorted(sequences)}."))

    all_action_ids: list = []
    for phase in parsed.phases:
        pp = f"phases[{phase.phase_id}]"
        if not PHASE_ID_PATTERN.match(phase.phase_id):
            errors.append(_err(f"{pp}.phase_id", "INVALID_PHASE_ID_FORMAT",
                               f"'{phase.phase_id}' does not match the required PHASE-NN format."))
        if not phase.actions:
            errors.append(_err(f"{pp}.actions", "EMPTY_PHASE", "Every phase requires at least one action."))
        for action in phase.actions:
            all_action_ids.append(action.action_id)
            ap = f"{pp}.actions[{action.action_id}]"
            if not ACTION_ID_PATTERN.match(action.action_id):
                errors.append(_err(f"{ap}.action_id", "INVALID_ACTION_ID_FORMAT",
                                   f"'{action.action_id}' does not match the required ACT-NNN format."))
            if not action.responsible_roles:
                errors.append(_err(f"{ap}.responsible_roles", "MISSING_RESPONSIBLE_ROLE",
                                   "At least one responsible role is required."))
            if not action.alert_triggers:
                errors.append(_err(f"{ap}.alert_triggers", "MISSING_ALERT_TRIGGER",
                                   "At least one alert trigger is required."))
            if not action.opsec_measures:
                errors.append(_err(f"{ap}.opsec_measures", "MISSING_OPSEC_MEASURE",
                                   "At least one OPSEC measure is required."))
            if _is_placeholder(action.action_summary):
                errors.append(_err(f"{ap}.action_summary", "PLACEHOLDER_VALUE",
                                   f"'{action.action_summary}' is a placeholder value."))

    if len(all_action_ids) != len(set(all_action_ids)):
        dupes = sorted({a for a in all_action_ids if all_action_ids.count(a) > 1})
        errors.append(_err("phases", "DUPLICATE_ACTION_ID", f"Duplicate action_id(s) across the plan: {dupes}."))

    # ---- Stage 3 test coverage ----
    json_source_ids = set(parsed.source_stage3_test_ids)
    stage3_ids = set(stage3_by_id.keys())
    if json_source_ids != stage3_ids:
        missing = stage3_ids - json_source_ids
        extra = json_source_ids - stage3_ids
        if missing:
            errors.append(_err("source_stage3_test_ids", "MISSING_STAGE3_TEST_ID",
                               f"source_stage3_test_ids is missing Stage 3 concept(s): {sorted(missing)}."))
        if extra:
            errors.append(_err("source_stage3_test_ids", "UNKNOWN_STAGE3_TEST_ID",
                               f"source_stage3_test_ids references nonexistent Stage 3 concept(s): {sorted(extra)}."))

    binding_test_ids = [b.test_id for b in parsed.test_bindings]
    if len(binding_test_ids) != len(set(binding_test_ids)):
        dupes = sorted({t for t in binding_test_ids if binding_test_ids.count(t) > 1})
        errors.append(_err("test_bindings", "DUPLICATE_BINDING", f"Duplicate test binding(s): {dupes}."))

    bound_ids = set(binding_test_ids)
    if bound_ids != stage3_ids:
        missing = stage3_ids - bound_ids
        extra = bound_ids - stage3_ids
        if missing:
            errors.append(_err("test_bindings", "MISSING_STAGE3_TEST_ID",
                               f"No binding for Stage 3 concept(s): {sorted(missing)}."))
        if extra:
            errors.append(_err("test_bindings", "UNKNOWN_STAGE3_TEST_ID",
                               f"Binding references nonexistent Stage 3 concept(s): {sorted(extra)}."))

    actions_by_test_id: dict = {}
    for phase in parsed.phases:
        for action in phase.actions:
            actions_by_test_id.setdefault(action.test_id, []).append(action)
            if action.test_id not in stage3_by_id:
                errors.append(_err(f"phases[{phase.phase_id}].actions[{action.action_id}].test_id",
                                   "UNKNOWN_STAGE3_TEST_ID",
                                   f"Action references nonexistent Stage 3 concept '{action.test_id}'."))

    # ---- Binding validation (agreement with Stage 3) ----
    for binding in parsed.test_bindings:
        bp = f"test_bindings[{binding.test_id}]"
        stage3_concept = stage3_by_id.get(binding.test_id)
        if stage3_concept is None:
            continue  # already reported above

        if set(binding.categories) != set(stage3_concept["categories"]):
            errors.append(_err(f"{bp}.categories", "CATEGORY_MISMATCH",
                               f"Binding categories {sorted(binding.categories)} do not match Stage 3 "
                               f"categories {sorted(stage3_concept['categories'])}."))
        if set(binding.stage2_vector_ids) != set(stage3_concept["stage2_vector_ids"]):
            errors.append(_err(f"{bp}.stage2_vector_ids", "STAGE2_VECTOR_MISMATCH",
                               "Binding stage2_vector_ids do not match Stage 3's declared vectors."))
        if binding.kcag_path != stage3_concept["kcag_path"]:
            errors.append(_err(f"{bp}.kcag_path", "KCAG_PATH_MISMATCH",
                               "Binding kcag_path does not match Stage 3's declared path (order-sensitive)."))

        stage3_technique_ids = {ref["technique_id"] for ref in stage3_concept.get("execution_techniques", [])}
        if set(binding.technique_ids) != stage3_technique_ids:
            errors.append(_err(f"{bp}.technique_ids", "TECHNIQUE_ID_MISMATCH",
                               f"Binding technique_ids {sorted(binding.technique_ids)} do not match Stage 3's "
                               f"{sorted(stage3_technique_ids)}."))

        # ---- Action assignment validation ----
        assigned = set(binding.assigned_action_ids)
        actual = {a.action_id for a in actions_by_test_id.get(binding.test_id, [])}
        if assigned != actual:
            missing = actual - assigned
            extra = assigned - actual
            if missing:
                errors.append(_err(f"{bp}.assigned_action_ids", "ASSIGNED_ACTIONS_MISSING",
                                   f"assigned_action_ids is missing real action(s): {sorted(missing)}."))
            if extra:
                errors.append(_err(f"{bp}.assigned_action_ids", "ASSIGNED_ACTIONS_STALE",
                                   f"assigned_action_ids references nonexistent action(s): {sorted(extra)}."))
        if not actual:
            errors.append(_err(f"{bp}", "TEST_HAS_NO_ACTION",
                               f"Stage 3 concept '{binding.test_id}' has no assigned Stage 4 action."))

        # ---- Criteria inheritance (union across all actions for this test) ----
        matching_actions = actions_by_test_id.get(binding.test_id, [])
        for field, code in _INHERITED_FIELDS:
            stage3_values = {_normalize(v) for v in stage3_concept.get(field, [])}
            stage4_union = {_normalize(v) for a in matching_actions for v in getattr(a, field)}
            missing_values = stage3_values - stage4_union
            if missing_values:
                errors.append(_err(f"{bp}.{field}", code,
                                   f"Stage 4 actions for '{binding.test_id}' do not collectively cover "
                                   f"Stage 3 {field}: {sorted(missing_values)}."))

    # ---- Structured Phase 0 validation ----
    category_2_3_ids = {tid for tid, c in stage3_by_id.items() if {2, 3} & set(c["categories"])}
    gate = parsed.phase0_safety_gate
    gp = "phase0_safety_gate"

    if category_2_3_ids:
        if not gate.required:
            errors.append(_err(f"{gp}.required", "SAFETY_GATE_FLAG_MISMATCH",
                               "required must be true when any Stage 3 concept carries Category 2/3."))
        covered = set(gate.covered_test_ids)
        if covered != category_2_3_ids:
            missing = category_2_3_ids - covered
            extra = covered - category_2_3_ids
            if missing:
                errors.append(_err(f"{gp}.covered_test_ids", "MISSING_COVERED_TEST_ID",
                                   f"covered_test_ids is missing: {sorted(missing)}."))
            if extra:
                errors.append(_err(f"{gp}.covered_test_ids", "EXTRA_COVERED_TEST_ID",
                                   f"covered_test_ids includes non-Category-2/3 test(s): {sorted(extra)}."))
        if gate.execution_release != "BLOCKED_PENDING_SIGNOFF":
            errors.append(_err(f"{gp}.execution_release", "INVALID_EXECUTION_RELEASE",
                               "execution_release must be BLOCKED_PENDING_SIGNOFF when Category 2/3 exists."))
        if gate.not_required_statement:
            errors.append(_err(f"{gp}.not_required_statement", "CONTRADICTORY_NOT_REQUIRED_STATEMENT",
                               "not_required_statement must be null when Category 2/3 concepts exist."))
        if not gate.required_approving_roles:
            errors.append(_err(f"{gp}.required_approving_roles", "EMPTY_APPROVING_ROLES",
                               "At least one approving role is required."))
        if not gate.safety_authority or _is_placeholder(gate.safety_authority):
            errors.append(_err(f"{gp}.safety_authority", "PLACEHOLDER_OR_MISSING", "safety_authority is required."))
        if not gate.abort_authority or _is_placeholder(gate.abort_authority):
            errors.append(_err(f"{gp}.abort_authority", "PLACEHOLDER_OR_MISSING", "abort_authority is required."))
        if not gate.abort_criteria:
            errors.append(_err(f"{gp}.abort_criteria", "EMPTY_ABORT_CRITERIA", "At least one entry is required."))
        if not gate.maximum_termination_seconds or gate.maximum_termination_seconds <= 0:
            errors.append(_err(f"{gp}.maximum_termination_seconds", "INVALID_TERMINATION_TIME",
                               "maximum_termination_seconds must be a positive integer."))
        if not gate.rollback_or_recovery_procedure or _is_placeholder(gate.rollback_or_recovery_procedure):
            errors.append(_err(f"{gp}.rollback_or_recovery_procedure", "PLACEHOLDER_OR_MISSING",
                               "rollback_or_recovery_procedure is required."))
        if not gate.release_condition:
            errors.append(_err(f"{gp}.release_condition", "MISSING_RELEASE_CONDITION", "release_condition is required."))
        else:
            lowered = gate.release_condition.lower()
            if not any(p in lowered for p in ("may not begin", "must not begin", "shall not begin")):
                errors.append(_err(f"{gp}.release_condition", "WEAK_RELEASE_CONDITION",
                                   "release_condition must contain blocking language."))

        # ---- Stage 4 must not weaken the Stage 3 assessment-level safety review ----
        stage3_seconds = stage3_review.get("maximum_termination_seconds")
        if (stage3_seconds is not None and gate.maximum_termination_seconds is not None
                and gate.maximum_termination_seconds > stage3_seconds):
            errors.append(_err(f"{gp}.maximum_termination_seconds", "TERMINATION_TIME_WEAKENED",
                               f"Stage 4 termination time ({gate.maximum_termination_seconds}s) exceeds "
                               f"Stage 3's approved maximum ({stage3_seconds}s)."))

        stage3_roles = {_normalize(r) for r in stage3_review.get("required_approving_roles", [])}
        stage4_roles = {_normalize(r) for r in gate.required_approving_roles}
        missing_roles = stage3_roles - stage4_roles
        if missing_roles:
            errors.append(_err(f"{gp}.required_approving_roles", "MISSING_STAGE3_APPROVING_ROLE",
                               f"Stage 4 drops Stage 3 approving role(s): {sorted(missing_roles)}."))

        stage3_abort = {_normalize(a) for a in stage3_review.get("abort_criteria", [])}
        stage4_abort = {_normalize(a) for a in gate.abort_criteria}
        missing_abort = stage3_abort - stage4_abort
        if missing_abort:
            errors.append(_err(f"{gp}.abort_criteria", "MISSING_STAGE3_ABORT_CRITERION",
                               f"Stage 4 drops Stage 3 assessment-level abort criteria: {sorted(missing_abort)}."))
    else:
        if gate.required:
            errors.append(_err(f"{gp}.required", "SAFETY_GATE_FLAG_MISMATCH",
                               "required must be false when no Stage 3 concept carries Category 2/3."))
        if gate.covered_test_ids:
            errors.append(_err(f"{gp}.covered_test_ids", "UNEXPECTED_COVERED_TEST_ID",
                               "covered_test_ids must be empty when no Category 2/3 concepts exist."))
        if gate.execution_release != "NOT_APPLICABLE":
            errors.append(_err(f"{gp}.execution_release", "INVALID_EXECUTION_RELEASE",
                               "execution_release must be NOT_APPLICABLE when no Category 2/3 concepts exist."))
        if (gate.not_required_statement or "").strip() != STAGE3_NO_GATE_REQUIRED:
            errors.append(_err(f"{gp}.not_required_statement", "MISSING_NOT_REQUIRED_STATEMENT",
                               f"not_required_statement must be exactly '{STAGE3_NO_GATE_REQUIRED}'."))

    is_valid = not errors
    return {
        "is_valid": is_valid,
        "status": "PASS" if is_valid else "FAIL",
        "checked_phases": len(parsed.phases),
        "checked_actions": len(all_action_ids),
        "errors": errors,
        "warnings": warnings,
        "summary": (f"Stage 4 execution-plan validation {'PASS' if is_valid else 'FAIL'}: "
                   f"{len(parsed.phases)} phase(s), {len(all_action_ids)} action(s) checked, "
                   f"{len(errors)} error(s)."),
    }


def check_stage4_artifact_consistency(*, stage4_text: str, execution_plan: dict) -> dict:
    """Deterministic anchors only -- no natural-language equivalence
    judgment. Confirms the prose and structured artifacts describe the
    SAME phases and actions, that every action heading includes its
    structured test ID, and that the Phase 0 disposition agrees."""
    errors: list = []
    stripped = _strip_markdown_emphasis(stage4_text or "")

    prose_phase_ids = set(STAGE4_PHASE_HEADING.findall(stripped))
    json_phase_ids = {p["phase_id"] for p in execution_plan.get("phases", [])}
    missing_phase_from_prose = json_phase_ids - prose_phase_ids
    missing_phase_from_json = prose_phase_ids - json_phase_ids
    if missing_phase_from_prose:
        errors.append(_err("phases", "PHASE_MISSING_FROM_PROSE",
                           f"Structured phase(s) have no matching heading in stage4_mission_plan.md: "
                           f"{sorted(missing_phase_from_prose)}."))
    if missing_phase_from_json:
        errors.append(_err("stage4_mission_plan.md", "PHASE_MISSING_FROM_JSON",
                           f"Prose phase heading(s) have no matching structured phase: "
                           f"{sorted(missing_phase_from_json)}."))

    prose_action_ids = set(STAGE4_ACTION_HEADING.findall(stripped))
    json_actions = [(a["action_id"], a["test_id"]) for p in execution_plan.get("phases", []) for a in p.get("actions", [])]
    json_action_ids = {aid for aid, _ in json_actions}
    missing_action_from_prose = json_action_ids - prose_action_ids
    missing_action_from_json = prose_action_ids - json_action_ids
    if missing_action_from_prose:
        errors.append(_err("phases", "ACTION_MISSING_FROM_PROSE",
                           f"Structured action(s) have no matching heading in stage4_mission_plan.md: "
                           f"{sorted(missing_action_from_prose)}."))
    if missing_action_from_json:
        errors.append(_err("stage4_mission_plan.md", "ACTION_MISSING_FROM_JSON",
                           f"Prose action heading(s) have no matching structured action: "
                           f"{sorted(missing_action_from_json)}."))

    # Every action heading's line must also carry its structured test_id (RT-NNN)
    action_heading_lines = {}
    for m in STAGE4_ACTION_HEADING.finditer(stripped):
        line_end = stripped.find("\n", m.end())
        action_heading_lines[m.group(1)] = stripped[m.start():line_end if line_end != -1 else None]
    for action_id, test_id in json_actions:
        line = action_heading_lines.get(action_id)
        if line is not None and test_id not in line:
            errors.append(_err(f"phases[...].actions[{action_id}]", "ACTION_HEADING_MISSING_TEST_ID",
                               f"Prose heading for {action_id} does not include its structured test_id "
                               f"'{test_id}'."))

    json_gate_required = bool((execution_plan.get("phase0_safety_gate") or {}).get("required"))
    if json_gate_required and STAGE3_NO_GATE_REQUIRED.lower() in stripped.lower():
        errors.append(_err("stage4_mission_plan.md", "PROSE_NO_GATE_CONTRADICTS_JSON",
                           "JSON declares the Phase 0 safety gate is required, but stage4_mission_plan.md "
                           "contains the 'NO CATEGORY 2/3 PAYLOADS' statement."))
    if not json_gate_required and STAGE3_NO_GATE_REQUIRED.lower() not in stripped.lower():
        errors.append(_err("stage4_mission_plan.md", "PROSE_MISSING_NOT_REQUIRED_STATEMENT",
                           "JSON declares the Phase 0 safety gate is not required, but stage4_mission_plan.md "
                           "does not contain the exact 'NO CATEGORY 2/3 PAYLOADS' statement."))

    is_consistent = not errors
    return {
        "is_consistent": is_consistent,
        "status": "PASS" if is_consistent else "FAIL",
        "errors": errors,
        "summary": (f"Stage 4 cross-artifact consistency {'PASS' if is_consistent else 'FAIL'}: "
                   f"{len(errors)} error(s)."),
    }
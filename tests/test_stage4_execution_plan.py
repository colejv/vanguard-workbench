"""
Tests for the structured Stage 4 execution-plan pipeline (Commit A):
  - src/stage4_schema.py (Pydantic schema)
  - write_stage4_execution_plan (writer tool, tools.py) -- shallow, writer-time checks
  - src/stage4_validation.py's validate_stage4_execution_plan() -- deep,
    referential validation against the real, already-verified Stage 3 test plan
  - check_stage4_artifact_consistency() -- prose/JSON cross-artifact agreement
  - enforce_stage4_execution_plan_validation() (state.py) -- the state transition

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import copy
import json

import pytest
from pydantic import ValidationError

from src import run_context
from src.tools import write_stage4_execution_plan
from src.stage4_schema import Stage4ExecutionPlan
from src.stage4_validation import validate_stage4_execution_plan, check_stage4_artifact_consistency
from src.state import init_assessment_state, enforce_stage4_execution_plan_validation
from src.schemas import StageStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    run_context.reset_active_run()
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.set_active_run("test-run", "sha256:test-corpus-hash", str(out_dir))
    yield out_dir
    run_context.reset_active_run()


STAGE3_PLAN = {
    "test_concepts": [{
        "test_id": "RT-001", "categories": [1],
        "stage2_vector_ids": ["V-01", "V-02"], "kcag_path": ["ADV_START", "N1", "G1"],
        "execution_techniques": [{"technique_id": "T1078", "vector_id": "V-01", "rationale": "x"}],
        "preconditions": ["Credentials obtained via phishing"],
        "success_criteria": ["Access confirmed via audit log"],
        "abort_criteria": ["Unexpected system instability observed"],
        "rollback_or_recovery_steps": ["Revoke test credentials"],
        "telemetry_requirements": ["Auth log monitoring"],
    }],
    "assessment_safety_review": {
        "category_2_3_present": False, "covered_test_ids": [],
        "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.",
    },
}

STAGE3_PLAN_CAT2 = {
    "test_concepts": [{
        "test_id": "RT-001", "categories": [2],
        "stage2_vector_ids": ["V-01", "V-02"], "kcag_path": ["ADV_START", "N1", "G1"],
        "execution_techniques": [{"technique_id": "T1078", "vector_id": "V-01", "rationale": "x"}],
        "preconditions": ["Credentials obtained via phishing"],
        "success_criteria": ["Access confirmed via audit log"],
        "abort_criteria": ["Unexpected system instability observed"],
        "rollback_or_recovery_steps": ["Revoke test credentials"],
        "telemetry_requirements": ["Auth log monitoring"],
    }],
    "assessment_safety_review": {
        "category_2_3_present": True, "covered_test_ids": ["RT-001"],
        "required_approving_roles": ["RSO"], "safety_authority": "RSO", "abort_authority": "Lead",
        "abort_criteria": ["Instability"], "maximum_termination_seconds": 15,
        "rollback_or_recovery_procedure": "Kill switch", "release_condition": "May not begin until cleared.",
    },
}


def _action(action_id="ACT-001", test_id="RT-001", **overrides):
    base = {
        "action_id": action_id, "test_id": test_id, "action_summary": "Use stolen credentials",
        "responsible_roles": ["Red Team Operator"], "preconditions": ["Credentials obtained via phishing"],
        "success_criteria": ["Access confirmed via audit log"], "abort_criteria": ["Unexpected system instability observed"],
        "rollback_or_recovery_steps": ["Revoke test credentials"], "telemetry_requirements": ["Auth log monitoring"],
        "alert_triggers": ["Failed auth spike"], "opsec_measures": ["Use isolated test account"],
    }
    base.update(overrides)
    return base


def _phase(phase_id="PHASE-01", sequence=1, actions=None, **overrides):
    base = {
        "phase_id": phase_id, "sequence": sequence, "name": "Preparation", "purpose": "Establish access",
        "entry_criteria": ["Authorization confirmed"], "exit_criteria": ["Access established"],
        "actions": actions if actions is not None else [_action()],
    }
    base.update(overrides)
    return base


def _binding(test_id="RT-001", assigned_action_ids=None, **overrides):
    base = {
        "test_id": test_id, "categories": [1], "stage2_vector_ids": ["V-01", "V-02"],
        "kcag_path": ["ADV_START", "N1", "G1"], "technique_ids": ["T1078"],
        "assigned_action_ids": assigned_action_ids if assigned_action_ids is not None else ["ACT-001"],
    }
    base.update(overrides)
    return base


def _plan(phases=None, bindings=None, gate=None, source_ids=None, **overrides):
    base = {
        "schema_version": 1, "plan_id": "MP-001", "plan_title": "NGC2 Mission Plan",
        "artifact_role": "HUMAN_REVIEWED_MISSION_PLAN_DRAFT", "execution_authorization": "NOT_GRANTED",
        "source_stage3_test_ids": source_ids if source_ids is not None else ["RT-001"],
        "phase0_safety_gate": gate or {"required": False, "covered_test_ids": [], "execution_release": "NOT_APPLICABLE",
                                       "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
        "test_bindings": bindings if bindings is not None else [_binding()],
        "phases": phases if phases is not None else [_phase()],
        "global_opsec_measures": ["Coordinate with Blue Team lead"],
        "assumptions": ["MFA is not enforced"], "limitations": ["Single endpoint tested"],
    }
    base.update(overrides)
    return base


def _validate(plan, stage3=None):
    return validate_stage4_execution_plan(plan=plan, stage3_test_plan=stage3 or STAGE3_PLAN)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_valid_plan_parses_schema():
    Stage4ExecutionPlan.model_validate(_plan())


def test_schema_version_required():
    bad = _plan()
    del bad["schema_version"]
    with pytest.raises(ValidationError):
        Stage4ExecutionPlan.model_validate(bad)


def test_unknown_fields_rejected():
    bad = _plan()
    bad["unexpected"] = "x"
    with pytest.raises(ValidationError):
        Stage4ExecutionPlan.model_validate(bad)


def test_execution_authorization_must_be_not_granted():
    bad = _plan(execution_authorization="GRANTED")
    with pytest.raises(ValidationError):
        Stage4ExecutionPlan.model_validate(bad)


def test_at_least_one_phase_required_by_writer():
    result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(_plan(phases=[])))
    assert result.startswith("REJECTED")


def test_phase_sequence_must_be_positive():
    with pytest.raises(ValidationError):
        Stage4ExecutionPlan.model_validate(_plan(phases=[_phase(sequence=0)]))


def test_termination_seconds_must_be_positive():
    with pytest.raises(ValidationError):
        Stage4ExecutionPlan.model_validate(_plan(gate={
            "required": True, "covered_test_ids": ["RT-001"], "required_approving_roles": ["RSO"],
            "safety_authority": "RSO", "abort_authority": "Lead", "abort_criteria": ["x"],
            "maximum_termination_seconds": 0, "rollback_or_recovery_procedure": "x",
            "release_condition": "May not begin.", "execution_release": "BLOCKED_PENDING_SIGNOFF"}))


# ---------------------------------------------------------------------------
# Writer tool
# ---------------------------------------------------------------------------

def test_writer_writes_stamped_json():
    result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(_plan()))
    assert result.startswith("WRITTEN")
    written = run_context.read_stamped_json(run_context.artifact_path("stage4_execution_plan.json"))
    assert written["plan_id"] == "MP-001"


def test_writer_rejects_invalid_json():
    result = write_stage4_execution_plan.func(execution_plan_json="{not valid")
    assert result.startswith("REJECTED")


def test_writer_rejects_schema_failure():
    bad = _plan(execution_authorization="GRANTED")
    result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(bad))
    assert result.startswith("REJECTED")


def test_writer_rejects_too_many_phases():
    phases = [_phase(phase_id=f"PHASE-{i:02d}", sequence=i, actions=[_action(action_id=f"ACT-{i:03d}")])
             for i in range(1, 14)]
    result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(_plan(phases=phases)))
    assert result.startswith("REJECTED")
    assert "too many phases" in result.lower()


def test_writer_rejects_duplicate_phase_id():
    plan = _plan(phases=[_phase(), _phase(sequence=2, actions=[_action(action_id="ACT-002")])])
    result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(plan))
    assert result.startswith("REJECTED")
    assert "phase_id" in result.lower()


def test_writer_rejects_placeholder_value():
    plan = _plan(phases=[_phase(actions=[_action(action_summary="TBD")])])
    result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(plan))
    assert result.startswith("REJECTED")
    assert "placeholder" in result.lower()


def test_writer_does_not_perform_referential_checks():
    """The writer accepts a fabricated Stage 2 vector / Stage 3 test_id
    reference -- that check belongs to validate_stage4_execution_plan()."""
    plan = _plan(bindings=[_binding(stage2_vector_ids=["V-DOES-NOT-EXIST"])])
    result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(plan))
    assert result.startswith("WRITTEN")


# ---------------------------------------------------------------------------
# Stage 3 binding
# ---------------------------------------------------------------------------

def test_every_stage3_test_requires_binding():
    r = _validate(_plan(bindings=[]))
    assert r["is_valid"] is False
    assert any(e["code"] == "MISSING_STAGE3_TEST_ID" for e in r["errors"])


def test_new_stage4_only_test_id_fails():
    r = _validate(_plan(source_ids=["RT-001", "RT-999"]))
    assert any(e["code"] == "UNKNOWN_STAGE3_TEST_ID" for e in r["errors"])


def test_missing_stage3_test_id_fails():
    r = _validate(_plan(source_ids=[]))
    assert any(e["code"] == "MISSING_STAGE3_TEST_ID" for e in r["errors"])


def test_categories_must_match_stage3():
    r = _validate(_plan(bindings=[_binding(categories=[2])]))
    assert any(e["code"] == "CATEGORY_MISMATCH" for e in r["errors"])


def test_vector_ids_must_match_stage3():
    r = _validate(_plan(bindings=[_binding(stage2_vector_ids=["V-99"])]))
    assert any(e["code"] == "STAGE2_VECTOR_MISMATCH" for e in r["errors"])


def test_kcag_path_must_match_stage3_exactly():
    r = _validate(_plan(bindings=[_binding(kcag_path=["ADV_START", "G1"])]))
    assert any(e["code"] == "KCAG_PATH_MISMATCH" for e in r["errors"])


def test_technique_ids_must_match_stage3():
    r = _validate(_plan(bindings=[_binding(technique_ids=["T9999"])]))
    assert any(e["code"] == "TECHNIQUE_ID_MISMATCH" for e in r["errors"])


def test_each_test_requires_an_action():
    empty_phase = _phase()
    empty_phase["actions"] = []
    r = _validate(_plan(phases=[empty_phase], bindings=[_binding(assigned_action_ids=[])]))
    assert any(e["code"] == "TEST_HAS_NO_ACTION" for e in r["errors"])


def test_assigned_action_ids_must_match_actual_actions():
    r = _validate(_plan(bindings=[_binding(assigned_action_ids=["ACT-001", "ACT-002"])]))
    assert any(e["code"] == "ASSIGNED_ACTIONS_STALE" for e in r["errors"])


# ---------------------------------------------------------------------------
# Criteria inheritance
# ---------------------------------------------------------------------------

def test_stage4_preserves_stage3_success_criteria():
    r = _validate(_plan(phases=[_phase(actions=[_action(success_criteria=["Something else"])])]))
    assert any(e["code"] == "MISSING_INHERITED_SUCCESS_CRITERION" for e in r["errors"])


def test_stage4_preserves_stage3_abort_criteria():
    r = _validate(_plan(phases=[_phase(actions=[_action(abort_criteria=["Something else"])])]))
    assert any(e["code"] == "MISSING_INHERITED_ABORT_CRITERION" for e in r["errors"])


def test_stage4_preserves_stage3_recovery_steps():
    r = _validate(_plan(phases=[_phase(actions=[_action(rollback_or_recovery_steps=["Something else"])])]))
    assert any(e["code"] == "MISSING_INHERITED_RECOVERY_STEP" for e in r["errors"])


def test_stage4_preserves_stage3_telemetry():
    r = _validate(_plan(phases=[_phase(actions=[_action(telemetry_requirements=["Something else"])])]))
    assert any(e["code"] == "MISSING_INHERITED_TELEMETRY" for e in r["errors"])


def test_stage4_may_add_stricter_criteria():
    """Adding EXTRA criteria beyond Stage 3's is fine -- only removal fails."""
    r = _validate(_plan(phases=[_phase(actions=[_action(
        abort_criteria=["Unexpected system instability observed", "Also abort if X happens"])])]))
    assert r["is_valid"] is True


def test_split_actions_may_collectively_cover_stage3_requirements():
    a1 = _action(action_id="ACT-001", abort_criteria=["Unexpected system instability observed"], success_criteria=[])
    a2 = _action(action_id="ACT-002", success_criteria=["Access confirmed via audit log"], abort_criteria=[])
    r = _validate(_plan(phases=[_phase(actions=[a1, a2])],
                        bindings=[_binding(assigned_action_ids=["ACT-001", "ACT-002"])]))
    assert r["is_valid"] is True


def test_each_action_requires_alert_trigger():
    r = _validate(_plan(phases=[_phase(actions=[_action(alert_triggers=[])])]))
    assert any(e["code"] == "MISSING_ALERT_TRIGGER" for e in r["errors"])


def test_each_action_requires_opsec_measure():
    r = _validate(_plan(phases=[_phase(actions=[_action(opsec_measures=[])])]))
    assert any(e["code"] == "MISSING_OPSEC_MEASURE" for e in r["errors"])


def test_each_action_requires_responsible_role():
    r = _validate(_plan(phases=[_phase(actions=[_action(responsible_roles=[])])]))
    assert any(e["code"] == "MISSING_RESPONSIBLE_ROLE" for e in r["errors"])


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

_VALID_CAT2_GATE = {
    "required": True, "covered_test_ids": ["RT-001"], "required_approving_roles": ["RSO"],
    "safety_authority": "RSO", "abort_authority": "Lead", "abort_criteria": ["Instability"],
    "maximum_termination_seconds": 15, "rollback_or_recovery_procedure": "Kill switch",
    "release_condition": "May not begin until safety clearance is signed off.",
    "execution_release": "BLOCKED_PENDING_SIGNOFF",
}


def test_category_2_requires_structured_phase0():
    r = _validate(_plan(bindings=[_binding(categories=[2])]), stage3=STAGE3_PLAN_CAT2)
    assert r["is_valid"] is False
    assert any(e["code"] == "SAFETY_GATE_FLAG_MISMATCH" for e in r["errors"])


def test_category_3_requires_structured_phase0():
    stage3_cat3 = copy.deepcopy(STAGE3_PLAN_CAT2)
    stage3_cat3["test_concepts"][0]["categories"] = [3]
    r = _validate(_plan(bindings=[_binding(categories=[3])]), stage3=stage3_cat3)
    assert r["is_valid"] is False


def test_phase0_coverage_matches_exact_test_set():
    r = _validate(_plan(bindings=[_binding(categories=[2])], gate={**_VALID_CAT2_GATE, "covered_test_ids": []}),
                  stage3=STAGE3_PLAN_CAT2)
    assert any(e["code"] == "MISSING_COVERED_TEST_ID" for e in r["errors"])


def test_phase0_release_must_be_blocked_pending_signoff():
    r = _validate(_plan(bindings=[_binding(categories=[2])], gate={**_VALID_CAT2_GATE, "execution_release": "NOT_APPLICABLE"}),
                  stage3=STAGE3_PLAN_CAT2)
    assert any(e["code"] == "INVALID_EXECUTION_RELEASE" for e in r["errors"])


def test_stage4_termination_time_cannot_be_weaker():
    r = _validate(_plan(bindings=[_binding(categories=[2])], gate={**_VALID_CAT2_GATE, "maximum_termination_seconds": 30}),
                  stage3=STAGE3_PLAN_CAT2)
    assert any(e["code"] == "TERMINATION_TIME_WEAKENED" for e in r["errors"])


def test_stage4_preserves_required_approving_roles():
    r = _validate(_plan(bindings=[_binding(categories=[2])], gate={**_VALID_CAT2_GATE, "required_approving_roles": ["Someone Else"]}),
                  stage3=STAGE3_PLAN_CAT2)
    assert any(e["code"] == "MISSING_STAGE3_APPROVING_ROLE" for e in r["errors"])


def test_no_category_2_3_requires_exact_statement():
    r = _validate(_plan(gate={"required": False, "covered_test_ids": [], "execution_release": "NOT_APPLICABLE",
                              "not_required_statement": "N/A"}))
    assert any(e["code"] == "MISSING_NOT_REQUIRED_STATEMENT" for e in r["errors"])


def test_not_required_statement_rejected_when_category_2_exists():
    r = _validate(_plan(bindings=[_binding(categories=[2])],
                        gate={**_VALID_CAT2_GATE, "not_required_statement":
                             "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."}),
                  stage3=STAGE3_PLAN_CAT2)
    assert any(e["code"] == "CONTRADICTORY_NOT_REQUIRED_STATEMENT" for e in r["errors"])


def test_fully_valid_category_2_plan_passes():
    r = _validate(_plan(bindings=[_binding(categories=[2])], gate=_VALID_CAT2_GATE), stage3=STAGE3_PLAN_CAT2)
    assert r["is_valid"] is True, r["errors"]


# ---------------------------------------------------------------------------
# Prose consistency
# ---------------------------------------------------------------------------

_CONSISTENCY_PLAN = {
    "phases": [{"phase_id": "PHASE-01", "actions": [{"action_id": "ACT-001", "test_id": "RT-001"}]}],
    "phase0_safety_gate": {"required": False},
}
_CONSISTENT_PROSE = ("## PHASE-01 — Preparation\n### ACT-001 — RT-001\nSome prose.\n"
                     "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n")


def test_every_json_phase_must_appear_in_prose():
    prose = "### ACT-001 — RT-001\nNO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n"
    r = check_stage4_artifact_consistency(stage4_text=prose, execution_plan=_CONSISTENCY_PLAN)
    assert any(e["code"] == "PHASE_MISSING_FROM_PROSE" for e in r["errors"])


def test_every_prose_phase_must_appear_in_json():
    prose = _CONSISTENT_PROSE + "\n## PHASE-02 — Extra\n"
    r = check_stage4_artifact_consistency(stage4_text=prose, execution_plan=_CONSISTENCY_PLAN)
    assert any(e["code"] == "PHASE_MISSING_FROM_JSON" for e in r["errors"])


def test_every_json_action_must_appear_in_prose():
    prose = "## PHASE-01 — Prep\nNO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n"
    r = check_stage4_artifact_consistency(stage4_text=prose, execution_plan=_CONSISTENCY_PLAN)
    assert any(e["code"] == "ACTION_MISSING_FROM_PROSE" for e in r["errors"])


def test_every_prose_action_must_appear_in_json():
    prose = _CONSISTENT_PROSE + "\n### ACT-002 — RT-002\n"
    r = check_stage4_artifact_consistency(stage4_text=prose, execution_plan=_CONSISTENCY_PLAN)
    assert any(e["code"] == "ACTION_MISSING_FROM_JSON" for e in r["errors"])


def test_action_test_id_must_match():
    prose = "## PHASE-01 — Prep\n### ACT-001 — Something else\nNO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n"
    r = check_stage4_artifact_consistency(stage4_text=prose, execution_plan=_CONSISTENCY_PLAN)
    assert any(e["code"] == "ACTION_HEADING_MISSING_TEST_ID" for e in r["errors"])


def test_structured_and_prose_phase0_must_agree():
    gate_required_plan = {**_CONSISTENCY_PLAN, "phase0_safety_gate": {"required": True}}
    r = check_stage4_artifact_consistency(stage4_text=_CONSISTENT_PROSE, execution_plan=gate_required_plan)
    assert any(e["code"] == "PROSE_NO_GATE_CONTRADICTS_JSON" for e in r["errors"])


def test_consistent_artifacts_pass():
    r = check_stage4_artifact_consistency(stage4_text=_CONSISTENT_PROSE, execution_plan=_CONSISTENCY_PLAN)
    assert r["is_consistent"] is True


# ---------------------------------------------------------------------------
# State transition
# ---------------------------------------------------------------------------

def test_enforce_execution_plan_validation_passes_through_on_valid(tmp_path):
    state = init_assessment_state("run-x", "sha256:x")
    result = enforce_stage4_execution_plan_validation(state, "run-x", is_valid=True, summary="ok", base=str(tmp_path))
    assert result is None


def test_enforce_execution_plan_validation_raises_and_sets_fail_on_invalid(tmp_path):
    state = init_assessment_state("run-x", "sha256:x")
    with pytest.raises(RuntimeError, match="structured execution-plan validation FAILED"):
        enforce_stage4_execution_plan_validation(state, "run-x", is_valid=False, summary="bad plan", base=str(tmp_path))
    assert state.current_stage == "stage4"
    assert state.stages["stage4"].status == StageStatus.FAIL


def test_enforce_execution_plan_validation_does_not_set_pass(tmp_path):
    state = init_assessment_state("run-x", "sha256:x")
    enforce_stage4_execution_plan_validation(state, "run-x", is_valid=True, summary="ok", base=str(tmp_path))
    assert state.stages["stage4"].status != StageStatus.PASS


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

def test_validation_does_not_modify_stage3_plan():
    stage3_before = copy.deepcopy(STAGE3_PLAN)
    plan_before = copy.deepcopy(_plan())
    _validate(_plan())
    assert STAGE3_PLAN == stage3_before


def test_validation_does_not_modify_stage4_plan():
    plan = _plan()
    plan_before = copy.deepcopy(plan)
    _validate(plan)
    assert plan == plan_before


def test_consistency_check_does_not_modify_stage4_prose_or_plan():
    plan_before = copy.deepcopy(_CONSISTENCY_PLAN)
    prose_before = _CONSISTENT_PROSE
    check_stage4_artifact_consistency(stage4_text=_CONSISTENT_PROSE, execution_plan=_CONSISTENCY_PLAN)
    assert _CONSISTENCY_PLAN == plan_before
    assert _CONSISTENT_PROSE == prose_before
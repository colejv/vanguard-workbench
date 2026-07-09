"""
Tests for the structured Stage 3 test-plan pipeline:
  - src/stage3_schema.py (Pydantic schema)
  - write_stage3_test_plan (writer tool, tools.py) -- shallow, writer-time checks
  - src/stage3_validation.py's validate_stage3_test_plan() -- deep,
    referential validation against the real Stage 2 graph, KCAG report,
    and technique index
  - check_stage3_artifact_consistency() -- prose/JSON cross-artifact agreement
  - enforce_stage3_test_plan_validation() (state.py) -- the state transition
  - build_stage4_task()'s new stage3_test_plan requirement (tasks.py)

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
from src.tools import write_stage3_test_plan
from src.stage3_schema import Stage3TestPlan
from src.stage3_validation import validate_stage3_test_plan, check_stage3_artifact_consistency
from src.state import (
    init_assessment_state, enforce_stage3_test_plan_validation,
)
from src.schemas import AssessmentState, StageStatus
from src.tasks import build_stage4_task


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


STAGE2_VECTORS = {
    "nodes": [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "N2", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ],
    "edges": [
        {"source": "ADV_START", "target": "N1", "technique": "T1078", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "N1", "target": "G1", "technique": "T1565.001", "difficulty": "MEDIUM", "effect": None, "vec": "V-02"},
        {"source": "ADV_START", "target": "N2", "technique": "T1190", "difficulty": "HIGH", "effect": None, "vec": "V-03"},
        {"source": "N2", "target": "G1", "technique": "CAPEC-628", "difficulty": "LOW", "effect": None, "vec": "V-04"},
    ],
}
KCAG_REPORT = {"priority_path": {"path": ["ADV_START", "N1", "G1"], "score": 0.4}}
TECHNIQUE_INDEX = json.load(open("corpus-index/technique_index.json"))


def _concept(test_id="RT-001", categories=None, path_relationship="PRIORITY_PATH",
            kcag_path=None, safety_controls=None, **overrides):
    base = {
        "test_id": test_id, "title": "Auth flow assessment", "objective": "Test authentication bypass path",
        "stage2_vector_ids": ["V-01", "V-02"],
        "kcag_path": kcag_path or ["ADV_START", "N1", "G1"],
        "path_relationship": path_relationship,
        "target_node_ids": ["N1"],
        "categories": categories or [1],
        "execution_techniques": [
            {"technique_id": "T1078", "vector_id": "V-01", "rationale": "Valid accounts used for initial access"},
        ],
        "defensive_concepts": ["MFA enforcement"],
        "mechanism_summary": "Adversary uses stolen credentials to access the C2 relay",
        "preconditions": ["Credentials obtained via phishing"],
        "expected_effects": ["Unauthorized access to C2 relay"],
        "success_criteria": ["Access confirmed via audit log"],
        "abort_criteria": ["Unexpected system instability observed"],
        "rollback_or_recovery_steps": ["Revoke test credentials"],
        "telemetry_requirements": ["Auth log monitoring"],
        "assumptions": ["MFA is not enforced on this endpoint"],
        "safety_controls": safety_controls,
    }
    base.update(overrides)
    return base


def _plan(concepts=None, review=None):
    return {
        "schema_version": 1, "plan_title": "Test Plan",
        "test_concepts": concepts or [_concept()],
        "assessment_safety_review": review or {
            "category_2_3_present": False, "covered_test_ids": [],
            "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.",
        },
    }


def _validate(plan):
    return validate_stage3_test_plan(plan=plan, stage2_vectors=STAGE2_VECTORS,
                                     kcag_report=KCAG_REPORT, technique_index=TECHNIQUE_INDEX)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_valid_plan_parses():
    Stage3TestPlan.model_validate(_plan())


def test_schema_rejects_extra_field():
    bad = _plan()
    bad["unexpected_field"] = "x"
    with pytest.raises(ValidationError):
        Stage3TestPlan.model_validate(bad)


def test_schema_rejects_invalid_category():
    bad = _plan([_concept(categories=[5])])
    with pytest.raises(ValidationError):
        Stage3TestPlan.model_validate(bad)


def test_schema_rejects_invalid_path_relationship():
    bad = _plan([_concept(path_relationship="SOME_OTHER_PATH")])
    with pytest.raises(ValidationError):
        Stage3TestPlan.model_validate(bad)


def test_schema_requires_positive_termination_seconds():
    with pytest.raises(ValidationError):
        Stage3TestPlan.model_validate(_plan([_concept(categories=[2], safety_controls={
            "affected_assets": ["x"], "required_approving_roles": ["y"], "safety_authority": "z",
            "abort_authority": "w", "maximum_termination_seconds": 0, "rollback_or_recovery_procedure": "v",
        })]))


# ---------------------------------------------------------------------------
# Writer tool (shallow, writer-time checks)
# ---------------------------------------------------------------------------

def test_writer_accepts_valid_plan():
    result = write_stage3_test_plan.func(test_plan_json=json.dumps(_plan()))
    assert result.startswith("WRITTEN")
    written = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert written["test_concepts"][0]["test_id"] == "RT-001"


def test_writer_rejects_duplicate_test_ids():
    plan = _plan([_concept(test_id="RT-001"), _concept(test_id="RT-001")])
    result = write_stage3_test_plan.func(test_plan_json=json.dumps(plan))
    assert result.startswith("REJECTED")
    assert "duplicate" in result.lower()


def test_writer_rejects_placeholder_value():
    plan = _plan([_concept(objective="TBD")])
    result = write_stage3_test_plan.func(test_plan_json=json.dumps(plan))
    assert result.startswith("REJECTED")
    assert "placeholder" in result.lower()


def test_writer_rejects_empty_test_concepts():
    plan = {
        "schema_version": 1, "plan_title": "Test Plan", "test_concepts": [],
        "assessment_safety_review": {"category_2_3_present": False, "covered_test_ids": [],
                                     "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
    }
    result = write_stage3_test_plan.func(test_plan_json=json.dumps(plan))
    assert result.startswith("REJECTED")


def test_writer_rejects_too_many_concepts():
    plan = _plan([_concept(test_id=f"RT-{i:03d}") for i in range(1, 25)])
    result = write_stage3_test_plan.func(test_plan_json=json.dumps(plan))
    assert result.startswith("REJECTED")
    assert "too many" in result.lower()


def test_writer_rejects_malformed_json():
    result = write_stage3_test_plan.func(test_plan_json="{not valid json")
    assert result.startswith("REJECTED")


def test_writer_does_not_perform_referential_checks():
    """The writer accepts a fabricated Stage 2 vector reference -- that
    check belongs to validate_stage3_test_plan(), not the writer."""
    plan = _plan([_concept(stage2_vector_ids=["V-DOES-NOT-EXIST"])])
    result = write_stage3_test_plan.func(test_plan_json=json.dumps(plan))
    assert result.startswith("WRITTEN")


# ---------------------------------------------------------------------------
# Deep referential validation
# ---------------------------------------------------------------------------

def test_valid_plan_passes_deep_validation():
    r = _validate(_plan())
    assert r["is_valid"] is True


def test_unknown_stage2_vector_fails():
    r = _validate(_plan([_concept(stage2_vector_ids=["V-99"])]))
    assert r["is_valid"] is False
    assert any(e["code"] == "UNKNOWN_STAGE2_VECTOR" for e in r["errors"])


def test_duplicate_stage2_vector_fails():
    r = _validate(_plan([_concept(stage2_vector_ids=["V-01", "V-01"])]))
    assert any(e["code"] == "DUPLICATE_STAGE2_VECTOR" for e in r["errors"])


def test_path_must_start_at_adv_start():
    r = _validate(_plan([_concept(kcag_path=["N1", "G1"])]))
    assert any(e["code"] == "PATH_MUST_START_AT_ADV_START" for e in r["errors"])


def test_path_must_end_at_goal():
    r = _validate(_plan([_concept(kcag_path=["ADV_START", "N1"])]))
    assert any(e["code"] == "PATH_MUST_END_AT_GOAL" for e in r["errors"])


def test_missing_directed_edge_fails():
    r = _validate(_plan([_concept(kcag_path=["ADV_START", "N2", "N1", "G1"])]))
    assert any(e["code"] == "MISSING_DIRECTED_EDGE" for e in r["errors"])


def test_priority_path_must_match_kcag_report():
    r = _validate(_plan([_concept(kcag_path=["ADV_START", "N2", "G1"], path_relationship="PRIORITY_PATH")]))
    assert any(e["code"] == "PRIORITY_PATH_MISMATCH" for e in r["errors"])


def test_alternate_valid_path_may_differ_from_priority_path():
    c = _concept(kcag_path=["ADV_START", "N2", "G1"], path_relationship="ALTERNATE_VALID_PATH",
                target_node_ids=["N2"], stage2_vector_ids=["V-03", "V-04"],
                execution_techniques=[{"technique_id": "T1190", "vector_id": "V-03", "rationale": "exploit"}])
    r = _validate(_plan([c]))
    assert r["is_valid"] is True


def test_target_node_must_be_on_path():
    c = _concept()
    c["target_node_ids"] = ["N2"]
    r = _validate(_plan([c]))
    assert any(e["code"] == "TARGET_NODE_NOT_ON_PATH" for e in r["errors"])


def test_unknown_technique_id_fails():
    c = _concept()
    c["execution_techniques"] = [{"technique_id": "T9999", "vector_id": "V-01", "rationale": "made up"}]
    r = _validate(_plan([c]))
    assert any(e["code"] == "UNKNOWN_TECHNIQUE_ID" for e in r["errors"])


def test_unmapped_with_rationale_warns_but_is_valid():
    c = _concept()
    c["execution_techniques"] = [{"technique_id": "[UNMAPPED]", "vector_id": "V-01",
                                  "rationale": "No matching framework entry found after search"}]
    r = _validate(_plan([c]))
    assert r["is_valid"] is True
    assert any(w["code"] == "UNMAPPED_TECHNIQUE" for w in r["warnings"])


def test_unmapped_without_rationale_fails():
    c = _concept()
    c["execution_techniques"] = [{"technique_id": "[UNMAPPED]", "vector_id": "V-01", "rationale": "idk"}]
    r = _validate(_plan([c]))
    assert any(e["code"] == "UNMAPPED_WITHOUT_RATIONALE" for e in r["errors"])


def test_invented_gap_spelling_is_rejected_as_unknown_technique():
    """Exactly '[UNMAPPED]' is the only accepted gap marker -- 'UNMAPPED'
    without brackets must not be silently treated the same way."""
    c = _concept()
    c["execution_techniques"] = [{"technique_id": "UNMAPPED", "vector_id": "V-01", "rationale": "close enough"}]
    r = _validate(_plan([c]))
    assert any(e["code"] == "UNKNOWN_TECHNIQUE_ID" for e in r["errors"])


def test_category_2_without_safety_controls_fails():
    c = _concept(categories=[2])
    review = {"category_2_3_present": True, "covered_test_ids": ["RT-001"],
             "required_approving_roles": ["RSO"], "safety_authority": "RSO", "abort_authority": "Red Team Lead",
             "abort_criteria": ["Instability"], "maximum_termination_seconds": 15,
             "rollback_or_recovery_procedure": "Kill switch",
             "release_condition": "Phase 1 may not begin until cleared."}
    r = _validate(_plan([c], review=review))
    assert any(e["code"] == "MISSING_SAFETY_CONTROLS" for e in r["errors"])


def test_category_1_with_safety_controls_fails():
    c = _concept(categories=[1], safety_controls={
        "affected_assets": ["x"], "required_approving_roles": ["y"], "safety_authority": "z",
        "abort_authority": "w", "maximum_termination_seconds": 10, "rollback_or_recovery_procedure": "v"})
    r = _validate(_plan([c]))
    assert any(e["code"] == "UNEXPECTED_SAFETY_CONTROLS" for e in r["errors"])


def test_fully_valid_category_2_concept_with_matching_review():
    c = _concept(categories=[2], safety_controls={
        "affected_assets": ["AFATDS endpoint"], "required_approving_roles": ["RSO"],
        "safety_authority": "Range Safety Officer", "abort_authority": "Red Team Lead",
        "maximum_termination_seconds": 15, "rollback_or_recovery_procedure": "Immediate kill-switch"})
    review = {"category_2_3_present": True, "covered_test_ids": ["RT-001"],
             "required_approving_roles": ["RSO"], "safety_authority": "RSO", "abort_authority": "Red Team Lead",
             "abort_criteria": ["Instability"], "maximum_termination_seconds": 15,
             "rollback_or_recovery_procedure": "Kill switch",
             "release_condition": "Phase 1 may not begin until safety clearance is signed off."}
    r = _validate(_plan([c], review=review))
    assert r["is_valid"] is True


def test_covered_test_ids_missing_a_category_2_3_test():
    c = _concept(categories=[2], safety_controls={
        "affected_assets": ["x"], "required_approving_roles": ["RSO"], "safety_authority": "RSO",
        "abort_authority": "Lead", "maximum_termination_seconds": 15, "rollback_or_recovery_procedure": "v"})
    review = {"category_2_3_present": True, "covered_test_ids": [],
             "required_approving_roles": ["RSO"], "safety_authority": "RSO", "abort_authority": "Lead",
             "abort_criteria": ["Instability"], "maximum_termination_seconds": 15,
             "rollback_or_recovery_procedure": "v", "release_condition": "May not begin until cleared."}
    r = _validate(_plan([c], review=review))
    assert any(e["code"] == "MISSING_COVERED_TEST_ID" for e in r["errors"])


def test_covered_test_ids_references_non_2_3_test():
    c = _concept(categories=[1])
    review = {"category_2_3_present": False, "covered_test_ids": ["RT-001"],
             "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."}
    r = _validate(_plan([c], review=review))
    assert any(e["code"] == "UNEXPECTED_COVERED_TEST_ID" for e in r["errors"])


def test_weak_release_condition_fails():
    c = _concept(categories=[2], safety_controls={
        "affected_assets": ["x"], "required_approving_roles": ["RSO"], "safety_authority": "RSO",
        "abort_authority": "Lead", "maximum_termination_seconds": 15, "rollback_or_recovery_procedure": "v"})
    review = {"category_2_3_present": True, "covered_test_ids": ["RT-001"],
             "required_approving_roles": ["RSO"], "safety_authority": "RSO", "abort_authority": "Lead",
             "abort_criteria": ["Instability"], "maximum_termination_seconds": 15,
             "rollback_or_recovery_procedure": "v", "release_condition": "Proceed with caution."}
    r = _validate(_plan([c], review=review))
    assert any(e["code"] == "WEAK_RELEASE_CONDITION" for e in r["errors"])


def test_contradictory_not_required_statement_fails():
    c = _concept(categories=[2], safety_controls={
        "affected_assets": ["x"], "required_approving_roles": ["RSO"], "safety_authority": "RSO",
        "abort_authority": "Lead", "maximum_termination_seconds": 15, "rollback_or_recovery_procedure": "v"})
    review = {"category_2_3_present": True, "covered_test_ids": ["RT-001"],
             "required_approving_roles": ["RSO"], "safety_authority": "RSO", "abort_authority": "Lead",
             "abort_criteria": ["Instability"], "maximum_termination_seconds": 15,
             "rollback_or_recovery_procedure": "v", "release_condition": "May not begin until cleared.",
             "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."}
    r = _validate(_plan([c], review=review))
    assert any(e["code"] == "CONTRADICTORY_NOT_REQUIRED_STATEMENT" for e in r["errors"])


def test_missing_not_required_statement_wording_fails():
    r = _validate(_plan(review={"category_2_3_present": False, "covered_test_ids": [],
                               "not_required_statement": "N/A"}))
    assert any(e["code"] == "MISSING_NOT_REQUIRED_STATEMENT" for e in r["errors"])


def test_identical_success_and_abort_criteria_fails():
    c = _concept()
    c["success_criteria"] = ["Access confirmed"]
    c["abort_criteria"] = ["Access confirmed"]
    r = _validate(_plan([c]))
    assert any(e["code"] == "IDENTICAL_SUCCESS_ABORT_CRITERIA" for e in r["errors"])


def test_duplicate_list_items_after_normalization_fails():
    c = _concept()
    c["preconditions"] = ["Creds obtained", "creds obtained"]
    r = _validate(_plan([c]))
    assert any(e["code"] == "DUPLICATE_LIST_ITEM" for e in r["errors"])


def test_validator_does_not_mutate_inputs():
    plan = _plan()
    stage2_before = copy.deepcopy(STAGE2_VECTORS)
    kcag_before = copy.deepcopy(KCAG_REPORT)
    plan_before = copy.deepcopy(plan)
    _validate(plan)
    assert STAGE2_VECTORS == stage2_before
    assert KCAG_REPORT == kcag_before
    assert plan == plan_before


def test_malformed_plan_fails_schema_revalidation():
    r = validate_stage3_test_plan(plan={"not": "a valid plan"}, stage2_vectors=STAGE2_VECTORS,
                                  kcag_report=KCAG_REPORT, technique_index=TECHNIQUE_INDEX)
    assert r["is_valid"] is False
    assert r["errors"][0]["code"] == "SCHEMA_INVALID"


# ---------------------------------------------------------------------------
# Cross-artifact consistency
# ---------------------------------------------------------------------------

def _prose_for(*sections):
    return "# Stage 3\n" + "\n".join(sections) + (
        "\n## PRE-STAGE-4 SAFETY REVIEW\nNO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n")


def test_consistent_prose_and_json_pass():
    plan = _plan()
    prose = _prose_for("### RT-001 — Auth flow assessment\n**Category:** 1\nSome prose.")
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert r["is_consistent"] is True


def test_json_test_id_missing_from_prose_fails():
    plan = _plan([_concept(test_id="RT-001"), _concept(test_id="RT-002")])
    prose = _prose_for("### RT-001 — Auth flow\n**Category:** 1\n")
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert r["is_consistent"] is False
    assert any(e["code"] == "TEST_ID_MISSING_FROM_PROSE" for e in r["errors"])


def test_prose_heading_missing_from_json_fails():
    plan = _plan([_concept(test_id="RT-001")])
    prose = _prose_for("### RT-001 — Auth flow\n**Category:** 1\n", "### RT-002 — Extra\n**Category:** 1\n")
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert any(e["code"] == "TEST_ID_MISSING_FROM_JSON" for e in r["errors"])


def test_category_mismatch_between_prose_and_json_fails():
    plan = _plan([_concept(test_id="RT-001", categories=[1, 4])])
    prose = _prose_for("### RT-001 — Auth flow\n**Category:** 2\n")
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert any(e["code"] == "CATEGORY_MISMATCH" for e in r["errors"])


def test_bold_markdown_category_labels_are_parsed():
    plan = _plan([_concept(test_id="RT-001", categories=[1, 4])])
    prose = _prose_for("### RT-001 — Auth flow\n**Category:** `1, 4`\n")
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert r["is_consistent"] is True


def test_prose_no_gate_sentence_contradicts_json_category_2_3():
    plan = _plan([_concept(test_id="RT-001", categories=[2])])
    prose = ("### RT-001 — X\n**Category:** 2\n"
            "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n")
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert any(e["code"] == "PROSE_NO_GATE_CONTRADICTS_JSON" for e in r["errors"])


# ---------------------------------------------------------------------------
# State transition
# ---------------------------------------------------------------------------

def test_enforce_test_plan_validation_passes_through_on_valid(tmp_path):
    state = init_assessment_state("run-x", "sha256:x")
    result = enforce_stage3_test_plan_validation(state, "run-x", is_valid=True, summary="ok", base=str(tmp_path))
    assert result is None  # no-op on success -- does not set PASS


def test_enforce_test_plan_validation_raises_and_sets_fail_on_invalid(tmp_path):
    state = init_assessment_state("run-x", "sha256:x")
    with pytest.raises(RuntimeError, match="structured test-plan validation FAILED"):
        enforce_stage3_test_plan_validation(state, "run-x", is_valid=False, summary="bad plan", base=str(tmp_path))
    assert state.current_stage == "stage3"


def test_enforce_test_plan_validation_does_not_set_pass(tmp_path):
    """Confirms the documented separation of concerns: only
    enforce_stage3_safety_gate (unchanged) sets Stage 3 to PASS."""
    state = init_assessment_state("run-x", "sha256:x")
    enforce_stage3_test_plan_validation(state, "run-x", is_valid=True, summary="ok", base=str(tmp_path))
    assert state.stages["stage3"].status != StageStatus.PASS


# ---------------------------------------------------------------------------
# build_stage4_task
# ---------------------------------------------------------------------------

def test_build_stage4_task_requires_test_plan():
    with pytest.raises(ValueError, match="structured Stage 3 test plan"):
        build_stage4_task("outputs/test-run", stage3_content="some content", stage3_test_plan=None)


def test_build_stage4_task_requires_stage3_content():
    with pytest.raises(ValueError):
        build_stage4_task("outputs/test-run", stage3_content="", stage3_test_plan=_plan())


def test_build_stage4_task_embeds_structured_plan():
    task = build_stage4_task("outputs/test-run", stage3_content="prose content", stage3_test_plan=_plan())
    assert "RT-001" in task.description
    assert "VERIFIED STRUCTURED STAGE 3 TEST PLAN" in task.description
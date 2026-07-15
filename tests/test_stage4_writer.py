"""
Tests for the Stage 4 structured compiler and its deterministic Phase 0
safety-gate overlay (src/stage4_writer.py).

The Phase 0 gate is derived from the VALIDATED Stage 3 test plan's
assessment_safety_review — not reparsed from stage3.md — so Stage 4's gate
is provably identical to what Stage 3 validated.
"""
import pytest

from src.stage4_writer import (
    build_stage4_phase0_gate, _apply_phase0_overlay,
    STAGE4_WRITE_PROMPT_TEMPLATE,
)
from src.stage4_schema import Stage4ExecutionPlan

_GATE_MODEL = Stage4ExecutionPlan.model_fields["phase0_safety_gate"].annotation


def _stage3_cat23():
    return {"data": {"assessment_safety_review": {
        "category_2_3_present": True, "covered_test_ids": ["RT-002"],
        "required_approving_roles": ["Safety Officer", "Operations Director"],
        "safety_authority": "Site Safety Manager",
        "abort_authority": "Lead Systems Engineer",
        "abort_criteria": ["Signal interference detected in primary navigation sensors"],
        "maximum_termination_seconds": 900,
        "rollback_or_recovery_procedure": "Revert to INS and manual override; clear spoofing buffer",
        "release_condition": "Execution may not begin before safety clearance is approved.",
        "not_required_statement": None,
    }}}


def _stage3_cat1():
    return {"data": {"assessment_safety_review": {
        "category_2_3_present": False, "covered_test_ids": [],
        "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.",
    }}}


def test_template_formats_cleanly():
    STAGE4_WRITE_PROMPT_TEMPLATE.format(referential_context="x", stage4_prose="y")


def test_gate_cat23_copies_governance_verbatim():
    gate = build_stage4_phase0_gate(_stage3_cat23())
    assert gate["required"] is True
    assert gate["required_approving_roles"] == ["Safety Officer", "Operations Director"]
    assert gate["safety_authority"] == "Site Safety Manager"
    assert gate["abort_authority"] == "Lead Systems Engineer"
    assert gate["maximum_termination_seconds"] == 900
    assert gate["covered_test_ids"] == ["RT-002"]


def test_gate_cat23_uses_blocked_enum_and_keeps_release_sentence():
    gate = build_stage4_phase0_gate(_stage3_cat23())
    # execution_release is a STATUS enum, not the sentence.
    assert gate["execution_release"] == "BLOCKED_PENDING_SIGNOFF"
    # The sentence lives in release_condition.
    assert gate["release_condition"].startswith("Execution may not begin")
    assert gate["not_required_statement"] is None


def test_gate_cat23_validates_against_schema():
    gate = build_stage4_phase0_gate(_stage3_cat23())
    v = _GATE_MODEL.model_validate(gate)
    assert v.required is True
    assert v.execution_release == "BLOCKED_PENDING_SIGNOFF"


def test_gate_cat1_is_not_applicable():
    gate = build_stage4_phase0_gate(_stage3_cat1())
    assert gate["required"] is False
    assert gate["execution_release"] == "NOT_APPLICABLE"
    v = _GATE_MODEL.model_validate(gate)
    assert v.required is False


def test_gate_accepts_bare_plan_or_stamped_artifact():
    bare = _stage3_cat23()["data"]  # unwrapped
    stamped = _stage3_cat23()       # {"data": {...}}
    assert build_stage4_phase0_gate(bare) == build_stage4_phase0_gate(stamped)


def test_overlay_replaces_model_phase0_gate():
    # Model emitted the WRONG field names (the real failure): rso_coordination,
    # max_termination_time, statement. Overlay must replace it wholesale.
    candidate = {
        "phase0_safety_gate": {
            "rso_coordination": "Required", "max_termination_time": "15 minutes",
            "statement": "Phase 1 may NOT begin until clearance is signed off.",
        }
    }
    _apply_phase0_overlay(candidate, _stage3_cat23())
    gate = candidate["phase0_safety_gate"]
    assert "rso_coordination" not in gate
    assert "max_termination_time" not in gate
    assert gate["required"] is True
    assert gate["execution_release"] == "BLOCKED_PENDING_SIGNOFF"


def test_overlay_never_invents_when_governance_absent():
    # A Cat 2/3 plan whose review has null authorities still overlays the
    # nulls verbatim (the gate is derived, not fabricated) — downstream deep
    # validation is what flags an incomplete gate, not this overlay.
    plan = {"data": {"assessment_safety_review": {
        "category_2_3_present": True, "covered_test_ids": ["RT-002"],
        "required_approving_roles": [], "safety_authority": None,
        "abort_authority": None, "abort_criteria": [],
        "maximum_termination_seconds": None, "rollback_or_recovery_procedure": None,
        "release_condition": None, "not_required_statement": None,
    }}}
    gate = build_stage4_phase0_gate(plan)
    assert gate["required"] is True
    assert gate["safety_authority"] is None
    assert gate["required_approving_roles"] == []


def test_build_stage4_validation_report_binds_hashes():
    from src.stage4_validation import build_stage4_validation_report, stage4_candidate_hash
    plan = {"schema_version": 1, "plan_id": "MP-001"}
    s3 = {"data": {"assessment_safety_review": {"category_2_3_present": False}}}
    report = build_stage4_validation_report(
        plan=plan, stage3_test_plan=s3,
        plan_validation={"is_valid": True, "summary": "ok"},
        consistency={"is_consistent": True, "summary": "ok"},
    )
    assert report["is_valid"] is True
    assert report["source_identity"]["stage4_execution_plan_sha256"] == stage4_candidate_hash(plan)
    assert report["source_identity"]["stage3_test_plan_sha256"] == stage4_candidate_hash(s3)
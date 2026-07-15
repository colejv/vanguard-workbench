"""
Tests for the deterministic safety overlay (_apply_safety_overlay in
src/stage3_writer.py) — injecting the parsed PRE-STAGE-4 SAFETY REVIEW
into a candidate before Pydantic validation, replacing the safety fields
the model routinely dropped/misfiled.
"""
import copy

import pytest

from src.stage3_writer import _apply_safety_overlay


_PROSE = """# STAGE 3

## PRE-STAGE-4 SAFETY REVIEW
Category 2/3 concepts present: YES
Covered test concepts: RT-002
Affected assets: Mobile Asset Navigation System, GPS Receiver
Required approving roles: Safety Officer, Operations Director
RSO or domain-equivalent safety authority: Site Safety Manager
Abort authority: Lead Systems Engineer
Abort criteria: Signal interference detected in primary navigation sensors
Maximum termination time: 15 minutes
Rollback or recovery procedure: Revert to INS and manual override
Release condition: Execution may not begin before safety clearance is approved.
"""

_PROSE_NO_CAT23 = """# STAGE 3

## PRE-STAGE-4 SAFETY REVIEW
Category 2/3 concepts present: NO
"""


def _candidate_with_empty_safety():
    """Mirrors exactly what the model produced on the real run: empty/null
    assessment_safety_review and a covered concept with partial controls."""
    return {
        "schema_version": 1, "plan_title": "x",
        "test_concepts": [
            {"test_id": "RT-001", "categories": [1], "safety_controls": None},
            {"test_id": "RT-002", "categories": [2],
             "safety_controls": {"maximum_termination_seconds": 999}},  # will be overlaid
        ],
        "assessment_safety_review": {
            "category_2_3_present": True, "covered_test_ids": ["RT-002"],
            "required_approving_roles": [], "safety_authority": None,
            "abort_authority": None, "abort_criteria": [],
            "maximum_termination_seconds": None,
            "rollback_or_recovery_procedure": None, "release_condition": None,
            "not_required_statement": "Execution may not begin before safety clearance is approved.",
        },
    }


def test_overlay_replaces_empty_assessment_review():
    cand = _candidate_with_empty_safety()
    _apply_safety_overlay(cand, _PROSE)
    review = cand["assessment_safety_review"]
    assert review["required_approving_roles"] == ["Safety Officer", "Operations Director"]
    assert review["safety_authority"] == "Site Safety Manager"
    assert review["abort_authority"] == "Lead Systems Engineer"
    assert review["abort_criteria"] == ["Signal interference detected in primary navigation sensors"]
    assert review["maximum_termination_seconds"] == 900
    assert review["release_condition"].startswith("Execution may not begin")
    # not_required_statement forced null because Cat 2/3 present
    assert review["not_required_statement"] is None


def test_overlay_populates_covered_concept_controls():
    cand = _candidate_with_empty_safety()
    _apply_safety_overlay(cand, _PROSE)
    rt002 = next(c for c in cand["test_concepts"] if c["test_id"] == "RT-002")
    sc = rt002["safety_controls"]
    assert sc["affected_assets"] == ["Mobile Asset Navigation System", "GPS Receiver"]
    assert sc["required_approving_roles"] == ["Safety Officer", "Operations Director"]
    assert sc["safety_authority"] == "Site Safety Manager"
    assert sc["abort_authority"] == "Lead Systems Engineer"
    assert sc["maximum_termination_seconds"] == 900  # overlaid over the model's 999
    assert sc["rollback_or_recovery_procedure"].startswith("Revert to INS")


def test_overlay_does_not_modify_uncovered_concepts():
    cand = _candidate_with_empty_safety()
    before = copy.deepcopy(next(c for c in cand["test_concepts"] if c["test_id"] == "RT-001"))
    _apply_safety_overlay(cand, _PROSE)
    after = next(c for c in cand["test_concepts"] if c["test_id"] == "RT-001")
    assert after == before  # RT-001 (Category 1, not covered) untouched


def test_overlay_noop_when_no_category_2_3():
    cand = {
        "schema_version": 1, "plan_title": "x",
        "test_concepts": [{"test_id": "RT-001", "categories": [1], "safety_controls": None}],
        "assessment_safety_review": {
            "category_2_3_present": False, "covered_test_ids": [],
            "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.",
        },
    }
    before = copy.deepcopy(cand)
    _apply_safety_overlay(cand, _PROSE_NO_CAT23)
    assert cand == before  # nothing overlaid — model's not-required path intact


def test_overlay_propagates_parse_failure_as_gap():
    """If Cat 2/3 is present but the prose safety block is incomplete, the
    parser raises — the overlay must let that propagate (analyst gap), not
    silently produce a partial plan."""
    bad_prose = _PROSE.replace(
        "RSO or domain-equivalent safety authority: Site Safety Manager\n", "")
    cand = _candidate_with_empty_safety()
    with pytest.raises(ValueError, match="safety_authority"):
        _apply_safety_overlay(cand, bad_prose)


def test_overlay_then_full_schema_validation_passes():
    """End-to-end: a candidate with the model's empty safety fields, after
    overlay, validates cleanly against the full Stage3TestPlan schema — the
    exact failure from the real run, now fixed deterministically."""
    from src.stage3_schema import Stage3TestPlan
    # Build a fully-formed candidate whose only defect is empty safety.
    cand = {
        "schema_version": 1, "plan_title": "NGC2 Test Plan",
        "test_concepts": [{
            "test_id": "RT-002", "title": "GPS Spoofing", "objective": "Test spoof path",
            "stage2_vector_ids": ["V-02", "V-05"],
            "kcag_path": ["ADV_START", "CAPEC-628", "G_CDL_ALL"],
            "path_relationship": "PRIORITY_PATH", "target_node_ids": ["CAPEC-628"],
            "categories": [2],
            "execution_techniques": [{"technique_id": "CAPEC-628", "vector_id": "V-02", "rationale": "spoof"}],
            "defensive_concepts": ["signal integrity monitoring"],
            "mechanism_summary": "Spoof GPS to corrupt navigation",
            "preconditions": ["RF access"], "expected_effects": ["nav corruption"],
            "success_criteria": ["nav drift observed"], "abort_criteria": ["unexpected instability"],
            "rollback_or_recovery_steps": ["revert to INS"], "telemetry_requirements": ["nav logs"],
            "assumptions": ["no jamming detection"],
            "safety_controls": None,  # model left it empty
        }],
        "assessment_safety_review": {
            "category_2_3_present": True, "covered_test_ids": ["RT-002"],
            "required_approving_roles": [], "safety_authority": None, "abort_authority": None,
            "abort_criteria": [], "maximum_termination_seconds": None,
            "rollback_or_recovery_procedure": None, "release_condition": None,
            "not_required_statement": None,
        },
    }
    _apply_safety_overlay(cand, _PROSE)
    # Must now validate against the full schema without error.
    validated = Stage3TestPlan.model_validate(cand)
    assert validated.assessment_safety_review.safety_authority == "Site Safety Manager"
    assert validated.test_concepts[0].safety_controls.maximum_termination_seconds == 900
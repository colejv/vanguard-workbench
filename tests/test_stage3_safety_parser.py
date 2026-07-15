"""
Tests for parse_pre_stage4_safety_review (src/stage3_writer.py) — the
deterministic extraction of the ## PRE-STAGE-4 SAFETY REVIEW prose block
into structured assessment_safety_review + concept safety_controls.

These are safety-governance values: the parser extracts the analyst-approved
prose verbatim and NEVER invents anything. If Category 2/3 concepts are
present and any required label is missing/placeholder, it fails closed.
"""
import pytest

from src.stage3_writer import parse_pre_stage4_safety_review, _duration_to_seconds


# The exact block from the real run (vaf_20260714_165237 stage3.md).
_REAL_BLOCK = """# STAGE 3

### RT-002 — GPS Spoofing Test
prose.

## PRE-STAGE-4 SAFETY REVIEW
Category 2/3 concepts present: YES
Covered test concepts: RT-002
Affected assets: Mobile Asset Navigation System, GPS Receiver
Required approving roles: Safety Officer, Operations Director
RSO or domain-equivalent safety authority: Site Safety Manager
Abort authority: Lead Systems Engineer
Abort criteria: Signal interference detected in primary navigation sensors
Maximum termination time: 15 minutes
Rollback or recovery procedure: Revert to inertial navigation system (INS) and manual override; clear spoofing buffer
Release condition: Execution may not begin before safety clearance is approved.
"""


def test_safety_parser_extracts_all_labeled_fields():
    review, controls = parse_pre_stage4_safety_review(_REAL_BLOCK)
    assert review["category_2_3_present"] is True
    assert review["covered_test_ids"] == ["RT-002"]
    assert review["required_approving_roles"] == ["Safety Officer", "Operations Director"]
    assert review["safety_authority"] == "Site Safety Manager"
    assert review["abort_authority"] == "Lead Systems Engineer"
    assert review["abort_criteria"] == ["Signal interference detected in primary navigation sensors"]
    assert review["rollback_or_recovery_procedure"].startswith("Revert to inertial")
    assert review["release_condition"].startswith("Execution may not begin")
    # concept_controls carries the schema-defined SafetyControls fields
    assert controls["affected_assets"] == ["Mobile Asset Navigation System", "GPS Receiver"]
    assert controls["required_approving_roles"] == ["Safety Officer", "Operations Director"]
    # abort_criteria / release_condition are NOT in concept controls (not in schema)
    assert "abort_criteria" not in controls
    assert "release_condition" not in controls


def test_safety_parser_converts_15_minutes_to_900_seconds():
    review, controls = parse_pre_stage4_safety_review(_REAL_BLOCK)
    assert review["maximum_termination_seconds"] == 900
    assert controls["maximum_termination_seconds"] == 900


def test_duration_conversion_units():
    assert _duration_to_seconds("15 minutes") == 900
    assert _duration_to_seconds("900 seconds") == 900
    assert _duration_to_seconds("900") == 900
    assert _duration_to_seconds("2 hours") == 7200
    assert _duration_to_seconds("30 min") == 1800
    with pytest.raises(ValueError):
        _duration_to_seconds("a while")


def test_category_2_3_forces_not_required_statement_null():
    review, _ = parse_pre_stage4_safety_review(_REAL_BLOCK)
    assert review["not_required_statement"] is None


def test_release_condition_is_not_mapped_to_not_required_statement():
    review, _ = parse_pre_stage4_safety_review(_REAL_BLOCK)
    # The release condition must land in release_condition, NOT in
    # not_required_statement (the exact bug the LLM made).
    assert review["release_condition"].startswith("Execution may not begin")
    assert review["not_required_statement"] is None


def test_missing_required_safety_label_fails_closed():
    # Drop the "Safety authority" line — Cat 2/3 present but a required
    # label absent must raise, never silently produce a partial review.
    block = _REAL_BLOCK.replace(
        "RSO or domain-equivalent safety authority: Site Safety Manager\n", "")
    with pytest.raises(ValueError, match="safety_authority"):
        parse_pre_stage4_safety_review(block)


def test_placeholder_value_fails_closed():
    block = _REAL_BLOCK.replace("Abort authority: Lead Systems Engineer",
                                "Abort authority: TBD")
    with pytest.raises(ValueError, match="abort_authority"):
        parse_pre_stage4_safety_review(block)


def test_no_category_2_3_returns_none():
    block = """## PRE-STAGE-4 SAFETY REVIEW
Category 2/3 concepts present: NO
"""
    review, controls = parse_pre_stage4_safety_review(block)
    assert review is None
    assert controls is None


def test_missing_section_raises():
    with pytest.raises(ValueError, match="No '## PRE-STAGE-4 SAFETY REVIEW'"):
        parse_pre_stage4_safety_review("# Stage 3\nno safety section here\n")
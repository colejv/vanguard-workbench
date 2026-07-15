"""
Tests for candidate-hash binding in the Stage 3 validation report
(src/stage3_validation.py) — so a stale passing report cannot be treated
as validating a different candidate.
"""
from src.stage3_validation import (
    stage3_candidate_hash, build_stage3_validation_report,
)


def _plan(title="Plan A"):
    return {
        "schema_version": 1, "plan_title": title,
        "test_concepts": [{"test_id": "RT-001", "categories": [1]}],
        "assessment_safety_review": {"category_2_3_present": False, "covered_test_ids": []},
    }


def test_hash_is_deterministic_for_same_content():
    assert stage3_candidate_hash(_plan()) == stage3_candidate_hash(_plan())


def test_hash_ignores_key_order():
    p1 = {"a": 1, "b": 2}
    p2 = {"b": 2, "a": 1}
    assert stage3_candidate_hash(p1) == stage3_candidate_hash(p2)


def test_hash_changes_when_plan_changes():
    assert stage3_candidate_hash(_plan("Plan A")) != stage3_candidate_hash(_plan("Plan B"))


def test_hash_has_sha256_prefix():
    h = stage3_candidate_hash(_plan())
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_report_records_validated_artifact_hash():
    plan = _plan()
    report = build_stage3_validation_report(
        plan=plan,
        plan_validation={"is_valid": True, "summary": "ok"},
        consistency={"is_consistent": True, "summary": "ok"},
        artifact_path="outputs/run/stage3_test_plan.json",
    )
    assert report["validated_artifact"]["path"] == "outputs/run/stage3_test_plan.json"
    assert report["validated_artifact"]["sha256"] == stage3_candidate_hash(plan)
    assert report["is_valid"] is True


def test_report_is_valid_reflects_both_checks():
    plan = _plan()
    # plan_validation fails -> is_valid False even if consistency passes
    report = build_stage3_validation_report(
        plan=plan,
        plan_validation={"is_valid": False, "summary": "12 errors"},
        consistency={"is_consistent": True, "summary": "ok"},
        artifact_path="x",
    )
    assert report["is_valid"] is False
    # the recorded hash still matches the plan that was checked
    assert report["validated_artifact"]["sha256"] == stage3_candidate_hash(plan)


def test_stale_report_hash_detects_changed_candidate():
    """The core protection: a report built for plan A does not match the
    hash of a later, different plan B — so resume logic can reject a stale
    passing report against a changed candidate."""
    plan_a = _plan("Plan A")
    report = build_stage3_validation_report(
        plan=plan_a,
        plan_validation={"is_valid": True, "summary": "ok"},
        consistency={"is_consistent": True, "summary": "ok"},
        artifact_path="x",
    )
    plan_b = _plan("Plan B (regenerated)")
    assert report["validated_artifact"]["sha256"] != stage3_candidate_hash(plan_b)
    assert report["validated_artifact"]["sha256"] == stage3_candidate_hash(plan_a)
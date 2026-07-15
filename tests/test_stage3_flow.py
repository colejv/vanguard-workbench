"""
Tests for the Stage 3 semantic-repair orchestrator (src/stage3_flow.py).

Uses in-memory fakes for the injected compile/validate callables, so the
loop, archival, feedback accumulation, and fail-closed behavior are tested
without a real model, crew, or validator.
"""
import json
import os

import pytest

from src import run_context


# In-memory stamped-json store for the identity-baseline persistence params.
_mem_store = {}
def _mem_read(p):
    if p not in _mem_store:
        raise FileNotFoundError(p)
    return _mem_store[p]
def _mem_write(p, payload):
    _mem_store[p] = payload
from src.stage3_flow import (
    compile_stage3_until_valid, stage3_is_semantically_complete,
    _format_semantic_feedback,
)


@pytest.fixture(autouse=True)
def _run(tmp_path):
    _mem_store.clear()
    run_context.reset_active_run()
    run_context.set_active_run("test-run", "sha256:test", str(tmp_path / "out"))
    yield
    run_context.reset_active_run()


def _paths():
    art = run_context.artifact_path("stage3_test_plan.json")
    rep = run_context.artifact_path("stage3_test_plan_validation.json")
    os.makedirs(os.path.dirname(art), exist_ok=True)
    return art, rep


def _valid_report():
    return {"is_valid": True,
            "plan_validation": {"is_valid": True, "errors": []},
            "artifact_consistency": {"is_consistent": True, "errors": []}}


def _invalid_report(errors):
    return {"is_valid": False,
            "plan_validation": {"is_valid": False, "errors": errors},
            "artifact_consistency": {"is_consistent": True, "errors": []}}


def test_returns_on_first_pass():
    art, rep = _paths()
    calls = {"compile": 0}

    def compile_candidate(*, external_feedback):
        calls["compile"] += 1
        with open(art, "w") as f:
            f.write("{}")

    report = compile_stage3_until_valid(
        compile_candidate=compile_candidate,
        validate_candidate=_valid_report,
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        read_candidate=lambda: {"test_concepts": []},
        identity_baseline_path="baseline_key",
        read_stamped_json=_mem_read, write_stamped_json=_mem_write,
        artifact_path=art, validation_report_path=rep,
    )
    assert report["is_valid"] is True
    assert calls["compile"] == 1


def test_candidate_2_receives_candidate_1_errors():
    """The core semantic-loop guarantee: candidate 1 fails deep validation,
    and candidate 2's compile receives every error as feedback."""
    art, rep = _paths()
    feedback_seen = []
    reports = iter([
        _invalid_report([
            {"path": "test_concepts[RT-002].target_node_ids[0]",
             "code": "TARGET_NODE_NOT_ON_PATH", "message": "Node 'CAPEC-628' is not on the declared kcag_path."},
            {"path": "assessment_safety_review.safety_authority",
             "code": "PLACEHOLDER_OR_MISSING", "message": "safety_authority is required."},
        ]),
        _valid_report(),
    ])

    def compile_candidate(*, external_feedback):
        feedback_seen.append(external_feedback)
        with open(art, "w") as f:
            f.write("{}")

    def validate_candidate():
        return next(reports)

    report = compile_stage3_until_valid(
        compile_candidate=compile_candidate,
        validate_candidate=validate_candidate,
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        read_candidate=lambda: {"test_concepts": []},
        identity_baseline_path="baseline_key",
        read_stamped_json=_mem_read, write_stamped_json=_mem_write,
        artifact_path=art, validation_report_path=rep,
    )
    assert report["is_valid"] is True
    # Attempt 1 had no feedback; attempt 2 must carry BOTH error messages.
    assert feedback_seen[0] == ""
    assert "CAPEC-628" in feedback_seen[1]
    assert "safety_authority" in feedback_seen[1]


def test_rejected_candidates_are_archived():
    art, rep = _paths()
    reports = iter([_invalid_report([{"message": "bad"}]), _valid_report()])

    def compile_candidate(*, external_feedback):
        with open(art, "w") as f:
            f.write('{"attempt": "x"}')

    compile_stage3_until_valid(
        compile_candidate=compile_candidate,
        validate_candidate=lambda: next(reports),
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        read_candidate=lambda: {"test_concepts": []},
        identity_baseline_path="baseline_key",
        read_stamped_json=_mem_read, write_stamped_json=_mem_write,
        artifact_path=art, validation_report_path=rep,
    )
    # The attempt-1 rejected candidate + report were archived.
    assert os.path.exists(art + ".semantic_rejected_1")
    assert os.path.exists(rep + ".semantic_rejected_1")


def test_fails_closed_and_removes_invalid_candidate():
    """After exhausting attempts, raise, and leave NO authoritative
    candidate on the primary path (all archived)."""
    art, rep = _paths()

    def compile_candidate(*, external_feedback):
        with open(art, "w") as f:
            f.write("{}")

    with pytest.raises(RuntimeError, match="failed after 3 attempt"):
        compile_stage3_until_valid(
            compile_candidate=compile_candidate,
            validate_candidate=lambda: _invalid_report([{"message": "always bad"}]),
            write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
            read_candidate=lambda: {"test_concepts": []},
        identity_baseline_path="baseline_key",
        read_stamped_json=_mem_read, write_stamped_json=_mem_write,
            artifact_path=art, validation_report_path=rep,
            max_semantic_attempts=3,
        )
    # No authoritative candidate remains; all three archived.
    assert not os.path.exists(art)
    assert os.path.exists(art + ".semantic_rejected_3")


def test_feedback_accumulates_across_semantic_attempts():
    art, rep = _paths()
    feedback_seen = []
    reports = iter([
        _invalid_report([{"message": "error_A"}]),
        _invalid_report([{"message": "error_B"}]),
        _valid_report(),
    ])

    def compile_candidate(*, external_feedback):
        feedback_seen.append(external_feedback)
        with open(art, "w") as f:
            f.write("{}")

    compile_stage3_until_valid(
        compile_candidate=compile_candidate,
        validate_candidate=lambda: next(reports),
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        read_candidate=lambda: {"test_concepts": []},
        identity_baseline_path="baseline_key",
        read_stamped_json=_mem_read, write_stamped_json=_mem_write,
        artifact_path=art, validation_report_path=rep,
    )
    # Attempt 3's feedback must contain BOTH prior errors (accumulated).
    assert "error_A" in feedback_seen[2]
    assert "error_B" in feedback_seen[2]


def test_format_feedback_groups_error_kinds():
    report = {
        "plan_validation": {"errors": [{"path": "p1", "message": "referential bad"}]},
        "artifact_consistency": {"errors": [{"message": "prose mismatch"}]},
    }
    fb = _format_semantic_feedback(report)
    assert "REFERENTIAL" in fb
    assert "referential bad" in fb
    assert "CROSS-ARTIFACT CONSISTENCY" in fb
    assert "prose mismatch" in fb


# ---- stage3_is_semantically_complete ----

def _write_plan_and_report(art, rep, plan, valid=True, bound_hash=None):
    from src.stage3_validation import stage3_candidate_hash
    run_context.write_stamped_json(art, plan)
    report = {
        "is_valid": valid,
        "plan_validation": {"is_valid": valid, "errors": []},
        "artifact_consistency": {"is_consistent": True, "errors": []},
        "validated_artifact": {"path": art, "sha256": bound_hash or stage3_candidate_hash(plan)},
    }
    run_context.write_stamped_json(rep, report)


def test_semantically_complete_true_when_valid_and_hash_matches():
    from src.stage3_validation import stage3_candidate_hash
    art, rep = _paths()
    plan = {"schema_version": 1, "plan_title": "P"}
    _write_plan_and_report(art, rep, plan, valid=True)
    assert stage3_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage3_candidate_hash(plan)) is True


def test_semantically_complete_false_on_stale_hash():
    """A passing report whose bound hash differs from the current candidate
    must NOT count as done."""
    from src.stage3_validation import stage3_candidate_hash
    art, rep = _paths()
    plan_a = {"schema_version": 1, "plan_title": "A"}
    _write_plan_and_report(art, rep, plan_a, valid=True,
                           bound_hash=stage3_candidate_hash({"different": "plan"}))
    assert stage3_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage3_candidate_hash(plan_a)) is False


def test_semantically_complete_false_when_report_invalid():
    from src.stage3_validation import stage3_candidate_hash
    art, rep = _paths()
    plan = {"schema_version": 1, "plan_title": "P"}
    _write_plan_and_report(art, rep, plan, valid=False)
    assert stage3_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage3_candidate_hash(plan)) is False


def test_semantically_complete_false_when_no_report():
    from src.stage3_validation import stage3_candidate_hash
    art, rep = _paths()
    run_context.write_stamped_json(art, {"schema_version": 1})
    assert stage3_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage3_candidate_hash({"schema_version": 1})) is False


def test_orchestrator_aborts_on_identity_mutation_mid_repair():
    """End-to-end in the orchestrator: candidate 1 is the correct AML.T0099
    binding but fails deep validation (incomplete KCAG path); candidate 2
    tries to 'fix' it by swapping to CAPEC-628. The orchestrator must abort
    with SemanticIdentityMutation, NOT accept the mutated plan."""
    from src.stage3_identity import SemanticIdentityMutation
    art, rep = _paths()

    plans = iter([
        # Candidate 1: correct technique, but will fail deep validation.
        {"test_concepts": [{"test_id": "RT-003", "categories": [1, 4],
                            "target_node_ids": ["AML.T0099"], "stage2_vector_ids": ["V-03"],
                            "execution_techniques": [{"technique_id": "AML.T0099", "vector_id": "V-03"}]}]},
        # Candidate 2: technique swapped to close the path — the forbidden move.
        {"test_concepts": [{"test_id": "RT-003", "categories": [1, 4],
                            "target_node_ids": ["CAPEC-628"], "stage2_vector_ids": ["V-02"],
                            "execution_techniques": [{"technique_id": "CAPEC-628", "vector_id": "V-02"}]}]},
    ])
    current = {"plan": None}

    def compile_candidate(*, external_feedback):
        current["plan"] = next(plans)
        open(art, "w").write(json.dumps(current["plan"]))

    with pytest.raises(SemanticIdentityMutation, match="AML.T0099"):
        compile_stage3_until_valid(
            compile_candidate=compile_candidate,
            validate_candidate=lambda: _invalid_report([{"message": "KCAG path unresolved"}]),
            write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
            read_candidate=lambda: current["plan"],
            identity_baseline_path="baseline_key",
            read_stamped_json=_mem_read, write_stamped_json=_mem_write,
            artifact_path=art, validation_report_path=rep,
        )
    # The mutated candidate must NOT remain as an authoritative artifact.
    assert not os.path.exists(art)
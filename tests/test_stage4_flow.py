"""
Tests for the Stage 4 semantic-repair orchestrator (src/stage4_flow.py).
In-memory fakes for the injected compile/validate callables.
"""
import json
import os

import pytest

from src import run_context
from src.stage4_flow import (
    compile_stage4_until_valid, stage4_is_semantically_complete,
    _format_semantic_feedback,
)
from src.stage4_validation import stage4_candidate_hash


@pytest.fixture(autouse=True)
def _run(tmp_path):
    run_context.reset_active_run()
    run_context.set_active_run("test-run", "sha256:test", str(tmp_path / "out"))
    yield
    run_context.reset_active_run()


def _paths():
    art = run_context.artifact_path("stage4_execution_plan.json")
    rep = run_context.artifact_path("stage4_execution_plan_validation.json")
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
    calls = {"n": 0}

    def compile_candidate(*, external_feedback):
        calls["n"] += 1
        open(art, "w").write("{}")

    report = compile_stage4_until_valid(
        compile_candidate=compile_candidate, validate_candidate=_valid_report,
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        artifact_path=art, validation_report_path=rep,
    )
    assert report["is_valid"] is True
    assert calls["n"] == 1


def test_candidate_2_receives_candidate_1_errors():
    art, rep = _paths()
    seen = []
    reports = iter([
        _invalid_report([
            {"path": "phases.0.actions.0.action_summary", "code": "X", "message": "action_summary required"},
            {"path": "test_bindings.0.test_id", "code": "Y", "message": "RT-999 not in Stage 3 plan"},
        ]),
        _valid_report(),
    ])

    def compile_candidate(*, external_feedback):
        seen.append(external_feedback)
        open(art, "w").write("{}")

    compile_stage4_until_valid(
        compile_candidate=compile_candidate, validate_candidate=lambda: next(reports),
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        artifact_path=art, validation_report_path=rep,
    )
    assert seen[0] == ""
    assert "action_summary required" in seen[1]
    assert "RT-999 not in Stage 3 plan" in seen[1]


def test_rejected_candidates_archived():
    art, rep = _paths()
    reports = iter([_invalid_report([{"message": "bad"}]), _valid_report()])

    def compile_candidate(*, external_feedback):
        open(art, "w").write('{"x": 1}')

    compile_stage4_until_valid(
        compile_candidate=compile_candidate, validate_candidate=lambda: next(reports),
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        artifact_path=art, validation_report_path=rep,
    )
    assert os.path.exists(art + ".semantic_rejected_1")
    assert os.path.exists(rep + ".semantic_rejected_1")


def test_fails_closed_and_removes_invalid_candidate():
    art, rep = _paths()

    def compile_candidate(*, external_feedback):
        open(art, "w").write("{}")

    with pytest.raises(RuntimeError, match="failed after 3 attempt"):
        compile_stage4_until_valid(
            compile_candidate=compile_candidate,
            validate_candidate=lambda: _invalid_report([{"message": "always bad"}]),
            write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
            artifact_path=art, validation_report_path=rep, max_semantic_attempts=3,
        )
    assert not os.path.exists(art)
    assert os.path.exists(art + ".semantic_rejected_3")


def test_feedback_accumulates():
    art, rep = _paths()
    seen = []
    reports = iter([
        _invalid_report([{"message": "err_A"}]),
        _invalid_report([{"message": "err_B"}]),
        _valid_report(),
    ])

    def compile_candidate(*, external_feedback):
        seen.append(external_feedback)
        open(art, "w").write("{}")

    compile_stage4_until_valid(
        compile_candidate=compile_candidate, validate_candidate=lambda: next(reports),
        write_validation_report=lambda r: open(rep, "w").write(json.dumps(r)),
        artifact_path=art, validation_report_path=rep,
    )
    assert "err_A" in seen[2]
    assert "err_B" in seen[2]


def test_format_feedback_groups_kinds():
    report = {
        "plan_validation": {"errors": [{"path": "p", "message": "binding bad"}]},
        "artifact_consistency": {"errors": [{"message": "prose mismatch"}]},
    }
    fb = _format_semantic_feedback(report)
    assert "REFERENTIAL / BINDING / STRUCTURE" in fb
    assert "binding bad" in fb
    assert "CROSS-ARTIFACT CONSISTENCY" in fb
    assert "prose mismatch" in fb


# ---- stage4_is_semantically_complete ----

def _write(art, rep, plan, valid=True, bound_hash=None):
    run_context.write_stamped_json(art, plan)
    run_context.write_stamped_json(rep, {
        "is_valid": valid,
        "plan_validation": {"is_valid": valid, "errors": []},
        "artifact_consistency": {"is_consistent": True, "errors": []},
        "source_identity": {
            "stage4_execution_plan_sha256": bound_hash or stage4_candidate_hash(plan),
            "stage3_test_plan_sha256": "sha256:whatever",
        },
    })


def test_complete_true_when_valid_and_hash_matches():
    art, rep = _paths()
    plan = {"schema_version": 1, "plan_id": "MP-001"}
    _write(art, rep, plan, valid=True)
    assert stage4_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage4_candidate_hash(plan)) is True


def test_complete_false_on_stale_hash():
    art, rep = _paths()
    plan = {"schema_version": 1, "plan_id": "MP-001"}
    _write(art, rep, plan, valid=True, bound_hash=stage4_candidate_hash({"other": "plan"}))
    assert stage4_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage4_candidate_hash(plan)) is False


def test_complete_false_when_invalid():
    art, rep = _paths()
    plan = {"schema_version": 1, "plan_id": "MP-001"}
    _write(art, rep, plan, valid=False)
    assert stage4_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage4_candidate_hash(plan)) is False


def test_complete_false_when_no_report():
    art, rep = _paths()
    run_context.write_stamped_json(art, {"schema_version": 1})
    assert stage4_is_semantically_complete(
        artifact_path=art, validation_report_path=rep,
        current_candidate_hash=stage4_candidate_hash({"schema_version": 1})) is False
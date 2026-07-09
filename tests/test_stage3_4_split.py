"""
Tests for the Stage 3 / Stage 4 crew split.

Covers:
  - test_build_tasks_does_not_return_stage4
  - test_build_stage4_task_requires_content
  - test_stage4_has_no_live_stage3_context
  - test_stage4_description_contains_stage3_content
  - test_stage3_round_trip_before_stage4
  - test_stage4_not_built_from_another_runs_stage3

These test the actual production functions (build_tasks, build_stage4_task,
run_context.stamp_prose_file/read_stamped_prose) directly -- no CrewAI
kickoff, no LLM. The full crew.py integration (analysis_crew ->
verification boundary -> stage4_crew, including the mocked end-to-end
pass proving stage4_crew is never even constructed when stage3.md is
missing) was additionally verified this session against the real
pipeline; that level of test isn't included here since it needs a
mocked-kickoff harness pattern I don't know this repo's existing
convention for wiring into pytest (fixtures/conftest.py) -- happy to add
it in whatever shape matches the rest of tests/ if useful.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import os
from pathlib import Path

import pytest

from src import run_context
from src.tasks import build_tasks, build_stage4_task


def test_build_tasks_does_not_return_stage4():
    tasks = build_tasks("/tmp/test-output-does-not-need-to-exist")
    assert "t_stage4" not in tasks
    assert set(tasks.keys()) == {
        "t_research", "t_synthesize_stage0", "t_stage1", "t_stage2",
        "t_annexB", "t_annexC", "t_stage3",
    }


_MINIMAL_STAGE3_TEST_PLAN = {
    "schema_version": 1, "plan_title": "Minimal Test Plan",
    "test_concepts": [{
        "test_id": "RT-001", "title": "x", "objective": "x",
        "stage2_vector_ids": ["V-01"], "kcag_path": ["ADV_START", "G1"],
        "path_relationship": "PRIORITY_PATH", "target_node_ids": [], "categories": [1],
        "execution_techniques": [], "defensive_concepts": [],
        "mechanism_summary": "x", "preconditions": ["x"], "expected_effects": ["x"],
        "success_criteria": ["x"], "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
        "telemetry_requirements": ["x"], "assumptions": ["x"], "safety_controls": None,
    }],
    "assessment_safety_review": {"category_2_3_present": False, "covered_test_ids": [],
                                 "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
}


def test_build_stage4_task_requires_content():
    with pytest.raises(ValueError, match="non-empty"):
        build_stage4_task("/tmp/test-output", "", stage3_test_plan=_MINIMAL_STAGE3_TEST_PLAN)
    with pytest.raises(ValueError, match="non-empty"):
        build_stage4_task("/tmp/test-output", "   \n\n  ", stage3_test_plan=_MINIMAL_STAGE3_TEST_PLAN)
    with pytest.raises(ValueError, match="non-empty"):
        build_stage4_task("/tmp/test-output", None, stage3_test_plan=_MINIMAL_STAGE3_TEST_PLAN)


def test_build_stage4_task_requires_test_plan():
    with pytest.raises(ValueError, match="structured Stage 3 test plan"):
        build_stage4_task("/tmp/test-output", "verified stage 3 content", stage3_test_plan=None)
    with pytest.raises(ValueError, match="structured Stage 3 test plan"):
        build_stage4_task("/tmp/test-output", "verified stage 3 content", stage3_test_plan={})


def test_stage4_has_no_live_stage3_context():
    task = build_stage4_task("/tmp/test-output", "verified stage 3 content",
                             stage3_test_plan=_MINIMAL_STAGE3_TEST_PLAN)
    assert not task.context


def test_stage4_description_contains_stage3_content():
    task = build_stage4_task("/tmp/test-output", "TEST-ID: RT-001",
                             stage3_test_plan=_MINIMAL_STAGE3_TEST_PLAN)
    assert "TEST-ID: RT-001" in task.description
    assert "=== VERIFIED STAGE 3 HUMAN-READABLE ARTIFACT ===" in task.description
    assert "=== VERIFIED STRUCTURED STAGE 3 TEST PLAN ===" in task.description
    # The doctrinal Phase 0 instruction must survive the refactor verbatim --
    # this is the actual safety-relevant content, not incidental text.
    assert "CRITICAL INSTRUCTION — PHASE 0 SAFETY GATE" in task.description
    assert "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED" in task.description


def test_stage3_round_trip_before_stage4(tmp_path):
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.reset_active_run()
    run_context.set_active_run("test-run", "sha256:test-corpus", str(out_dir))

    stage3_path = run_context.artifact_path("stage3.md")
    Path(stage3_path).write_text("# Stage 3\n\nVerified content", encoding="utf-8")

    run_context.stamp_prose_file(stage3_path)
    stage3_text = run_context.read_stamped_prose(stage3_path)

    task = build_stage4_task(str(out_dir), stage3_text, stage3_test_plan=_MINIMAL_STAGE3_TEST_PLAN)
    assert "Verified content" in task.description

    run_context.reset_active_run()


def test_stage4_not_built_from_another_runs_stage3(tmp_path):
    """The mismatched-run case: Stage 3 was written and stamped under run
    A. If somehow read against run B's active context, read_stamped_prose
    must raise BEFORE build_stage4_task is ever reachable -- proving the
    artifact-identity check, not just the emptiness check, is what
    actually gates Stage 4 construction."""
    out_dir_a = tmp_path / "outputs" / "run-a"
    run_context.reset_active_run()
    run_context.set_active_run("run-a", "sha256:corpus-a", str(out_dir_a))
    stage3_path = run_context.artifact_path("stage3.md")
    Path(stage3_path).write_text("# Stage 3 (run A)\n\nRun A content", encoding="utf-8")
    run_context.stamp_prose_file(stage3_path)
    run_context.reset_active_run()

    # Switch to run B, but try to read run A's already-stamped file.
    out_dir_b = tmp_path / "outputs" / "run-b"
    run_context.set_active_run("run-b", "sha256:corpus-b", str(out_dir_b))

    with pytest.raises(ValueError, match="belongs to run"):
        run_context.read_stamped_prose(stage3_path)

    # build_stage4_task must never be reached in this failure path -- there
    # is no code between the raise above and a Task object.
    run_context.reset_active_run()
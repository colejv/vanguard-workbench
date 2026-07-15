"""
Pipeline-level tests for the Stage 0 / Stage 1 / Stage 2 crew split
(src/crew.py): confirms a missing structured artifact from one stage
prevents the next stage's crew from ever being constructed, not just
from completing successfully.

These run the REAL src.crew module as __main__ (via runpy), with only
crewai.Crew.kickoff mocked -- every writer tool call inside the mock is
the real write_stageN_output/write_stage2_vectors/write_stage3_test_plan/
write_stage4_execution_plan function, and every downstream gate
(verify_stage2_vectors, validate_kcag, structured Stage 3/4 validation,
the prose safety gates) is the real deterministic check. This is
integration-level verification of the actual orchestration bug fix, not
a mock of the fix itself.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import hashlib
import json
import os
import runpy
import sys
from pathlib import Path

import pytest
import crewai

from src import run_context

# Captured at module import time, before any test's monkeypatch.chdir() can
# run -- resolves to the real repo root regardless of whose machine this
# runs on. The earlier version of this fixture hardcoded an absolute path
# into a specific development sandbox (an absolute machine-specific path),
# which only ever worked in that one environment. This is the actual fix,
# not a workaround: no path in this file should ever be specific to any
# one machine again.
_REPO_ROOT = Path(__file__).resolve().parent.parent

STAGE0_SIGNATURES = [{"signature_id": "S-T-01", "category": "technical", "description": "x",
                      "confidence": "HIGH", "deceive_candidate": False, "is_gap": False}]
STAGE1_TECHNICAL = [{"component_id": "C-T-01", "layer": "technical", "name": "x",
                     "asset_control_levels": [], "information_flows": "x",
                     "downstream_dependencies": [], "is_gap": False}]
STAGE2_NODES = [{"id": "ADV_START", "node_type": "privilege", "criticality": 1},
                {"id": "G1", "node_type": "goal", "criticality": 10}]
STAGE2_EDGES = [{"source": "ADV_START", "target": "G1", "technique": "T1078", "difficulty": "LOW",
                 "effect": None, "vec": "V-01"}]


def _classify_crew(crew_self):
    names = {t.output_file.split("/")[-1] for t in crew_self.tasks if t.output_file}
    if names == {"stage1.md"}:
        return "stage1"
    if names == {"stage2.md"}:
        return "stage2"
    if names == {"stage4_mission_plan.md"}:
        return "stage4"
    if any("corpus is fixed" in (t.description or "").lower() for t in crew_self.tasks) or names == {"stage0.md"}:
        return "stage0"
    return "analysis"


def _build_mock_kickoff(captured, *, stage1_should_fail=False):
    def mock_kickoff(self, inputs=None):
        kind = _classify_crew(self)

        if kind == "stage0":
            captured.setdefault("crews_run", []).append("stage0")
            open(run_context.artifact_path("stage0.md"), "w").write("# Stage 0\n")
            from src.tools import write_stage0_output
            assert write_stage0_output.func(signatures=STAGE0_SIGNATURES).startswith("WRITTEN")
            return "mock stage0_crew"

        if kind == "stage1":
            captured.setdefault("crews_run", []).append("stage1")
            captured["stage1_crew_task_count"] = len(self.tasks)
            open(run_context.artifact_path("stage1.md"), "w").write("# Stage 1\n")
            # NOTE: the structured JSON write no longer happens inside the
            # crew — it's done by compile_stage1_structured_output() outside
            # the agent executor (patched separately in _run_pipeline). This
            # mock only produces the prose artifact, matching the real crew.
            return "mock stage1_crew"

        if kind == "stage2":
            captured.setdefault("crews_run", []).append("stage2")
            open(run_context.artifact_path("stage2.md"), "w").write("# Stage 2\n")
            from src.tools import write_stage2_vectors
            assert write_stage2_vectors.func(nodes=STAGE2_NODES, edges=STAGE2_EDGES).startswith("WRITTEN")
            return "mock stage2_crew"

        if kind == "stage4":
            captured.setdefault("crews_run", []).append("stage4")
            open(run_context.artifact_path("stage4_mission_plan.md"), "w").write(
                "# STAGE 4\n\n## PHASE-01 — Prep\n\n### ACT-001 — RT-001\nx\n\n"
                "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n")
            from src.tools import write_stage4_execution_plan
            plan = {
                "schema_version": 1, "plan_id": "MP-001", "plan_title": "x",
                "artifact_role": "HUMAN_REVIEWED_MISSION_PLAN_DRAFT", "execution_authorization": "NOT_GRANTED",
                "source_stage3_test_ids": ["RT-001"],
                "phase0_safety_gate": {"required": False, "covered_test_ids": [], "execution_release": "NOT_APPLICABLE",
                                       "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
                "test_bindings": [{"test_id": "RT-001", "categories": [1], "stage2_vector_ids": ["V-01"],
                                   "kcag_path": ["ADV_START", "G1"], "technique_ids": ["T1078"], "assigned_action_ids": ["ACT-001"]}],
                "phases": [{"phase_id": "PHASE-01", "sequence": 1, "name": "Prep", "purpose": "x",
                           "entry_criteria": ["x"], "exit_criteria": ["x"],
                           "actions": [{"action_id": "ACT-001", "test_id": "RT-001", "action_summary": "x",
                                       "responsible_roles": ["x"], "preconditions": ["x"],
                                       "success_criteria": ["Access confirmed"], "abort_criteria": ["Instability observed"],
                                       "rollback_or_recovery_steps": ["x"], "telemetry_requirements": ["x"],
                                       "alert_triggers": ["x"], "opsec_measures": ["x"]}]}],
                "global_opsec_measures": [], "assumptions": [], "limitations": [],
            }
            result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(plan))
            assert result.startswith("WRITTEN")
            return "mock stage4_crew"

        captured.setdefault("crews_run", []).append("analysis")
        open(run_context.artifact_path("model_assumptions.md"), "w").write("# review\nACCEPT\n")
        run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
            "objective_results": {"G1": {"top_path_score": 0.4}},
            "priority_path": {"path": ["ADV_START", "G1"]},
        })
        open(run_context.artifact_path("annexB_kcag.md"), "w").write("# annexB\n")
        open(run_context.artifact_path("annexC_bbn.md"), "w").write("# annexC\n")
        # Annex C completed with a PASS status so the Annex C -> Stage 3
        # transition gate allows Stage 3 (the happy path). Tests that exercise
        # the blocked/waiver paths do so directly against evaluate_stage3_transition.
        run_context.write_stamped_json(run_context.artifact_path("bbn_report.json"), {
            "status": "PASS", "threat_score": 0.5, "phase_estimate": "SHAPE",
        })
        open(run_context.artifact_path("stage3.md"), "w").write(
            "# STAGE 3\n\n### RT-001 — Test\n**Category:** 1\nx\n\n"
            "## PRE-STAGE-4 SAFETY REVIEW\nNO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n")
        # The analysis crew now produces PROSE ONLY. The structured Stage 3
        # test plan is compiled outside the crew by
        # compile_stage3_structured_output(), patched in _run_pipeline.
        return "mock analysis_crew"

    return mock_kickoff


@pytest.fixture
def pipeline_workspace(tmp_path, monkeypatch):
    import shutil
    monkeypatch.chdir(tmp_path)
    os.makedirs("sources", exist_ok=True)
    os.makedirs("collection", exist_ok=True)
    os.makedirs("corpus-index", exist_ok=True)
    os.makedirs("config", exist_ok=True)

    # Constructed inline rather than copied from anywhere -- the mocked
    # pipeline's fixtures only ever reference technique ID T1078, so a
    # full copy of the real (much larger) technique_index.json would be
    # both unnecessary and another way for this test to depend on
    # something outside itself. Read via a relative file path
    # (verify_stage2_vectors), so this is resolved against the real,
    # current OS-level cwd (tmp_path, after chdir above) -- unlike a
    # Python import, a plain file open() genuinely does follow chdir.
    json.dump(
        {"T1078": {"id": "T1078", "name": "Valid Accounts", "description": "existing credentials"}},
        open("corpus-index/technique_index.json", "w"),
    )

    # config/llm.py is NOT recreated here. It's resolved via `from
    # config.llm import light_llm, reason_llm` inside src/agents.py --
    # a Python import, which depends on sys.path, not the OS-level cwd.
    # pytest already puts the real repo root (where config/llm.py
    # actually, permanently lives) on sys.path at collection time;
    # writing a second copy into tmp_path after chdir would only be
    # reachable by relative *file* lookups, never by `import config.llm`
    # itself, so it was dead code that happened to look like it worked.

    # bbn_priors.json genuinely needs its real content -- Annex C runs an
    # actual BBN computation against it during the mocked pipeline run.
    # Read via a relative file path (bbn_threat_score's own default),
    # so -- like technique_index.json above -- this one correctly
    # depends on cwd and must be physically present under tmp_path.
    # Copied from the real repo, located relative to this test file's
    # own path rather than any hardcoded machine-specific one.
    shutil.copy(_REPO_ROOT / "config" / "bbn_priors.json", "config/bbn_priors.json")

    content = "# PAI Finding\nLTC Brinkman serves as 25ID S6 lead.\n"
    open("sources/pai_signal.md", "w").write(content)
    manifest = {
        "operation": "pytest-split-test", "sut": "n/a", "count": 1,
        "files": [{"file": "pai_signal.md", "sha256": hashlib.sha256(content.encode()).hexdigest(),
                  "bytes": len(content.encode())}],
    }
    open("sources/corpus_manifest.md", "w").write("# Corpus Manifest (FROZEN)\n\n```json\n" + json.dumps(manifest, indent=2) + "\n```\n")
    open("collection/brief.md", "w").write("# Test brief\n")
    return tmp_path


def _run_pipeline(run_id_hint, *, stage1_should_fail=False, stage3_should_fail=False,
                  stage3_semantic_recovery=False):
    """run_id_hint is NOT the actual run_id the pipeline will use --
    new_run_id() always generates its own vaf_<timestamp> ID, ignoring
    any pre-created directory name. Returns the REAL run_id discovered
    from outputs/ after the run, so callers can find the real
    assessment_state.json.

    Both the Stage 1 and Stage 3 structured writes now happen via
    compile_*_structured_output() outside the CrewAI agent executor,
    making real HTTP calls to Ollama. We patch both helpers here: on
    success each writes a minimal valid artifact through the real writer
    tool; on *_should_fail, each raises RuntimeError exactly as the real
    helper does after exhausting retries, so the hard gates are
    exercised."""
    import src.stage1_writer as stage1_writer_module
    import src.stage3_writer as stage3_writer_module
    import src.stage4_writer as stage4_writer_module
    from src.tools import write_stage1_output, write_stage3_test_plan, write_stage4_execution_plan

    def _fake_compile_stage1(*, stage1_prose, llm, writer_tool, artifact_path, **kwargs):
        if stage1_should_fail:
            raise RuntimeError(
                "Stage 1 structured write failed after 3 attempts. "
                "See terminal output above for per-attempt details."
            )
        result = write_stage1_output.func(
            technical_nodes=STAGE1_TECHNICAL, procedural_nodes=[],
            cognitive_nodes=[], trust_boundaries=[],
        )
        assert result.startswith("WRITTEN"), result

    _compile_calls = {"stage3": 0}

    def _fake_compile_stage3(*, stage3_prose, referential_context, llm,
                             writer_tool, artifact_path, **kwargs):
        if stage3_should_fail:
            raise RuntimeError(
                "Stage 3 structured write failed after 3 attempts. "
                "See terminal output above for per-attempt details."
            )
        _compile_calls["stage3"] += 1
        # In semantic-recovery mode, the FIRST candidate has a bad kcag_path
        # (deep validation will reject it); the SECOND is valid. This
        # exercises the stage3_flow semantic-repair loop end-to-end in crew.py.
        bad_first = stage3_semantic_recovery and _compile_calls["stage3"] == 1
        plan3 = {
            "schema_version": 1, "plan_title": "x",
            "test_concepts": [{
                "test_id": "RT-001", "title": "x", "objective": "x",
                "stage2_vector_ids": ["V-01"],
                "kcag_path": (["ADV_START", "NOT_A_REAL_NODE"] if bad_first
                              else ["ADV_START", "G1"]),
                "path_relationship": "PRIORITY_PATH", "target_node_ids": [],
                "categories": [1],
                "execution_techniques": [{"technique_id": "T1078", "vector_id": "V-01", "rationale": "x"}],
                "defensive_concepts": ["x"], "mechanism_summary": "x",
                "preconditions": ["x"], "expected_effects": ["x"],
                "success_criteria": ["Access confirmed"], "abort_criteria": ["Instability observed"],
                "rollback_or_recovery_steps": ["x"], "telemetry_requirements": ["x"],
                "assumptions": ["x"], "safety_controls": None,
            }],
            "assessment_safety_review": {"category_2_3_present": False, "covered_test_ids": [],
                                        "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
        }
        result = write_stage3_test_plan.func(test_plan_json=json.dumps(plan3))
        assert result.startswith("WRITTEN"), result

    def _fake_compile_stage4(*, stage4_prose, referential_context, stage3_test_plan,
                             llm, writer_tool, artifact_path, **kwargs):
        # Mirrors the real compiler contract: writes a valid Stage 4 plan via
        # the real writer tool, deriving the Phase 0 gate from the Stage 3
        # plan exactly as the production overlay does.
        from src.stage4_writer import build_stage4_phase0_gate
        plan4 = {
            "schema_version": 1, "plan_id": "MP-001", "plan_title": "Test Mission Plan",
            "artifact_role": "HUMAN_REVIEWED_MISSION_PLAN_DRAFT",
            "execution_authorization": "NOT_GRANTED",
            "source_stage3_test_ids": ["RT-001"],
            "phase0_safety_gate": build_stage4_phase0_gate(stage3_test_plan),
            "test_bindings": [{"test_id": "RT-001", "categories": [1], "stage2_vector_ids": ["V-01"],
                               "kcag_path": ["ADV_START", "G1"], "technique_ids": ["T1078"],
                               "assigned_action_ids": ["ACT-001"]}],
            "phases": [{"phase_id": "PHASE-01", "sequence": 1, "name": "Recon", "purpose": "x",
                        "entry_criteria": ["start"], "exit_criteria": ["done"],
                        "actions": [{"action_id": "ACT-001", "test_id": "RT-001", "action_summary": "x",
                                     "responsible_roles": ["operator"], "preconditions": ["x"],
                                     "success_criteria": ["Access confirmed"], "abort_criteria": ["Instability observed"],
                                     "rollback_or_recovery_steps": ["x"], "telemetry_requirements": ["x"],
                                     "alert_triggers": ["anomaly"], "opsec_measures": ["encrypted comms"]}]}],
            "global_opsec_measures": ["minimize footprint"], "assumptions": ["lab environment"],
            "limitations": ["scope limited to test range"],
        }
        result = write_stage4_execution_plan.func(execution_plan_json=json.dumps(plan4))
        assert result.startswith("WRITTEN"), result

    captured = {}
    crewai.Crew.kickoff = _build_mock_kickoff(captured, stage1_should_fail=stage1_should_fail)
    os.makedirs("outputs", exist_ok=True)
    before = set(os.listdir("outputs"))
    sys.argv = ["src.crew"]

    import unittest.mock as _mock
    # crew.py imports compile_stage1_structured_output inside the function
    # body (patch the source module) and compile_stage3_structured_output
    # at module top-level (patch the source module too — the name is looked
    # up on src.stage3_writer at call time when we patch the attribute
    # there before crew import resolves it, and crew re-imports src.crew
    # fresh via runpy each run).
    with _mock.patch.object(stage1_writer_module, "compile_stage1_structured_output", _fake_compile_stage1), \
         _mock.patch.object(stage3_writer_module, "compile_stage3_structured_output", _fake_compile_stage3), \
         _mock.patch.object(stage4_writer_module, "compile_stage4_structured_output", _fake_compile_stage4):
        try:
            runpy.run_module("src.crew", run_name="__main__")
            result = "SUCCESS"
        except RuntimeError as e:
            result = f"RuntimeError: {e}"
    after = set(os.listdir("outputs"))
    new_dirs = after - before
    real_run_id = new_dirs.pop() if new_dirs else run_id_hint
    return result, captured, real_run_id


def test_full_pipeline_succeeds_with_split_stage012_crews(pipeline_workspace):
    result, captured, _ = _run_pipeline("happy_run")
    assert result == "SUCCESS", result
    assert captured["crews_run"] == ["stage0", "stage1", "stage2", "analysis", "stage4"]


def test_stage1_crew_runs_prose_only_with_direct_write_outside_executor(pipeline_workspace):
    """Stage 1's prompt used to combine three prose layers plus a trailing
    four-argument tool call in one task -- observed directly to let the
    model treat a complete-looking prose answer as finishing the whole
    task, with the write_stage1_output call never even attempted. The fix
    evolved past a two-task split: the structured write now happens OUTSIDE
    CrewAI's agent executor entirely, via compile_stage1_structured_output()
    (Ollama structured output + deterministic writer), because the CrewAI
    agent executor itself was returning empty native-tool responses for
    this model. This asserts stage1_crew is now a prose-only crew (1 task),
    with the write handled by the patched helper in _run_pipeline."""
    result, captured, _ = _run_pipeline("split_check_run")
    assert result == "SUCCESS", result
    assert captured.get("stage1_crew_task_count") == 1, (
        f"expected stage1_crew to be a prose-only crew (1 task), with the "
        f"structured write handled outside the executor, got "
        f"{captured.get('stage1_crew_task_count')}"
    )


def test_missing_stage1_artifact_prevents_stage2(pipeline_workspace):
    """The exact bug: Stage 1's crew ran (agent attempted the writer call),
    but never actually produced stage1_output.json. Stage 2's crew must
    never be constructed on top of that -- not run against stale/absent
    prose, not silently proceed."""
    result, captured, _ = _run_pipeline("stage1_fail_run", stage1_should_fail=True)
    assert result.startswith("RuntimeError")
    # The failure now surfaces from compile_stage1_structured_output()
    # exhausting its retries, rather than the old in-crew writer-missing
    # message. Either way, the hard gate must prevent Stage 2.
    assert "Stage 1 structured write failed" in result or "stage1_output.json" in result
    assert captured["crews_run"] == ["stage0", "stage1"], (
        f"Stage 2 (or later) crew was constructed despite Stage 1's artifact never "
        f"being written: {captured['crews_run']}"
    )


def test_stage1_failure_marks_correct_state(pipeline_workspace):
    result, captured, real_run_id = _run_pipeline("stage1_fail_state_run", stage1_should_fail=True)
    assert result.startswith("RuntimeError")
    state = json.load(open(os.path.join("outputs", real_run_id, "assessment_state.json")))
    assert state["current_stage"] == "stage1"
    assert state["stages"]["stage0"]["status"] == "PENDING"
    assert state["stages"]["stage1"]["status"] == "FAIL"
    assert state["stages"]["stage2"]["status"] == "NOT_STARTED"


def test_missing_stage0_artifact_prevents_stage1(pipeline_workspace, monkeypatch):
    """Same property, one stage earlier: if Stage 0's crew runs but never
    produces stage0_output.json, Stage 1's crew must never be
    constructed."""
    captured = {}

    def mock_kickoff_stage0_fails(self, inputs=None):
        kind = _classify_crew(self)
        captured.setdefault("crews_run", []).append(kind)
        if kind == "stage0":
            open(run_context.artifact_path("stage0.md"), "w").write("# Stage 0\n")
            # Deliberately never call write_stage0_output.
            return "mock stage0_crew (writer never succeeded)"
        return "mock (should not reach this crew)"

    crewai.Crew.kickoff = mock_kickoff_stage0_fails
    os.makedirs("outputs/stage0_fail_run", exist_ok=True)
    sys.argv = ["src.crew"]
    try:
        runpy.run_module("src.crew", run_name="__main__")
        result = "SUCCESS"
    except RuntimeError as e:
        result = f"RuntimeError: {e}"

    assert result.startswith("RuntimeError")
    assert "stage0_output.json" in result
    assert captured["crews_run"] == ["stage0"], (
        f"Stage 1 (or later) crew was constructed despite Stage 0's artifact never "
        f"being written: {captured['crews_run']}"
    )


def test_stage3_compile_failure_fails_closed_and_blocks_stage4(pipeline_workspace):
    """When compile_stage3_structured_output exhausts its retries, the
    pipeline must fail closed at Stage 3 and never construct Stage 4."""
    result, captured, _ = _run_pipeline("stage3_fail_run", stage3_should_fail=True)
    assert result.startswith("RuntimeError")
    assert "Stage 3 structured write failed" in result
    assert "stage4" not in captured["crews_run"], (
        f"Stage 4 crew was constructed despite Stage 3 compile failure: "
        f"{captured['crews_run']}"
    )


def test_stage3_compile_failure_marks_correct_state(pipeline_workspace):
    result, captured, real_run_id = _run_pipeline("stage3_fail_state_run", stage3_should_fail=True)
    assert result.startswith("RuntimeError")
    state = json.load(open(os.path.join("outputs", real_run_id, "assessment_state.json")))
    assert state["current_stage"] == "stage3"
    assert state["stages"]["stage3"]["status"] == "FAIL"


def test_stage3_semantic_recovery_recompiles_after_deep_validation_failure(pipeline_workspace):
    """The stage3_flow orchestrator, wired into crew.py: when the FIRST
    compiled candidate fails deep referential validation (a kcag_path node
    that isn't in the real graph), the pipeline must archive it, recompile,
    and succeed on the valid second candidate — reaching Stage 4."""
    result, captured, real_run_id = _run_pipeline(
        "stage3_recover_run", stage3_semantic_recovery=True)
    assert result == "SUCCESS", result
    assert "stage4" in captured["crews_run"], captured["crews_run"]
    # The first (invalid) candidate was archived by the semantic loop.
    out = os.path.join("outputs", real_run_id)
    archived = [f for f in os.listdir(out) if f.startswith("stage3_test_plan.json.semantic_rejected_")]
    assert archived, f"expected an archived rejected candidate in {os.listdir(out)}"
    # The authoritative candidate that remains is the valid one.
    final_plan = json.load(open(os.path.join(out, "stage3_test_plan.json")))
    data = final_plan.get("data", final_plan)
    assert data["test_concepts"][0]["kcag_path"] == ["ADV_START", "G1"]
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
# into a specific development sandbox (/home/claude/split_test_final/...),
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
            open(run_context.artifact_path("stage1.md"), "w").write("# Stage 1\n")
            if stage1_should_fail:
                return "mock stage1_crew (writer never succeeded, no artifact produced)"
            from src.tools import write_stage1_output
            result = write_stage1_output.func(
                technical_nodes=STAGE1_TECHNICAL, procedural_nodes=[], cognitive_nodes=[], trust_boundaries=[],
            )
            assert result.startswith("WRITTEN")
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
        open(run_context.artifact_path("stage3.md"), "w").write(
            "# STAGE 3\n\n### RT-001 — Test\n**Category:** 1\nx\n\n"
            "## PRE-STAGE-4 SAFETY REVIEW\nNO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.\n")
        from src.tools import write_stage3_test_plan
        plan3 = {
            "schema_version": 1, "plan_title": "x",
            "test_concepts": [{
                "test_id": "RT-001", "title": "x", "objective": "x", "stage2_vector_ids": ["V-01"],
                "kcag_path": ["ADV_START", "G1"], "path_relationship": "PRIORITY_PATH", "target_node_ids": [],
                "categories": [1], "execution_techniques": [{"technique_id": "T1078", "vector_id": "V-01", "rationale": "x"}],
                "defensive_concepts": ["x"], "mechanism_summary": "x", "preconditions": ["x"], "expected_effects": ["x"],
                "success_criteria": ["Access confirmed"], "abort_criteria": ["Instability observed"],
                "rollback_or_recovery_steps": ["x"], "telemetry_requirements": ["x"], "assumptions": ["x"], "safety_controls": None,
            }],
            "assessment_safety_review": {"category_2_3_present": False, "covered_test_ids": [],
                                        "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
        }
        result = write_stage3_test_plan.func(test_plan_json=json.dumps(plan3))
        assert result.startswith("WRITTEN")
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


def _run_pipeline(run_id_hint, *, stage1_should_fail=False):
    """run_id_hint is NOT the actual run_id the pipeline will use --
    new_run_id() always generates its own vaf_<timestamp> ID, ignoring
    any pre-created directory name. Returns the REAL run_id discovered
    from outputs/ after the run, so callers can find the real
    assessment_state.json."""
    captured = {}
    crewai.Crew.kickoff = _build_mock_kickoff(captured, stage1_should_fail=stage1_should_fail)
    os.makedirs("outputs", exist_ok=True)
    before = set(os.listdir("outputs"))
    sys.argv = ["src.crew"]
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


def test_missing_stage1_artifact_prevents_stage2(pipeline_workspace):
    """The exact bug: Stage 1's crew ran (agent attempted the writer call),
    but never actually produced stage1_output.json. Stage 2's crew must
    never be constructed on top of that -- not run against stale/absent
    prose, not silently proceed."""
    result, captured, _ = _run_pipeline("stage1_fail_run", stage1_should_fail=True)
    assert result.startswith("RuntimeError")
    assert "stage1_output.json" in result
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
"""
Tests for the dashboard's migration to the run-scoped structured Purple
Team artifacts: src/ui/dashboard.py, src/ui/components/threat_graph.py,
coverage_map.py, and sigma_viewer.py.

Uses Streamlit's official streamlit.testing.v1.AppTest framework to run
the real app script in a simulated session (no browser required) and
inspect the resulting widget tree -- this is genuine execution of the
real Streamlit code, not a mock of it. A handful of tests also call the
extracted pure functions (_color_for_status, _available_runs) directly.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import json
import os
import shutil

import pytest
from streamlit.testing.v1 import AppTest

from src import run_context
from src.state import init_assessment_state, save_assessment_state, set_stage_status, run_output_dir
from src.schemas import StageStatus
from src.purple.purple_compiler import load_structured_stage4_run, compile_structured_plan, write_purple_artifacts
from src.purple.sigma_generator import generate_rules_for_run
from src.ui.components.coverage_map import _color_for_status
from src.ui.dashboard import _available_runs

DASHBOARD_PATH = os.path.abspath("src/ui/dashboard.py")

VALID_STAGE4_PLAN = {
    "schema_version": 1, "plan_id": "MP-001", "plan_title": "Dashboard Test Plan",
    "artifact_role": "HUMAN_REVIEWED_MISSION_PLAN_DRAFT", "execution_authorization": "NOT_GRANTED",
    "source_stage3_test_ids": ["RT-001", "RT-002"],
    "phase0_safety_gate": {"required": False, "covered_test_ids": [], "execution_release": "NOT_APPLICABLE",
                           "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
    "test_bindings": [
        {"test_id": "RT-001", "categories": [1], "stage2_vector_ids": ["V-01"], "kcag_path": ["ADV_START", "G1"],
         "technique_ids": ["T1078"], "assigned_action_ids": ["ACT-001"]},
        {"test_id": "RT-002", "categories": [1], "stage2_vector_ids": ["V-02"], "kcag_path": ["ADV_START", "G2"],
         "technique_ids": ["T9999", "CAPEC-628"], "assigned_action_ids": ["ACT-002"]},
    ],
    "phases": [{"phase_id": "PHASE-01", "sequence": 1, "name": "Preparation", "purpose": "Establish access",
               "entry_criteria": ["x"], "exit_criteria": ["x"],
               "actions": [
                   {"action_id": "ACT-001", "test_id": "RT-001", "action_summary": "Use stolen credentials",
                    "responsible_roles": ["Operator"], "preconditions": ["x"], "success_criteria": ["x"],
                    "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
                    "telemetry_requirements": ["Auth logs"], "alert_triggers": ["Spike"], "opsec_measures": ["x"]},
                   {"action_id": "ACT-002", "test_id": "RT-002", "action_summary": "Exploit unknown technique",
                    "responsible_roles": ["Operator"], "preconditions": ["x"], "success_criteria": ["x"],
                    "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
                    "telemetry_requirements": ["Net logs"], "alert_triggers": ["Anomaly"], "opsec_measures": ["x"]},
               ]}],
    "global_opsec_measures": [], "assumptions": [], "limitations": [],
}

FAKE_ART_INDEX = {"T1078": {"technique_name": "Valid Accounts", "test_count": 3, "test_names": ["A", "B", "C"]}}


def _fake_rule_generator(**kwargs):
    return "title: Test Rule\nstatus: experimental\n"


@pytest.fixture(autouse=True)
def _isolated_active_run():
    run_context.reset_active_run()
    yield
    run_context.reset_active_run()


@pytest.fixture
def full_run(tmp_path, monkeypatch):
    """A complete run with a real, compiled Purple scaffold/graph and
    generated Sigma rules, built through the actual compiler and
    generator (not hand-crafted JSON) -- and with the process cwd
    pointed at tmp_path, since dashboard.py resolves 'outputs' relative
    to cwd, same as the rest of the pipeline's CLI entry points."""
    monkeypatch.chdir(tmp_path)
    run_context.set_active_run("vaf-dashboard-test", "sha256:dash", str(tmp_path / "outputs" / "vaf-dashboard-test"))
    state = init_assessment_state("vaf-dashboard-test", "sha256:dash")
    set_stage_status(state, "stage4", StageStatus.PASS)
    save_assessment_state(state, "vaf-dashboard-test")
    run_context.write_stamped_json(run_context.artifact_path("stage4_execution_plan.json"), VALID_STAGE4_PLAN)
    run_context.write_stamped_json(run_context.artifact_path("stage4_execution_plan_validation.json"), {"is_valid": True})
    run_context.reset_active_run()

    ctx = load_structured_stage4_run("vaf-dashboard-test")
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    generate_rules_for_run("vaf-dashboard-test", rule_generator=_fake_rule_generator)
    run_context.reset_active_run()
    return "vaf-dashboard-test"


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------

def test_color_status_maps_vetted_reference_available_to_green():
    assert _color_for_status("VETTED_REFERENCE_AVAILABLE") == "color: green"


def test_color_status_maps_coverage_gap_to_red():
    assert _color_for_status("COVERAGE_GAP") == "color: red"


def test_color_status_old_vetted_string_no_longer_maps_to_green():
    """The legacy status string was exactly 'VETTED'. Confirms the
    rename to VETTED_REFERENCE_AVAILABLE didn't leave a stale mapping
    that would silently color an unrecognized status green."""
    assert _color_for_status("VETTED") == "color: red"


def test_available_runs_lists_only_directories_with_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("outputs/vaf-real-run")
    open("outputs/vaf-real-run/assessment_state.json", "w").write("{}")
    os.makedirs("outputs/not-a-real-run")  # no assessment_state.json
    runs = _available_runs()
    assert runs == ["vaf-real-run"]


def test_available_runs_empty_when_no_outputs_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _available_runs() == []


# ---------------------------------------------------------------------------
# Dashboard app-level tests (AppTest)
# ---------------------------------------------------------------------------

def test_dashboard_renders_without_exception_when_no_runs_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("outputs", exist_ok=True)
    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    assert not at.exception
    assert any("No assessment runs found" in w.value for w in at.warning)


def test_dashboard_renders_without_exception_with_real_run(full_run):
    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    assert not at.exception
    assert at.sidebar.selectbox[0].value == full_run


def test_dashboard_shows_clear_error_when_purple_not_yet_compiled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_context.set_active_run("vaf-no-purple", "sha256:x", str(tmp_path / "outputs" / "vaf-no-purple"))
    state = init_assessment_state("vaf-no-purple", "sha256:x")
    set_stage_status(state, "stage4", StageStatus.PASS)
    save_assessment_state(state, "vaf-no-purple")
    run_context.reset_active_run()

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    assert not at.exception
    error_texts = [e.value for e in at.error]
    assert any("purple_scaffold.json not found" in e for e in error_texts)
    assert any("purple_graph.json not found" in e for e in error_texts)


def test_coverage_map_shows_all_actions_by_default(full_run):
    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    df = at.dataframe[0].value
    assert len(df) == 3  # ACT-001 has 1 technique ref, ACT-002 has 2
    assert set(df["Action"]) == {"ACT-001", "ACT-002"}


def test_coverage_map_filters_to_selected_action(full_run):
    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    at.session_state["selected_action_id"] = "ACT-001"
    at.run(timeout=30)
    df = at.dataframe[0].value
    assert len(df) == 1
    assert df.iloc[0]["Action"] == "ACT-001"
    assert df.iloc[0]["Status"] == "VETTED_REFERENCE_AVAILABLE"


def test_coverage_map_reflects_real_coverage_gap(full_run):
    """ACT-002's technique_ids are ['T9999', 'CAPEC-628'] -- neither has
    a real Atomic Red Team entry in FAKE_ART_INDEX, so both must show as
    COVERAGE_GAP, proving the real crosswalk_techniques() output flows
    through to the rendered table correctly."""
    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    at.session_state["selected_action_id"] = "ACT-002"
    at.run(timeout=30)
    df = at.dataframe[0].value
    assert len(df) == 2
    assert set(df["Status"]) == {"COVERAGE_GAP"}


def test_sigma_viewer_global_selector_lists_real_generated_files(full_run):
    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    sigma_selectors = [sb for sb in at.selectbox if "Sigma Rule" in sb.label]
    assert len(sigma_selectors) == 1
    assert set(sigma_selectors[0].options) == {"ACT-001_RT-001.yml", "ACT-002_RT-002.yml"}


def test_sigma_viewer_filters_by_action_id_via_filename_match(full_run):
    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    at.session_state["selected_action_id"] = "ACT-001"
    at.run(timeout=30)
    captions = [c.value for c in at.caption]
    assert any("ACT-001" in c for c in captions)
    # Exactly one match -- no selectbox needed, the rule renders directly
    code_blocks = at.code
    assert len(code_blocks) >= 1


def test_threat_graph_node_ids_are_action_ids_not_integers(full_run):
    """Confirms the real purple_graph.json (from the actual compiler,
    not hand-crafted) produces action-ID node IDs -- the specific
    property that made the old dashboard.py's int(clicked_id) cast
    incompatible with the new graph format."""
    run_context.set_active_run(full_run, "sha256:dash", run_output_dir(full_run))
    graph = run_context.read_stamped_json(run_context.artifact_path("purple_graph.json"))
    run_context.reset_active_run()
    for node in graph["nodes"]:
        assert node["id"].startswith("ACT-")
        with pytest.raises(ValueError):
            int(node["id"])


def test_dashboard_does_not_int_cast_clicked_node_id():
    """Structural confirmation: dashboard.py's click handler must not
    call int() on the value returned by render_threat_graph() -- that
    cast is exactly what would break against ACT-NNN node IDs."""
    source = open(DASHBOARD_PATH).read()
    assert "int(clicked_id)" not in source


def test_legacy_scaffold_missing_atomic_test_references_key_does_not_crash(tmp_path, monkeypatch):
    """A scaffold record with no atomic_test_references at all (e.g. a
    legacy-provenance record before crosswalk_techniques ever ran) must
    not crash the coverage map -- it should just contribute no rows for
    that action."""
    monkeypatch.chdir(tmp_path)
    run_context.set_active_run("vaf-bare", "sha256:x", str(tmp_path / "outputs" / "vaf-bare"))
    state = init_assessment_state("vaf-bare", "sha256:x")
    set_stage_status(state, "stage4", StageStatus.PASS)
    save_assessment_state(state, "vaf-bare")
    run_context.write_stamped_json(run_context.artifact_path("purple_scaffold.json"), {
        "actions": [{"action_id": "ACT-001", "phase_name": "P1"}],  # no atomic_test_references key
    })
    run_context.write_stamped_json(run_context.artifact_path("purple_graph.json"), {"nodes": [], "edges": []})
    run_context.reset_active_run()

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run(timeout=30)
    assert not at.exception
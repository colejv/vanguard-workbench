"""
Tests for the Purple Team migration to the structured Stage 4 artifact
(Commit B): src/purple/purple_compiler.py and src/purple/sigma_generator.py.

No test in this file performs live network access -- load_art_index() is
always given an injected dict, and generate_sigma_rule() is always
replaced with a fixed-output stub. This mirrors the same discipline
already established for load_art_index's network fetch and the LLM call
in generate_sigma_rule -- both are designed to be pure functions of their
inputs once the network/LLM boundary is injected out.

This file is integrated into the project's tests/ directory and uses its
real fixtures and modules directly.
"""
import copy
import json
import os
import warnings

import pytest

from src import run_context
from src.schemas import StageStatus
from src.state import (init_assessment_state, save_assessment_state, set_stage_status, run_output_dir,
                       canonical_json_sha256, load_assessment_state)
from src.purple.purple_compiler import (
    load_structured_stage4_run,
    compile_structured_plan,
    crosswalk_techniques,
    build_coverage_summary,
    build_purple_graph,
    parse_legacy_mdmp_plan,
    write_purple_artifacts,
    PurpleActionRecord,
    build_arg_parser as build_compiler_arg_parser,
    main as compiler_main,
)
from src.purple.sigma_generator import (
    generate_rules_for_run,
    build_arg_parser as build_sigma_arg_parser,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_STAGE4_PLAN = {
    "schema_version": 1, "plan_id": "MP-001", "plan_title": "NGC2 Mission Plan",
    "artifact_role": "HUMAN_REVIEWED_MISSION_PLAN_DRAFT", "execution_authorization": "NOT_GRANTED",
    "source_stage3_test_ids": ["RT-001"],
    "phase0_safety_gate": {"required": False, "covered_test_ids": [], "execution_release": "NOT_APPLICABLE",
                           "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."},
    "test_bindings": [{"test_id": "RT-001", "categories": [1], "stage2_vector_ids": ["V-01", "V-02"],
                       "kcag_path": ["ADV_START", "N1", "G1"], "technique_ids": ["T1078", "CAPEC-628"],
                       "assigned_action_ids": ["ACT-001"]}],
    "phases": [{"phase_id": "PHASE-01", "sequence": 1, "name": "Preparation", "purpose": "Establish access",
               "entry_criteria": ["x"], "exit_criteria": ["x"],
               "actions": [{"action_id": "ACT-001", "test_id": "RT-001", "action_summary": "Use stolen credentials",
                           "responsible_roles": ["Red Team Operator"], "preconditions": ["x"],
                           "success_criteria": ["x"], "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
                           "telemetry_requirements": ["Auth log monitoring"], "alert_triggers": ["Failed auth spike"],
                           "opsec_measures": ["Use isolated test account"]}]}],
    "global_opsec_measures": [], "assumptions": [], "limitations": [],
}

FAKE_ART_INDEX = {
    "T1078": {"technique_name": "Valid Accounts", "tactic": "initial-access", "test_count": 3,
             "test_names": ["Test A", "Test B", "Test C"]},
}


MINIMAL_STAGE3_PLAN_FOR_HASHING = {
    "schema_version": 1, "plan_title": "Minimal Stage 3 Plan",
    "test_concepts": [], "assessment_safety_review": {"category_2_3_present": False, "covered_test_ids": []},
}


def _setup_run(tmp_path, run_id="vaf-test", *, stage4_status=StageStatus.PASS,
               plan=None, validation_is_valid=True, corpus_hash="sha256:testcorpus",
               stage3_plan=None, include_source_identity=True, matching_hashes=True):
    base = str(tmp_path / "outputs")
    out_dir = run_output_dir(run_id, base)
    run_context.set_active_run(run_id, corpus_hash, out_dir)
    state = init_assessment_state(run_id, corpus_hash)
    if stage4_status is not None:
        set_stage_status(state, "stage4", stage4_status)
    save_assessment_state(state, run_id, base=base)
    if plan is not None:
        run_context.write_stamped_json(run_context.artifact_path("stage4_execution_plan.json"), plan)
        s3_plan = stage3_plan if stage3_plan is not None else MINIMAL_STAGE3_PLAN_FOR_HASHING
        run_context.write_stamped_json(run_context.artifact_path("stage3_test_plan.json"), s3_plan)
        validation_report = {"is_valid": validation_is_valid}
        if include_source_identity:
            validation_report["source_identity"] = {
                "stage4_execution_plan_sha256": canonical_json_sha256(plan if matching_hashes else {"different": True}),
                "stage3_test_plan_sha256": canonical_json_sha256(s3_plan if matching_hashes else {"different": True}),
            }
        run_context.write_stamped_json(run_context.artifact_path("stage4_execution_plan_validation.json"), validation_report)
    run_context.reset_active_run()
    return base, out_dir


@pytest.fixture(autouse=True)
def _isolated_active_run():
    run_context.reset_active_run()
    yield
    run_context.reset_active_run()


def _fake_rule_generator(**kwargs):
    return "title: Detect test\nstatus: experimental\ndescription: x\nlogsource:\n  category: x\ndetection:\n  x: y\ncondition: x"


# ---------------------------------------------------------------------------
# Run and state boundary
# ---------------------------------------------------------------------------

def test_run_id_is_required():
    parser = build_compiler_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_missing_assessment_state_fails(tmp_path):
    base = str(tmp_path / "outputs")
    with pytest.raises(RuntimeError, match="No assessment_state.json"):
        load_structured_stage4_run("does-not-exist", base=base)


def test_stage4_not_started_fails(tmp_path):
    base, _ = _setup_run(tmp_path, stage4_status=StageStatus.NOT_STARTED, plan=VALID_STAGE4_PLAN)
    with pytest.raises(RuntimeError, match="PASS is required"):
        load_structured_stage4_run("vaf-test", base=base)


def test_stage4_pending_fails(tmp_path):
    base, _ = _setup_run(tmp_path, stage4_status=StageStatus.PENDING, plan=VALID_STAGE4_PLAN)
    with pytest.raises(RuntimeError, match="PASS is required"):
        load_structured_stage4_run("vaf-test", base=base)


def test_stage4_fail_status_fails(tmp_path):
    base, _ = _setup_run(tmp_path, stage4_status=StageStatus.FAIL, plan=VALID_STAGE4_PLAN)
    with pytest.raises(RuntimeError, match="PASS is required"):
        load_structured_stage4_run("vaf-test", base=base)


def test_stage4_pass_is_required(tmp_path):
    base, _ = _setup_run(tmp_path, stage4_status=StageStatus.PASS, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    assert ctx.execution_plan["plan_id"] == "MP-001"


def test_cross_run_execution_plan_is_rejected(tmp_path):
    base1, _ = _setup_run(tmp_path, run_id="vaf-source", plan=VALID_STAGE4_PLAN)
    base2, out_dir2 = _setup_run(tmp_path, run_id="vaf-target", plan=None)
    import shutil
    shutil.copy(os.path.join(run_output_dir("vaf-source", base1), "stage4_execution_plan.json"),
               os.path.join(out_dir2, "stage4_execution_plan.json"))
    shutil.copy(os.path.join(run_output_dir("vaf-source", base1), "stage4_execution_plan_validation.json"),
               os.path.join(out_dir2, "stage4_execution_plan_validation.json"))
    with pytest.raises(Exception, match="belongs to run"):
        load_structured_stage4_run("vaf-target", base=base2)


def test_cross_corpus_execution_plan_is_rejected(tmp_path):
    base1, _ = _setup_run(tmp_path, run_id="vaf-corpusA", plan=VALID_STAGE4_PLAN, corpus_hash="sha256:corpusA")
    # Same run_id namespace-wise but a different corpus hash recorded in state --
    # simulate by writing the plan under corpusA's stamp then reloading state
    # that claims corpusB. The stamp mismatch must still be caught.
    base2, out_dir2 = _setup_run(tmp_path, run_id="vaf-corpusB", plan=None, corpus_hash="sha256:corpusB")
    import shutil
    shutil.copy(os.path.join(run_output_dir("vaf-corpusA", base1), "stage4_execution_plan.json"),
               os.path.join(out_dir2, "stage4_execution_plan.json"))
    shutil.copy(os.path.join(run_output_dir("vaf-corpusA", base1), "stage4_execution_plan_validation.json"),
               os.path.join(out_dir2, "stage4_execution_plan_validation.json"))
    with pytest.raises(Exception):
        load_structured_stage4_run("vaf-corpusB", base=base2)


def test_failed_stage4_validation_report_is_rejected(tmp_path):
    base, _ = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN, validation_is_valid=False)
    with pytest.raises(RuntimeError, match="is_valid=True"):
        load_structured_stage4_run("vaf-test", base=base)


def test_validation_report_binds_exact_stage4_plan(tmp_path):
    """A validation report with no source_identity at all must be
    rejected -- an unbound report can't prove it validated THIS plan."""
    base, _ = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN, include_source_identity=False)
    with pytest.raises(RuntimeError, match="does not identify the execution plan"):
        load_structured_stage4_run("vaf-test", base=base)


def test_same_run_rewritten_stage4_plan_is_rejected(tmp_path):
    """The actual swap attack: a validated plan is replaced, same run,
    same corpus stamp, still schema-valid -- but the content differs
    from what the (stale) validation report actually checked."""
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    run_context.set_active_run("vaf-test", "sha256:testcorpus", out_dir)
    swapped_plan = copy.deepcopy(VALID_STAGE4_PLAN)
    swapped_plan["plan_title"] = "SWAPPED -- NOT WHAT WAS VALIDATED"
    run_context.write_stamped_json(run_context.artifact_path("stage4_execution_plan.json"), swapped_plan)
    run_context.reset_active_run()
    with pytest.raises(RuntimeError, match="has changed since deterministic Stage 4 validation"):
        load_structured_stage4_run("vaf-test", base=base)


def test_validation_report_binds_stage3_source_plan(tmp_path):
    base, _ = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN, include_source_identity=False)
    # include_source_identity=False already covers the "no source_identity at
    # all" case above; here, confirm the specific stage3 sub-key matters too.
    base2, out_dir2 = _setup_run(tmp_path, run_id="vaf-test2", plan=VALID_STAGE4_PLAN)
    run_context.set_active_run("vaf-test2", "sha256:testcorpus", out_dir2)
    report = run_context.read_stamped_json(run_context.artifact_path("stage4_execution_plan_validation.json"))
    del report["source_identity"]["stage3_test_plan_sha256"]
    run_context.write_stamped_json(run_context.artifact_path("stage4_execution_plan_validation.json"), report)
    run_context.reset_active_run()
    with pytest.raises(RuntimeError, match="does not identify.*Stage 3 test plan"):
        load_structured_stage4_run("vaf-test2", base=base2)


def test_same_run_rewritten_stage3_plan_is_rejected(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    run_context.set_active_run("vaf-test", "sha256:testcorpus", out_dir)
    swapped_stage3 = dict(MINIMAL_STAGE3_PLAN_FOR_HASHING)
    swapped_stage3["plan_title"] = "SWAPPED STAGE 3 PLAN"
    run_context.write_stamped_json(run_context.artifact_path("stage3_test_plan.json"), swapped_stage3)
    run_context.reset_active_run()
    with pytest.raises(RuntimeError, match="stage3_test_plan.json has changed"):
        load_structured_stage4_run("vaf-test", base=base)


# ---------------------------------------------------------------------------
# Structured compilation
# ---------------------------------------------------------------------------

def test_one_record_created_per_stage4_action():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert len(records) == 1
    assert records[0].action_id == "ACT-001"


def test_one_record_per_action_with_multiple_actions():
    plan = copy.deepcopy(VALID_STAGE4_PLAN)
    plan["phases"][0]["actions"].append({
        "action_id": "ACT-002", "test_id": "RT-001", "action_summary": "Second action",
        "responsible_roles": ["x"], "preconditions": ["x"], "success_criteria": ["x"],
        "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
        "telemetry_requirements": ["x"], "alert_triggers": ["x"], "opsec_measures": ["x"],
    })
    plan["test_bindings"][0]["assigned_action_ids"] = ["ACT-001", "ACT-002"]
    records = compile_structured_plan(plan)
    assert len(records) == 2


def test_phase_order_uses_sequence():
    plan = copy.deepcopy(VALID_STAGE4_PLAN)
    plan["phases"].insert(0, {
        "phase_id": "PHASE-02", "sequence": 2, "name": "Later", "purpose": "x",
        "entry_criteria": ["x"], "exit_criteria": ["x"],
        "actions": [{"action_id": "ACT-002", "test_id": "RT-001", "action_summary": "y",
                    "responsible_roles": ["x"], "preconditions": ["x"], "success_criteria": ["x"],
                    "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
                    "telemetry_requirements": ["x"], "alert_triggers": ["x"], "opsec_measures": ["x"]}],
    })
    plan["test_bindings"][0]["assigned_action_ids"] = ["ACT-001", "ACT-002"]
    records = compile_structured_plan(plan)
    # Even though PHASE-02 (sequence 2) is listed FIRST in the plan dict,
    # output order must follow sequence, not list position.
    assert [r.phase_id for r in records] == ["PHASE-01", "PHASE-02"]


def test_action_order_is_preserved():
    plan = copy.deepcopy(VALID_STAGE4_PLAN)
    plan["phases"][0]["actions"].append({
        "action_id": "ACT-002", "test_id": "RT-001", "action_summary": "Second",
        "responsible_roles": ["x"], "preconditions": ["x"], "success_criteria": ["x"],
        "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
        "telemetry_requirements": ["x"], "alert_triggers": ["x"], "opsec_measures": ["x"],
    })
    plan["test_bindings"][0]["assigned_action_ids"] = ["ACT-001", "ACT-002"]
    records = compile_structured_plan(plan)
    assert [r.action_id for r in records] == ["ACT-001", "ACT-002"]


def test_binding_categories_are_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].categories == [1]


def test_stage2_vector_ids_are_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].stage2_vector_ids == ["V-01", "V-02"]


def test_kcag_path_is_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].kcag_path == ["ADV_START", "N1", "G1"]


def test_technique_ids_are_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].technique_ids == ["T1078", "CAPEC-628"]


def test_abort_criteria_are_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].abort_criteria == ["x"]


def test_recovery_steps_are_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].rollback_or_recovery_steps == ["x"]


def test_telemetry_is_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].telemetry_requirements == ["Auth log monitoring"]


def test_alert_triggers_are_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].alert_triggers == ["Failed auth spike"]


def test_opsec_measures_are_preserved():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    assert records[0].opsec_measures == ["Use isolated test account"]


def test_unbound_action_raises():
    plan = copy.deepcopy(VALID_STAGE4_PLAN)
    plan["phases"][0]["actions"][0]["test_id"] = "RT-999"
    with pytest.raises(RuntimeError, match="unbound test"):
        compile_structured_plan(plan)


# ---------------------------------------------------------------------------
# Crosswalk
# ---------------------------------------------------------------------------

def test_attack_id_with_atomic_entry_is_available():
    r = PurpleActionRecord(phase_id="P", phase_sequence=1, phase_name="x", phase_purpose="x",
                           action_id="A", action_summary="x", technique_ids=["T1078"])
    result = crosswalk_techniques([r], FAKE_ART_INDEX)
    assert result[0].atomic_test_references[0]["status"] == "VETTED_REFERENCE_AVAILABLE"
    assert result[0].atomic_test_references[0]["test_count"] == 3


def test_attack_id_without_atomic_entry_is_gap():
    r = PurpleActionRecord(phase_id="P", phase_sequence=1, phase_name="x", phase_purpose="x",
                           action_id="A", action_summary="x", technique_ids=["T9999"])
    result = crosswalk_techniques([r], FAKE_ART_INDEX)
    assert result[0].atomic_test_references[0]["status"] == "COVERAGE_GAP"
    assert result[0].atomic_test_references[0]["framework"] == "Atomic Red Team"


def test_capec_is_non_attack_coverage_gap():
    r = PurpleActionRecord(phase_id="P", phase_sequence=1, phase_name="x", phase_purpose="x",
                           action_id="A", action_summary="x", technique_ids=["CAPEC-628"])
    result = crosswalk_techniques([r], FAKE_ART_INDEX)
    assert result[0].atomic_test_references[0]["status"] == "COVERAGE_GAP"
    assert result[0].atomic_test_references[0]["framework"] == "NON_ATTACK"


def test_unmapped_marker_is_coverage_gap():
    r = PurpleActionRecord(phase_id="P", phase_sequence=1, phase_name="x", phase_purpose="x",
                           action_id="A", action_summary="x", technique_ids=["[UNMAPPED]"])
    result = crosswalk_techniques([r], FAKE_ART_INDEX)
    assert result[0].atomic_test_references[0]["status"] == "COVERAGE_GAP"


def test_multiple_techniques_are_all_crosswalked():
    r = PurpleActionRecord(phase_id="P", phase_sequence=1, phase_name="x", phase_purpose="x",
                           action_id="A", action_summary="x", technique_ids=["T1078", "CAPEC-628", "T9999"])
    result = crosswalk_techniques([r], FAKE_ART_INDEX)
    assert len(result[0].atomic_test_references) == 3
    summary = build_coverage_summary(result)
    assert summary == {"total_technique_references": 3, "vetted_reference_available": 1, "coverage_gap": 2}


def test_crosswalk_does_not_modify_source_plan():
    plan_before = copy.deepcopy(VALID_STAGE4_PLAN)
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    crosswalk_techniques(records, FAKE_ART_INDEX)
    assert VALID_STAGE4_PLAN == plan_before


# ---------------------------------------------------------------------------
# Artifact behavior
# ---------------------------------------------------------------------------

def test_scaffold_is_written_under_run_directory(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    assert os.path.exists(os.path.join(out_dir, "purple_scaffold.json"))


def test_scaffold_is_run_stamped(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    raw = json.load(open(os.path.join(out_dir, "purple_scaffold.json")))
    assert raw["_meta"]["run_id"] == "vaf-test"


def test_graph_is_written_under_run_directory(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    assert os.path.exists(os.path.join(out_dir, "purple_graph.json"))


def test_graph_is_run_stamped(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    raw = json.load(open(os.path.join(out_dir, "purple_graph.json")))
    assert raw["_meta"]["run_id"] == "vaf-test"


def test_scaffold_preserves_not_granted_authorization(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    scaffold, _ = write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    assert scaffold["safety"]["execution_authorization"] == "NOT_GRANTED"


def test_graph_uses_action_ids_as_nodes():
    records = compile_structured_plan(VALID_STAGE4_PLAN)
    crosswalk_techniques(records, FAKE_ART_INDEX)
    graph = build_purple_graph(records)
    assert graph["nodes"][0]["id"] == "ACT-001"


def test_graph_edges_follow_phase_and_action_order():
    plan = copy.deepcopy(VALID_STAGE4_PLAN)
    plan["phases"][0]["actions"].append({
        "action_id": "ACT-002", "test_id": "RT-001", "action_summary": "y",
        "responsible_roles": ["x"], "preconditions": ["x"], "success_criteria": ["x"],
        "abort_criteria": ["x"], "rollback_or_recovery_steps": ["x"],
        "telemetry_requirements": ["x"], "alert_triggers": ["x"], "opsec_measures": ["x"],
    })
    plan["test_bindings"][0]["assigned_action_ids"] = ["ACT-001", "ACT-002"]
    records = compile_structured_plan(plan)
    crosswalk_techniques(records, FAKE_ART_INDEX)
    graph = build_purple_graph(records)
    assert graph["edges"][0]["transition_type"] == "WITHIN_PHASE"


def test_source_artifacts_are_not_modified(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    plan_path = os.path.join(out_dir, "stage4_execution_plan.json")
    before = open(plan_path, "rb").read()
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    after = open(plan_path, "rb").read()
    assert before == after


def test_no_flat_output_files_are_written(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    flat_root = tmp_path / "outputs" / "purple_scaffold.json"
    assert not flat_root.exists()
    legacy_flat = tmp_path / "outputs" / "kcag_data.json"
    assert not legacy_flat.exists()


# ---------------------------------------------------------------------------
# Legacy behavior
# ---------------------------------------------------------------------------

LEGACY_PROSE = (
    "### **Phase 1: Initial Access\n"
    "* **Action:** Use stolen credentials\n"
    "* **MITRE ATT&CK Mapping:**\n"
    "  - T1078\n"
    "* **Execution Timeline:** Day 1\n"
    "* **Telemetry:** Auth logs\n"
    "* **Alert Trigger:** Failed auth spike\n"
)


def test_missing_structured_plan_does_not_auto_fallback(tmp_path):
    base, _ = _setup_run(tmp_path, plan=None)
    with pytest.raises(RuntimeError, match="never silently falls back"):
        load_structured_stage4_run("vaf-test", base=base)


def test_legacy_mode_requires_existing_assessment_state(tmp_path, monkeypatch):
    """--legacy-markdown compensates for a missing stage4_execution_plan.json,
    not for a run ID with no real assessment_state.json at all."""
    import src.purple.purple_compiler as pc
    monkeypatch.setattr(pc, "load_art_index", lambda refresh=False: {})
    monkeypatch.chdir(tmp_path)
    prose_path = tmp_path / "legacy.md"
    prose_path.write_text(LEGACY_PROSE)
    with pytest.raises(RuntimeError, match="No assessment_state.json found"):
        compiler_main(["--run-id", "vaf-nonexistent", "--legacy-markdown", str(prose_path)])


def test_legacy_mode_uses_state_corpus_hash(tmp_path, monkeypatch):
    import src.purple.purple_compiler as pc
    monkeypatch.setattr(pc, "load_art_index", lambda refresh=False: {})
    monkeypatch.chdir(tmp_path)

    run_context.set_active_run("vaf-legacy-real", "sha256:the-real-corpus-hash", str(tmp_path / "outputs" / "vaf-legacy-real"))
    state = init_assessment_state("vaf-legacy-real", "sha256:the-real-corpus-hash")
    save_assessment_state(state, "vaf-legacy-real")
    run_context.reset_active_run()

    prose_path = tmp_path / "legacy.md"
    prose_path.write_text(LEGACY_PROSE)
    compiler_main(["--run-id", "vaf-legacy-real", "--legacy-markdown", str(prose_path)])

    written = json.load(open(tmp_path / "outputs" / "vaf-legacy-real" / "purple_scaffold.json"))
    assert written["_meta"]["corpus_manifest_hash"] == "sha256:the-real-corpus-hash"


def test_legacy_parser_requires_explicit_flag():
    """Structural confirmation: parse_legacy_mdmp_plan is never called by
    load_structured_stage4_run or compile_structured_plan -- the only
    call site is main()'s explicit --legacy-markdown branch."""
    import inspect
    import src.purple.purple_compiler as pc
    source = inspect.getsource(pc.load_structured_stage4_run) + inspect.getsource(pc.compile_structured_plan)
    assert "parse_legacy_mdmp_plan" not in source


def test_legacy_mode_emits_warning(tmp_path):
    prose_path = tmp_path / "legacy.md"
    prose_path.write_text(LEGACY_PROSE)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        parse_legacy_mdmp_plan(str(prose_path))
        assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_legacy_output_is_run_scoped(tmp_path):
    prose_path = tmp_path / "legacy.md"
    prose_path.write_text(LEGACY_PROSE)
    base, out_dir = _setup_run(tmp_path, run_id="vaf-legacy", plan=None)
    run_context.set_active_run("vaf-legacy", "sha256:legacy", out_dir)
    records = parse_legacy_mdmp_plan(str(prose_path))
    write_purple_artifacts(None, records, FAKE_ART_INDEX, legacy=True, legacy_path=str(prose_path))
    run_context.reset_active_run()
    assert os.path.exists(os.path.join(out_dir, "purple_scaffold.json"))


def test_legacy_output_marks_partial_provenance(tmp_path):
    prose_path = tmp_path / "legacy.md"
    prose_path.write_text(LEGACY_PROSE)
    records = parse_legacy_mdmp_plan(str(prose_path))
    assert records[0].provenance_status == "LEGACY_PARTIAL"
    assert records[0].test_id is None
    assert records[0].stage2_vector_ids == []
    assert records[0].kcag_path == []


def test_legacy_scaffold_does_not_claim_authorization(tmp_path):
    prose_path = tmp_path / "legacy.md"
    prose_path.write_text(LEGACY_PROSE)
    base, out_dir = _setup_run(tmp_path, run_id="vaf-legacy2", plan=None)
    run_context.set_active_run("vaf-legacy2", "sha256:legacy", out_dir)
    records = parse_legacy_mdmp_plan(str(prose_path))
    scaffold, _ = write_purple_artifacts(None, records, FAKE_ART_INDEX, legacy=True, legacy_path=str(prose_path))
    run_context.reset_active_run()
    assert scaffold["safety"]["execution_authorization"] is None
    assert scaffold["source"]["format"] == "legacy_markdown"


# ---------------------------------------------------------------------------
# Sigma migration
# ---------------------------------------------------------------------------

def test_sigma_generator_requires_run_id():
    parser = build_sigma_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_sigma_reads_stamped_run_scaffold(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    manifest = generate_rules_for_run("vaf-test", base=base, rule_generator=_fake_rule_generator)
    assert len(manifest["rules"]) == 1
    assert manifest["rules"][0]["action_id"] == "ACT-001"


def test_sigma_rejects_cross_run_scaffold(tmp_path):
    base1, out_dir1 = _setup_run(tmp_path, run_id="vaf-sigma-src", plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-sigma-src", base=base1)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    base2, out_dir2 = _setup_run(tmp_path, run_id="vaf-sigma-dst", plan=None)
    import shutil
    shutil.copy(os.path.join(out_dir1, "purple_scaffold.json"), os.path.join(out_dir2, "purple_scaffold.json"))

    with pytest.raises(Exception, match="belongs to run"):
        generate_rules_for_run("vaf-sigma-dst", base=base2, rule_generator=_fake_rule_generator)


def test_sigma_rules_are_run_scoped(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    generate_rules_for_run("vaf-test", base=base, rule_generator=_fake_rule_generator)
    assert os.path.exists(os.path.join(out_dir, "sigma_rules", "ACT-001_RT-001.yml"))


def test_sigma_filename_uses_action_and_test_ids(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    manifest = generate_rules_for_run("vaf-test", base=base, rule_generator=_fake_rule_generator)
    assert manifest["rules"][0]["path"] == "sigma_rules/ACT-001_RT-001.yml"


def test_sigma_manifest_is_stamped(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    generate_rules_for_run("vaf-test", base=base, rule_generator=_fake_rule_generator)
    raw = json.load(open(os.path.join(out_dir, "sigma_rules_manifest.json")))
    assert raw["_meta"]["run_id"] == "vaf-test"


def test_sigma_prompt_uses_structured_telemetry_and_alerts(tmp_path):
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    captured = {}

    def capturing_generator(*, action_summary, telemetry, alert, test_id, technique_ids):
        captured["telemetry"] = telemetry
        captured["alert"] = alert
        captured["test_id"] = test_id
        captured["technique_ids"] = technique_ids
        return "title: x\n"

    generate_rules_for_run("vaf-test", base=base, rule_generator=capturing_generator)
    assert captured["telemetry"] == "Auth log monitoring"
    assert captured["alert"] == "Failed auth spike"
    assert captured["test_id"] == "RT-001"
    assert captured["technique_ids"] == ["T1078", "CAPEC-628"]


def test_sigma_skips_actions_without_detection_criteria(tmp_path):
    plan = copy.deepcopy(VALID_STAGE4_PLAN)
    plan["phases"][0]["actions"][0]["telemetry_requirements"] = []
    plan["phases"][0]["actions"][0]["alert_triggers"] = []
    base, out_dir = _setup_run(tmp_path, plan=plan)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    manifest = generate_rules_for_run("vaf-test", base=base, rule_generator=_fake_rule_generator)
    assert len(manifest["rules"]) == 0


def test_sigma_generation_failure_writes_error_txt_not_yml(tmp_path):
    """A failed LLM call must never produce a .yml file -- downstream
    tooling that globs sigma_rules/*.yml could otherwise mistake
    'ERROR generating rule: ...' text for a real detection rule."""
    base, out_dir = _setup_run(tmp_path, plan=VALID_STAGE4_PLAN)
    ctx = load_structured_stage4_run("vaf-test", base=base)
    records = compile_structured_plan(ctx.execution_plan)
    write_purple_artifacts(ctx, records, FAKE_ART_INDEX, legacy=False)
    run_context.reset_active_run()

    def failing_generator(**kwargs):
        return "ERROR generating rule: connection refused"

    manifest = generate_rules_for_run("vaf-test", base=base, rule_generator=failing_generator)
    assert manifest["rules"][0]["status"] == "GENERATION_FAILED"
    assert manifest["rules"][0]["path"].endswith(".error.txt")
    assert not manifest["rules"][0]["path"].endswith(".yml")

    rules_dir = os.path.join(out_dir, "sigma_rules")
    written_files = os.listdir(rules_dir)
    assert not any(f.endswith(".yml") for f in written_files)
    assert any(f.endswith(".error.txt") for f in written_files)


# ---------------------------------------------------------------------------
# No-network unit tests
# ---------------------------------------------------------------------------

def test_injected_art_index_avoids_network():
    """Confirms crosswalk_techniques works purely off the injected dict
    -- no network call is even reachable from this function."""
    r = PurpleActionRecord(phase_id="P", phase_sequence=1, phase_name="x", phase_purpose="x",
                           action_id="A", action_summary="x", technique_ids=["T1078"])
    result = crosswalk_techniques([r], {"T1078": {"technique_name": "x", "test_count": 0, "test_names": []}})
    assert result[0].atomic_test_references[0]["status"] == "VETTED_REFERENCE_AVAILABLE"


def test_cached_index_is_used_without_refresh(tmp_path, monkeypatch):
    import src.purple.purple_compiler as pc
    cache_file = tmp_path / "art_index.json"
    cache_file.write_text(json.dumps({"T1078": {"technique_name": "cached", "test_count": 1, "test_names": []}}))
    monkeypatch.setattr(pc, "CACHE_FILE", str(cache_file))

    def fail_if_called(*a, **k):
        raise AssertionError("network fetch should not have been called when cache exists")
    monkeypatch.setattr(pc.urllib.request, "urlopen", fail_if_called)

    index = pc.load_art_index(refresh=False)
    assert index["T1078"]["technique_name"] == "cached"


def test_refresh_flag_calls_fetcher(tmp_path, monkeypatch):
    import src.purple.purple_compiler as pc
    cache_file = tmp_path / "art_index.json"
    cache_file.write_text(json.dumps({"T1078": {"technique_name": "stale", "test_count": 1, "test_names": []}}))
    monkeypatch.setattr(pc, "CACHE_FILE", str(cache_file))
    monkeypatch.setattr(pc, "CACHE_DIR", str(tmp_path))

    called = {"count": 0}

    class FakeResponse:
        def read(self):
            return b"tactic1:\n  T1078:\n    technique:\n      name: Fresh\n    atomic_tests: []\n"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(*a, **k):
        called["count"] += 1
        return FakeResponse()

    monkeypatch.setattr(pc.urllib.request, "urlopen", fake_urlopen)
    index = pc.load_art_index(refresh=True)
    assert called["count"] == 1
    assert index["T1078"]["technique_name"] == "Fresh"
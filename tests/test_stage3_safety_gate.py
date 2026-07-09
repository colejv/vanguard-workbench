"""
Tests for the pre-Stage-4 safety gate (check_stage3_safety_gate), the
section-scoping fix, the tightened contradiction handling in
check_phase0_safety_gate, and the enforce_stage3_safety_gate orchestration
helper.

Covers the reviewer's 11 originally-requested checker unit tests, plus 3
markdown-robustness tests added after finding that the originally proposed
CATEGORY_LINE regex silently fails to match real Stage 3 output (observed
this session: '**Category:** 3, 4', '**Category:** `1, 4`') -- a bolded
field label is the norm for this project's actual LLM output, not an edge
case, and a regex that only matches unstyled 'Category: 2' would be a
dangerous false negative for a safety gate. See _strip_markdown_emphasis
in tools.py.

Also covers: the five section-scoping tests (required fields and the
no-gate declaration must come from inside the PRE-STAGE-4 SAFETY REVIEW
section specifically, not anywhere in the document -- a real bug found
and fixed after a reviewer's adversarial example reproduced it against
the shipped code); the two gate-report artifact-boundary tests (stamped,
run-rejecting); the check_phase0_safety_gate contradiction fix and its
own false-positive regression (Stage 3's own required override sentence
self-triggering category detection); and four orchestration tests calling
the real enforce_stage3_safety_gate() and build_stage4_task() functions
directly, proving that a gate failure raises before build_stage4_task is
structurally reachable, marks stage3 FAIL, and leaves stage4 untouched at
NOT_STARTED.

Note on scope: the orchestration tests above prove the function-level
ordering contract (enforce_stage3_safety_gate raises before
build_stage4_task can run) -- they do not additionally mock
crewai.Crew.kickoff() to prove the stage4_crew Crew object itself is never
instantiated in the real pipeline. That fuller mocked-kickoff proof was
run manually against the real pipeline this session (4 scenarios,
asserting a call-flag on the stage4_crew mock is never set on failure)
but isn't packaged as a pytest file here. The function-level proof is the
one that actually matters for correctness -- crew.py has no code path
that reaches build_stage4_task without going through
enforce_stage3_safety_gate first -- but flagging the distinction rather
than overstating coverage.
"""
import json
from pathlib import Path

import pytest

from src import run_context
from src.tools import check_stage3_safety_gate, check_phase0_safety_gate, STAGE3_REQUIRED_SAFETY_FIELDS


COMPLETE_REVIEW = """
## PRE-STAGE-4 SAFETY REVIEW
Category 2/3 concepts present: YES
Covered test concepts: RT-001, RT-004
Affected assets: AFATDS fire control endpoint
Required approving roles: RSO, Blue Team Commander
RSO or domain-equivalent safety authority: Range Safety Officer
Abort authority: Red Team Lead
Abort criteria: Any telemetry showing coordinate deviation >5m
Maximum termination time: <15 sec
Rollback or recovery procedure: Immediate kill-switch, revert to baseline routing
Release condition: Phase 1 may not begin until safety clearance is signed off.
"""

NO_GATE = "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."


# ---------- check_stage3_safety_gate: reviewer-requested unit tests ----------

def test_no_category_2_3_with_exact_statement_passes():
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 1\n\n## PRE-STAGE-4 SAFETY REVIEW\n{NO_GATE}")
    assert r["is_compliant"] is True
    assert r["category_2_3_detected"] is False


def test_no_category_2_3_without_statement_fails():
    r = check_stage3_safety_gate("### RT-001\nCategory: 1\n")
    assert r["is_compliant"] is False
    assert r["category_2_3_detected"] is False


def test_category_2_with_complete_safety_review_passes():
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 2\n{COMPLETE_REVIEW}")
    assert r["is_compliant"] is True
    assert r["category_2_3_detected"] is True
    assert not r["missing_fields"]
    assert not r["invalid_fields"]


def test_category_3_with_complete_safety_review_passes():
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 3\n{COMPLETE_REVIEW}")
    assert r["is_compliant"] is True


def test_mixed_category_3_4_passes_with_complete_review():
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 3, 4\n{COMPLETE_REVIEW}")
    assert r["is_compliant"] is True
    assert r["matched_categories"] == [3]


@pytest.mark.parametrize("removed_line", [
    "Affected assets: AFATDS fire control endpoint\n",
    "Required approving roles: RSO, Blue Team Commander\n",
    "RSO or domain-equivalent safety authority: Range Safety Officer\n",
    "Abort authority: Red Team Lead\n",
    "Abort criteria: Any telemetry showing coordinate deviation >5m\n",
    "Maximum termination time: <15 sec\n",
    "Rollback or recovery procedure: Immediate kill-switch, revert to baseline routing\n",
])
def test_category_2_missing_each_required_field_fails(removed_line):
    bad_review = COMPLETE_REVIEW.replace(removed_line, "")
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 2\n{bad_review}")
    assert r["is_compliant"] is False
    assert r["missing_fields"], "at least one field must be reported missing"


def test_tbd_values_fail():
    bad_review = COMPLETE_REVIEW.replace("Range Safety Officer", "TBD")
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 2\n{bad_review}")
    assert r["is_compliant"] is False
    assert "safety_authority" in r["invalid_fields"]


def test_missing_release_condition_fails():
    bad_review = COMPLETE_REVIEW.replace(
        "Release condition: Phase 1 may not begin until safety clearance is signed off.", "")
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 2\n{bad_review}")
    assert r["is_compliant"] is False
    assert "release_condition" in r["missing_fields"]


def test_weak_release_condition_fails():
    bad_review = COMPLETE_REVIEW.replace(
        "Release condition: Phase 1 may not begin until safety clearance is signed off.",
        "Release condition: Proceed with caution.")
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 2\n{bad_review}")
    assert r["is_compliant"] is False
    assert "release_condition" in r["invalid_fields"]


def test_category_2_with_not_required_statement_fails():
    """Contradiction: Category 2 declared AND the not-required sentence
    both present. Must fail, not silently pick one."""
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 2\n{COMPLETE_REVIEW}\n{NO_GATE}")
    assert r["is_compliant"] is False
    assert "contradictory_not_required_statement" in r["invalid_fields"]


def test_no_gate_sentence_does_not_trigger_category_detection():
    """The sentinel phrase itself contains the literal text 'CATEGORY 2/3'
    -- a naive substring search would false-positive against its own
    override statement. Must not self-trigger detection. (Embedded in a
    properly-sectioned document here, not bare -- the self-triggering
    concern is exercised regardless of surrounding structure, since
    category detection scans the whole document either way.)"""
    r = check_stage3_safety_gate(f"### RT-001\nCategory: 1\n\n## PRE-STAGE-4 SAFETY REVIEW\n{NO_GATE}")
    assert r["category_2_3_detected"] is False
    assert r["is_compliant"] is True


# ---------- Additional: markdown-robustness (found during verification) ----------

def test_bold_category_label_still_detected():
    """Real Stage 3 output bolds field labels -- this must still work,
    not just the illustrative unstyled format."""
    r = check_stage3_safety_gate(f"### RT-001\n**Category:** 2\n{COMPLETE_REVIEW}")
    assert r["category_2_3_detected"] is True
    assert r["is_compliant"] is True


def test_bold_field_labels_in_review_still_detected():
    text = (
        "### RT-001\n**Category:** 2\n\n"
        "## PRE-STAGE-4 SAFETY REVIEW\n"
        "**Category 2/3 concepts present:** YES\n"
        "**Covered test concepts:** RT-001\n"
        "**Affected assets:** AFATDS\n"
        "**Required approving roles:** RSO\n"
        "**RSO or domain-equivalent safety authority:** RSO\n"
        "**Abort authority:** Red Team Lead\n"
        "**Abort criteria:** deviation >5m\n"
        "**Maximum termination time:** <15 sec\n"
        "**Rollback or recovery procedure:** kill-switch\n"
        "**Release condition:** Phase 1 may not begin until cleared.\n"
    )
    r = check_stage3_safety_gate(text)
    assert r["is_compliant"] is True, r


def test_backtick_wrapped_category_value_still_detected():
    """Matches the exact format observed in a real Stage 3 transcript
    this session: '**Category:** `1, 4`'."""
    r = check_stage3_safety_gate(f"### RT-001\n**Category:** `2, 3`\n{COMPLETE_REVIEW}")
    assert r["category_2_3_detected"] is True
    assert r["is_compliant"] is True


# ---------- Gate report artifact-boundary tests ----------

def test_gate_report_is_run_stamped(tmp_path):
    run_context.reset_active_run()
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.set_active_run("test-run", "sha256:test-corpus", str(out_dir))

    gate_result = check_stage3_safety_gate(f"### RT-001\nCategory: 1\n\n## PRE-STAGE-4 SAFETY REVIEW\n{NO_GATE}")
    gate_path = run_context.artifact_path("stage3_safety_gate.json")
    run_context.write_stamped_json(gate_path, gate_result)

    envelope = json.loads(Path(gate_path).read_text())
    assert envelope["_meta"]["run_id"] == "test-run"
    assert envelope["_meta"]["corpus_manifest_hash"] == "sha256:test-corpus"
    assert envelope["data"]["is_compliant"] is True

    run_context.reset_active_run()


def test_gate_rejects_stage3_from_another_run(tmp_path):
    out_dir_a = tmp_path / "outputs" / "run-a"
    run_context.reset_active_run()
    run_context.set_active_run("run-a", "sha256:corpus-a", str(out_dir_a))
    gate_path = run_context.artifact_path("stage3_safety_gate.json")
    run_context.write_stamped_json(gate_path, {"is_compliant": True})
    run_context.reset_active_run()

    out_dir_b = tmp_path / "outputs" / "run-b"
    run_context.set_active_run("run-b", "sha256:corpus-b", str(out_dir_b))
    with pytest.raises(ValueError):
        run_context.read_stamped_json(gate_path)
    run_context.reset_active_run()


# ---------- Section-scoping tests (required-field fix) ----------

def test_complete_fields_outside_safety_section_do_not_pass():
    """The exact adversarial case that motivated this fix: every required
    field is present in the document, but scattered in an unrelated
    per-payload block -- only 'Release condition' is actually inside the
    PRE-STAGE-4 SAFETY REVIEW section. Must fail."""
    doc = (
        "### RT-001\n\nCategory: 2\n\n"
        "Affected assets: System A\n"
        "Required approving roles: RSO\n"
        "RSO or domain-equivalent safety authority: Range Safety Officer\n"
        "Abort authority: Red Team Lead\n"
        "Abort criteria: Any unexpected effect\n"
        "Maximum termination time: 15 seconds\n"
        "Rollback or recovery procedure: Restore baseline\n\n"
        "## PRE-STAGE-4 SAFETY REVIEW\n\n"
        "Release condition: Phase 1 may not begin until approved.\n"
    )
    r = check_stage3_safety_gate(doc)
    assert r["is_compliant"] is False
    assert set(r["missing_fields"]) == {
        "affected_assets", "approving_roles", "safety_authority",
        "abort_authority", "abort_criteria", "termination_time", "rollback",
    }


def test_no_gate_statement_outside_safety_section_does_not_pass():
    """The no-gate sentence appearing outside the section (e.g. stray, or
    left over from an earlier draft) must not satisfy compliance -- it
    has to be INSIDE the section, same requirement as CRITICAL
    INSTRUCTION 5 places on it."""
    doc = f"### RT-001\nCategory: 1\n\n{NO_GATE}\n\n## PRE-STAGE-4 SAFETY REVIEW\n(empty)\n"
    r = check_stage3_safety_gate(doc)
    assert r["is_compliant"] is False
    assert r["explicit_not_required"] is False


def test_empty_safety_section_fails():
    """The heading exists, but its body is empty -- no fields, no no-gate
    statement. Must fail with the section correctly detected as present
    but incomplete, not silently treated as compliant."""
    doc = "### RT-001\nCategory: 2\n\n## PRE-STAGE-4 SAFETY REVIEW\n"
    r = check_stage3_safety_gate(doc)
    assert r["is_compliant"] is False
    assert r["safety_review_present"] is True
    assert len(r["missing_fields"]) == len(STAGE3_REQUIRED_SAFETY_FIELDS)


def test_complete_safety_section_passes_with_unrelated_fields_elsewhere():
    """The inverse of the adversarial case: the safety-review section
    itself is genuinely complete, AND (as CRITICAL INSTRUCTION 5 actually
    asks for) the same fields are also legitimately repeated per-payload.
    Duplication elsewhere in the document must not cause a false
    rejection -- only the section's own content is what's checked."""
    doc = (
        "### RT-001\n\nCategory: 2\n"
        "Affected assets: System A (per-payload copy)\n"
        "Abort criteria: per-payload copy\n\n"
        f"{COMPLETE_REVIEW}"
    )
    r = check_stage3_safety_gate(doc)
    assert r["is_compliant"] is True


def test_safety_section_stops_at_next_heading():
    """Content after the NEXT markdown heading must not leak into the
    extracted section -- otherwise a well-formed section followed by an
    unrelated later section that happens to contain a no-gate sentence
    (or stray field labels) could contaminate the check."""
    doc = (
        f"### RT-001\nCategory: 2\n\n{COMPLETE_REVIEW}\n"
        f"## APPENDIX\n{NO_GATE}\nAffected assets: should not count\n"
    )
    r = check_stage3_safety_gate(doc)
    # COMPLETE_REVIEW alone is already fully compliant -- the appendix
    # content must have no effect on the result either way.
    assert r["is_compliant"] is True
    assert r["explicit_not_required"] is False, \
        "the no-gate sentence in a LATER, unrelated section must not count"


# ---------- Orchestration: enforce_stage3_safety_gate (real production function) ----------

from src.schemas import AssessmentState, StageStatus
from src.state import init_assessment_state, enforce_stage3_safety_gate


def test_failed_stage3_gate_marks_stage3_fail(tmp_path):
    state = init_assessment_state("test_run", "sha256:testhash")
    base = str(tmp_path / "outputs_base")
    with pytest.raises(RuntimeError, match="Stage 3 safety gate FAILED"):
        enforce_stage3_safety_gate(state, "test_run", is_compliant=False,
                                   summary="missing fields", base=base)
    assert state.stages["stage3"].status == StageStatus.FAIL
    assert state.current_stage == "stage3"


def test_failed_stage3_gate_leaves_stage4_not_started(tmp_path):
    """enforce_stage3_safety_gate never touches stage4's own state record
    -- a Stage 3 gate failure must leave Stage 4 exactly as it started,
    not implicitly marked anything."""
    state = init_assessment_state("test_run", "sha256:testhash")
    base = str(tmp_path / "outputs_base")
    with pytest.raises(RuntimeError):
        enforce_stage3_safety_gate(state, "test_run", is_compliant=False,
                                   summary="missing fields", base=base)
    assert state.stages["stage4"].status == StageStatus.NOT_STARTED


def test_failed_stage3_gate_raises_before_stage4_builder(tmp_path):
    """Proves the actual ordering property, not just that both events
    happen to occur: build_stage4_task must never be reached when the
    gate fails. Uses a mutable flag rather than trusting that 'it raised'
    implies 'the next line never ran' -- this makes the assertion explicit."""
    from src.tasks import build_stage4_task

    state = init_assessment_state("test_run", "sha256:testhash")
    base = str(tmp_path / "outputs_base")
    stage4_builder_reached = {"value": False}

    try:
        enforce_stage3_safety_gate(state, "test_run", is_compliant=False,
                                   summary="missing fields", base=base)
        stage4_builder_reached["value"] = True
        build_stage4_task(str(tmp_path), "should never get here")
    except RuntimeError:
        pass

    assert stage4_builder_reached["value"] is False, \
        "code reached the line after enforce_stage3_safety_gate on the failure path"


def test_passing_stage3_gate_marks_stage3_pass(tmp_path):
    state = init_assessment_state("test_run", "sha256:testhash")
    base = str(tmp_path / "outputs_base")
    enforce_stage3_safety_gate(state, "test_run", is_compliant=True,
                               summary="compliant", base=base)
    assert state.stages["stage3"].status == StageStatus.PASS
    # A pass must NOT force current_stage to "complete" -- Stage 4 hasn't
    # run yet at this point in the real pipeline; only finalize_stage4_state
    # (called later, after stage4_crew finishes) owns that transition.
    assert state.current_stage != "complete"


# ---------- check_phase0_safety_gate: tightened contradiction handling ----------

def test_final_phase0_check_still_runs():
    """Baseline: the existing defense-in-depth check is unaffected for
    the normal compliant case."""
    s3 = "Category: 3\nkinetic effect"
    s4 = "PHASE 0 -- SAFETY GATE\nRSO required. Abort <15 sec."
    r = check_phase0_safety_gate(s3, s4)
    assert r["is_compliant"] is True


def test_stage4_contradiction_fails_final_check():
    """The fix this commit makes: Stage 3 declares Category 2/3, but
    Stage 4 states no Category 2/3 payloads apply -- must now FAIL, not
    pass with a 'flagged for review' note."""
    s3 = "Category: 2\nDegradation payload targeting the fires control endpoint."
    s4 = NO_GATE
    r = check_phase0_safety_gate(s3, s4)
    assert r["is_compliant"] is False
    assert "COMPLIANCE GAP" in r["summary"]


def test_clean_stage3_override_sentence_does_not_self_trigger_final_check():
    """Regression test for a bug found DURING verification of this
    commit, not present in the original proposal: Stage 3's own required
    override sentence ('NO CATEGORY 2/3 PAYLOADS...', now mandated by
    CRITICAL INSTRUCTION 5) contains the literal substring 'CATEGORY 2',
    which check_phase0_safety_gate's cruder KINETIC_CATEGORY_MARKERS scan
    of raw stage3_text would otherwise match -- making a genuinely clean
    Stage 3 output (no Category 2/3 concepts, correctly stating so)
    falsely register as category_2_3_detected=True. This bug did not
    exist before this commit, because Stage 3 never needed to contain
    this sentence prior to CRITICAL INSTRUCTION 5."""
    s3_clean = f"Category: 1\n\n{NO_GATE}"
    s4_clean = "# stage4\nPhase 1: normal operations."
    r = check_phase0_safety_gate(s3_clean, s4_clean)
    assert r["category_2_3_detected"] is False, \
        "the override sentence's own text must not self-trigger category detection"
    assert r["is_compliant"] is True
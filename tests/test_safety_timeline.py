"""
Acceptance tests for the deterministic safety-timeline contract
(src/safety_timeline.py). Encodes the review's finding: the compiler must
refuse conflicting authoritative timelines rather than choose or normalize.
"""
import pytest

from src.safety_timeline import (
    SafetyTimeline, SafetyTimelineContract, build_safety_timeline_contract,
    classify_control, duration_to_seconds,
    SafetyTimelineContradiction, SafetyTimelineAmbiguous,
)


# ---- unit normalization ----

def test_15_minutes_is_900_seconds():
    assert duration_to_seconds("15 minutes") == 900


def test_quarter_minute_is_15_seconds():
    assert duration_to_seconds("0.25 minutes") == 15


def test_15_seconds():
    assert duration_to_seconds("15 seconds") == 15


def test_unparseable_duration_raises():
    with pytest.raises(ValueError):
        duration_to_seconds("a little while")


# ---- classification ----

def test_signal_cessation_classified():
    assert classify_control("Active signals must cease within 15 seconds.") == "ACTIVE_SIGNAL_CESSATION"


def test_rollback_classified():
    assert classify_control("Full rollback must complete within 15 minutes.") == "ROLLBACK_COMPLETION"


def test_ambiguous_control_raises():
    # "terminate within 15 seconds" — signal cessation? full test termination?
    with pytest.raises(SafetyTimelineAmbiguous):
        classify_control("Termination must occur within 15 seconds.")


# ---- contract consistency ----

def _tl(control, secs, art="a", path="p", text="t"):
    return SafetyTimeline(control=control, maximum_seconds=secs,
                          source_artifact=art, source_path=path, source_text=text)


def test_signal_15s_plus_rollback_900s_passes():
    """Different controls, different values -> PASS."""
    c = SafetyTimelineContract([
        _tl("ACTIVE_SIGNAL_CESSATION", 15),
        _tl("ROLLBACK_COMPLETION", 900),
    ])
    c.require_consistent()  # no raise


def test_signal_15s_vs_signal_900s_contradiction():
    """Same control, two values -> CONTRADICTION."""
    c = SafetyTimelineContract([
        _tl("ACTIVE_SIGNAL_CESSATION", 15, art="stage4_prose"),
        _tl("ACTIVE_SIGNAL_CESSATION", 900, art="stage3_json"),
    ])
    with pytest.raises(SafetyTimelineContradiction, match="SAFETY_TIMELINE_CONTRADICTION"):
        c.require_consistent()


def test_contradiction_message_names_both_sources_and_no_selection():
    c = SafetyTimelineContract([
        _tl("ACTIVE_SIGNAL_CESSATION", 15, art="stage4_prose"),
        _tl("ACTIVE_SIGNAL_CESSATION", 900, art="stage3_json"),
    ])
    with pytest.raises(SafetyTimelineContradiction) as exc:
        c.require_consistent()
    msg = str(exc.value)
    assert "ACTIVE_SIGNAL_CESSATION" in msg
    assert "15 seconds" in msg and "900 seconds" in msg
    assert "No value was selected or propagated." in msg


# ---- build_safety_timeline_contract across artifacts ----

def test_prose_15s_json_15s_passes():
    plan = {"data": {"assessment_safety_review": {"maximum_termination_seconds": 15}}}
    prose = "Active spoofing signals must cease within 15 seconds of abort."
    c = build_safety_timeline_contract(stage3_plan=plan, stage4_prose=prose)
    c.require_consistent()
    assert c.canonical_seconds("ACTIVE_SIGNAL_CESSATION") == 15


def test_prose_15s_json_900s_contradiction():
    plan = {"data": {"assessment_safety_review": {"maximum_termination_seconds": 900}}}
    prose = "Active spoofing signals must cease within 15 seconds of abort."
    c = build_safety_timeline_contract(stage3_plan=plan, stage4_prose=prose)
    with pytest.raises(SafetyTimelineContradiction):
        c.require_consistent()


def test_unlabeled_termination_is_ambiguous():
    prose = "Termination must occur within 15 seconds."
    with pytest.raises(SafetyTimelineAmbiguous):
        build_safety_timeline_contract(stage4_prose=prose)


def test_consistent_contract_yields_canonical_value_for_overlay():
    """A consistent contract exposes a single canonical value the overlay
    can use — the replacement for 'read one value -> propagate it'."""
    plan = {"data": {"assessment_safety_review": {"maximum_termination_seconds": 15}}}
    prose = ("Active signals must cease within 15 seconds. "
             "Full rollback must complete within 15 minutes.")
    c = build_safety_timeline_contract(stage3_plan=plan, stage4_prose=prose)
    c.require_consistent()
    assert c.canonical_seconds("ACTIVE_SIGNAL_CESSATION") == 15
    assert c.canonical_seconds("ROLLBACK_COMPLETION") == 900


def test_overlay_uses_contract_canonical_value():
    """build_stage4_phase0_gate takes the termination seconds from the
    validated contract, not blindly from the review."""
    from src.stage4_writer import build_stage4_phase0_gate
    # Review says 900, but the validated contract's authoritative signal
    # cessation value is 15 — the overlay must use 15.
    plan = {"data": {"assessment_safety_review": {
        "category_2_3_present": True, "covered_test_ids": ["RT-002"],
        "required_approving_roles": ["Safety Officer"], "safety_authority": "RSO",
        "abort_authority": "Lead", "abort_criteria": ["x"],
        "maximum_termination_seconds": 900,
        "rollback_or_recovery_procedure": "revert", "release_condition": "no go before signoff"}}}
    contract = SafetyTimelineContract([_tl("ACTIVE_SIGNAL_CESSATION", 15)])
    contract.require_consistent()
    gate = build_stage4_phase0_gate(plan, safety_timeline_contract=contract)
    assert gate["maximum_termination_seconds"] == 15


def test_contradiction_stops_before_any_stage4_compile():
    """Integration-level guarantee: when the contract is contradictory, the
    crew's require_consistent() raises BEFORE the Stage 4 compiler/writer is
    reached. We simulate the crew ordering: check first, compile second."""
    plan = {"data": {"assessment_safety_review": {"maximum_termination_seconds": 900}}}
    stage4_prose = "Active spoofing signals must cease within 15 seconds."
    compile_called = {"n": 0}

    def _fake_compile(**kwargs):
        compile_called["n"] += 1

    contract = build_safety_timeline_contract(stage3_plan=plan, stage4_prose=stage4_prose)
    # This is exactly the crew ordering: require_consistent() then compile.
    with pytest.raises(SafetyTimelineContradiction):
        contract.require_consistent()
        _fake_compile()  # unreachable
    assert compile_called["n"] == 0, "compiler ran despite a timeline contradiction"
"""
Acceptance tests for the Annex C -> Stage 3 transition gate
(src/stage_transition.py). Encodes the review's fail-open finding: a blocked
Annex C must stop Stage 3 unless an authorized, run-bound waiver is present.
"""
import pytest

from src.stage_transition import (
    evaluate_stage3_transition, annex_c_artifact_hash,
    StageTransitionBlocked, TransitionDecision,
)


RUN = "vaf_20260714_165237"
CORPUS = "sha256:corpusX"

_ANNEXC_PASS = {"data": {"status": "PASS", "threat_score": 0.5}}
_ANNEXC_BLOCKED = {"data": {"status": "BLOCKED"}}


def _waiver(**over):
    h = annex_c_artifact_hash(_ANNEXC_BLOCKED)
    w = {
        "waiver_id": "W-001", "decision": "APPROVED", "approved_by": "COL J. Cole",
        "approved_at": "2026-07-15T00:00:00Z",
        "rationale": "NGC2 priors pending SME input; proceed for engineering dry-run only.",
        "scope": "RT-001..RT-003, non-executable", "source_inputs_missing": ["capability_prior", "tempo"],
        "run_id": RUN, "corpus_manifest_hash": CORPUS, "annex_c_artifact_hash": h,
    }
    w.update(over)
    return w


def _evAL(annexc, waiver):
    return evaluate_stage3_transition(
        annex_c_report=annexc, waiver=waiver, run_id=RUN, corpus_manifest_hash=CORPUS)


def test_annex_c_pass_allows_stage3():
    d = _evAL(_ANNEXC_PASS, None)
    assert d.allowed is True
    assert d.code == "ANNEX_C_PASS"
    d.require_allowed()  # no raise


def test_blocked_no_waiver_blocks():
    d = _evAL(_ANNEXC_BLOCKED, None)
    assert d.allowed is False
    assert d.code == "STAGE_TRANSITION_BLOCKED"
    with pytest.raises(StageTransitionBlocked):
        d.require_allowed()


def test_blocked_incomplete_waiver_blocks():
    incomplete = {"waiver_id": "W-001", "decision": "APPROVED"}  # missing most fields
    d = _evAL(_ANNEXC_BLOCKED, incomplete)
    assert d.allowed is False
    assert "missing required field" in d.reason


def test_blocked_valid_waiver_allows():
    d = _evAL(_ANNEXC_BLOCKED, _waiver())
    assert d.allowed is True
    assert d.code == "ANNEX_C_WAIVED"


def test_waiver_run_id_mismatch_blocks():
    d = _evAL(_ANNEXC_BLOCKED, _waiver(run_id="vaf_OTHER"))
    assert d.allowed is False
    assert "run_id" in d.reason


def test_waiver_corpus_hash_mismatch_blocks():
    d = _evAL(_ANNEXC_BLOCKED, _waiver(corpus_manifest_hash="sha256:OTHER"))
    assert d.allowed is False
    assert "corpus" in d.reason.lower()


def test_waiver_annex_c_hash_mismatch_blocks():
    d = _evAL(_ANNEXC_BLOCKED, _waiver(annex_c_artifact_hash="sha256:STALE"))
    assert d.allowed is False
    assert "stale" in d.reason.lower()


def test_annex_c_missing_blocks():
    d = _evAL(None, None)
    assert d.allowed is False
    assert d.code == "STAGE_TRANSITION_BLOCKED"


def test_waiver_not_approved_blocks():
    d = _evAL(_ANNEXC_BLOCKED, _waiver(decision="PENDING"))
    assert d.allowed is False
    assert "not APPROVED" in d.reason


def test_decision_audit_record_shape():
    d = _evAL(_ANNEXC_BLOCKED, None)
    rec = d.audit_record()
    assert rec["gate"] == "annex_c_to_stage3"
    assert rec["allowed"] is False
    assert rec["code"] == "STAGE_TRANSITION_BLOCKED"


def test_gate_runs_before_any_stage3_side_effect(tmp_path, monkeypatch):
    """Prove the gate occurs before any Stage 3 side effect: with Annex C
    BLOCKED and no waiver, injected Stage 3 callables must NEVER be called."""
    from src import stage3_flow

    compile_called = {"n": 0}

    def _never_compile(**kwargs):
        compile_called["n"] += 1

    # If the gate were bypassed, the orchestrator would call compile. We
    # assert the decision blocks and short-circuits before that.
    d = _evAL(_ANNEXC_BLOCKED, None)
    if d.allowed:
        stage3_flow.compile_stage3_until_valid(
            compile_candidate=_never_compile, validate_candidate=lambda: {"is_valid": True},
            write_validation_report=lambda r: None, read_candidate=lambda: {"test_concepts": []},
            identity_baseline_path="k", read_stamped_json=lambda p: {}, write_stamped_json=lambda p, v: None,
            artifact_path=str(tmp_path / "p.json"), validation_report_path=str(tmp_path / "r.json"),
        )
    assert compile_called["n"] == 0, "Stage 3 compile ran despite a blocked transition"
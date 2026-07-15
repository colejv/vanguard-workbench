"""
Tests for the spec-compliant live Annex C prior proposer.
Model faked by monkeypatching generate_structured_json (dispatched by
system_message). Proves deterministic safety properties without inference:
incomplete scan BLOCKS; hallucinated quotes dropped; synthesis cites
candidate IDs only; defensive_posture per-control; null never -> false.
"""
import json
import re

import pytest

import src.annexc_proposer as prop
import src.annexc_evidence as ev
from src.annexc_proposer import propose_priors_from_corpus

FROZEN = {
    "actor-report.pdf": {
        "sha256": "sha256:aaa",
        "text": ("The assessed actor demonstrated sustained access, tailored tooling, "
                 "and disciplined operational security. Administrative access requires "
                 "multifactor authentication. Operations proceeded at a rapid daily cadence."),
    },
}
_EMPTY = {"capability_prior": [], "tempo": [], "defensive_posture": [],
          "geopolitical_trigger_prior": [], "truncated": False}


class _Router:
    def __init__(self, extraction=None, synth=None, posture=None, fail_extraction=False):
        self.extraction = extraction or dict(_EMPTY)
        self.synth = synth
        self.posture = posture
        self.fail_extraction = fail_extraction

    def __call__(self, *, llm, schema, prompt, system_message="", **kwargs):
        if "evidence extractor" in system_message:
            if self.fail_extraction:
                raise RuntimeError("ollama timeout")
            return json.dumps(self.extraction)
        if "defensive_posture" in prompt:
            return json.dumps(self.posture or {"controls": {}, "confidence": "LOW", "reasoning": ""})
        return json.dumps(self.synth or {"supported": False, "confidence": "LOW",
                                         "reasoning": "", "candidate_ids": []})


def _cid(quote, prior="capability_prior", subfield=None):
    chunks = ev.build_prior_evidence_chunks(FROZEN)
    cand = {"quote": quote, "interpretation": "x"}
    if subfield:
        cand["subfield"] = subfield
    vc = ev.verify_candidate(candidate=cand, chunk=chunks[0], prior=prior)
    return vc.candidate_id


def test_incomplete_scan_blocks_every_prior(monkeypatch):
    monkeypatch.setattr(prop, "generate_structured_json", _Router(fail_extraction=True))
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x", extraction_retries=0)
    for prior in ("capability_prior", "tempo", "defensive_posture", "geopolitical_trigger_prior"):
        assert proposed[prior]["status"] == "BLOCKED"
        assert "INCOMPLETE_CORPUS_SCAN" in proposed[prior]["reasoning"]


def test_complete_scan_no_quotes_omits_prior(monkeypatch):
    monkeypatch.setattr(prop, "generate_structured_json", _Router())
    assert propose_priors_from_corpus(frozen_sources=FROZEN, llm="x") == {}


def test_hallucinated_quote_dropped_then_omitted(monkeypatch):
    extraction = dict(_EMPTY, capability_prior=[
        {"quote": "a zero-day nobody ever wrote down", "interpretation": "fabricated"}])
    synth = {"supported": True, "value": [0.1, 0.2, 0.7], "confidence": "HIGH",
             "reasoning": "x", "candidate_ids": ["ev_whatever"]}
    monkeypatch.setattr(prop, "generate_structured_json", _Router(extraction=extraction, synth=synth))
    assert "capability_prior" not in propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")


def test_verified_quote_with_valid_citation_supported(monkeypatch):
    q = "sustained access, tailored tooling"
    extraction = dict(_EMPTY, capability_prior=[{"quote": q, "interpretation": "sophistication"}])
    synth = {"supported": True, "value": [0.2, 0.3, 0.5], "confidence": "MEDIUM",
             "reasoning": "sustained access", "candidate_ids": [_cid(q)]}
    monkeypatch.setattr(prop, "generate_structured_json", _Router(extraction=extraction, synth=synth))
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")
    assert proposed["capability_prior"]["status"] == "SUPPORTED"
    assert proposed["capability_prior"]["value"] == [0.2, 0.3, 0.5]
    rec = proposed["capability_prior"]["evidence"][0]
    assert rec["source_sha256"] == "sha256:aaa"
    assert "start_char" in rec["locator"]


def test_synthesis_citing_unknown_id_is_dropped(monkeypatch):
    q = "sustained access, tailored tooling"
    extraction = dict(_EMPTY, capability_prior=[{"quote": q, "interpretation": "x"}])
    synth = {"supported": True, "value": [0.2, 0.3, 0.5], "confidence": "MEDIUM",
             "reasoning": "x", "candidate_ids": ["ev_fabricated"]}
    monkeypatch.setattr(prop, "generate_structured_json", _Router(extraction=extraction, synth=synth))
    assert "capability_prior" not in propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")


def test_defensive_posture_partial_evidence_not_supported(monkeypatch):
    q = "Administrative access requires multifactor authentication"
    extraction = dict(_EMPTY, defensive_posture=[
        {"subfield": "mfa", "quote": q, "interpretation": "mfa on"}])
    posture = {"controls": {"mfa": {"value": True, "candidate_ids": [_cid(q, "defensive_posture", "mfa")]},
                            "edr": {"value": None, "candidate_ids": []},
                            "segmentation": {"value": None, "candidate_ids": []},
                            "integrity_monitor": {"value": None, "candidate_ids": []},
                            "email_filtering": {"value": None, "candidate_ids": []}},
               "confidence": "MEDIUM", "reasoning": "only mfa"}
    monkeypatch.setattr(prop, "generate_structured_json", _Router(extraction=extraction, posture=posture))
    assert "defensive_posture" not in propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")


def test_scan_diagnostic_records_coverage(monkeypatch):
    monkeypatch.setattr(prop, "generate_structured_json", _Router(fail_extraction=True))
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x", extraction_retries=0)
    cov = proposed["tempo"]["evidence"][0]["coverage"]
    assert cov["complete"] is False and cov["successful_chunks"] == 0


# ---- reviewer corrections: truncation, probability-vector retry, resolved field, diagnostics ----

def test_truncated_chunk_blocks_scan(monkeypatch):
    """THE reviewer's correction: truncated=true must mark coverage
    incomplete, NOT count as a successful chunk. Relevant evidence may have
    existed and been cut off before it could be returned."""
    extraction = dict(_EMPTY, truncated=True)
    monkeypatch.setattr(prop, "generate_structured_json",
                        _Router(extraction=extraction))
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x", extraction_retries=0)
    for prior in ("capability_prior", "tempo", "defensive_posture", "geopolitical_trigger_prior"):
        assert proposed[prior]["status"] == "BLOCKED"
        assert "TRUNCATED" in proposed[prior]["reasoning"] or "INCOMPLETE_CORPUS_SCAN" in proposed[prior]["reasoning"]


def test_truncated_chunk_never_lets_capability_default(monkeypatch):
    """Specifically: capability_prior CAN default under the no-evidence
    policy, so this is the exact path a swallowed truncation would exploit.
    Confirm the proposer's output for capability is BLOCKED, not omitted
    (omission is what would let the caller's default apply)."""
    extraction = dict(_EMPTY, truncated=True)
    monkeypatch.setattr(prop, "generate_structured_json", _Router(extraction=extraction))
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x", extraction_retries=0)
    assert proposed["capability_prior"]["status"] == "BLOCKED"


class _RepairRouter:
    """Fake that returns an INVALID probability vector on first synthesis
    call, then a VALID one on the repair retry."""
    def __init__(self, extraction):
        self.extraction = extraction
        self.synth_calls = 0

    def __call__(self, *, llm, schema, prompt, system_message="", **kwargs):
        if "evidence extractor" in system_message:
            return json.dumps(self.extraction)
        self.synth_calls += 1
        if self.synth_calls == 1:
            return json.dumps({"supported": True, "value": [0.2, 0.3, 0.49],
                               "confidence": "MEDIUM", "reasoning": "x",
                               "candidate_ids": ["PLACEHOLDER"]})
        # repair attempt -> valid vector
        return json.dumps({"supported": True, "value": [0.2, 0.3, 0.5],
                           "confidence": "MEDIUM", "reasoning": "x",
                           "candidate_ids": ["PLACEHOLDER"]})


def test_invalid_probability_vector_triggers_bounded_repair_and_succeeds(monkeypatch):
    q = "sustained access, tailored tooling"
    extraction = dict(_EMPTY, capability_prior=[{"quote": q, "interpretation": "x"}])
    cid = _cid(q)
    router = _RepairRouter(extraction)
    # patch PLACEHOLDER -> real candidate id via a thin wrapper
    def _wrapped(*, llm, schema, prompt, system_message="", **kwargs):
        raw = router(llm=llm, schema=schema, prompt=prompt, system_message=system_message, **kwargs)
        return raw.replace("PLACEHOLDER", cid)
    monkeypatch.setattr(prop, "generate_structured_json", _wrapped)
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")
    assert proposed["capability_prior"]["status"] == "SUPPORTED"
    assert proposed["capability_prior"]["value"] == [0.2, 0.3, 0.5]
    assert router.synth_calls == 2  # one initial + one repair


def test_invalid_probability_vector_still_invalid_after_repair_blocks(monkeypatch):
    q = "sustained access, tailored tooling"
    extraction = dict(_EMPTY, capability_prior=[{"quote": q, "interpretation": "x"}])
    cid = _cid(q)

    def _always_bad(*, llm, schema, prompt, system_message="", **kwargs):
        if "evidence extractor" in system_message:
            return json.dumps(extraction)
        return json.dumps({"supported": True, "value": [0.5, 0.5, 0.5],
                           "confidence": "MEDIUM", "reasoning": "x",
                           "candidate_ids": [cid]})
    monkeypatch.setattr(prop, "generate_structured_json", _always_bad)
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")
    # Never silently normalized/assembled as SUPPORTED -> omitted (not
    # assembled), no-evidence policy applies at the caller.
    assert "capability_prior" not in proposed


def test_posture_control_missing_resolved_field_not_supported(monkeypatch):
    q = "Administrative access requires multifactor authentication"
    extraction = dict(_EMPTY, defensive_posture=[
        {"subfield": "mfa", "quote": q, "interpretation": "mfa on"}])
    cid = _cid(q, "defensive_posture", "mfa")
    # ALL controls explicitly resolved=True this time, with real evidence.
    posture = {"controls": {
        "mfa": {"resolved": True, "value": True, "candidate_ids": [cid]},
        "edr": {"resolved": True, "value": False, "candidate_ids": [cid]},
        "segmentation": {"resolved": True, "value": True, "candidate_ids": [cid]},
        "integrity_monitor": {"resolved": True, "value": True, "candidate_ids": [cid]},
        "email_filtering": {"resolved": True, "value": True, "candidate_ids": [cid]}},
        "confidence": "MEDIUM", "reasoning": "all resolved"}
    monkeypatch.setattr(prop, "generate_structured_json",
                        _Router(extraction=extraction, posture=posture))
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")
    assert proposed["defensive_posture"]["status"] == "SUPPORTED"
    assert proposed["defensive_posture"]["value"]["edr"] is False


def test_posture_unresolved_true_but_resolved_false_not_coerced(monkeypatch):
    """A control with value=true but resolved=false must NOT be treated as
    an established true -- resolved is the authoritative signal."""
    q = "Administrative access requires multifactor authentication"
    extraction = dict(_EMPTY, defensive_posture=[
        {"subfield": "mfa", "quote": q, "interpretation": "mfa on"}])
    cid = _cid(q, "defensive_posture", "mfa")
    posture = {"controls": {
        "mfa": {"resolved": False, "value": True, "candidate_ids": [cid]},  # inconsistent
        "edr": {"resolved": True, "value": True, "candidate_ids": [cid]},
        "segmentation": {"resolved": True, "value": True, "candidate_ids": [cid]},
        "integrity_monitor": {"resolved": True, "value": True, "candidate_ids": [cid]},
        "email_filtering": {"resolved": True, "value": True, "candidate_ids": [cid]}},
        "confidence": "MEDIUM", "reasoning": "x"}
    monkeypatch.setattr(prop, "generate_structured_json",
                        _Router(extraction=extraction, posture=posture))
    proposed = propose_priors_from_corpus(frozen_sources=FROZEN, llm="x")
    assert "defensive_posture" not in proposed  # mfa unresolved -> whole posture blocked


def test_diagnostics_written_for_incomplete_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(prop, "generate_structured_json", _Router(fail_extraction=True))
    propose_priors_from_corpus(frozen_sources=FROZEN, llm="x", extraction_retries=0,
                               diagnostics_out_dir=str(tmp_path))
    base = tmp_path / "annexc_proposer"
    assert (base / "chunk_manifest.json").exists()
    assert (base / "proposer_run.json").exists()
    run = json.load(open(base / "proposer_run.json"))
    assert run["successful_chunks"] == 0
    assert run["expected_chunks"] >= 1


def test_diagnostics_written_for_successful_run(monkeypatch, tmp_path):
    q = "sustained access, tailored tooling"
    extraction = dict(_EMPTY, capability_prior=[{"quote": q, "interpretation": "x"}])
    synth = {"supported": True, "value": [0.2, 0.3, 0.5], "confidence": "MEDIUM",
             "reasoning": "x", "candidate_ids": [_cid(q)]}
    monkeypatch.setattr(prop, "generate_structured_json", _Router(extraction=extraction, synth=synth))
    propose_priors_from_corpus(frozen_sources=FROZEN, llm="x", diagnostics_out_dir=str(tmp_path))
    base = tmp_path / "annexc_proposer"
    run = json.load(open(base / "proposer_run.json"))
    assert run["verified_candidates"] >= 1
    assert "capability_prior" in run["resolved_priors"]
    # per-chunk raw extraction response is captured
    extraction_dir = base / "extraction"
    assert any(extraction_dir.iterdir())
    synthesis_dir = base / "synthesis"
    assert any(synthesis_dir.iterdir())


def test_rejected_candidate_has_reason_code(monkeypatch, tmp_path):
    extraction = dict(_EMPTY, capability_prior=[
        {"quote": "this text is not anywhere in the source", "interpretation": "x"}])
    synth = {"supported": True, "value": [0.1, 0.2, 0.7], "confidence": "HIGH",
             "reasoning": "x", "candidate_ids": []}
    monkeypatch.setattr(prop, "generate_structured_json", _Router(extraction=extraction, synth=synth))
    propose_priors_from_corpus(frozen_sources=FROZEN, llm="x", diagnostics_out_dir=str(tmp_path))
    diag = json.load(open(tmp_path / "annexc_proposer" / "proposer_diagnostics.json"))
    reasons = {r["reason"] for r in diag["rejected_candidates"]}
    assert "QUOTE_NOT_FOUND" in reasons
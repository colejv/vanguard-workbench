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
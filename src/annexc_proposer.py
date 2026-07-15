"""
Live Annex C prior proposer (two-stage evidence funnel).

Normal path is N + 4 model calls for N chunks: one all-prior extraction call
per source-local chunk, then one focused synthesis call per prior. Two
independent deterministic checks bracket the model: post-extraction quote
verification here, and validate_derivation() downstream.

THE MOST IMPORTANT RULE: incomplete corpus processing is NOT the same as no
evidence. If any chunk times out, returns invalid JSON, or exhausts retries,
the scan is INCOMPLETE and every prior is BLOCKED (INCOMPLETE_CORPUS_SCAN) —
never allowed to fall through to a no-evidence default that would conceal an
LLM or infrastructure failure.

Three materially different cases:
  complete scan + no relevant quotes    -> deterministic no-evidence policy
  complete scan + insufficient support  -> BLOCKED (analytically insufficient)
  incomplete scan                        -> BLOCKED (corpus coverage incomplete)

Extraction and synthesis are kept separate because they fail differently:
extraction answers "what relevant text exists?" (never proposes values);
synthesis answers "what value does verified evidence support?" (cites only
pre-verified candidate IDs, never quotes/sources).
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from src.structured_output import generate_structured_json
from src.annexc_derivation import (
    FOUR_PRIORS, ALLOWED_TEMPO, EXPECTED_DEFENSIVE_CONTROLS,
)
from src.annexc_evidence import (
    build_prior_evidence_chunks, verify_candidate, deduplicate_candidates,
    CorpusScanCoverage,
)

MAX_CANDIDATES_PER_PRIOR_PER_CHUNK = 5
DEFAULT_EXTRACTION_RETRIES = 2


class IncompleteCorpusScan(Exception):
    """Raised internally when a chunk exhausts retries; the proposer converts
    this into BLOCKED records rather than propagating."""


_FIELD_PATH = {
    "capability_prior": "adversary.capability_prior",
    "tempo": "adversary.tempo",
    "defensive_posture": "defensive_posture",
    "geopolitical_trigger_prior": "geopolitical_trigger_prior",
}


# ---- extraction schema (all four priors, per chunk) ----

_QUOTE_ITEM = {
    "type": "object",
    "properties": {"quote": {"type": "string"}, "interpretation": {"type": "string"}},
    "required": ["quote", "interpretation"],
}
_POSTURE_ITEM = {
    "type": "object",
    "properties": {"subfield": {"type": "string", "enum": sorted(EXPECTED_DEFENSIVE_CONTROLS)},
                   "quote": {"type": "string"}, "interpretation": {"type": "string"}},
    "required": ["subfield", "quote", "interpretation"],
}
_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "capability_prior": {"type": "array", "items": _QUOTE_ITEM},
        "tempo": {"type": "array", "items": _QUOTE_ITEM},
        "defensive_posture": {"type": "array", "items": _POSTURE_ITEM},
        "geopolitical_trigger_prior": {"type": "array", "items": _QUOTE_ITEM},
        "truncated": {"type": "boolean"},
    },
    "required": ["capability_prior", "tempo", "defensive_posture",
                 "geopolitical_trigger_prior", "truncated"],
}

_EXTRACTION_SYSTEM = (
    "You are an evidence extractor, not an assessor.\n"
    "Extract only exact, contiguous quotations that appear verbatim in the chunk.\n"
    "Do not: propose prior values; paraphrase quotations; combine noncontiguous "
    "passages; use outside knowledge; infer that missing information means LOW, "
    "false, or zero.\n"
    "An empty evidence list is correct when the chunk contains no relevant evidence.\n"
    "Return relevant contradictory evidence as well as supporting evidence.\n"
    "Return all four top-level arrays even when empty. Return only the JSON object."
)

_PRIOR_DEFS = (
    "capability_prior: adversary sophistication/tooling/resourcing attributed to a "
    "class among [hacktivist, criminal, nation-state].\n"
    "tempo: adversary operational cadence/speed (maps to LOW/MEDIUM/HIGH).\n"
    "defensive_posture: which FRIENDLY controls are deployed — one of "
    f"{sorted(EXPECTED_DEFENSIVE_CONTROLS)} per quote (set subfield).\n"
    "geopolitical_trigger_prior: geopolitical conditions raising/lowering trigger likelihood."
)


def _extract_with_retries(chunk, *, llm, retries: int, timeout_seconds: int) -> dict:
    """One chunk extraction with bounded retries. Raises IncompleteCorpusScan
    if every attempt fails — the caller treats that as incomplete coverage,
    NOT as an empty (no-evidence) result."""
    prompt = (
        f"PRIOR DEFINITIONS:\n{_PRIOR_DEFS}\n\n"
        f"CHUNK ({chunk.chunk_id}, source {chunk.source_file}):\n"
        f"\"\"\"\n{chunk.text}\n\"\"\"\n\n"
        "Extract verbatim quotes from THIS chunk bearing on any prior. Set "
        "truncated=true only if the chunk clearly cut off mid-evidence."
    )
    last_err = None
    for _ in range(retries + 1):
        try:
            raw = generate_structured_json(
                llm=llm, schema=_EXTRACTION_SCHEMA, prompt=prompt,
                system_message=_EXTRACTION_SYSTEM, num_predict=4096,
                timeout_seconds=timeout_seconds)
            return json.loads(raw)
        except Exception as e:  # timeout, malformed JSON, incomplete response
            last_err = e
            continue
    raise IncompleteCorpusScan(f"{chunk.chunk_id}: {last_err}")


def _verify_chunk_extraction(extraction: dict, chunk) -> list:
    """Verify every extracted quote against this chunk's frozen text. Returns
    verified candidates only (bounded per prior, deduplicated per chunk)."""
    verified = []
    for prior in FOUR_PRIORS:
        items = extraction.get(prior, []) or []
        kept = 0
        for cand in items:
            if kept >= MAX_CANDIDATES_PER_PRIOR_PER_CHUNK:
                break
            vc = verify_candidate(candidate=cand, chunk=chunk, prior=prior)
            if vc is not None:
                verified.append(vc)
                kept += 1
    return verified


# ---- synthesis (per prior; cite candidate IDs only) ----

def _synthesis_value_schema(prior: str) -> dict:
    if prior == "capability_prior":
        return {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
    if prior == "tempo":
        return {"type": "string", "enum": sorted(ALLOWED_TEMPO)}
    if prior == "geopolitical_trigger_prior":
        return {"type": "number"}
    return {"type": "object"}


_SYNTH_SYSTEM = (
    "Assess only the requested prior.\n"
    "You may rely only on the VERIFIED_EVIDENCE candidates supplied.\n"
    "Citations must be expressed only as candidate_ids from that list.\n"
    "Do not create quotations, source names, or candidate IDs.\n"
    "Do not use outside knowledge. Do not apply a policy default yourself.\n"
    "If the evidence is missing, ambiguous, contradictory, or insufficient to "
    "support an allowed value, return supported=false and explain the gap.\n"
    "Return only the JSON object."
)


def _render_candidates(candidates: list) -> str:
    return "\n".join(
        f"[{c.candidate_id}] ({c.source_file})"
        + (f" [{c.subfield}]" if c.subfield else "")
        + f" \"{c.quote}\""
        for c in candidates
    )


def _synthesize_simple_prior(*, prior, candidates, llm, timeout_seconds):
    schema = {
        "type": "object",
        "properties": {
            "supported": {"type": "boolean"},
            "value": _synthesis_value_schema(prior),
            "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "reasoning": {"type": "string"},
            "candidate_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["supported", "confidence", "reasoning", "candidate_ids"],
    }
    prompt = (
        f"PRIOR: {prior}\nVERIFIED_EVIDENCE:\n{_render_candidates(candidates)}\n\n"
        "Return supported=true with value, confidence, reasoning, and the "
        "candidate_ids that support the ACTUAL estimate; else supported=false."
    )
    raw = generate_structured_json(
        llm=llm, schema=schema, prompt=prompt, system_message=_SYNTH_SYSTEM,
        num_predict=2048, timeout_seconds=timeout_seconds)
    return json.loads(raw)


def _synthesize_defensive_posture(*, candidates, llm, timeout_seconds):
    """Defensive posture is per-control: one MFA quote cannot support the whole
    object, and a control with no verified evidence must stay null (never
    coerced to false)."""
    control_schema = {
        "type": "object",
        "properties": {"value": {"type": ["boolean", "null"]},
                       "candidate_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["value", "candidate_ids"],
    }
    schema = {
        "type": "object",
        "properties": {
            "controls": {"type": "object",
                         "properties": {c: control_schema for c in sorted(EXPECTED_DEFENSIVE_CONTROLS)},
                         "required": sorted(EXPECTED_DEFENSIVE_CONTROLS)},
            "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "reasoning": {"type": "string"},
        },
        "required": ["controls", "confidence", "reasoning"],
    }
    prompt = (
        "PRIOR: defensive_posture (assess EACH control separately)\n"
        f"Controls: {sorted(EXPECTED_DEFENSIVE_CONTROLS)}\n"
        f"VERIFIED_EVIDENCE:\n{_render_candidates(candidates)}\n\n"
        "For each control set value=true/false ONLY if verified evidence supports "
        "it, citing candidate_ids; otherwise value=null with empty candidate_ids. "
        "Never treat absence of evidence as false."
    )
    raw = generate_structured_json(
        llm=llm, schema=schema, prompt=prompt, system_message=_SYNTH_SYSTEM,
        num_predict=2048, timeout_seconds=timeout_seconds)
    return json.loads(raw)


# ---- record assembly ----

def _evidence_records(candidate_ids, by_id):
    records = []
    for cid in candidate_ids:
        c = by_id.get(cid)
        if c is None:
            continue  # model cited an ID not in the verified set -> dropped
        records.append({
            "source_type": "CORPUS", "source_file": c.source_file,
            "source_sha256": c.source_sha256,
            "locator": {"chunk_id": c.chunk_id, "start_char": c.start_char,
                        "end_char": c.end_char},
            "quote": c.quote,
        })
    return records


def _assemble_simple_record(*, prior, synthesis, by_id):
    if not synthesis.get("supported"):
        return None
    ids = synthesis.get("candidate_ids", []) or []
    evidence = _evidence_records(ids, by_id)
    if not evidence:  # supported but cites nothing verifiable -> not supported
        return None
    return {
        "field": _FIELD_PATH[prior], "value": synthesis.get("value"),
        "status": "SUPPORTED", "source_mode": "CORPUS",
        "confidence": synthesis.get("confidence", "LOW"),
        "reasoning": synthesis.get("reasoning", ""), "evidence": evidence,
    }


def _assemble_posture_record(*, synthesis, by_id):
    """Return a posture record only if EVERY control has verified evidence;
    otherwise None (coverage incomplete -> no-evidence policy BLOCKS it). A
    null control is never coerced to false."""
    controls = synthesis.get("controls", {}) or {}
    value = {}
    evidence = []
    for control in sorted(EXPECTED_DEFENSIVE_CONTROLS):
        c = controls.get(control) or {}
        v = c.get("value")
        recs = _evidence_records(c.get("candidate_ids", []) or [], by_id)
        if v is None or not recs:
            return None  # incomplete control coverage -> not a full posture
        value[control] = bool(v)
        evidence.extend(recs)
    return {
        "field": "defensive_posture", "value": value,
        "status": "SUPPORTED", "source_mode": "CORPUS",
        "confidence": synthesis.get("confidence", "LOW"),
        "reasoning": synthesis.get("reasoning", ""), "evidence": evidence,
    }


def _blocked_incomplete_record(prior: str, coverage: CorpusScanCoverage) -> dict:
    return {
        "field": _FIELD_PATH[prior], "value": None, "status": "BLOCKED",
        "source_mode": "CORPUS", "confidence": "LOW",
        "reasoning": ("INCOMPLETE_CORPUS_SCAN — corpus coverage was incomplete "
                      f"({coverage.successful_chunks}/{coverage.expected_chunks} chunks; "
                      f"failed: {coverage.failed_chunks}). No no-evidence default may "
                      "run, as it would conceal an extraction/infrastructure failure."),
        "evidence": [{"source_type": "SCAN_DIAGNOSTIC", "coverage": coverage.as_dict()}],
    }


def _blocked_synthesis_record(prior: str) -> dict:
    return {
        "field": _FIELD_PATH[prior], "value": None, "status": "BLOCKED",
        "source_mode": "CORPUS", "confidence": "LOW",
        "reasoning": ("Verified evidence existed for this prior but synthesis could "
                      "not produce a supported estimate; blocked rather than defaulted."),
        "evidence": [],
    }


# ---- orchestration ----

def propose_priors_from_corpus(*, frozen_sources: Mapping, llm,
                               timeout_seconds: int = 600,
                               extraction_retries: int = DEFAULT_EXTRACTION_RETRIES) -> dict:
    """Full two-stage funnel. Returns {prior: record}. A prior may be:
      - a SUPPORTED corpus record (verified evidence synthesized),
      - omitted (complete scan, no/insufficient verified evidence -> caller's
        no-evidence policy applies), or
      - a BLOCKED record (INCOMPLETE_CORPUS_SCAN on coverage failure, or
        analytical block when evidence existed but synthesis couldn't assess).
    """
    chunks = build_prior_evidence_chunks(dict(frozen_sources))
    coverage = CorpusScanCoverage(expected_chunks=len(chunks))

    # PHASE A: extract + verify, tracking coverage explicitly.
    all_verified = []
    scan_failed = False
    for chunk in chunks:
        try:
            extraction = _extract_with_retries(
                chunk, llm=llm, retries=extraction_retries, timeout_seconds=timeout_seconds)
        except IncompleteCorpusScan:
            coverage.failed_chunks.append(chunk.chunk_id)
            scan_failed = True
            continue
        coverage.successful_chunks += 1
        all_verified.extend(_verify_chunk_extraction(extraction, chunk))

    # FAIL CLOSED: an incomplete scan blocks every prior. No no-evidence
    # default may run, because that would conceal the failure.
    if scan_failed or not coverage.complete:
        return {prior: _blocked_incomplete_record(prior, coverage) for prior in FOUR_PRIORS}

    all_verified = deduplicate_candidates(all_verified)
    by_id = {c.candidate_id: c for c in all_verified}

    def _for(prior):
        return [c for c in all_verified if c.prior == prior]

    # PHASE B: focused synthesis per prior. Omit a prior (-> no-evidence
    # policy) only on a COMPLETE scan with no supporting record.
    proposed = {}
    for prior in FOUR_PRIORS:
        candidates = _for(prior)
        if not candidates:
            continue  # complete scan, no relevant quotes -> policy applies
        try:
            if prior == "defensive_posture":
                synth = _synthesize_defensive_posture(
                    candidates=candidates, llm=llm, timeout_seconds=timeout_seconds)
                record = _assemble_posture_record(synthesis=synth, by_id=by_id)
            else:
                synth = _synthesize_simple_prior(
                    prior=prior, candidates=candidates, llm=llm, timeout_seconds=timeout_seconds)
                record = _assemble_simple_record(prior=prior, synthesis=synth, by_id=by_id)
        except Exception:
            record = _blocked_synthesis_record(prior)
        if record is not None:
            proposed[prior] = record
    return proposed
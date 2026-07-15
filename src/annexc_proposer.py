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
    """Raised internally when a chunk exhausts retries OR reports truncated
    output; the proposer converts this into BLOCKED records rather than
    propagating. A truncated response is NOT a successful chunk: relevant
    evidence may have existed and been cut off before it could be returned.
    Silently counting it as coverage would let a truncation conceal real
    evidence behind a no-evidence default for capability/geopolitical
    priors (tempo/posture already block regardless, but capability and
    geopolitical CAN default -- that is exactly the path a swallowed
    truncation would exploit)."""


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


def _extract_with_retries(chunk, *, llm, retries: int, timeout_seconds: int,
                          diag=None) -> dict:
    """One chunk extraction with bounded retries. Raises IncompleteCorpusScan
    if every attempt fails OR the model reports truncated output — the
    caller treats that as incomplete coverage, NOT as an empty (no-evidence)
    result. When diag is supplied, the raw response (or error) is recorded
    regardless of outcome."""
    prompt = (
        f"PRIOR DEFINITIONS:\n{_PRIOR_DEFS}\n\n"
        f"CHUNK ({chunk.chunk_id}, source {chunk.source_file}):\n"
        f"\"\"\"\n{chunk.text}\n\"\"\"\n\n"
        "Extract verbatim quotes from THIS chunk bearing on any prior. Set "
        "truncated=true only if the chunk clearly cut off mid-evidence."
    )
    last_err = None
    for _ in range(retries + 1):
        raw = None
        try:
            raw = generate_structured_json(
                llm=llm, schema=_EXTRACTION_SCHEMA, prompt=prompt,
                system_message=_EXTRACTION_SYSTEM, num_predict=4096,
                timeout_seconds=timeout_seconds)
            parsed = json.loads(raw)
            if parsed.get("truncated"):
                if diag is not None:
                    diag.record_extraction(chunk_id=chunk.chunk_id, request_prompt=prompt,
                                           raw_response=raw, parsed=parsed,
                                           error="MODEL_OUTPUT_TRUNCATED")
                    diag.record_truncated(chunk.chunk_id)
                # A truncated response is not a completed scan of this chunk.
                # Do not retry into a longer response silently -- treat this
                # attempt as failed coverage; caller marks the chunk incomplete.
                raise IncompleteCorpusScan(
                    f"{chunk.chunk_id}: MODEL_OUTPUT_TRUNCATED")
            if diag is not None:
                diag.record_extraction(chunk_id=chunk.chunk_id, request_prompt=prompt,
                                       raw_response=raw, parsed=parsed)
            return parsed
        except IncompleteCorpusScan:
            raise
        except Exception as e:  # timeout, malformed JSON, incomplete response
            last_err = e
            if diag is not None:
                diag.record_extraction(chunk_id=chunk.chunk_id, request_prompt=prompt,
                                       raw_response=raw, error=str(e))
            continue
    raise IncompleteCorpusScan(f"{chunk.chunk_id}: {last_err}")


def _verify_chunk_extraction(extraction: dict, chunk, diag=None) -> list:
    """Verify every extracted quote against this chunk's frozen text. Returns
    verified candidates only (bounded per prior, deduplicated per chunk).
    Rejections are recorded with a reason code when diag is supplied."""
    from src.annexc_evidence import (
        REJECT_EMPTY_QUOTE, REJECT_QUOTE_NOT_FOUND, quote_rejection_diagnostic,
    )
    verified = []
    for prior in FOUR_PRIORS:
        items = extraction.get(prior, []) or []
        kept = 0
        for cand in items:
            if kept >= MAX_CANDIDATES_PER_PRIOR_PER_CHUNK:
                if diag is not None:
                    diag.record_rejected_candidate(
                        reason="CANDIDATE_LIMIT_EXCEEDED", prior=prior,
                        diagnostic={"chunk_id": chunk.chunk_id})
                break
            vc = verify_candidate(candidate=cand, chunk=chunk, prior=prior)
            if vc is not None:
                verified.append(vc)
                kept += 1
                if diag is not None:
                    diag.record_accepted_candidate()
            elif diag is not None:
                quote = cand.get("quote", "")
                reason = REJECT_EMPTY_QUOTE if not quote.strip() else REJECT_QUOTE_NOT_FOUND
                diag.record_rejected_candidate(
                    reason=reason, prior=prior,
                    diagnostic=quote_rejection_diagnostic(
                        quote=quote, chunk=chunk, source_file=chunk.source_file))
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


def _probability_vector_error(value) -> str | None:
    """Deterministic check: exactly 3 finite numbers in [0,1] summing to
    1.00 (small float tolerance). Returns an error description or None.
    NEVER silently renormalizes -- an invalid vector is a defect to report
    back to the model (bounded retry) or block, not to code-correct."""
    if not isinstance(value, list) or len(value) != 3:
        return f"value must be exactly 3 numbers, got {value!r}"
    try:
        nums = [float(v) for v in value]
    except (TypeError, ValueError):
        return f"value must be numeric, got {value!r}"
    if any(n < 0 or n > 1 for n in nums):
        return f"each value must be in [0,1], got {nums}"
    total = sum(nums)
    if abs(total - 1.0) > 1e-6:
        return f"your probability vector totaled {total:.4f}, not 1.00"
    return None


def _synthesize_simple_prior(*, prior, candidates, llm, timeout_seconds, diag=None):
    """One (or for capability_prior, up to two) synthesis calls. capability_
    prior gets a bounded repair retry on an invalid probability vector: the
    SECOND attempt receives only the mathematical error, may not change
    citations or introduce new evidence, and a still-invalid vector BLOCKS
    rather than being silently normalized in code."""
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
    if prior == "capability_prior":
        prompt += ("\nvalue is a 3-element probability vector in increments of "
                   "0.05 that must total exactly 1.00. Check the sum before returning.")

    raw = generate_structured_json(
        llm=llm, schema=schema, prompt=prompt, system_message=_SYNTH_SYSTEM,
        num_predict=2048, timeout_seconds=timeout_seconds)
    parsed = json.loads(raw)
    if diag is not None:
        diag.record_synthesis(prior=prior, request_prompt=prompt, raw_response=raw,
                              parsed=parsed,
                              offered_candidate_ids=[c.candidate_id for c in candidates])

    if prior != "capability_prior" or not parsed.get("supported"):
        return parsed

    vec_error = _probability_vector_error(parsed.get("value"))
    if vec_error is None:
        return parsed

    # Bounded repair retry: ONE additional attempt, math-only feedback, same
    # evidence. No code-side normalization of the model's estimate.
    repair_prompt = (
        f"PRIOR: {prior}\nVERIFIED_EVIDENCE:\n{_render_candidates(candidates)}\n\n"
        f"Your probability vector was invalid: {vec_error}\n"
        "Return exactly three values from 0.00 to 1.00 whose sum is 1.00. "
        "Do not change citations or introduce new evidence."
    )
    raw2 = generate_structured_json(
        llm=llm, schema=schema, prompt=repair_prompt, system_message=_SYNTH_SYSTEM,
        num_predict=2048, timeout_seconds=timeout_seconds)
    parsed2 = json.loads(raw2)
    if diag is not None:
        diag.record_synthesis(prior=f"{prior}_repair_attempt", request_prompt=repair_prompt,
                              raw_response=raw2, parsed=parsed2,
                              offered_candidate_ids=[c.candidate_id for c in candidates])

    if parsed2.get("supported") and _probability_vector_error(parsed2.get("value")) is None:
        return parsed2

    # Still invalid after the bounded retry -> BLOCK, do not guess.
    return {"supported": False, "confidence": "LOW",
           "reasoning": f"Probability vector remained invalid after repair attempt: {vec_error}",
           "candidate_ids": []}


def _synthesize_defensive_posture(*, candidates, llm, timeout_seconds, diag=None):
    """Defensive posture is per-control: one MFA quote cannot support the whole
    object, and a control with no verified evidence must stay UNRESOLVED
    (explicit resolved=false), never coerced to false. Asking for an explicit
    resolved flag per control (rather than inferring it from value is None)
    prevents null/omitted/"unknown" from silently becoming a plain boolean
    False when the record is compiled."""
    control_schema = {
        "type": "object",
        "properties": {
            "resolved": {"type": "boolean"},
            "value": {"type": ["boolean", "null"]},
            "candidate_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["resolved", "value", "candidate_ids"],
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
        "For each control: set resolved=true with value=true/false and "
        "citing candidate_ids ONLY if verified evidence supports a specific "
        "determination; otherwise resolved=false, value=null, "
        "candidate_ids=[]. Never treat absence of evidence as false."
    )
    raw = generate_structured_json(
        llm=llm, schema=schema, prompt=prompt, system_message=_SYNTH_SYSTEM,
        num_predict=2048, timeout_seconds=timeout_seconds)
    parsed = json.loads(raw)
    if diag is not None:
        diag.record_synthesis(prior="defensive_posture", request_prompt=prompt,
                              raw_response=raw, parsed=parsed,
                              offered_candidate_ids=[c.candidate_id for c in candidates])
    return parsed


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
    if prior == "capability_prior":
        # Defense in depth: even if an invalid vector somehow reaches here,
        # never assemble it as a SUPPORTED record.
        if _probability_vector_error(synthesis.get("value")) is not None:
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


def _assemble_posture_record(*, synthesis, by_id, diag=None):
    """Return a posture record only if EVERY control is explicitly resolved
    with verified evidence; otherwise None (incomplete -> no-evidence policy
    BLOCKS it later). An unresolved control is never coerced to false."""
    controls = synthesis.get("controls", {}) or {}
    value = {}
    evidence = []
    for control in sorted(EXPECTED_DEFENSIVE_CONTROLS):
        c = controls.get(control)
        if c is None:
            if diag is not None:
                diag.record_rejected_candidate(
                    reason="INVALID_CONTROL", prior="defensive_posture",
                    diagnostic={"control": control, "detail": "missing from synthesis response"})
            return None
        resolved = bool(c.get("resolved"))
        v = c.get("value")
        recs = _evidence_records(c.get("candidate_ids", []) or [], by_id)
        if not resolved or v is None or not recs:
            return None  # unresolved control -> not a full posture
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
                               extraction_retries: int = DEFAULT_EXTRACTION_RETRIES,
                               diagnostics_out_dir: str | None = None) -> dict:
    """Full two-stage funnel. Returns {prior: record}. A prior may be:
      - a SUPPORTED corpus record (verified evidence synthesized),
      - omitted (complete scan, no/insufficient verified evidence -> caller's
        no-evidence policy applies), or
      - a BLOCKED record (INCOMPLETE_CORPUS_SCAN on coverage failure, or
        analytical block when evidence existed but synthesis couldn't assess).

    diagnostics_out_dir: when supplied, writes the full instrumented-run
    artifact set (chunk manifest, raw/parsed extraction + synthesis
    responses, rejected-candidate reasons, run summary) under
    <diagnostics_out_dir>/annexc_proposer/. Run-local only; never written to
    a shared/general log, since the corpus may be sensitive. This does not
    affect the derivation outcome in any way -- pure observability.
    """
    from src.annexc_diagnostics import ProposerDiagnostics
    from src.annexc_evidence import REJECT_DUPLICATE_CANDIDATE

    diag = ProposerDiagnostics(model=str(llm)) if diagnostics_out_dir else None

    chunks = build_prior_evidence_chunks(dict(frozen_sources))
    coverage = CorpusScanCoverage(expected_chunks=len(chunks))

    # PHASE A: extract + verify, tracking coverage explicitly.
    all_verified = []
    scan_failed = False
    for chunk in chunks:
        if diag is not None:
            diag.record_chunk(chunk)
        try:
            extraction = _extract_with_retries(
                chunk, llm=llm, retries=extraction_retries,
                timeout_seconds=timeout_seconds, diag=diag)
        except IncompleteCorpusScan as e:
            coverage.failed_chunks.append(chunk.chunk_id)
            scan_failed = True
            if diag is not None:
                diag.record_failed_chunk(chunk.chunk_id, str(e))
            continue
        coverage.successful_chunks += 1
        all_verified.extend(_verify_chunk_extraction(extraction, chunk, diag=diag))

    # FAIL CLOSED: an incomplete scan blocks every prior. No no-evidence
    # default may run, because that would conceal the failure.
    if scan_failed or not coverage.complete:
        records = {prior: _blocked_incomplete_record(prior, coverage) for prior in FOUR_PRIORS}
        if diag is not None:
            diag.write(diagnostics_out_dir, resolved_priors=[],
                      blocked_priors=list(records.keys()))
        return records

    before_dedup = len(all_verified)
    all_verified = deduplicate_candidates(all_verified)
    if diag is not None and len(all_verified) < before_dedup:
        diag.record_rejected_candidate(
            reason=REJECT_DUPLICATE_CANDIDATE, prior="*",
            diagnostic={"removed_count": before_dedup - len(all_verified)})
        # Deduplicated candidates were already counted as accepted; correct.
        diag.accepted_candidate_count -= (before_dedup - len(all_verified))

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
                    candidates=candidates, llm=llm, timeout_seconds=timeout_seconds, diag=diag)
                record = _assemble_posture_record(synthesis=synth, by_id=by_id, diag=diag)
            else:
                synth = _synthesize_simple_prior(
                    prior=prior, candidates=candidates, llm=llm,
                    timeout_seconds=timeout_seconds, diag=diag)
                record = _assemble_simple_record(prior=prior, synthesis=synth, by_id=by_id)
        except Exception:
            record = _blocked_synthesis_record(prior)
        if record is not None:
            proposed[prior] = record

    if diag is not None:
        resolved = [p for p, r in proposed.items() if r.get("status") == "SUPPORTED"]
        blocked = [p for p, r in proposed.items() if r.get("status") == "BLOCKED"]
        diag.write(diagnostics_out_dir, resolved_priors=resolved, blocked_priors=blocked)

    return proposed
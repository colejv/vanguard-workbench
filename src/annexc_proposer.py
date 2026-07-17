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

import os
import time
from datetime import datetime, timezone

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
    "Return all four top-level arrays even when empty.\n"
    "Every array item MUST be a JSON object, never a bare string.\n"
    "For capability_prior, tempo, and geopolitical_trigger_prior, every item "
    "must contain string fields `quote` and `interpretation`.\n"
    "For defensive_posture, every item must contain string fields `subfield`, "
    "`quote`, and `interpretation`.\n"
    "Return only the JSON object."
)

_PRIOR_DEFS = (
    "capability_prior: adversary sophistication/tooling/resourcing attributed to a "
    "class among [hacktivist, criminal, nation-state].\n"
    "tempo: adversary operational cadence/speed (maps to LOW/MEDIUM/HIGH).\n"
    "defensive_posture: which FRIENDLY controls are deployed — one of "
    f"{sorted(EXPECTED_DEFENSIVE_CONTROLS)} per quote (set subfield).\n"
    "geopolitical_trigger_prior: geopolitical conditions raising/lowering trigger likelihood."
)

def _normalize_truncated_flag(
    extraction: dict,
) -> dict:
    """
    Normalize only unambiguous string representations of the JSON boolean.

    Persisted and validated output remains a real bool. Missing values,
    nulls, numbers, and arbitrary strings still fail closed.
    """

    if not isinstance(extraction, dict):
        raise ValueError(
            "top-level extraction must be a JSON object"
        )

    value = extraction.get("truncated")

    if isinstance(value, bool):
        return extraction

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized == "true":
            extraction["truncated"] = True
            return extraction

        if normalized == "false":
            extraction["truncated"] = False
            return extraction

    raise ValueError(
        "`truncated` must be the JSON boolean true or false"
    )

def _validate_extraction_shape(
    extraction,
) -> None:
    """
    Validate the model's extraction response before quote verification.

    A schema-invalid response is an extraction failure, not an empty-evidence
    result. The caller retries it and ultimately marks corpus coverage
    incomplete if the model cannot repair the response.
    """

    if not isinstance(extraction, Mapping):
        raise ValueError(
            "top-level extraction must be a JSON object"
        )

    truncated = extraction.get("truncated")

    if not isinstance(truncated, bool):
        raise ValueError(
            "`truncated` must be a boolean"
        )

    for prior in FOUR_PRIORS:
        if prior not in extraction:
            raise ValueError(
                f"missing required extraction array `{prior}`"
            )

        items = extraction[prior]

        if not isinstance(items, list):
            raise ValueError(
                f"`{prior}` must be an array"
            )

        for index, candidate in enumerate(items):
            candidate_path = (
                f"{prior}[{index}]"
            )

            if not isinstance(candidate, Mapping):
                raise ValueError(
                    f"`{candidate_path}` must be an object, "
                    f"not {type(candidate).__name__}"
                )

            quote = candidate.get("quote")
            interpretation = candidate.get(
                "interpretation"
            )

            if not isinstance(quote, str):
                raise ValueError(
                    f"`{candidate_path}.quote` must be a string"
                )

            if not isinstance(
                interpretation,
                str,
            ):
                raise ValueError(
                    f"`{candidate_path}.interpretation` "
                    "must be a string"
                )

            if prior == "defensive_posture":
                subfield = candidate.get(
                    "subfield"
                )

                if not isinstance(subfield, str):
                    raise ValueError(
                        f"`{candidate_path}.subfield` "
                        "must be a string"
                    )

                if (
                    subfield
                    not in EXPECTED_DEFENSIVE_CONTROLS
                ):
                    raise ValueError(
                        f"`{candidate_path}.subfield` must be one of "
                        f"{sorted(EXPECTED_DEFENSIVE_CONTROLS)}"
                    )

def _extract_with_retries(
    chunk,
    *,
    llm,
    retries: int,
    timeout_seconds: int,
    diag=None,
) -> dict:
    """
    Extract one chunk with bounded retries.

    Malformed JSON, schema-invalid candidate shapes, timeouts, and other
    response failures are retried. Exhaustion becomes an incomplete corpus
    scan, never an empty-evidence result.
    """

    base_prompt = (
        f"PRIOR DEFINITIONS:\n{_PRIOR_DEFS}\n\n"
        f"CHUNK ({chunk.chunk_id}, source {chunk.source_file}):\n"
        f"\"\"\"\n{chunk.text}\n\"\"\"\n\n"
        "Extract verbatim quotes from THIS chunk bearing on any prior. "
        "Set truncated=true only if the chunk clearly cut off mid-evidence."
    )

    last_error: Exception | None = None
    repair_feedback: str | None = None

    for attempt in range(retries + 1):
        raw = None
        parsed = None

        request_prompt = base_prompt

        if repair_feedback:
            request_prompt += (
                "\n\nPREVIOUS RESPONSE REJECTED:\n"
                f"{repair_feedback}\n\n"
                "Repair the response. Every prior field must be an array of "
                "objects. Do not return bare strings as array items. "
                "`truncated` must be the unquoted JSON boolean true or false. "
                "Do not return \"true\", \"false\", null, 0, or 1. "
                "If the previous response was truncated, return fewer candidates: "
                "keep only the strongest 2 candidates per prior, keep each quote "
                "short and contiguous, and keep each interpretation to one sentence."
            )

        try:
            raw = generate_structured_json(
                llm=llm,
                schema=_EXTRACTION_SCHEMA,
                prompt=request_prompt,
                system_message=_EXTRACTION_SYSTEM,
                num_predict=4096,
                timeout_seconds=timeout_seconds,
            )

            parsed = json.loads(raw)

            parsed = _normalize_truncated_flag(
                parsed
            )

            _validate_extraction_shape(
                parsed
            )

            if parsed["truncated"]:
                if diag is not None:
                    diag.record_extraction(
                        chunk_id=chunk.chunk_id,
                        request_prompt=request_prompt,
                        raw_response=raw,
                        parsed=parsed,
                        error="MODEL_OUTPUT_TRUNCATED",
                    )
                    diag.record_truncated(
                        chunk.chunk_id
                    )

                raise ValueError(
                    "MODEL_OUTPUT_TRUNCATED: retry with fewer "
                    "evidence candidates and shorter interpretations"
                )

            if diag is not None:
                diag.record_extraction(
                    chunk_id=chunk.chunk_id,
                    request_prompt=request_prompt,
                    raw_response=raw,
                    parsed=parsed,
                )

            return parsed

        except IncompleteCorpusScan:
            raise

        except Exception as exc:
            last_error = exc
            repair_feedback = (
                f"{type(exc).__name__}: {exc}"
            )

            if diag is not None:
                diagnostic_kwargs = {
                    "chunk_id": chunk.chunk_id,
                    "request_prompt": (
                        request_prompt
                    ),
                    "raw_response": raw,
                    "error": (
                        "INVALID_EXTRACTION_RESPONSE: "
                        f"{repair_feedback}"
                    ),
                }

                if isinstance(parsed, Mapping):
                    diagnostic_kwargs[
                        "parsed"
                    ] = parsed

                diag.record_extraction(
                    **diagnostic_kwargs
                )

            if attempt < retries:
                continue

    raise IncompleteCorpusScan(
        f"{chunk.chunk_id}: extraction failed after "
        f"{retries + 1} attempt(s): {last_error}"
    )


def _verify_chunk_extraction(
    extraction: dict,
    chunk,
    diag=None,
) -> list:
    """
    Verify every extracted quote against the frozen chunk.

    Invalid candidate shapes are rejected deterministically instead of
    raising AttributeError. Normally they are intercepted earlier by
    _validate_extraction_shape(); this remains defense in depth.
    """

    from src.annexc_evidence import (
        REJECT_EMPTY_QUOTE,
        REJECT_QUOTE_NOT_FOUND,
        quote_rejection_diagnostic,
    )

    verified = []

    if not isinstance(extraction, Mapping):
        return verified

    for prior in FOUR_PRIORS:
        items = extraction.get(
            prior,
            [],
        ) or []

        if not isinstance(items, list):
            if diag is not None:
                diag.record_rejected_candidate(
                    reason=(
                        "INVALID_CANDIDATE_COLLECTION"
                    ),
                    prior=prior,
                    diagnostic={
                        "chunk_id": chunk.chunk_id,
                        "actual_type": (
                            type(items).__name__
                        ),
                    },
                )

            continue

        kept = 0

        for index, candidate in enumerate(items):
            if (
                kept
                >= MAX_CANDIDATES_PER_PRIOR_PER_CHUNK
            ):
                if diag is not None:
                    diag.record_rejected_candidate(
                        reason=(
                            "CANDIDATE_LIMIT_EXCEEDED"
                        ),
                        prior=prior,
                        diagnostic={
                            "chunk_id": (
                                chunk.chunk_id
                            )
                        },
                    )

                break

            if not isinstance(candidate, Mapping):
                if diag is not None:
                    diag.record_rejected_candidate(
                        reason=(
                            "INVALID_CANDIDATE_SHAPE"
                        ),
                        prior=prior,
                        diagnostic={
                            "chunk_id": (
                                chunk.chunk_id
                            ),
                            "candidate_index": index,
                            "actual_type": (
                                type(candidate).__name__
                            ),
                        },
                    )

                continue

            verified_candidate = verify_candidate(
                candidate=dict(candidate),
                chunk=chunk,
                prior=prior,
            )

            if verified_candidate is not None:
                verified.append(
                    verified_candidate
                )
                kept += 1

                if diag is not None:
                    diag.record_accepted_candidate()

                continue

            if diag is None:
                continue

            quote = candidate.get(
                "quote",
                "",
            )

            if not isinstance(quote, str):
                quote = ""

            reason = (
                REJECT_EMPTY_QUOTE
                if not quote.strip()
                else REJECT_QUOTE_NOT_FOUND
            )

            diag.record_rejected_candidate(
                reason=reason,
                prior=prior,
                diagnostic=(
                    quote_rejection_diagnostic(
                        quote=quote,
                        chunk=chunk,
                        source_file=(
                            chunk.source_file
                        ),
                    )
                ),
            )

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

def _write_live_progress(
    *,
    out_dir: str | None,
    payload: dict,
) -> None:
    """Atomically write the current Annex C proposer position."""

    if not out_dir:
        return

    progress_dir = os.path.join(
        out_dir,
        "annexc_proposer",
    )
    os.makedirs(
        progress_dir,
        exist_ok=True,
    )

    progress_path = os.path.join(
        progress_dir,
        "progress.json",
    )
    temporary_path = (
        progress_path
        + ".tmp"
    )

    document = {
        "updated_at": datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        **payload,
    }

    with open(
        temporary_path,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            document,
            handle,
            indent=2,
        )
        handle.flush()
        os.fsync(
            handle.fileno()
        )

    os.replace(
        temporary_path,
        progress_path,
    )

def propose_priors_from_corpus(
    *,
    frozen_sources: Mapping,
    llm,
    timeout_seconds: int = 180,
    extraction_retries: int = DEFAULT_EXTRACTION_RETRIES,
    diagnostics_out_dir: str | None = None,
) -> dict:
    """
    Run the two-stage Annex C evidence funnel.

    Every chunk emits visible console progress and updates
    annexc_proposer/progress.json. Each model call has a 180-second default
    whole-call deadline.
    """

    from src.annexc_diagnostics import (
        ProposerDiagnostics,
    )
    from src.annexc_evidence import (
        REJECT_DUPLICATE_CANDIDATE,
    )

    diagnostics = (
        ProposerDiagnostics(
            model=str(llm)
        )
        if diagnostics_out_dir
        else None
    )

    chunks = build_prior_evidence_chunks(
        dict(frozen_sources)
    )
    total_chunks = len(chunks)

    coverage = CorpusScanCoverage(
        expected_chunks=total_chunks
    )

    print(
        "[Annex C] Starting corpus evidence scan: "
        f"{total_chunks} chunks, "
        f"{timeout_seconds}s deadline per model call, "
        f"{extraction_retries + 1} maximum attempts per chunk.",
        flush=True,
    )

    _write_live_progress(
        out_dir=diagnostics_out_dir,
        payload={
            "phase": "extraction",
            "status": "STARTING",
            "expected_chunks": total_chunks,
            "successful_chunks": 0,
            "failed_chunks": [],
            "current_chunk_index": 0,
            "current_chunk_id": None,
        },
    )

    all_verified = []
    scan_failed = False

    for chunk_index, chunk in enumerate(
        chunks,
        start=1,
    ):
        if diagnostics is not None:
            diagnostics.record_chunk(
                chunk
            )

        print(
            "[Annex C] "
            f"Chunk {chunk_index}/{total_chunks} "
            f"START {chunk.chunk_id} "
            f"({len(chunk.text):,} chars)",
            flush=True,
        )

        _write_live_progress(
            out_dir=diagnostics_out_dir,
            payload={
                "phase": "extraction",
                "status": "RUNNING",
                "expected_chunks": total_chunks,
                "successful_chunks": (
                    coverage.successful_chunks
                ),
                "failed_chunks": list(
                    coverage.failed_chunks
                ),
                "current_chunk_index": (
                    chunk_index
                ),
                "current_chunk_id": (
                    chunk.chunk_id
                ),
                "current_source_file": (
                    chunk.source_file
                ),
            },
        )

        started_at = time.monotonic()

        try:
            extraction = _extract_with_retries(
                chunk,
                llm=llm,
                retries=extraction_retries,
                timeout_seconds=timeout_seconds,
                diag=diagnostics,
            )

        except IncompleteCorpusScan as exc:
            elapsed = (
                time.monotonic()
                - started_at
            )

            coverage.failed_chunks.append(
                chunk.chunk_id
            )
            scan_failed = True

            if diagnostics is not None:
                diagnostics.record_failed_chunk(
                    chunk.chunk_id,
                    str(exc),
                )

            print(
                "[Annex C] "
                f"Chunk {chunk_index}/{total_chunks} "
                f"FAILED after {elapsed:.1f}s: {exc}",
                flush=True,
            )

            _write_live_progress(
                out_dir=diagnostics_out_dir,
                payload={
                    "phase": "extraction",
                    "status": "CHUNK_FAILED",
                    "expected_chunks": (
                        total_chunks
                    ),
                    "successful_chunks": (
                        coverage.successful_chunks
                    ),
                    "failed_chunks": list(
                        coverage.failed_chunks
                    ),
                    "current_chunk_index": (
                        chunk_index
                    ),
                    "current_chunk_id": (
                        chunk.chunk_id
                    ),
                    "last_error": str(exc),
                },
            )

            continue

        verified = _verify_chunk_extraction(
            extraction,
            chunk,
            diag=diagnostics,
        )

        all_verified.extend(
            verified
        )
        coverage.successful_chunks += 1

        elapsed = (
            time.monotonic()
            - started_at
        )

        print(
            "[Annex C] "
            f"Chunk {chunk_index}/{total_chunks} "
            f"PASS in {elapsed:.1f}s; "
            f"{len(verified)} verified candidate(s).",
            flush=True,
        )

        _write_live_progress(
            out_dir=diagnostics_out_dir,
            payload={
                "phase": "extraction",
                "status": "CHUNK_COMPLETE",
                "expected_chunks": total_chunks,
                "successful_chunks": (
                    coverage.successful_chunks
                ),
                "failed_chunks": list(
                    coverage.failed_chunks
                ),
                "current_chunk_index": (
                    chunk_index
                ),
                "current_chunk_id": (
                    chunk.chunk_id
                ),
                "verified_candidates_so_far": (
                    len(all_verified)
                ),
            },
        )

    if (
        scan_failed
        or not coverage.complete
    ):
        records = {
            prior: _blocked_incomplete_record(
                prior,
                coverage,
            )
            for prior in FOUR_PRIORS
        }

        print(
            "[Annex C] Extraction scan INCOMPLETE: "
            f"{coverage.successful_chunks}/{total_chunks} passed; "
            f"{len(coverage.failed_chunks)} failed.",
            flush=True,
        )

        _write_live_progress(
            out_dir=diagnostics_out_dir,
            payload={
                "phase": "complete",
                "status": "INCOMPLETE",
                **coverage.as_dict(),
            },
        )

        if diagnostics is not None:
            diagnostics.write(
                diagnostics_out_dir,
                resolved_priors=[],
                blocked_priors=list(
                    records.keys()
                ),
            )

        return records

    before_deduplication = len(
        all_verified
    )
    all_verified = deduplicate_candidates(
        all_verified
    )

    removed_duplicates = (
        before_deduplication
        - len(all_verified)
    )

    if (
        diagnostics is not None
        and removed_duplicates > 0
    ):
        diagnostics.record_rejected_candidate(
            reason=(
                REJECT_DUPLICATE_CANDIDATE
            ),
            prior="*",
            diagnostic={
                "removed_count": (
                    removed_duplicates
                )
            },
        )
        diagnostics.accepted_candidate_count -= (
            removed_duplicates
        )

    print(
        "[Annex C] Extraction scan COMPLETE: "
        f"{coverage.successful_chunks}/{total_chunks} chunks; "
        f"{len(all_verified)} unique verified candidate(s).",
        flush=True,
    )

    by_id = {
        candidate.candidate_id: candidate
        for candidate in all_verified
    }

    def candidates_for(
        prior: str,
    ) -> list:
        return [
            candidate
            for candidate in all_verified
            if candidate.prior == prior
        ]

    proposed = {}

    for prior_index, prior in enumerate(
        FOUR_PRIORS,
        start=1,
    ):
        candidates = candidates_for(
            prior
        )

        if not candidates:
            print(
                "[Annex C] "
                f"Synthesis {prior_index}/4 SKIP {prior}: "
                "no verified candidates; policy will apply.",
                flush=True,
            )
            continue

        print(
            "[Annex C] "
            f"Synthesis {prior_index}/4 START {prior}: "
            f"{len(candidates)} candidate(s).",
            flush=True,
        )

        _write_live_progress(
            out_dir=diagnostics_out_dir,
            payload={
                "phase": "synthesis",
                "status": "RUNNING",
                "prior_index": prior_index,
                "prior": prior,
                "candidate_count": (
                    len(candidates)
                ),
                **coverage.as_dict(),
            },
        )

        started_at = time.monotonic()

        try:
            if prior == "defensive_posture":
                synthesis = (
                    _synthesize_defensive_posture(
                        candidates=candidates,
                        llm=llm,
                        timeout_seconds=(
                            timeout_seconds
                        ),
                        diag=diagnostics,
                    )
                )

                record = _assemble_posture_record(
                    synthesis=synthesis,
                    by_id=by_id,
                    diag=diagnostics,
                )

            else:
                synthesis = (
                    _synthesize_simple_prior(
                        prior=prior,
                        candidates=candidates,
                        llm=llm,
                        timeout_seconds=(
                            timeout_seconds
                        ),
                        diag=diagnostics,
                    )
                )

                record = _assemble_simple_record(
                    prior=prior,
                    synthesis=synthesis,
                    by_id=by_id,
                )

        except Exception as exc:
            record = _blocked_synthesis_record(
                prior
            )

            print(
                "[Annex C] "
                f"Synthesis {prior} FAILED: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        if record is not None:
            proposed[prior] = record

        elapsed = (
            time.monotonic()
            - started_at
        )

        result_status = (
            record.get("status")
            if record is not None
            else "NO_SUPPORTED_RECORD"
        )

        print(
            "[Annex C] "
            f"Synthesis {prior_index}/4 END {prior} "
            f"in {elapsed:.1f}s: {result_status}.",
            flush=True,
        )

    if diagnostics is not None:
        resolved = [
            prior
            for prior, record in proposed.items()
            if record.get("status")
            == "SUPPORTED"
        ]
        blocked = [
            prior
            for prior, record in proposed.items()
            if record.get("status")
            == "BLOCKED"
        ]

        diagnostics.write(
            diagnostics_out_dir,
            resolved_priors=resolved,
            blocked_priors=blocked,
        )

    _write_live_progress(
        out_dir=diagnostics_out_dir,
        payload={
            "phase": "complete",
            "status": "COMPLETE",
            "resolved_priors": [
                prior
                for prior, record
                in proposed.items()
                if record.get("status")
                == "SUPPORTED"
            ],
            "blocked_priors": [
                prior
                for prior, record
                in proposed.items()
                if record.get("status")
                == "BLOCKED"
            ],
            **coverage.as_dict(),
        },
    )

    print(
        "[Annex C] Prior proposal complete.",
        flush=True,
    )

    return proposed
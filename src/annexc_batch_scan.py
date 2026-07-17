"""
Fast, resumable Annex C corpus evidence extraction.

The original proposer made one sequential LLM call per evidence chunk.
This module:

* packs chunks into bounded extraction batches;
* checkpoints each successful batch immediately;
* reloads valid checkpoints on resume;
* recursively splits only batches that fail;
* verifies every proposed quote against its original frozen chunk;
* preserves fail-closed corpus coverage semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.annexc_derivation import FOUR_PRIORS
from src.annexc_evidence import (
    CorpusScanCoverage,
    EvidenceChunk,
    REJECT_EMPTY_QUOTE,
    REJECT_QUOTE_NOT_FOUND,
    build_prior_evidence_chunks,
    quote_rejection_diagnostic,
    verify_candidate,
)
from src.bbn_validation import EXPECTED_DEFENSIVE_CONTROLS
from src.structured_output import generate_structured_json


CHECKPOINT_VERSION = "annexc-batch-v1"

DEFAULT_MAX_BATCH_CHARS = 40_000
DEFAULT_MAX_BATCH_CHUNKS = 8
MAX_CANDIDATES_PER_PRIOR_PER_BATCH = 8
MAX_CANDIDATES_PER_PRIOR_PER_CHUNK = 2


_EXTRACTION_SYSTEM = (
    "You are an evidence extractor, not an assessor.\n"
    "Extract only exact, contiguous quotations copied verbatim from the "
    "provided chunks.\n"
    "Every candidate must identify the exact CHUNK_REF containing its quote.\n"
    "Do not paraphrase, combine passages, infer missing facts, propose prior "
    "values, or use outside knowledge.\n"
    "Return all four top-level arrays, even when empty.\n"
    "Return at most two strong candidates per prior from any one chunk and "
    "at most eight candidates per prior for the complete batch.\n"
    "Keep interpretations to one short sentence.\n"
    "Return only the JSON object."
)

_PRIOR_DEFINITIONS = (
    "capability_prior: adversary sophistication, tooling, access, resourcing, "
    "or organizational capability relevant to classification among "
    "hacktivist, criminal, and nation-state.\n"
    "tempo: adversary operational cadence or speed, eventually mapped to "
    "LOW, MEDIUM, or HIGH.\n"
    "defensive_posture: evidence that a FRIENDLY defensive control is "
    "deployed or absent. Valid controls are "
    f"{sorted(EXPECTED_DEFENSIVE_CONTROLS)}.\n"
    "geopolitical_trigger_prior: geopolitical conditions that raise or lower "
    "the likelihood of hostile activity."
)


def build_extraction_batches(
    chunks: list[EvidenceChunk],
    *,
    max_batch_chars: int = DEFAULT_MAX_BATCH_CHARS,
    max_batch_chunks: int = DEFAULT_MAX_BATCH_CHUNKS,
) -> list[list[EvidenceChunk]]:
    """Partition chunks deterministically into bounded sequential batches."""

    if max_batch_chars <= 0:
        raise ValueError(
            "max_batch_chars must be greater than zero"
        )

    if max_batch_chunks <= 0:
        raise ValueError(
            "max_batch_chunks must be greater than zero"
        )

    batches: list[list[EvidenceChunk]] = []
    current: list[EvidenceChunk] = []
    current_chars = 0

    for chunk in chunks:
        chunk_chars = len(chunk.text)

        would_exceed_chars = (
            current
            and current_chars + chunk_chars
            > max_batch_chars
        )
        would_exceed_count = (
            current
            and len(current) >= max_batch_chunks
        )

        if would_exceed_chars or would_exceed_count:
            batches.append(current)
            current = []
            current_chars = 0

        current.append(chunk)
        current_chars += chunk_chars

    if current:
        batches.append(current)

    return batches


def _batch_id(
    chunks: list[EvidenceChunk],
) -> str:
    digest = hashlib.sha256()

    for chunk in chunks:
        digest.update(
            chunk.chunk_id.encode("utf-8")
        )
        digest.update(b"\x00")
        digest.update(
            chunk.source_sha256.encode("utf-8")
        )
        digest.update(b"\x00")

    return "batch_" + digest.hexdigest()[:16]


def _chunk_refs(
    chunks: list[EvidenceChunk],
) -> dict[str, EvidenceChunk]:
    return {
        f"C{index:02d}": chunk
        for index, chunk in enumerate(
            chunks,
            start=1,
        )
    }


def _checkpoint_identity(
    chunks: list[EvidenceChunk],
) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": chunk.chunk_id,
            "source_file": chunk.source_file,
            "source_sha256": chunk.source_sha256,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
        }
        for chunk in chunks
    ]


def _candidate_schema(
    chunk_refs: list[str],
    *,
    defensive_posture: bool,
) -> dict:
    properties: dict[str, Any] = {
        "chunk_ref": {
            "type": "string",
            "enum": chunk_refs,
        },
        "quote": {
            "type": "string",
        },
        "interpretation": {
            "type": "string",
        },
    }

    required = [
        "chunk_ref",
        "quote",
        "interpretation",
    ]

    if defensive_posture:
        properties["subfield"] = {
            "type": "string",
            "enum": sorted(
                EXPECTED_DEFENSIVE_CONTROLS
            ),
        }
        required.append("subfield")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _batch_schema(
    chunk_refs: list[str],
) -> dict:
    quote_candidate = _candidate_schema(
        chunk_refs,
        defensive_posture=False,
    )
    posture_candidate = _candidate_schema(
        chunk_refs,
        defensive_posture=True,
    )

    return {
        "type": "object",
        "properties": {
            "capability_prior": {
                "type": "array",
                "items": quote_candidate,
                "maxItems": (
                    MAX_CANDIDATES_PER_PRIOR_PER_BATCH
                ),
            },
            "tempo": {
                "type": "array",
                "items": quote_candidate,
                "maxItems": (
                    MAX_CANDIDATES_PER_PRIOR_PER_BATCH
                ),
            },
            "defensive_posture": {
                "type": "array",
                "items": posture_candidate,
                "maxItems": (
                    MAX_CANDIDATES_PER_PRIOR_PER_BATCH
                ),
            },
            "geopolitical_trigger_prior": {
                "type": "array",
                "items": quote_candidate,
                "maxItems": (
                    MAX_CANDIDATES_PER_PRIOR_PER_BATCH
                ),
            },
        },
        "required": list(FOUR_PRIORS),
        "additionalProperties": False,
    }


def _render_batch_prompt(
    refs: Mapping[str, EvidenceChunk],
) -> str:
    sections = []

    for chunk_ref, chunk in refs.items():
        sections.append(
            f"=== CHUNK_REF {chunk_ref} ===\n"
            f"SOURCE_FILE: {chunk.source_file}\n"
            f"CHUNK_ID: {chunk.chunk_id}\n"
            f"TEXT:\n{chunk.text}\n"
            f"=== END CHUNK_REF {chunk_ref} ==="
        )

    return (
        f"PRIOR DEFINITIONS:\n{_PRIOR_DEFINITIONS}\n\n"
        "Extract relevant verbatim evidence from every provided chunk.\n"
        "Use the short CHUNK_REF value exactly as shown.\n\n"
        + "\n\n".join(sections)
    )


def _validate_batch_extraction(
    extraction: Any,
    *,
    allowed_refs: set[str],
) -> dict:
    if not isinstance(extraction, Mapping):
        raise ValueError(
            "top-level extraction must be a JSON object"
        )

    validated = dict(extraction)

    for prior in FOUR_PRIORS:
        if prior not in validated:
            raise ValueError(
                f"missing required extraction array `{prior}`"
            )

        candidates = validated[prior]

        if not isinstance(candidates, list):
            raise ValueError(
                f"`{prior}` must be an array"
            )

        if (
            len(candidates)
            > MAX_CANDIDATES_PER_PRIOR_PER_BATCH
        ):
            raise ValueError(
                f"`{prior}` contains too many candidates"
            )

        for index, candidate in enumerate(
            candidates
        ):
            path = f"{prior}[{index}]"

            if not isinstance(candidate, Mapping):
                raise ValueError(
                    f"`{path}` must be an object"
                )

            chunk_ref = candidate.get(
                "chunk_ref"
            )

            if chunk_ref not in allowed_refs:
                raise ValueError(
                    f"`{path}.chunk_ref` is not a valid "
                    "chunk reference"
                )

            quote = candidate.get("quote")
            interpretation = candidate.get(
                "interpretation"
            )

            if not isinstance(quote, str):
                raise ValueError(
                    f"`{path}.quote` must be a string"
                )

            if not isinstance(
                interpretation,
                str,
            ):
                raise ValueError(
                    f"`{path}.interpretation` must be a string"
                )

            if prior == "defensive_posture":
                subfield = candidate.get(
                    "subfield"
                )

                if (
                    subfield
                    not in EXPECTED_DEFENSIVE_CONTROLS
                ):
                    raise ValueError(
                        f"`{path}.subfield` must be one of "
                        f"{sorted(EXPECTED_DEFENSIVE_CONTROLS)}"
                    )

    return validated


def _extract_batch_with_retries(
    chunks: list[EvidenceChunk],
    *,
    llm,
    retries: int,
    timeout_seconds: int,
    diag=None,
) -> tuple[dict, str]:
    refs = _chunk_refs(chunks)
    allowed_refs = set(refs)

    base_prompt = _render_batch_prompt(refs)
    schema = _batch_schema(
        sorted(allowed_refs)
    )
    batch_id = _batch_id(chunks)

    last_error: Exception | None = None
    repair_feedback: str | None = None

    for attempt in range(
        retries + 1
    ):
        prompt = base_prompt

        if repair_feedback:
            prompt += (
                "\n\nPREVIOUS RESPONSE REJECTED:\n"
                f"{repair_feedback}\n\n"
                "Repair only the JSON structure and candidate references. "
                "Return all four arrays. Every candidate must be an object "
                "with a valid CHUNK_REF and an exact verbatim quote. Return "
                "fewer candidates if necessary."
            )

        raw = None
        parsed = None

        try:
            raw = generate_structured_json(
                llm=llm,
                schema=schema,
                prompt=prompt,
                system_message=_EXTRACTION_SYSTEM,
                num_predict=4096,
                timeout_seconds=timeout_seconds,
            )

            parsed = json.loads(raw)

            parsed = _validate_batch_extraction(
                parsed,
                allowed_refs=allowed_refs,
            )

            if diag is not None:
                diag.record_extraction(
                    chunk_id=batch_id,
                    request_prompt=prompt,
                    raw_response=raw,
                    parsed=parsed,
                )

            return parsed, raw

        except Exception as exc:
            last_error = exc
            repair_feedback = (
                f"{type(exc).__name__}: {exc}"
            )

            if diag is not None:
                diag.record_extraction(
                    chunk_id=batch_id,
                    request_prompt=prompt,
                    raw_response=raw or "",
                    parsed=(
                        parsed
                        if isinstance(parsed, dict)
                        else None
                    ),
                    error=repair_feedback,
                )

    raise RuntimeError(
        f"{batch_id}: extraction failed after "
        f"{retries + 1} attempt(s): {last_error}"
    )


def _checkpoint_directory(
    diagnostics_out_dir: str | None,
) -> Path | None:
    if not diagnostics_out_dir:
        return None

    path = (
        Path(diagnostics_out_dir)
        / "annexc_proposer"
        / "checkpoints"
    )
    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def _load_checkpoint(
    checkpoint_dir: Path | None,
    chunks: list[EvidenceChunk],
) -> dict | None:
    if checkpoint_dir is None:
        return None

    path = (
        checkpoint_dir
        / f"{_batch_id(chunks)}.json"
    )

    if not path.is_file():
        return None

    try:
        document = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if (
            document.get("checkpoint_version")
            != CHECKPOINT_VERSION
        ):
            return None

        if (
            document.get("chunk_identity")
            != _checkpoint_identity(chunks)
        ):
            return None

        refs = _chunk_refs(chunks)

        extraction = _validate_batch_extraction(
            document.get("extraction"),
            allowed_refs=set(refs),
        )

        return {
            "extraction": extraction,
            "raw_response": document.get(
                "raw_response",
                "",
            ),
            "path": str(path),
        }

    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ):
        return None


def _write_checkpoint(
    checkpoint_dir: Path | None,
    chunks: list[EvidenceChunk],
    *,
    extraction: dict,
    raw_response: str,
) -> str | None:
    if checkpoint_dir is None:
        return None

    path = (
        checkpoint_dir
        / f"{_batch_id(chunks)}.json"
    )
    temporary = path.with_suffix(
        ".json.tmp"
    )

    document = {
        "checkpoint_version": (
            CHECKPOINT_VERSION
        ),
        "created_at": datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "batch_id": _batch_id(chunks),
        "chunk_identity": (
            _checkpoint_identity(chunks)
        ),
        "extraction": extraction,
        "raw_response": raw_response,
    }

    with temporary.open(
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
        temporary,
        path,
    )

    return str(path)


def _write_progress(
    diagnostics_out_dir: str | None,
    payload: dict,
) -> None:
    if not diagnostics_out_dir:
        return

    directory = (
        Path(diagnostics_out_dir)
        / "annexc_proposer"
    )
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = directory / "progress.json"
    temporary = directory / "progress.json.tmp"

    document = {
        "updated_at": datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        **payload,
    }

    with temporary.open(
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
        temporary,
        path,
    )


def _verify_batch_extraction(
    extraction: dict,
    chunks: list[EvidenceChunk],
    *,
    diag=None,
) -> list:
    refs = _chunk_refs(chunks)
    verified = []

    kept_by_chunk_prior: dict[
        tuple[str, str],
        int,
    ] = {}

    for prior in FOUR_PRIORS:
        candidates = extraction.get(
            prior,
            [],
        )

        for candidate in candidates:
            chunk_ref = candidate[
                "chunk_ref"
            ]
            chunk = refs[chunk_ref]

            limit_key = (
                chunk_ref,
                prior,
            )
            kept = kept_by_chunk_prior.get(
                limit_key,
                0,
            )

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
                            ),
                            "chunk_ref": chunk_ref,
                        },
                    )

                continue

            verified_candidate = (
                verify_candidate(
                    candidate=dict(candidate),
                    chunk=chunk,
                    prior=prior,
                )
            )

            if verified_candidate is not None:
                verified.append(
                    verified_candidate
                )
                kept_by_chunk_prior[
                    limit_key
                ] = kept + 1

                if diag is not None:
                    diag.record_accepted_candidate()

                continue

            if diag is not None:
                quote = candidate.get(
                    "quote",
                    "",
                )

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


def scan_corpus_batched(
    *,
    frozen_sources: Mapping,
    llm,
    timeout_seconds: int,
    extraction_retries: int,
    diagnostics_out_dir: str | None,
    diag=None,
    max_batch_chars: int = (
        DEFAULT_MAX_BATCH_CHARS
    ),
    max_batch_chunks: int = (
        DEFAULT_MAX_BATCH_CHUNKS
    ),
) -> tuple[list, CorpusScanCoverage]:
    """
    Extract and verify evidence using resumable batches.

    Failed multi-chunk batches are split recursively. Coverage is marked
    failed only when an individual chunk still fails after retries.
    """

    chunks = build_prior_evidence_chunks(
        dict(frozen_sources)
    )
    coverage = CorpusScanCoverage(
        expected_chunks=len(chunks)
    )

    if diag is not None:
        for chunk in chunks:
            diag.record_chunk(chunk)

    batches = build_extraction_batches(
        chunks,
        max_batch_chars=max_batch_chars,
        max_batch_chunks=max_batch_chunks,
    )
    checkpoint_dir = _checkpoint_directory(
        diagnostics_out_dir
    )

    print(
        "[Annex C] Starting batched corpus scan: "
        f"{len(chunks)} chunks in "
        f"{len(batches)} initial batches; "
        f"{timeout_seconds}s deadline; "
        f"{extraction_retries + 1} attempts per batch.",
        flush=True,
    )

    all_verified = []

    def process_batch(
        batch_chunks: list[EvidenceChunk],
        *,
        label: str,
    ) -> None:
        batch_id = _batch_id(
            batch_chunks
        )
        total_chars = sum(
            len(chunk.text)
            for chunk in batch_chunks
        )

        checkpoint = _load_checkpoint(
            checkpoint_dir,
            batch_chunks,
        )

        if checkpoint is not None:
            extraction = checkpoint[
                "extraction"
            ]

            print(
                "[Annex C] "
                f"{label} CACHED {batch_id}: "
                f"{len(batch_chunks)} chunks, "
                f"{total_chars:,} chars.",
                flush=True,
            )

            if diag is not None:
                diag.record_extraction(
                    chunk_id=batch_id,
                    raw_response=checkpoint[
                        "raw_response"
                    ],
                    parsed=extraction,
                )

        else:
            print(
                "[Annex C] "
                f"{label} START {batch_id}: "
                f"{len(batch_chunks)} chunks, "
                f"{total_chars:,} chars.",
                flush=True,
            )

            _write_progress(
                diagnostics_out_dir,
                {
                    "phase": "extraction",
                    "status": "RUNNING",
                    "batch": label,
                    "batch_id": batch_id,
                    "batch_chunk_count": (
                        len(batch_chunks)
                    ),
                    "expected_chunks": (
                        coverage.expected_chunks
                    ),
                    "successful_chunks": (
                        coverage.successful_chunks
                    ),
                    "failed_chunks": list(
                        coverage.failed_chunks
                    ),
                },
            )

            started_at = time.monotonic()

            try:
                extraction, raw_response = (
                    _extract_batch_with_retries(
                        batch_chunks,
                        llm=llm,
                        retries=(
                            extraction_retries
                        ),
                        timeout_seconds=(
                            timeout_seconds
                        ),
                        diag=diag,
                    )
                )

            except Exception as exc:
                elapsed = (
                    time.monotonic()
                    - started_at
                )

                if len(batch_chunks) > 1:
                    midpoint = (
                        len(batch_chunks)
                        // 2
                    )

                    print(
                        "[Annex C] "
                        f"{label} SPLIT after "
                        f"{elapsed:.1f}s: {exc}",
                        flush=True,
                    )

                    process_batch(
                        batch_chunks[:midpoint],
                        label=f"{label}.A",
                    )
                    process_batch(
                        batch_chunks[midpoint:],
                        label=f"{label}.B",
                    )
                    return

                failed_chunk = batch_chunks[0]

                if (
                    failed_chunk.chunk_id
                    not in coverage.failed_chunks
                ):
                    coverage.failed_chunks.append(
                        failed_chunk.chunk_id
                    )

                if diag is not None:
                    diag.record_failed_chunk(
                        failed_chunk.chunk_id,
                        str(exc),
                    )

                print(
                    "[Annex C] "
                    f"{label} FAILED single chunk "
                    f"{failed_chunk.chunk_id}: {exc}",
                    flush=True,
                )
                return

            checkpoint_path = _write_checkpoint(
                checkpoint_dir,
                batch_chunks,
                extraction=extraction,
                raw_response=raw_response,
            )

            elapsed = (
                time.monotonic()
                - started_at
            )

            print(
                "[Annex C] "
                f"{label} PASS in {elapsed:.1f}s; "
                f"checkpoint={checkpoint_path}.",
                flush=True,
            )

        verified = _verify_batch_extraction(
            extraction,
            batch_chunks,
            diag=diag,
        )
        all_verified.extend(verified)
        coverage.successful_chunks += len(
            batch_chunks
        )

        _write_progress(
            diagnostics_out_dir,
            {
                "phase": "extraction",
                "status": "BATCH_COMPLETE",
                "batch": label,
                "batch_id": batch_id,
                "expected_chunks": (
                    coverage.expected_chunks
                ),
                "successful_chunks": (
                    coverage.successful_chunks
                ),
                "failed_chunks": list(
                    coverage.failed_chunks
                ),
                "verified_candidates": (
                    len(all_verified)
                ),
            },
        )

    for batch_index, batch in enumerate(
        batches,
        start=1,
    ):
        process_batch(
            batch,
            label=(
                f"Batch {batch_index}/"
                f"{len(batches)}"
            ),
        )

    final_status = (
        "COMPLETE"
        if coverage.complete
        else "INCOMPLETE"
    )

    _write_progress(
        diagnostics_out_dir,
        {
            "phase": "extraction",
            "status": final_status,
            **coverage.as_dict(),
            "verified_candidates": (
                len(all_verified)
            ),
        },
    )

    print(
        "[Annex C] Batched extraction "
        f"{final_status}: "
        f"{coverage.successful_chunks}/"
        f"{coverage.expected_chunks} chunks; "
        f"{len(all_verified)} verified candidates; "
        f"{len(coverage.failed_chunks)} failures.",
        flush=True,
    )

    return all_verified, coverage
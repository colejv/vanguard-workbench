"""
Source-local evidence chunking + verified-candidate model for Annex C
prior derivation.

Quote-level evidence work needs different chunks than Stage 0's broad
60,000-character extraction chunks: source-local (never mixing two source
files), token-bounded, overlapping, and carrying exact character offsets in
the normalized source text so a verified quote's locator is derived in code
rather than trusted from the model.

Everything here is deterministic. No model calls.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


# Rough chars-per-token for budgeting. Deliberately conservative: it is
# better to under-fill a chunk than to silently truncate evidence.
_CHARS_PER_TOKEN = 4

# Default chunk budget in tokens of corpus text (see the spec's allocation:
# ~55-65% corpus text, 20-25% prompt/schema, 15-20% response headroom).
DEFAULT_CHUNK_TOKENS = 1200
DEFAULT_OVERLAP_TOKENS = 300


@dataclass(frozen=True)
class EvidenceChunk:
    """One source-local, bounded span of normalized source text."""
    chunk_id: str
    source_file: str
    source_sha256: str
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class VerifiedCandidate:
    """An evidence candidate whose quote has been confirmed verbatim in its
    chunk's frozen text, with locators derived in code."""
    candidate_id: str
    prior: str
    source_file: str
    source_sha256: str
    chunk_id: str
    start_char: int
    end_char: int
    quote: str
    interpretation: str
    subfield: str | None = None


@dataclass
class CorpusScanCoverage:
    """Explicit extraction coverage. Incomplete corpus processing is NOT the
    same as no evidence — the caller must refuse to apply any no-evidence
    policy unless complete is True."""
    expected_chunks: int = 0
    successful_chunks: int = 0
    failed_chunks: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return (self.expected_chunks > 0
                and self.successful_chunks == self.expected_chunks
                and not self.failed_chunks)

    def as_dict(self) -> dict:
        return {
            "expected_chunks": self.expected_chunks,
            "successful_chunks": self.successful_chunks,
            "failed_chunks": list(self.failed_chunks),
            "complete": self.complete,
        }


def normalize_source_text(text: str) -> str:
    """Collapse whitespace to a single canonical form. Offsets and quote
    verification are both computed against THIS normalized text, so they
    always agree."""
    return " ".join((text or "").split())


def build_prior_evidence_chunks(
    frozen_sources: dict, *,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list:
    """Create stable, source-local, token-bounded, overlapping chunks with
    explicit offsets into each source's NORMALIZED text.

    Never mixes two source files in one chunk. Chunk IDs derive from the
    source hash and offsets, so they are stable across runs.
    """
    span = max(1, chunk_tokens * _CHARS_PER_TOKEN)
    overlap = max(0, min(overlap_tokens * _CHARS_PER_TOKEN, span - 1))
    stride = max(1, span - overlap)

    chunks = []
    for source_file in sorted(frozen_sources):
        src = frozen_sources[source_file] or {}
        text = normalize_source_text(src.get("text", ""))
        if not text:
            continue
        source_sha256 = src.get("sha256") or ""
        start = 0
        while start < len(text):
            end = min(start + span, len(text))
            chunk_text = text[start:end]
            digest = hashlib.sha256(
                f"{source_sha256}\x00{start}\x00{end}".encode("utf-8")
            ).hexdigest()[:8]
            chunks.append(EvidenceChunk(
                chunk_id=f"{source_file}#{digest}",
                source_file=source_file,
                source_sha256=source_sha256,
                text=chunk_text,
                start_char=start,
                end_char=end,
            ))
            if end >= len(text):
                break
            start += stride
    return chunks


def make_candidate_id(*, source_sha256: str, chunk_id: str, quote: str) -> str:
    """Deterministic candidate ID. The PROPOSER generates this, never the
    model — so a model cannot mint an ID for evidence that doesn't exist."""
    payload = f"{source_sha256}\x00{chunk_id}\x00{quote}".encode("utf-8")
    return "ev_" + hashlib.sha256(payload).hexdigest()[:16]


def verify_candidate(
    *,
    candidate: dict,
    chunk: EvidenceChunk,
    prior: str,
) -> VerifiedCandidate | None:
    """
    Verify one model-proposed evidence candidate.

    Invalid candidate types are rejected rather than raising. Quotes must
    occur verbatim after deterministic whitespace normalization.
    """

    if not isinstance(candidate, dict):
        return None

    raw_quote = candidate.get(
        "quote",
        "",
    )

    if not isinstance(raw_quote, str):
        return None

    quote = normalize_source_text(
        raw_quote
    )

    if not quote:
        return None

    index = chunk.text.find(quote)

    if index < 0:
        return None

    raw_interpretation = candidate.get(
        "interpretation",
        "",
    )

    if not isinstance(
        raw_interpretation,
        str,
    ):
        raw_interpretation = ""

    subfield = candidate.get(
        "subfield"
    )

    if (
        subfield is not None
        and not isinstance(subfield, str)
    ):
        return None

    start_char = (
        chunk.start_char
        + index
    )
    end_char = (
        start_char
        + len(quote)
    )

    return VerifiedCandidate(
        candidate_id=make_candidate_id(
            source_sha256=(
                chunk.source_sha256
            ),
            chunk_id=chunk.chunk_id,
            quote=quote,
        ),
        prior=prior,
        source_file=chunk.source_file,
        source_sha256=(
            chunk.source_sha256
        ),
        chunk_id=chunk.chunk_id,
        start_char=start_char,
        end_char=end_char,
        quote=quote,
        interpretation=(
            raw_interpretation.strip()
        ),
        subfield=subfield,
    )


def deduplicate_candidates(candidates: list) -> list:
    """Drop identical normalized quotes from the same source, preserving the
    first occurrence. Candidates expressing conflicting signals are NOT
    merged — only exact duplicates are removed."""
    seen = set()
    out = []
    for c in candidates:
        if c.candidate_id in seen:
            continue
        seen.add(c.candidate_id)
        out.append(c)
    return out


# ---- rejection reason taxonomy (deterministic, one code per rejected item) --

REJECT_EMPTY_QUOTE = "EMPTY_QUOTE"
REJECT_QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
REJECT_UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
REJECT_SOURCE_HASH_MISMATCH = "SOURCE_HASH_MISMATCH"
REJECT_DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
REJECT_INVALID_PRIOR = "INVALID_PRIOR"
REJECT_INVALID_CONTROL = "INVALID_CONTROL"


def quote_rejection_diagnostic(*, quote: str, chunk, source_file: str) -> dict:
    """Safe (non-fuzzy) comparison diagnostics for a rejected quote — length
    and exact-match only. Never used on the acceptance path; diagnostic only,
    to help distinguish paraphrase/punctuation/OCR drift from a genuinely
    absent quote during first-run tuning."""
    normalized = normalize_source_text(quote)
    return {
        "quote_length": len(quote or ""),
        "normalized_quote_length": len(normalized),
        "exact_match": normalized in chunk.text if normalized else False,
        "source_file": source_file,
        "chunk_id": chunk.chunk_id,
    }
"""Tests for the deterministic evidence chunker + verifier."""
from src.annexc_evidence import (
    build_prior_evidence_chunks, verify_candidate, make_candidate_id,
    deduplicate_candidates, normalize_source_text, CorpusScanCoverage)

FROZEN = {"a.pdf": {"sha256": "sha256:a",
                    "text": "The actor showed sustained access over six months."}}


def test_chunks_are_source_local():
    frozen = {"a.pdf": {"sha256": "sha256:a", "text": "alpha " * 500},
              "b.pdf": {"sha256": "sha256:b", "text": "beta " * 500}}
    chunks = build_prior_evidence_chunks(frozen)
    for c in chunks:
        # No chunk mixes sources: its text belongs to exactly one file.
        assert c.source_file in ("a.pdf", "b.pdf")
    assert {c.source_file for c in chunks} == {"a.pdf", "b.pdf"}


def test_chunk_ids_stable():
    a = build_prior_evidence_chunks(FROZEN)
    b = build_prior_evidence_chunks(FROZEN)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]


def test_verify_accepts_verbatim_quote():
    chunk = build_prior_evidence_chunks(FROZEN)[0]
    vc = verify_candidate(candidate={"quote": "sustained access", "interpretation": "x"},
                          chunk=chunk, prior="capability_prior")
    assert vc is not None
    assert chunk.text[vc.start_char - chunk.start_char: vc.end_char - chunk.start_char] == "sustained access"


def test_verify_rejects_absent_quote():
    chunk = build_prior_evidence_chunks(FROZEN)[0]
    assert verify_candidate(candidate={"quote": "never written", "interpretation": "x"},
                            chunk=chunk, prior="tempo") is None


def test_candidate_id_deterministic():
    a = make_candidate_id(source_sha256="s", chunk_id="c", quote="q")
    b = make_candidate_id(source_sha256="s", chunk_id="c", quote="q")
    assert a == b and a.startswith("ev_")


def test_coverage_complete_logic():
    cov = CorpusScanCoverage(expected_chunks=3, successful_chunks=3)
    assert cov.complete is True
    cov2 = CorpusScanCoverage(expected_chunks=3, successful_chunks=2, failed_chunks=["x"])
    assert cov2.complete is False
    assert CorpusScanCoverage().complete is False  # zero expected -> not complete


def test_normalize_collapses_whitespace():
    assert normalize_source_text("a   b\n\nc") == "a b c"
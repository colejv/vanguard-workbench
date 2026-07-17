"""Tests for fast, resumable Annex C batch extraction."""

from __future__ import annotations

import json

import src.annexc_batch_scan as batch_scan
from src.annexc_evidence import EvidenceChunk


class _FakeLLM:
    base_url = "http://localhost:11434"
    model = "ollama/test-model"


def _chunks(count: int) -> list[EvidenceChunk]:
    chunks = []

    for index in range(count):
        text = (
            f"Frozen evidence chunk {index}. "
            "The actor maintained sustained access."
        )

        chunks.append(
            EvidenceChunk(
                chunk_id=f"source.txt#chunk-{index}",
                source_file="source.txt",
                source_sha256="sha256:test",
                text=text,
                start_char=index * 100,
                end_char=(
                    index * 100
                    + len(text)
                ),
            )
        )

    return chunks


def _empty_response() -> str:
    return json.dumps(
        {
            "capability_prior": [],
            "tempo": [],
            "defensive_posture": [],
            "geopolitical_trigger_prior": [],
        }
    )


def test_builds_bounded_batches():
    batches = (
        batch_scan.build_extraction_batches(
            _chunks(17),
            max_batch_chars=1_000_000,
            max_batch_chunks=8,
        )
    )

    assert [
        len(batch)
        for batch in batches
    ] == [8, 8, 1]


def test_scan_checkpoints_and_reuses_batches(
    tmp_path,
    monkeypatch,
):
    chunks = _chunks(10)

    monkeypatch.setattr(
        batch_scan,
        "build_prior_evidence_chunks",
        lambda frozen: chunks,
    )

    calls = []

    def generate(**kwargs):
        calls.append(kwargs["prompt"])
        return _empty_response()

    monkeypatch.setattr(
        batch_scan,
        "generate_structured_json",
        generate,
    )

    _, first_coverage = (
        batch_scan.scan_corpus_batched(
            frozen_sources={
                "source.txt": {
                    "sha256": "sha256:test",
                    "text": "unused",
                }
            },
            llm=_FakeLLM(),
            timeout_seconds=1,
            extraction_retries=0,
            diagnostics_out_dir=str(
                tmp_path
            ),
            max_batch_chars=1_000_000,
            max_batch_chunks=8,
        )
    )

    assert first_coverage.complete
    assert len(calls) == 2

    def must_not_call(**kwargs):
        raise AssertionError(
            "cached batches should not invoke the model"
        )

    monkeypatch.setattr(
        batch_scan,
        "generate_structured_json",
        must_not_call,
    )

    _, resumed_coverage = (
        batch_scan.scan_corpus_batched(
            frozen_sources={
                "source.txt": {
                    "sha256": "sha256:test",
                    "text": "unused",
                }
            },
            llm=_FakeLLM(),
            timeout_seconds=1,
            extraction_retries=0,
            diagnostics_out_dir=str(
                tmp_path
            ),
            max_batch_chars=1_000_000,
            max_batch_chunks=8,
        )
    )

    assert resumed_coverage.complete


def test_failed_batch_is_split_before_failing_coverage(
    tmp_path,
    monkeypatch,
):
    chunks = _chunks(2)

    monkeypatch.setattr(
        batch_scan,
        "build_prior_evidence_chunks",
        lambda frozen: chunks,
    )

    calls = []

    def generate(**kwargs):
        prompt = kwargs["prompt"]
        calls.append(prompt)

        if (
            prompt.count(
                "=== CHUNK_REF "
            )
            > 1
        ):
            raise RuntimeError(
                "simulated oversized batch"
            )

        return _empty_response()

    monkeypatch.setattr(
        batch_scan,
        "generate_structured_json",
        generate,
    )

    _, coverage = (
        batch_scan.scan_corpus_batched(
            frozen_sources={
                "source.txt": {
                    "sha256": "sha256:test",
                    "text": "unused",
                }
            },
            llm=_FakeLLM(),
            timeout_seconds=1,
            extraction_retries=0,
            diagnostics_out_dir=str(
                tmp_path
            ),
            max_batch_chars=1_000_000,
            max_batch_chunks=8,
        )
    )

    assert coverage.complete
    assert coverage.failed_chunks == []
    assert len(calls) == 3
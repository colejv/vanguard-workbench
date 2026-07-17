"""Regression tests for malformed Annex C extraction responses."""

from __future__ import annotations

import json

import pytest

import src.annexc_proposer as proposer
from src.annexc_evidence import (
    EvidenceChunk,
    verify_candidate,
)


def _chunk() -> EvidenceChunk:
    text = (
        "The assessed actor demonstrated "
        "sustained access."
    )

    return EvidenceChunk(
        chunk_id="actor-report.pdf#test",
        source_file="actor-report.pdf",
        source_sha256="sha256:aaa",
        text=text,
        start_char=0,
        end_char=len(text),
    )


def _empty_extraction() -> dict:
    return {
        "capability_prior": [],
        "tempo": [],
        "defensive_posture": [],
        "geopolitical_trigger_prior": [],
        "truncated": False,
    }


def test_verify_candidate_rejects_string():
    assert (
        verify_candidate(
            candidate=(
                "sustained access"
            ),
            chunk=_chunk(),
            prior="capability_prior",
        )
        is None
    )


def test_extraction_shape_rejects_string_candidate():
    extraction = _empty_extraction()
    extraction["capability_prior"] = [
        "sustained access"
    ]

    with pytest.raises(
        ValueError,
        match=(
            "capability_prior\\[0\\]` "
            "must be an object"
        ),
    ):
        proposer._validate_extraction_shape(
            extraction
        )


def test_extraction_shape_accepts_candidate_object():
    extraction = _empty_extraction()
    extraction["capability_prior"] = [
        {
            "quote": "sustained access",
            "interpretation": (
                "Evidence of persistent capability."
            ),
        }
    ]

    proposer._validate_extraction_shape(
        extraction
    )


def test_extract_retries_after_string_candidate(
    monkeypatch,
):
    invalid = _empty_extraction()
    invalid["capability_prior"] = [
        "sustained access"
    ]

    valid = _empty_extraction()
    valid["capability_prior"] = [
        {
            "quote": "sustained access",
            "interpretation": (
                "Evidence of persistent capability."
            ),
        }
    ]

    responses = iter(
        [
            json.dumps(invalid),
            json.dumps(valid),
        ]
    )

    monkeypatch.setattr(
        proposer,
        "generate_structured_json",
        lambda **kwargs: next(responses),
    )

    result = proposer._extract_with_retries(
        _chunk(),
        llm=object(),
        retries=1,
        timeout_seconds=1,
    )

    assert result == valid


def test_extract_exhaustion_becomes_incomplete_scan(
    monkeypatch,
):
    invalid = _empty_extraction()
    invalid["tempo"] = [
        "rapid operations"
    ]

    monkeypatch.setattr(
        proposer,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            invalid
        ),
    )

    with pytest.raises(
        proposer.IncompleteCorpusScan,
        match=(
            "extraction failed after "
            "2 attempt"
        ),
    ):
        proposer._extract_with_retries(
            _chunk(),
            llm=object(),
            retries=1,
            timeout_seconds=1,
        )


def test_verifier_defensively_skips_string_candidate():
    extraction = _empty_extraction()
    extraction["capability_prior"] = [
        "sustained access"
    ]

    result = (
        proposer._verify_chunk_extraction(
            extraction,
            _chunk(),
        )
    )

    assert result == []

def test_normalizes_string_false_truncated():
    extraction = _empty_extraction()
    extraction["truncated"] = "false"

    result = proposer._normalize_truncated_flag(
        extraction
    )

    assert result["truncated"] is False


def test_normalizes_string_true_truncated():
    extraction = _empty_extraction()
    extraction["truncated"] = "true"

    result = proposer._normalize_truncated_flag(
        extraction
    )

    assert result["truncated"] is True


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        1,
        "yes",
        "",
    ],
)
def test_rejects_ambiguous_truncated_values(
    value,
):
    extraction = _empty_extraction()
    extraction["truncated"] = value

    with pytest.raises(
        ValueError,
        match="JSON boolean true or false",
    ):
        proposer._normalize_truncated_flag(
            extraction
        )

def test_truncated_response_is_retried(
    monkeypatch,
):
    truncated = _empty_extraction()
    truncated["truncated"] = True

    valid = _empty_extraction()
    valid["capability_prior"] = [
        {
            "quote": "sustained access",
            "interpretation": (
                "Evidence of persistent capability."
            ),
        }
    ]

    responses = iter(
        [
            json.dumps(truncated),
            json.dumps(valid),
        ]
    )

    monkeypatch.setattr(
        proposer,
        "generate_structured_json",
        lambda **kwargs: next(responses),
    )

    result = proposer._extract_with_retries(
        _chunk(),
        llm=object(),
        retries=1,
        timeout_seconds=1,
    )

    assert result == valid
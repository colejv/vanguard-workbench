"""Tests for single-call Annex C artifact derivation."""

from __future__ import annotations

import json

import pytest

import src.annexc_artifact_gate as artifact_gate


POLICY = {
    "schema_version": "1.0",
    "policy_version": "2026-07-15",
    "no_evidence": {
        "capability_prior": [
            0.3333333333333333,
            0.3333333333333333,
            0.3333333333333334,
        ],
        "tempo": {
            "action": "BLOCK",
        },
        "defensive_posture": {
            "action": "BLOCK",
        },
        "geopolitical_trigger_prior": {
            "action": "DEFAULT",
            "value": 0.10,
        },
    },
}


def _sources():
    stage0_text = (
        '{"finding":"The actor demonstrated sustained access '
        'and rapid operational cadence."}'
    )
    stage1_text = (
        '{"systems":["command platform"],'
        '"controls":"not assessed"}'
    )
    stage2_text = (
        '{"nodes":[{"id":"ADV_START"}],"edges":[]}'
    )
    annexb_text = (
        '{"priority_path":["ADV_START"],'
        '"assessment":"heuristic only"}'
    )

    return {
        "stage0_output.json": {
            "path": "outputs/test/stage0_output.json",
            "sha256": "sha256:stage0",
            "text": stage0_text,
        },
        "stage1_output.json": {
            "path": "outputs/test/stage1_output.json",
            "sha256": "sha256:stage1",
            "text": stage1_text,
        },
        "stage2_vectors.json": {
            "path": "outputs/test/stage2_vectors.json",
            "sha256": "sha256:stage2",
            "text": stage2_text,
        },
        "kcag_report.json": {
            "path": "outputs/test/kcag_report.json",
            "sha256": "sha256:annexb",
            "text": annexb_text,
        },
    }


def _model_response():
    return {
        "capability_prior": [
            {
                "value": [
                    0.1,
                    0.2,
                    0.7,
                ],
                "confidence": "MEDIUM",
                "reasoning": (
                    "Sustained access supports a "
                    "higher-capability assessment."
                ),
                "evidence": [
                    {
                        "artifact_name": (
                            "stage0_output.json"
                        ),
                        "quote": (
                            "The actor demonstrated "
                            "sustained access"
                        ),
                    }
                ],
            }
        ],
        "tempo": [
            {
                "value": "HIGH",
                "confidence": "MEDIUM",
                "reasoning": (
                    "The Stage 0 finding explicitly "
                    "describes rapid cadence."
                ),
                "evidence": [
                    {
                        "artifact_name": (
                            "stage0_output.json"
                        ),
                        "quote": (
                            "rapid operational cadence"
                        ),
                    }
                ],
            }
        ],
        "defensive_posture": [],
        "geopolitical_trigger_prior": [],
    }


def test_derivation_uses_one_artifact_call(
    monkeypatch,
):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            _model_response()
        )

    monkeypatch.setattr(
        artifact_gate,
        "generate_structured_json",
        generate,
    )

    derivation = (
        artifact_gate
        .derive_annexc_from_prior_artifacts(
            sources=_sources(),
            policy=POLICY,
            llm=object(),
        )
    )

    assert len(calls) == 1

    assert (
        derivation["priors"][
            "capability_prior"
        ]["status"]
        == "SUPPORTED"
    )
    assert (
        derivation["priors"]["tempo"][
            "status"
        ]
        == "SUPPORTED"
    )
    assert (
        derivation["priors"][
            "defensive_posture"
        ]["status"]
        == "BLOCKED"
    )
    assert (
        derivation["priors"][
            "geopolitical_trigger_prior"
        ]["status"]
        == "DEFAULTED"
    )


def test_invalid_quote_gets_one_repair_call(
    monkeypatch,
):
    invalid = _model_response()
    invalid["tempo"][0]["evidence"][0][
        "quote"
    ] = "quote that does not exist"

    responses = iter(
        [
            json.dumps(invalid),
            json.dumps(_model_response()),
        ]
    )
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(
        artifact_gate,
        "generate_structured_json",
        generate,
    )

    derivation = (
        artifact_gate
        .derive_annexc_from_prior_artifacts(
            sources=_sources(),
            policy=POLICY,
            llm=object(),
        )
    )

    assert len(calls) == 2
    assert (
        derivation["priors"]["tempo"][
            "status"
        ]
        == "SUPPORTED"
    )


def test_artifact_hash_change_blocks_evidence():
    sources = _sources()

    derivation = {
        "priors": {
            field: artifact_gate.apply_no_evidence_policy(
                field,
                POLICY,
            )
            for field in artifact_gate.FOUR_PRIORS
        }
    }

    derivation["priors"][
        "capability_prior"
    ] = {
        "field": (
            "adversary.capability_prior"
        ),
        "value": [
            0.1,
            0.2,
            0.7,
        ],
        "status": "SUPPORTED",
        "source_mode": (
            artifact_gate.ARTIFACT_SOURCE_MODE
        ),
        "confidence": "MEDIUM",
        "reasoning": "Supported by Stage 0.",
        "evidence": [
            {
                "source_type": (
                    "ASSESSMENT_ARTIFACT"
                ),
                "source_file": (
                    "stage0_output.json"
                ),
                "source_sha256": (
                    "sha256:old-hash"
                ),
                "quote": (
                    "sustained access"
                ),
            }
        ],
    }

    result = (
        artifact_gate
        .validate_artifact_derivation(
            derivation,
            sources=sources,
            policy=POLICY,
        )
    )

    assert result["is_valid"] is False
    assert (
        result["priors"][
            "capability_prior"
        ]
        == "BLOCKED"
    )

    assert any(
        error["code"]
        == "ARTIFACT_HASH_MISMATCH"
        for error in result["errors"]
    )


def test_single_prior_object_is_normalized_to_array(
    monkeypatch,
):
    response = _model_response()

    response["defensive_posture"] = {
        "value": {
            control: False
            for control in sorted(
                artifact_gate
                .EXPECTED_DEFENSIVE_CONTROLS
            )
        },
        "confidence": "LOW",
        "reasoning": (
            "The assessment artifacts do not show "
            "deployed defensive controls."
        ),
        "evidence": [
            {
                "artifact_name": (
                    "stage1_output.json"
                ),
                "quote": "controls",
            }
        ],
    }

    monkeypatch.setattr(
        artifact_gate,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            response
        ),
    )

    derivation = (
        artifact_gate
        .derive_annexc_from_prior_artifacts(
            sources=_sources(),
            policy=POLICY,
            llm=object(),
        )
    )

    assert (
        derivation["priors"][
            "defensive_posture"
        ]["status"]
        == "SUPPORTED"
    )


@pytest.mark.parametrize(
    "value",
    [
        "invalid",
        123,
        True,
    ],
)
def test_malformed_prior_container_fails_closed(
    value,
):
    with pytest.raises(
        ValueError,
        match=(
            "must be an array or a single "
            "proposal object"
        ),
    ):
        artifact_gate._normalize_prior_records(
            "defensive_posture",
            value,
        )



def test_missing_reasoning_is_deterministically_filled(
    monkeypatch,
):
    response = _model_response()
    response["capability_prior"][0].pop(
        "reasoning"
    )

    monkeypatch.setattr(
        artifact_gate,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            response
        ),
    )

    derivation = (
        artifact_gate
        .derive_annexc_from_prior_artifacts(
            sources=_sources(),
            policy=POLICY,
            llm=object(),
        )
    )

    record = derivation["priors"][
        "capability_prior"
    ]

    assert record["status"] == "SUPPORTED"
    assert record["reasoning"] == (
        "Derived from the cited prior-stage "
        "assessment artifact evidence for "
        "capability_prior."
    )


def test_single_evidence_object_is_normalized(
    monkeypatch,
):
    response = _model_response()

    evidence = response[
        "capability_prior"
    ][0]["evidence"][0]

    response[
        "capability_prior"
    ][0]["evidence"] = evidence

    monkeypatch.setattr(
        artifact_gate,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            response
        ),
    )

    derivation = (
        artifact_gate
        .derive_annexc_from_prior_artifacts(
            sources=_sources(),
            policy=POLICY,
            llm=object(),
        )
    )

    assert (
        derivation["priors"][
            "capability_prior"
        ]["status"]
        == "SUPPORTED"
    )

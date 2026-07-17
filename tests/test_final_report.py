from __future__ import annotations

import json

import src.final_report as final_report


def _context():
    artifacts = [
        "stage0.md",
        "stage1.md",
        "stage2.md",
        "annexB_kcag.md",
        "annexC_bbn.md",
        "stage3.md",
        "stage4_mission_plan.md",
    ]

    return {
        "schema_version": "1.0",
        "assessment_identity": {
            "run_id": "vaf_test",
            "corpus_manifest_hash": (
                "sha256:test"
            ),
            "generated_at": (
                "2026-07-16T00:00:00Z"
            ),
        },
        "context_hash": "sha256:context",
        "narrative_sources": {
            "stage0.md": "Verified Stage 0 source narrative.",
            "stage1.md": "Verified Stage 1 source narrative.",
            "stage2.md": "Verified Stage 2 source narrative.",
            "annexB_kcag.md": "Verified Annex B source narrative.",
            "annexC_bbn.md": "Verified Annex C source narrative.",
            "stage3.md": "Verified Stage 3 source narrative.",
            "stage4_mission_plan.md": (
                "Verified Stage 4 source narrative."
            ),
        },
        "source_artifact_names": artifacts,
        "authoritative_facts": {
            "state": {
                "current_stage": "stage4",
                "stage_statuses": {},
                "gap_count": 0,
                "gate_decision_count": 0,
            },
            "stage2": {
                "graph_stats": {
                    "nodes": 7,
                    "edges": 6,
                    "objectives": 3,
                },
                "node_ids": [
                    "ADV_START",
                    "G_TEST",
                ],
                "goal_ids": [
                    "G_TEST",
                ],
                "vector_ids": [
                    "V-01",
                ],
                "technique_ids": [
                    "T1040",
                ],
            },
            "annex_b": {
                "scoring_model": {
                    "semantics": (
                        "heuristic_relative_ranking"
                    )
                },
                "minimum_cut": {},
                "priority_path": {
                    "path": [
                        "ADV_START",
                        "G_TEST",
                    ],
                    "score": 0.25,
                },
                "top_paths": [],
            },
            "annex_c": {
                "assessment_config": {
                    "adversary": {
                        "capability_prior": [
                            0.3,
                            0.3,
                            0.4,
                        ],
                        "tempo": "MEDIUM",
                    },
                    "defensive_posture": {
                        "edr": False,
                    },
                    "geopolitical_trigger_prior": (
                        0.1
                    ),
                },
                "prior_statuses": {},
                "prior_source_modes": {},
                "threat_score": 0.1312,
                "bbn_status": "PASS",
                "sensitivity_status": "PASS",
                "analyst_resolution": {},
            },
            "stage3": {
                "test_ids": [
                    "RT-001",
                ],
                "categories_by_test_id": {
                    "RT-001": [
                        1,
                    ]
                },
                "safety_review": {},
            },
            "stage4": {
                "plan_id": "MP-001",
                "phase_ids": [
                    "PHASE-01",
                ],
                "action_ids": [
                    "ACT-001",
                ],
                "action_test_bindings": {
                    "ACT-001": "RT-001",
                },
                "execution_authorization": (
                    "NOT_GRANTED"
                ),
                "artifact_role": (
                    "HUMAN_REVIEWED_MISSION_PLAN_DRAFT"
                ),
                "phase0_safety_gate": {},
            },
            "validation_statuses": {
                "kcag_validation.json": "PASS",
                "bbn_report.json": "PASS",
                "bbn_sensitivity.json": "PASS",
                "stage3_test_plan_validation.json": (
                    "PASS"
                ),
                "stage4_execution_plan_validation.json": (
                    "PASS"
                ),
            },
        },
    }


def _model_payload():
    refs = [
        "stage0.md",
        "stage1.md",
        "stage2.md",
        "annexB_kcag.md",
        "annexC_bbn.md",
        "stage3.md",
        "stage4_mission_plan.md",
    ]

    return {
        "report_id": "FR-001",
        "title": "Comprehensive Assessment",
        "executive_summary": (
            "The completed assessment identified "
            "validated attack paths and defensive gaps."
        ),
        "overall_assessment": {
            "risk_level": "HIGH",
            "confidence": "MEDIUM",
            "rationale": (
                "The conclusion reflects verified "
                "cross-stage findings."
            ),
        },
        "scope_and_methodology": (
            "The report consolidates verified "
            "Stage 0 through Stage 4 artifacts."
        ),
        "stage_narratives": {
            "stage0": "Stage 0 summary.",
            "stage1": "Stage 1 summary.",
            "stage2": "Stage 2 summary.",
            "annex_b": "Annex B summary.",
            "annex_c": "Annex C summary.",
            "stage3": "Stage 3 summary.",
            "stage4": "Stage 4 summary.",
        },
        "key_findings": [
            {
                "finding_id": f"FR-F-{index:03d}",
                "title": f"Finding {index}",
                "severity": "HIGH",
                "confidence": "MEDIUM",
                "statement": "Verified finding.",
                "implications": (
                    "The finding affects mission risk."
                ),
                "source_artifacts": [
                    refs[
                        (index - 1) % len(refs)
                    ]
                ],
            }
            for index in range(1, 4)
        ],
        "recommendations": [
            {
                "recommendation_id": (
                    f"FR-R-{index:03d}"
                ),
                "priority": "NEAR_TERM",
                "title": (
                    f"Recommendation {index}"
                ),
                "action": (
                    "Implement the verified defensive "
                    "improvement."
                ),
                "rationale": (
                    "This addresses a verified finding."
                ),
                "source_artifacts": [
                    refs[
                        (index + 1) % len(refs)
                    ]
                ],
            }
            for index in range(1, 4)
        ],
        "limitations": [
            {
                "item_id": "FR-L-001",
                "statement": (
                    "KCAG scores are heuristic."
                ),
                "source_artifacts": [
                    "annexB_kcag.md"
                ],
            }
        ],
        "unresolved_items": [
            {
                "item_id": "FR-U-001",
                "statement": (
                    "Some defensive controls remain "
                    "partially deployed."
                ),
                "source_artifacts": [
                    "annexC_bbn.md"
                ],
            }
        ],
    }


def _inventory():
    return {
        "artifacts": [
            {
                "artifact": name,
                "included_in_report": True,
            }
            for name in _context()[
                "source_artifact_names"
            ]
        ]
    }


def test_synthesis_attaches_authoritative_facts(
    monkeypatch,
):
    payload = _model_payload()

    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(payload),
    )

    context = _context()

    report = final_report.synthesize_final_report(
        context=context,
        llm=object(),
    )

    assert (
        report["authoritative_facts"]
        == context["authoritative_facts"]
    )

    # The report must contain an independent deep copy.
    assert (
        report["authoritative_facts"]
        is not context["authoritative_facts"]
    )

    assert (
        report["required_disclosures"][
            "execution_authorization"
        ]
        == "NOT_GRANTED"
    )

def test_valid_final_report_passes(
    monkeypatch,
):
    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            _model_payload()
        ),
    )

    context = _context()

    report = (
        final_report.synthesize_final_report(
            context=context,
            llm=object(),
        )
    )

    result = (
        final_report.validate_final_report(
            report=report,
            context=context,
            inventory=_inventory(),
        )
    )

    assert result["is_valid"]
    assert result["status"] == "PASS"


def test_fact_change_fails_validation(
    monkeypatch,
):
    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            _model_payload()
        ),
    )

    context = _context()

    report = (
        final_report.synthesize_final_report(
            context=context,
            llm=object(),
        )
    )

    report[
        "authoritative_facts"
    ][
        "annex_c"
    ][
        "threat_score"
    ] = 0.99

    result = (
        final_report.validate_final_report(
            report=report,
            context=context,
            inventory=_inventory(),
        )
    )

    assert not result["is_valid"]

    assert any(
        error["code"]
        == "AUTHORITATIVE_FACT_MISMATCH"
        for error in result["errors"]
    )


def test_markdown_preserves_not_granted(
    monkeypatch,
):
    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            _model_payload()
        ),
    )

    report = (
        final_report.synthesize_final_report(
            context=_context(),
            llm=object(),
        )
    )

    markdown = (
        final_report
        .render_final_report_markdown(
            report
        )
    )

    assert (
        "Execution authorization:** "
        "`NOT_GRANTED`"
        in markdown
    )

    assert (
        "KCAG traversal scores are configured "
        "heuristics"
        in markdown
    )


def test_synthesis_normalizes_model_generated_ids(
    monkeypatch,
):
    payload = _model_payload()

    # Simulate malformed identifiers returned by the local model.
    payload["report_id"] = 17

    for finding in payload["key_findings"]:
        finding["finding_id"] = {
            "value": "invalid"
        }

    for recommendation in payload["recommendations"]:
        recommendation["recommendation_id"] = 99

    for limitation in payload["limitations"]:
        limitation["item_id"] = None

    for unresolved in payload["unresolved_items"]:
        unresolved["item_id"] = [
            "invalid"
        ]

    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(payload),
    )

    report = final_report.synthesize_final_report(
        context=_context(),
        llm=object(),
    )

    assert report["report_id"] == "FR-001"

    assert [
        item["finding_id"]
        for item in report["key_findings"]
    ] == [
        "FR-F-001",
        "FR-F-002",
        "FR-F-003",
    ]

    assert [
        item["recommendation_id"]
        for item in report["recommendations"]
    ] == [
        "FR-R-001",
        "FR-R-002",
        "FR-R-003",
    ]

    assert report["limitations"][0]["item_id"] == (
        "FR-L-001"
    )

    assert (
        report["unresolved_items"][0]["item_id"]
        == "FR-U-001"
    )



def test_synthesis_normalizes_wrapped_text_fields(
    monkeypatch,
):
    payload = _model_payload()

    payload["title"] = {
        "text": "Incorrect model title"
    }

    payload["executive_summary"] = [
        "First summary paragraph.",
        {
            "text": "Second summary paragraph."
        },
    ]

    payload["scope_and_methodology"] = {
        "content": "Verified methodology."
    }

    payload["overall_assessment"][
        "rationale"
    ] = {
        "value": "Verified rationale."
    }

    payload["stage_narratives"]["stage0"] = {
        "summary": "Normalized Stage 0 summary."
    }

    payload["key_findings"][0]["title"] = {
        "text": "Normalized finding title"
    }

    payload["recommendations"][0]["action"] = [
        "First action paragraph.",
        "Second action paragraph.",
    ]

    payload["limitations"][0][
        "source_artifacts"
    ] = {
        "artifacts": [
            "annexB_kcag.md"
        ]
    }

    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(payload),
    )

    report = final_report.synthesize_final_report(
        context=_context(),
        llm=object(),
    )

    assert report["title"] == (
        "Comprehensive Final Assessment Report"
    )

    assert report["executive_summary"] == (
        "First summary paragraph.\n\n"
        "Second summary paragraph."
    )

    assert report["scope_and_methodology"] == (
        "Verified methodology."
    )

    assert report[
        "overall_assessment"
    ]["rationale"] == "Verified rationale."

    assert report[
        "stage_narratives"
    ]["stage0"] == (
        "Normalized Stage 0 summary."
    )

    assert report[
        "key_findings"
    ][0]["title"] == (
        "Normalized finding title"
    )

    assert report[
        "recommendations"
    ][0]["action"] == (
        "First action paragraph.\n\n"
        "Second action paragraph."
    )

    assert report[
        "limitations"
    ][0]["source_artifacts"] == [
        "annexB_kcag.md"
    ]


def test_synthesis_fills_missing_required_narratives(
    monkeypatch,
):
    payload = _model_payload()

    payload["executive_summary"] = None
    payload["scope_and_methodology"] = {}
    payload["overall_assessment"]["rationale"] = None
    payload["stage_narratives"]["stage0"] = None

    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(payload),
    )

    context = _context()

    report = final_report.synthesize_final_report(
        context=context,
        llm=object(),
    )

    assert report["executive_summary"]
    assert (
        "Execution authorization remains NOT_GRANTED"
        in report["executive_summary"]
    )

    assert report["scope_and_methodology"]
    assert report[
        "overall_assessment"
    ]["rationale"]

    assert report[
        "stage_narratives"
    ]["stage0"] == (
        "Verified Stage 0 source narrative."
    )


def test_synthesis_uses_safe_enum_fallbacks(
    monkeypatch,
):
    payload = _model_payload()

    payload["overall_assessment"]["risk_level"] = {
        "unexpected": "unknown value"
    }
    payload["overall_assessment"]["confidence"] = None

    payload["key_findings"][0]["severity"] = [
        "not",
        "a",
        "rating",
    ]
    payload["key_findings"][0]["confidence"] = {}

    payload["recommendations"][0]["priority"] = {
        "value": "something else"
    }

    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(payload),
    )

    report = final_report.synthesize_final_report(
        context=_context(),
        llm=object(),
    )

    assert (
        report["overall_assessment"]["risk_level"]
        == "NOT_RATED"
    )
    assert (
        report["overall_assessment"]["confidence"]
        == "UNSPECIFIED"
    )
    assert (
        report["key_findings"][0]["severity"]
        == "NOT_RATED"
    )
    assert (
        report["key_findings"][0]["confidence"]
        == "UNSPECIFIED"
    )
    assert (
        report["recommendations"][0]["priority"]
        == "UNSPECIFIED"
    )


def test_synthesis_normalizes_non_object_overall_assessment(
    monkeypatch,
):
    payload = _model_payload()

    payload["overall_assessment"] = [
        {
            "risk_level": {
                "value": "unrecognized rating"
            },
            "confidence": [
                "not specified"
            ],
            "rationale": {
                "text": "Verified assessment rationale."
            },
        }
    ]

    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(payload),
    )

    report = final_report.synthesize_final_report(
        context=_context(),
        llm=object(),
    )

    assert report[
        "overall_assessment"
    ] == {
        "risk_level": "NOT_RATED",
        "confidence": "UNSPECIFIED",
        "rationale": "Verified assessment rationale.",
    }


def test_synthesis_backfills_missing_collections(
    monkeypatch,
):
    payload = _model_payload()

    payload["key_findings"] = []
    payload["recommendations"] = None
    payload["limitations"] = []
    payload["unresolved_items"] = "invalid"

    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(payload),
    )

    report = final_report.synthesize_final_report(
        context=_context(),
        llm=object(),
    )

    assert len(report["key_findings"]) >= 3
    assert len(report["recommendations"]) >= 3
    assert len(report["limitations"]) >= 1
    assert report["unresolved_items"] == []

    assert report["key_findings"][0][
        "finding_id"
    ] == "FR-F-001"

    assert report["recommendations"][0][
        "recommendation_id"
    ] == "FR-R-001"

    assert report["limitations"][0][
        "item_id"
    ] == "FR-L-001"

    assert all(
        item["source_artifacts"]
        for item in report["key_findings"]
    )



def _write_valid_final_completion(
    tmp_path,
):
    identity = {
        "run_id": "vaf_completion_test",
        "corpus_manifest_hash": (
            "sha256:completion-test"
        ),
        "generated_at": (
            "2026-07-17T00:00:00Z"
        ),
    }

    context = {
        "assessment_identity": identity,
        "context_hash": "sha256:context",
    }

    inventory = {
        "run_id": identity["run_id"],
        "corpus_manifest_hash": (
            identity[
                "corpus_manifest_hash"
            ]
        ),
        "artifact_count": 1,
        "artifacts": [],
    }

    report = {
        "assessment_identity": identity,
        "context_hash": "sha256:context",
        "required_disclosures": {
            "execution_authorization": (
                "NOT_GRANTED"
            )
        },
    }

    validation = {
        "status": "PASS",
        "is_valid": True,
    }

    final_report.run_context.write_stamped_json(
        str(
            tmp_path
            / final_report.FINAL_CONTEXT_NAME
        ),
        context,
    )
    final_report.run_context.write_stamped_json(
        str(
            tmp_path
            / final_report.ARTIFACT_INVENTORY_NAME
        ),
        inventory,
    )
    final_report.run_context.write_stamped_json(
        str(
            tmp_path
            / final_report.FINAL_JSON_NAME
        ),
        report,
    )

    markdown_path = (
        tmp_path
        / final_report.FINAL_MARKDOWN_NAME
    )
    markdown_path.write_text(
        "# Completed report\n",
        encoding="utf-8",
    )
    final_report.run_context.stamp_prose_file(
        str(markdown_path)
    )

    final_report.run_context.write_stamped_json(
        str(
            tmp_path
            / final_report.FINAL_VALIDATION_NAME
        ),
        validation,
    )

    report_path = (
        tmp_path
        / final_report.FINAL_JSON_NAME
    )

    completion = {
        "status": "COMPLETE",
        "run_id": identity["run_id"],
        "corpus_manifest_hash": (
            identity[
                "corpus_manifest_hash"
            ]
        ),
        "final_report_json": (
            final_report.FINAL_JSON_NAME
        ),
        "final_report_json_sha256": (
            final_report.sha256_file(
                report_path
            )
        ),
        "final_report_markdown": (
            final_report.FINAL_MARKDOWN_NAME
        ),
        "final_report_markdown_sha256": (
            final_report.sha256_file(
                markdown_path
            )
        ),
        "final_report_validation": (
            final_report.FINAL_VALIDATION_NAME
        ),
        "final_report_validation_status": (
            "PASS"
        ),
        "context_hash": "sha256:context",
        "execution_authorization": (
            "NOT_GRANTED"
        ),
    }

    final_report.run_context.write_stamped_json(
        str(
            tmp_path
            / final_report.COMPLETION_NAME
        ),
        completion,
    )


def test_existing_final_report_is_reused(
    tmp_path,
    monkeypatch,
):
    final_report.run_context.reset_active_run()

    try:
        final_report.run_context.set_active_run(
            run_id="vaf_completion_test",
            corpus_manifest_hash=(
                "sha256:completion-test"
            ),
            out_dir=str(tmp_path),
        )

        _write_valid_final_completion(
            tmp_path
        )

        def fail_if_generated(**kwargs):
            raise AssertionError(
                "Generator should not run when "
                "completion is valid."
            )

        monkeypatch.setattr(
            final_report,
            "generate_and_validate_final_report",
            fail_if_generated,
        )

        outcome = (
            final_report
            .generate_or_reuse_final_report(
                out_dir=str(tmp_path),
                llm=object(),
            )
        )

        assert outcome["reused"] is True
        assert outcome["quarantine"] is None

        verified = (
            final_report
            .validate_existing_final_report(
                tmp_path
            )
        )

        assert verified["is_valid"] is True

    finally:
        final_report.run_context.reset_active_run()


def test_existing_final_report_detects_tampering(
    tmp_path,
):
    final_report.run_context.reset_active_run()

    try:
        final_report.run_context.set_active_run(
            run_id="vaf_completion_test",
            corpus_manifest_hash=(
                "sha256:completion-test"
            ),
            out_dir=str(tmp_path),
        )

        _write_valid_final_completion(
            tmp_path
        )

        markdown_path = (
            tmp_path
            / final_report.FINAL_MARKDOWN_NAME
        )

        with markdown_path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                "\nUnauthorized modification.\n"
            )

        verified = (
            final_report
            .validate_existing_final_report(
                tmp_path
            )
        )

        assert verified["is_valid"] is False
        assert any(
            "Markdown hash mismatch"
            in error
            for error in verified["errors"]
        )

    finally:
        final_report.run_context.reset_active_run()


def test_markdown_can_record_validation_pass(
    monkeypatch,
):
    monkeypatch.setattr(
        final_report,
        "generate_structured_json",
        lambda **kwargs: json.dumps(
            _model_payload()
        ),
    )

    report = final_report.synthesize_final_report(
        context=_context(),
        llm=object(),
    )

    markdown = (
        final_report
        .render_final_report_markdown(
            report,
            validation_status="PASS",
        )
    )

    assert (
        "**Final-report validation:** PASS"
        in markdown
    )

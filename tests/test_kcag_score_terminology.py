"""
Tests for the KCAG probability-to-heuristic-score terminology migration:
kcag_min_cut's renamed internals (TRAVERSAL_SCORE_BY_DIFFICULTY, score
instead of probability, top_path_score instead of top_path_prob, schema
version 2 with scoring_model metadata), extract_kcag_objective_score()
(the backward-compatible reader that lets a resumed run consume a
pre-migration kcag_report.json), and bbn_threat_score's updated KCAG
ingestion.

The algorithm itself does not change in this commit -- only names and
metadata. Every numerical-non-regression test below asserts an EXACT
expected value computed by hand from TRAVERSAL_SCORE_BY_DIFFICULTY, not
just "some value came back."

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import json

import pytest

from src import run_context
from src.tools import (
    kcag_min_cut,
    bbn_threat_score,
    extract_kcag_objective_score,
    TRAVERSAL_SCORE_BY_DIFFICULTY,
)


@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    run_context.reset_active_run()
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.set_active_run("test-run", "sha256:test-corpus-hash", str(out_dir))
    yield out_dir
    run_context.reset_active_run()


def _write_graph(nodes, edges):
    path = run_context.artifact_path("stage2_vectors.json")
    run_context.write_stamped_json(path, {"nodes": nodes, "edges": edges})
    return path


def _simple_graph(diff1="LOW", diff2="MEDIUM"):
    """ADV_START -> N1 -> G1, one edge of each given difficulty."""
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "N1", "difficulty": diff1, "effect": None, "vec": "V-01"},
        {"source": "N1", "target": "G1", "difficulty": diff2, "effect": None, "vec": "V-02"},
    ]
    return nodes, edges


def _collect_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _collect_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _collect_keys(child)


def _run_kcag_and_get_report():
    result = kcag_min_cut._run()
    report = run_context.read_stamped_json(run_context.artifact_path("kcag_report.json"))
    return result, report


# ---------------------------------------------------------------------------
# New report contract
# ---------------------------------------------------------------------------

def test_new_kcag_report_has_schema_version_2():
    _write_graph(*_simple_graph())
    _, report = _run_kcag_and_get_report()
    assert report["schema_version"] == 2


def test_new_report_has_scoring_model_metadata():
    _write_graph(*_simple_graph())
    _, report = _run_kcag_and_get_report()
    model = report["scoring_model"]
    assert model["calibrated_probability"] is False
    assert model["semantics"] == "heuristic_relative_ranking"
    assert model["range"] == [0.0, 1.0]
    assert model["aggregation"] == "product"
    assert model["score_by_difficulty"] == TRAVERSAL_SCORE_BY_DIFFICULTY


def test_new_report_uses_top_path_score():
    _write_graph(*_simple_graph())
    _, report = _run_kcag_and_get_report()
    assert "top_path_score" in report["objective_results"]["G1"]
    assert "top_path_prob" not in report["objective_results"]["G1"]


def test_new_report_uses_score_for_ranked_paths():
    _write_graph(*_simple_graph())
    _, report = _run_kcag_and_get_report()
    assert all("score" in p and "probability" not in p for p in report["top_paths"])
    assert "score" in report["priority_path"]
    assert "probability" not in report["priority_path"]


def test_new_report_contains_no_probability_keys():
    _write_graph(*_simple_graph())
    _, report = _run_kcag_and_get_report()
    keys = set(_collect_keys(report))
    assert "probability" not in keys
    assert "top_path_prob" not in keys


def test_human_summary_uses_score_not_probability():
    _write_graph(*_simple_graph())
    result, _ = _run_kcag_and_get_report()
    assert "S=0.4" in result
    assert "P=" not in result
    assert "highest heuristic traversal score" in result
    assert "not an empirically calibrated probability" in result


# ---------------------------------------------------------------------------
# Numerical non-regression -- exact values, not just "something returned"
# ---------------------------------------------------------------------------

def test_score_migration_preserves_path_values():
    """The reviewer's own worked example: one LOW edge (0.8) times one
    MEDIUM edge (0.5) = 0.4 exactly."""
    _write_graph(*_simple_graph("LOW", "MEDIUM"))
    _, report = _run_kcag_and_get_report()
    assert report["objective_results"]["G1"]["top_path_score"] == 0.4


def test_score_migration_preserves_priority_path():
    _write_graph(*_simple_graph("LOW", "MEDIUM"))
    _, report = _run_kcag_and_get_report()
    assert report["priority_path"]["score"] == 0.4
    assert report["priority_path"]["path"] == ["ADV_START", "N1", "G1"]


def test_low_difficulty_edge_scores_higher_than_high():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G_LOW", "node_type": "goal", "criticality": 10},
        {"id": "G_HIGH", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "G_LOW", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "ADV_START", "target": "G_HIGH", "difficulty": "HIGH", "effect": None, "vec": "V-02"},
    ]
    _write_graph(nodes, edges)
    _, report = _run_kcag_and_get_report()
    assert report["objective_results"]["G_LOW"]["top_path_score"] > report["objective_results"]["G_HIGH"]["top_path_score"]
    assert report["objective_results"]["G_LOW"]["top_path_score"] == 0.8
    assert report["objective_results"]["G_HIGH"]["top_path_score"] == 0.2


def test_path_score_remains_multiplicative():
    """Three edges: LOW * MEDIUM * HIGH = 0.8 * 0.5 * 0.2 = 0.08"""
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 3},
        {"id": "N2", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "N1", "target": "N2", "difficulty": "MEDIUM", "effect": None, "vec": "V-02"},
        {"source": "N2", "target": "G1", "difficulty": "HIGH", "effect": None, "vec": "V-03"},
    ]
    _write_graph(nodes, edges)
    _, report = _run_kcag_and_get_report()
    assert report["objective_results"]["G1"]["top_path_score"] == 0.08


# ---------------------------------------------------------------------------
# Compatibility reader: extract_kcag_objective_score
# ---------------------------------------------------------------------------

def test_score_reader_accepts_schema_v2():
    r = extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": 0.4}}})
    assert r == {"score": 0.4, "used_legacy_field": False, "source_field": "top_path_score"}


def test_score_reader_accepts_legacy_top_path_prob():
    r = extract_kcag_objective_score({"objective_results": {"G1": {"top_path_prob": 0.4}}})
    assert r == {"score": 0.4, "used_legacy_field": True, "source_field": "top_path_prob"}


def test_score_reader_records_legacy_usage():
    r = extract_kcag_objective_score({"objective_results": {"G1": {"top_path_prob": 0.4}}})
    assert r["used_legacy_field"] is True


def test_score_reader_prefers_current_field_when_equal():
    r = extract_kcag_objective_score({"objective_results": {
        "G1": {"top_path_score": 0.4, "top_path_prob": 0.4}
    }})
    assert r["used_legacy_field"] is False
    assert r["source_field"] == "top_path_score"


def test_score_reader_rejects_conflicting_dual_fields():
    with pytest.raises(ValueError, match="conflicting"):
        extract_kcag_objective_score({"objective_results": {
            "G1": {"top_path_score": 0.4, "top_path_prob": 0.9}
        }})


def test_score_reader_rejects_missing_score_field():
    with pytest.raises(ValueError, match="neither"):
        extract_kcag_objective_score({"objective_results": {"G1": {}}})


@pytest.mark.parametrize("bad_value,match", [
    ("not a number", "must be numeric"),
    (True, "must be numeric"),
    (float("nan"), "must be finite"),
    (float("inf"), "must be finite"),
    (-0.5, "must be between 0 and 1"),
    (1.5, "must be between 0 and 1"),
])
def test_score_reader_rejects_invalid_values(bad_value, match):
    with pytest.raises(ValueError, match=match):
        extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": bad_value}}})


def test_score_reader_rejects_string_value():
    with pytest.raises(ValueError, match="must be numeric"):
        extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": "0.4"}}})


def test_score_reader_rejects_boolean_value():
    with pytest.raises(ValueError, match="must be numeric"):
        extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": True}}})


def test_score_reader_rejects_nan():
    with pytest.raises(ValueError, match="must be finite"):
        extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": float("nan")}}})


def test_score_reader_rejects_infinity():
    with pytest.raises(ValueError, match="must be finite"):
        extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": float("inf")}}})


def test_score_reader_rejects_negative_value():
    with pytest.raises(ValueError, match="must be between 0 and 1"):
        extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": -0.1}}})


def test_score_reader_rejects_value_above_one():
    with pytest.raises(ValueError, match="must be between 0 and 1"):
        extract_kcag_objective_score({"objective_results": {"G1": {"top_path_score": 1.1}}})


def test_score_reader_rejects_empty_objective_results():
    with pytest.raises(ValueError, match="no non-empty objective_results"):
        extract_kcag_objective_score({"objective_results": {}})


def test_score_reader_takes_max_across_objectives():
    r = extract_kcag_objective_score({"objective_results": {
        "G1": {"top_path_score": 0.2}, "G2": {"top_path_score": 0.6},
    }})
    assert r["score"] == 0.6


# ---------------------------------------------------------------------------
# BBN integration
# ---------------------------------------------------------------------------

_BBN_CFG = json.dumps({
    "adversary": {"capability_prior": [0.1, 0.2, 0.7], "tempo": "HIGH"},
    "defensive_posture": {"mfa": True, "edr": False, "segmentation": False,
                          "integrity_monitor": False, "email_filtering": True},
    "geopolitical_trigger_prior": 0.5,
})


def _run_bbn():
    return bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")


def test_bbn_accepts_new_kcag_score_report():
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "schema_version": 2, "objective_results": {"G1": {"top_path_score": 0.4}},
    })
    result = _run_bbn()
    assert not result.startswith("ERROR")
    assert "KCAG heuristic factor: 0.4000" in result
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    assert report["kcag_objective_score"] == 0.4
    assert report["kcag_used_legacy_field"] is False


def test_bbn_accepts_legacy_report_on_resume():
    """The most important compatibility scenario: Annex B already ran
    under old code (report has no schema_version, uses top_path_prob),
    resume skips Annex B, Annex C still must succeed."""
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "objective_results": {"G1": {"top_path_prob": 0.4}},
    })
    result = _run_bbn()
    assert not result.startswith("ERROR")
    assert "KCAG heuristic factor: 0.4000" in result
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    assert report["kcag_objective_score"] == 0.4
    assert report["kcag_used_legacy_field"] is True


def test_bbn_audit_labels_legacy_value_as_heuristic():
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "objective_results": {"G1": {"top_path_prob": 0.4}},
    })
    _run_bbn()
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    audit = report["cpd_audit_log"]
    entries = [e for e in audit if "KCAG" in str(e)]
    assert any("heuristic" in str(e).lower() for e in entries)
    assert any("legacy" in str(e).lower() for e in entries)


def test_bbn_rejects_conflicting_score_fields():
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "objective_results": {"G1": {"top_path_score": 0.4, "top_path_prob": 0.9}},
    })
    result = _run_bbn()
    assert result.startswith("ERROR")
    assert "conflicting" in result.lower()


def test_bbn_rejects_malformed_kcag_score():
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "objective_results": {"G1": {"top_path_score": 1.5}},
    })
    result = _run_bbn()
    assert result.startswith("ERROR")


def test_bbn_does_not_call_kcag_score_a_prior():
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "schema_version": 2, "objective_results": {"G1": {"top_path_score": 0.4}},
    })
    result = _run_bbn()
    assert "kcag_objective_prior" not in result.lower()
    assert "KCAG prior" not in result
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    assert "kcag_objective_prior" not in report
    assert "kcag_objective_score" in report


def test_bbn_numerical_output_identical_across_schema_versions():
    """The central non-regression guarantee: whether Annex C reads a
    schema-v2 or a legacy report, the resulting threat_score must be
    byte-identical -- the migration changes names and metadata only."""
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "schema_version": 2, "objective_results": {"G1": {"top_path_score": 0.4}},
    })
    _run_bbn()
    report_v2 = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))

    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "objective_results": {"G1": {"top_path_prob": 0.4}},
    })
    _run_bbn()
    report_legacy = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))

    assert report_v2["threat_score"] == report_legacy["threat_score"]
    assert report_v2["phase_distribution"] == report_legacy["phase_distribution"]
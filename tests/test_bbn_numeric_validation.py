"""
Tests for deterministic numeric validation of BBN inputs and priors:
src/bbn_validation.py, its integration into bbn_threat_score() (rejecting
malformed input before any pgmpy model construction), and preflight_check.py
using the SAME validator (not a second, independent implementation).

This commit does not add sensitivity analysis and does not change valid-
model formulas or BBN topology -- the numerical regression tests below
confirm the actual threat_score output is unchanged for a fixed valid
configuration, with the one deliberate, documented exception (capability_
prior is no longer silently floored/renormalized).

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import json
from unittest.mock import patch

import pytest

# Pre-import pgmpy's submodules for real, before any test below patches
# pgmpy.models.DiscreteBayesianNetwork / pgmpy.factors.discrete.TabularCPD.
# pgmpy.inference.ExactInference does `from pgmpy.models import
# DiscreteBayesianNetwork` at ITS OWN module level -- if that import
# happens for the first time in this process while a test's mock.patch is
# active, ExactInference permanently captures the mock (a separate name
# binding in a different module's namespace), and unpatching afterward
# does NOT undo that, since the patch context manager only restores
# pgmpy.models' own attribute, not other modules that already copied a
# reference to it. Importing for real here, before any test runs, avoids
# the whole class of pollution regardless of test execution order.
import pgmpy.inference       # noqa: F401
import pgmpy.models          # noqa: F401
import pgmpy.factors.discrete  # noqa: F401

from src import run_context
from src.tools import bbn_threat_score
from src.bbn_validation import (
    validate_bbn_assessment_config,
    validate_bbn_priors_document,
    _validate_finite_number,
    _validate_probability_vector,
    _validate_delta_vector,
    _validate_cpd_matrix,
    format_bbn_validation_error,
    PROBABILITY_SUM_TOLERANCE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    run_context.reset_active_run()
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.set_active_run("test-run", "sha256:test-corpus-hash", str(out_dir))
    yield out_dir
    run_context.reset_active_run()


@pytest.fixture
def priors_document():
    return json.load(open("config/bbn_priors.json"))


@pytest.fixture
def valid_assessment_config():
    return {
        "adversary": {"capability_prior": [0.1, 0.2, 0.7], "tempo": "HIGH"},
        "defensive_posture": {"mfa": True, "edr": False, "segmentation": False,
                              "integrity_monitor": False, "email_filtering": True},
        "geopolitical_trigger_prior": 0.5,
    }


def _write_kcag_report(score=0.4):
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), {
        "schema_version": 2, "objective_results": {"G1": {"top_path_score": score}},
    })


# ---------------------------------------------------------------------------
# Numeric primitive tests
# ---------------------------------------------------------------------------

def test_probability_rejects_boolean():
    assert _validate_finite_number(True, path="x", minimum=0.0, maximum=1.0)


def test_probability_rejects_string():
    assert _validate_finite_number("0.5", path="x", minimum=0.0, maximum=1.0)


def test_probability_rejects_nan():
    assert _validate_finite_number(float("nan"), path="x", minimum=0.0, maximum=1.0)


def test_probability_rejects_positive_infinity():
    assert _validate_finite_number(float("inf"), path="x", minimum=0.0, maximum=1.0)


def test_probability_rejects_negative_infinity():
    assert _validate_finite_number(float("-inf"), path="x", minimum=0.0, maximum=1.0)


def test_probability_rejects_negative_value():
    assert _validate_finite_number(-0.1, path="x", minimum=0.0, maximum=1.0)


def test_probability_rejects_value_above_one():
    assert _validate_finite_number(1.1, path="x", minimum=0.0, maximum=1.0)


def test_probability_vector_rejects_wrong_length():
    errs = _validate_probability_vector([0.5, 0.5], path="x", expected_length=3)
    assert any(e["code"] == "INVALID_LENGTH" for e in errs)


def test_probability_vector_rejects_wrong_sum():
    errs = _validate_probability_vector([0.2, 0.3, 0.6], path="x", expected_length=3)
    assert any(e["code"] == "PROBABILITY_SUM" for e in errs)


def test_probability_vector_accepts_zero():
    assert _validate_probability_vector([0.0, 0.0, 1.0], path="x", expected_length=3) == []


def test_probability_vector_uses_tight_tolerance():
    assert _validate_probability_vector([0.1, 0.2, 0.7 + 1e-10], path="x", expected_length=3) == []
    assert _validate_probability_vector([0.1, 0.2, 0.7 + 1e-6], path="x", expected_length=3) != []


def test_delta_vector_rejects_wrong_sum():
    errs = _validate_delta_vector([-0.1, 0.2, 0.0, 0.0], path="x", expected_length=4)
    assert any(e["code"] == "DELTA_SUM" for e in errs)


def test_delta_vector_accepts_negative_values():
    assert _validate_delta_vector([-0.1, 0.1, 0.0, 0.0], path="x", expected_length=4) == []


def test_cpd_matrix_validates_columns_not_rows():
    """A matrix whose ROWS happen to sum to 1.0 but whose COLUMNS do not
    must still fail -- proves the implementation checks the correct axis."""
    matrix = [[0.5, 0.3, 0.2], [0.5, 0.3, 0.2]]  # rows sum to 1.0; col1=0.6, col2=0.4
    errs = _validate_cpd_matrix(matrix, path="x", rows=2, columns=3)
    assert any(e["code"] == "CPD_COLUMN_SUM" for e in errs)


def test_cpd_matrix_accepts_valid_shape():
    matrix = [[0.90, 0.50, 0.15], [0.10, 0.50, 0.85]]
    assert _validate_cpd_matrix(matrix, path="x", rows=2, columns=3) == []


# ---------------------------------------------------------------------------
# Per-assessment input tests
# ---------------------------------------------------------------------------

def test_valid_assessment_config_passes(valid_assessment_config):
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is True


def test_capability_prior_must_have_three_states(valid_assessment_config):
    valid_assessment_config["adversary"]["capability_prior"] = [0.5, 0.5]
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False


def test_capability_prior_must_sum_to_one(valid_assessment_config):
    valid_assessment_config["adversary"]["capability_prior"] = [0.2, 0.3, 0.6]
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    assert any(e["code"] == "PROBABILITY_SUM" for e in r["errors"])


def test_capability_zero_is_preserved(valid_assessment_config):
    """[0.0, 0.05, 0.95] is a valid distribution -- the value itself is
    tested for reaching the CPD unchanged in the runtime integration
    section below; here we confirm the validator accepts it."""
    valid_assessment_config["adversary"]["capability_prior"] = [0.0, 0.05, 0.95]
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is True


@pytest.mark.parametrize("bad_tempo", ["low", "High", "FAST", 1, None])
def test_tempo_must_be_exact_enum(valid_assessment_config, bad_tempo):
    valid_assessment_config["adversary"]["tempo"] = bad_tempo
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False


def test_posture_requires_all_controls(valid_assessment_config):
    del valid_assessment_config["defensive_posture"]["edr"]
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    assert any(e["code"] == "MISSING_CONTROL" for e in r["errors"])


def test_posture_rejects_unknown_controls(valid_assessment_config):
    valid_assessment_config["defensive_posture"]["firewall"] = True
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    assert any(e["code"] == "UNKNOWN_CONTROL" for e in r["errors"])


def test_posture_rejects_integer_flags(valid_assessment_config):
    valid_assessment_config["defensive_posture"]["edr"] = 1
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    assert any(e["code"] == "NOT_BOOLEAN" for e in r["errors"])


def test_geo_prior_must_be_finite_probability(valid_assessment_config):
    valid_assessment_config["geopolitical_trigger_prior"] = 1.5
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False


def test_evidence_is_optional(valid_assessment_config):
    assert "evidence" not in valid_assessment_config
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is True


def test_unknown_evidence_node_fails(valid_assessment_config):
    valid_assessment_config["evidence"] = {"UnknownNode": 0}
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    assert any(e["code"] == "UNKNOWN_EVIDENCE_NODE" for e in r["errors"])


def test_evidence_boolean_fails(valid_assessment_config):
    valid_assessment_config["evidence"] = {"AuthAnomaly": True}
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    assert any(e["code"] == "STATE_NOT_INTEGER" for e in r["errors"])


def test_evidence_state_out_of_range_fails(valid_assessment_config):
    valid_assessment_config["evidence"] = {"AdversaryCapability": 3}
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    assert any(e["code"] == "STATE_OUT_OF_RANGE" for e in r["errors"])


def test_kcag_path_must_be_nonempty_string_when_supplied(valid_assessment_config):
    valid_assessment_config["kcag_report_path"] = ""
    r = validate_bbn_assessment_config(valid_assessment_config)
    assert r["is_valid"] is False
    valid_assessment_config["kcag_report_path"] = None  # explicit null is fine (means unset)
    r2 = validate_bbn_assessment_config(valid_assessment_config)
    assert r2["is_valid"] is True


# ---------------------------------------------------------------------------
# Priors document tests
# ---------------------------------------------------------------------------

def test_current_bbn_priors_file_passes(priors_document):
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is True, r["errors"]


def test_missing_required_prior_fails(priors_document):
    del priors_document["priors"]["auth_anomaly_root"]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "MISSING_REQUIRED_PRIOR" for e in r["errors"])


def test_prior_requires_value(priors_document):
    del priors_document["priors"]["defensive_posture_floor"]["value"]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "MISSING_VALUE" for e in r["errors"])


def test_prior_requires_nonempty_source(priors_document):
    priors_document["priors"]["defensive_posture_floor"]["source"] = "   "
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "EMPTY_SOURCE" for e in r["errors"])


def test_tempo_distributions_have_three_states(priors_document):
    priors_document["priors"]["operational_tempo_distribution"]["LOW"]["value"] = [0.6, 0.4]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False


def test_tempo_distributions_sum_to_one(priors_document):
    priors_document["priors"]["operational_tempo_distribution"]["LOW"]["value"] = [0.6, 0.3, 0.2]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "PROBABILITY_SUM" for e in r["errors"])


def test_auth_root_has_two_states(priors_document):
    priors_document["priors"]["auth_anomaly_root"]["value"] = [0.5, 0.3, 0.2]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False


def test_cpd_matrix_shape_is_enforced(priors_document):
    priors_document["priors"]["phishing_given_capability"]["value"] = [[0.9, 0.5], [0.1, 0.5]]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False


def test_cpd_columns_must_sum_to_one(priors_document):
    priors_document["priors"]["phishing_given_capability"]["value"] = [[0.90, 0.50, 0.15], [0.10, 0.50, 1.00]]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "CPD_COLUMN_SUM" for e in r["errors"])


def test_phase_bases_have_four_states(priors_document):
    priors_document["priors"]["killchain_phase_base"]["nation_state"]["value"] = [0.5, 0.3, 0.2]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False


def test_delta_must_have_four_values(priors_document):
    priors_document["priors"]["killchain_phase_evidence_delta_phishing"]["value"] = [-0.1, 0.1, 0.0]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False


def test_delta_must_sum_to_zero(priors_document):
    priors_document["priors"]["killchain_phase_evidence_delta_phishing"]["value"] = [-0.1, 0.2, 0.0, 0.0]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "DELTA_SUM" for e in r["errors"])


def test_combined_deltas_cannot_create_negative_phase_mass(priors_document):
    """Individually well-formed deltas that, combined, drive a phase
    component negative must be caught -- this is exactly the check a
    per-field validator alone would miss."""
    priors_document["priors"]["killchain_phase_evidence_delta_auth_anomaly"]["value"] = [0.0, -0.5, 0.5, 0.0]
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] in ("COMBINED_PHASE_NEGATIVE", "COMBINED_PHASE_SUM") for e in r["errors"])


def test_scalar_probability_bounds(priors_document):
    priors_document["priors"]["defensive_posture_floor"]["value"] = 0.9  # max is 0.5
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "ABOVE_MAXIMUM" for e in r["errors"])


def test_multiplier_may_exceed_one_where_allowed(priors_document):
    priors_document["priors"]["iw_effect_geo_multiplier"]["value"] = 3.0
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is True, r["errors"]


def test_convergence_factor_must_be_positive(priors_document):
    priors_document["priors"]["iw_effect_objective_convergence_factor"]["value"] = 0.0
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "NOT_ABOVE_EXCLUSIVE_MINIMUM" for e in r["errors"])


def test_strong_posture_multiplier_not_above_moderate(priors_document):
    priors_document["priors"]["iw_effect_posture_multiplier_strong"]["value"] = 0.9
    priors_document["priors"]["iw_effect_posture_multiplier_moderate"]["value"] = 0.5
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "POSTURE_MULTIPLIER_ORDER" for e in r["errors"])


def test_phase_bases_are_monotonic(priors_document):
    priors_document["priors"]["iw_effect_phase_base_lateral"]["value"] = 0.01  # below initial_access
    r = validate_bbn_priors_document(priors_document)
    assert r["is_valid"] is False
    assert any(e["code"] == "PHASE_BASE_NOT_MONOTONIC" for e in r["errors"])


# ---------------------------------------------------------------------------
# Runtime integration tests
# ---------------------------------------------------------------------------

def test_bbn_rejects_invalid_config_before_model_construction(valid_assessment_config):
    _write_kcag_report()
    valid_assessment_config["adversary"]["tempo"] = "FAST"
    with patch("pgmpy.models.DiscreteBayesianNetwork") as mock_model, \
         patch("pgmpy.factors.discrete.TabularCPD") as mock_cpd:
        result = bbn_threat_score.func(cpd_config_json=json.dumps(valid_assessment_config),
                                       priors_path="config/bbn_priors.json")
        assert result.startswith("ERROR:")
        assert mock_model.call_count == 0
        assert mock_cpd.call_count == 0


def test_bbn_rejects_invalid_priors_before_model_construction(valid_assessment_config, priors_document, tmp_path):
    _write_kcag_report()
    priors_document["priors"]["phishing_given_capability"]["value"] = [[0.90, 0.50, 0.15], [0.10, 0.50, 1.00]]
    bad_priors_path = str(tmp_path / "bad_priors.json")
    json.dump(priors_document, open(bad_priors_path, "w"))
    with patch("pgmpy.models.DiscreteBayesianNetwork") as mock_model, \
         patch("pgmpy.factors.discrete.TabularCPD") as mock_cpd:
        result = bbn_threat_score.func(cpd_config_json=json.dumps(valid_assessment_config),
                                       priors_path=bad_priors_path)
        assert result.startswith("ERROR:")
        assert mock_model.call_count == 0
        assert mock_cpd.call_count == 0


def test_bbn_rejects_nan_even_when_json_parser_accepts_it():
    """Python's json module accepts NaN/Infinity as a non-standard
    extension -- confirm a NaN that survives PARSING is still caught by
    validation before it reaches a CPD."""
    _write_kcag_report()
    raw = ('{"adversary": {"capability_prior": [0.1, 0.2, NaN], "tempo": "HIGH"}, '
          '"defensive_posture": {"mfa": true, "edr": false, "segmentation": false, '
          '"integrity_monitor": false, "email_filtering": true}, '
          '"geopolitical_trigger_prior": 0.5}')
    parsed = json.loads(raw)
    assert parsed["adversary"]["capability_prior"][2] != parsed["adversary"]["capability_prior"][2]  # is nan

    result = bbn_threat_score.func(cpd_config_json=raw, priors_path="config/bbn_priors.json")
    assert result.startswith("ERROR:")
    assert "NON_FINITE_NUMBER" in result


def test_bbn_does_not_silently_normalize_capability_prior(valid_assessment_config):
    """The one deliberate numerical behavior change in this commit."""
    _write_kcag_report()
    valid_assessment_config["adversary"]["capability_prior"] = [0.0, 0.05, 0.95]
    result = bbn_threat_score.func(cpd_config_json=json.dumps(valid_assessment_config),
                                   priors_path="config/bbn_priors.json")
    assert not result.startswith("ERROR")
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    cap_entry = next(e for e in report["cpd_audit_log"] if e["node"] == "AdversaryCapability")
    assert cap_entry["value"] == [0.0, 0.05, 0.95]


def test_bbn_valid_config_still_builds_and_checks_model(valid_assessment_config):
    _write_kcag_report()
    result = bbn_threat_score.func(cpd_config_json=json.dumps(valid_assessment_config),
                                   priors_path="config/bbn_priors.json")
    assert result.startswith("=== ANNEX C")
    assert "STATUS: SUCCESS" in result


def test_bbn_validation_status_appears_in_audit(valid_assessment_config):
    _write_kcag_report()
    bbn_threat_score.func(cpd_config_json=json.dumps(valid_assessment_config),
                          priors_path="config/bbn_priors.json")
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    assert report["validation"]["assessment_config"]["status"] == "PASS"
    assert report["validation"]["priors"]["status"] == "PASS"
    assert report["validation"]["silent_normalization"] is False


def test_preflight_uses_same_priors_validator():
    """Confirms preflight_check.py imports validate_bbn_priors_document
    from src.bbn_validation rather than reimplementing its own check.
    Reads the file's source text directly rather than importing it as a
    module -- preflight_check.py is a standalone script whose top-level
    code runs its actual checks (including sys.exit) as an import side
    effect, so importing it here would be fragile and environment-
    dependent rather than a clean, isolated assertion."""
    import pathlib
    candidates = [pathlib.Path("preflight_check.py"), pathlib.Path("../preflight_check.py")]
    path = next((p for p in candidates if p.exists()), None)
    assert path is not None, "preflight_check.py not found relative to the test working directory"
    source = path.read_text()
    assert "from src.bbn_validation import validate_bbn_priors_document" in source
    assert "validate_bbn_priors_document(priors_doc)" in source


# ---------------------------------------------------------------------------
# Numerical regression: fixed valid configuration through old vs new paths
# ---------------------------------------------------------------------------

def test_numerical_regression_matches_known_baseline(valid_assessment_config):
    """This exact config produced threat_score=0.1408 before this commit
    (verified during the terminology-migration commit, itself unchanged
    by this one). The validation layer must not alter that."""
    _write_kcag_report(score=0.4)
    result = bbn_threat_score.func(cpd_config_json=json.dumps(valid_assessment_config),
                                   priors_path="config/bbn_priors.json")
    assert "Threat Score:  0.1408" in result
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    assert report["threat_score"] == 0.1408
    assert report["phase_distribution"] == {
        "RECON": 0.2419, "INITIAL ACCESS": 0.4868, "LATERAL / PIVOT": 0.2288, "OBJECTIVE": 0.0425,
    }
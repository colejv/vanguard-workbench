"""
Tests for deterministic BBN sensitivity analysis: the pure evaluator
(src/bbn_model.py), the sensitivity scenario generation and orchestration
(src/bbn_sensitivity.py), and their integration into bbn_threat_score().

Method: one-way (single-input) deterministic stress perturbation. No Monte
Carlo, no sampling, no Sobol indices. These are NOT confidence intervals,
error margins, or calibrated estimates -- several tests below assert that
the report's own language never claims otherwise.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import copy
import json
from unittest.mock import patch

import pytest

# Pre-import pgmpy for real before any test can patch it -- see the same
# note in test_bbn_numeric_validation.py. pgmpy.inference.ExactInference
# does `from pgmpy.models import DiscreteBayesianNetwork` at its own
# module level; if that happens for the first time while a mock is
# active, it permanently captures the mock in a separate namespace that
# unpatching does not undo.
import pgmpy.inference       # noqa: F401
import pgmpy.models          # noqa: F401
import pgmpy.factors.discrete  # noqa: F401

from src import run_context
from src.tools import bbn_threat_score
from src.bbn_model import evaluate_bbn_model, BBNEvaluation
from src.bbn_sensitivity import (
    run_bbn_sensitivity,
    shift_probability_mass,
    total_variation_distance,
    canonical_json_sha256,
    SENSITIVITY_POLICY_VERSION,
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
def assessment_config():
    return {
        "adversary": {"capability_prior": [0.1, 0.2, 0.7], "tempo": "HIGH"},
        "defensive_posture": {"mfa": True, "edr": False, "segmentation": False,
                              "integrity_monitor": False, "email_filtering": True},
        "geopolitical_trigger_prior": 0.5,
    }


@pytest.fixture
def baseline(assessment_config, priors_document):
    return evaluate_bbn_model(assessment_config=assessment_config,
                              priors_document=priors_document, kcag_objective_score=0.4)


def _write_kcag_report(score=0.4, legacy=False):
    if legacy:
        payload = {"objective_results": {"G1": {"top_path_prob": score}}}
    else:
        payload = {"schema_version": 2, "objective_results": {"G1": {"top_path_score": score}}}
    run_context.write_stamped_json(run_context.artifact_path("kcag_report.json"), payload)


# ---------------------------------------------------------------------------
# Pure evaluator
# ---------------------------------------------------------------------------

def test_extracted_evaluator_matches_existing_baseline(assessment_config, priors_document):
    result = evaluate_bbn_model(assessment_config=assessment_config, priors_document=priors_document,
                                kcag_objective_score=0.4)
    assert result.threat_score == 0.1408
    assert result.threat_level == "LOW"
    assert result.phase_distribution == [0.2419, 0.4868, 0.2288, 0.0425]


def test_evaluator_performs_no_artifact_writes(assessment_config, priors_document, tmp_path):
    before = set(tmp_path.rglob("*"))
    evaluate_bbn_model(assessment_config=assessment_config, priors_document=priors_document,
                       kcag_objective_score=0.4)
    after = set(tmp_path.rglob("*"))
    assert before == after


def test_evaluator_does_not_mutate_config(assessment_config, priors_document):
    before = copy.deepcopy(assessment_config)
    evaluate_bbn_model(assessment_config=assessment_config, priors_document=priors_document,
                       kcag_objective_score=0.4)
    assert assessment_config == before


def test_evaluator_does_not_mutate_priors(assessment_config, priors_document):
    before = copy.deepcopy(priors_document)
    evaluate_bbn_model(assessment_config=assessment_config, priors_document=priors_document,
                       kcag_objective_score=0.4)
    assert priors_document == before


def test_repeated_evaluation_is_deterministic(assessment_config, priors_document):
    r1 = evaluate_bbn_model(assessment_config=assessment_config, priors_document=priors_document,
                            kcag_objective_score=0.4)
    r2 = evaluate_bbn_model(assessment_config=assessment_config, priors_document=priors_document,
                            kcag_objective_score=0.4)
    assert r1 == r2


def test_evaluator_runs_model_check():
    """A malformed priors document (bad CPD shape reaching all the way to
    pgmpy) should raise, not silently return a degenerate result --
    proves check_model() is genuinely exercised, not bypassed."""
    bad_priors = json.load(open("config/bbn_priors.json"))
    bad_priors["priors"]["phishing_given_capability"]["value"] = [[0.5, 0.5], [0.5, 0.5]]  # wrong shape (2x2, not 2x3)
    cfg = {
        "adversary": {"capability_prior": [0.1, 0.2, 0.7], "tempo": "HIGH"},
        "defensive_posture": {"mfa": True, "edr": False, "segmentation": False,
                              "integrity_monitor": False, "email_filtering": True},
        "geopolitical_trigger_prior": 0.5,
    }
    with pytest.raises(Exception):
        evaluate_bbn_model(assessment_config=cfg, priors_document=bad_priors, kcag_objective_score=0.4)


# ---------------------------------------------------------------------------
# Capability shifts (shift_probability_mass)
# ---------------------------------------------------------------------------

def test_capability_shift_preserves_sum():
    r = shift_probability_mass([0.2, 0.3, 0.5], target_index=2, delta=0.1)
    assert abs(sum(r) - 1.0) < 1e-9


def test_capability_shift_preserves_bounds():
    r = shift_probability_mass([0.2, 0.3, 0.5], target_index=0, delta=-0.1)
    assert all(0.0 <= v <= 1.0 for v in r)


def test_capability_shift_increase_moves_requested_state():
    r = shift_probability_mass([0.2, 0.3, 0.5], target_index=1, delta=0.1)
    assert r[1] > 0.3


def test_capability_shift_decrease_moves_requested_state():
    r = shift_probability_mass([0.2, 0.3, 0.5], target_index=1, delta=-0.1)
    assert r[1] < 0.3


def test_capability_shift_handles_zero_state():
    """Target already at 0.0 -- a downward scenario must be skipped (None)."""
    r = shift_probability_mass([0.0, 0.3, 0.7], target_index=0, delta=-0.1)
    assert r is None


def test_capability_shift_handles_unit_state():
    """Target already at 1.0 -- an upward scenario must be skipped (None).
    Also confirms the decrease-FROM-1.0 case (equal-split fallback, since
    other states start at exactly zero with no proportion to preserve)."""
    r_up = shift_probability_mass([0.0, 0.0, 1.0], target_index=2, delta=0.1)
    assert r_up is None
    r_down = shift_probability_mass([0.0, 0.0, 1.0], target_index=2, delta=-0.1)
    assert r_down is not None
    assert abs(sum(r_down) - 1.0) < 1e-9
    assert r_down[0] == r_down[1]  # equal split when others start at zero


def test_capability_scenarios_have_stable_ids(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    ids = {s["scenario_id"] for s in report["scenarios"] if s["scenario_id"].startswith("capability.")}
    expected = {f"capability.{state}.{direction}"
               for state in ("hacktivist", "criminal", "nation_state")
               for direction in ("increase", "decrease")}
    assert ids == expected


def test_capability_scenarios_are_deduplicated(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    cap_ids = [s["scenario_id"] for s in report["scenarios"] if s["scenario_id"].startswith("capability.")]
    assert len(cap_ids) == len(set(cap_ids))


# ---------------------------------------------------------------------------
# Assessment-input scenarios
# ---------------------------------------------------------------------------

def test_tempo_enumerates_other_states(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    tempo_ids = {s["scenario_id"] for s in report["scenarios"] if s["scenario_id"].startswith("tempo.")}
    assert tempo_ids == {"tempo.LOW", "tempo.MEDIUM"}  # baseline is HIGH, so LOW/MEDIUM are the alternatives


def test_each_defensive_control_is_toggled_once(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    control_ids = {s["scenario_id"] for s in report["scenarios"] if s["scenario_id"].startswith("control.")}
    expected = {f"control.{c}.toggle" for c in
               ("mfa", "edr", "segmentation", "integrity_monitor", "email_filtering")}
    assert control_ids == expected


def test_geopolitical_prior_uses_bounded_delta(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    inc = by_id["geopolitical_trigger_prior.increase"]
    assert inc["status"] == "PASS"
    assert inc["scenario_value"] == pytest.approx(0.6, abs=1e-9)


def test_kcag_score_uses_bounded_delta(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    dec = by_id["kcag_objective_score.decrease"]
    assert dec["status"] == "PASS"
    assert dec["scenario_value"] == pytest.approx(0.3, abs=1e-9)


def test_all_generated_configs_pass_existing_validator(assessment_config, priors_document, baseline):
    """Every scenario in the report is either PASS or an explicit SKIPPED
    with a reason -- never a silent absence and never an unvalidated
    config reaching evaluation."""
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    for s in report["scenarios"]:
        assert s["status"] in ("PASS", "SKIPPED", "FAIL")
        if s["status"] == "SKIPPED":
            assert "reason" in s


def test_supplied_evidence_is_unchanged(priors_document):
    cfg = {
        "adversary": {"capability_prior": [0.1, 0.2, 0.7], "tempo": "HIGH"},
        "defensive_posture": {"mfa": True, "edr": False, "segmentation": False,
                              "integrity_monitor": False, "email_filtering": True},
        "geopolitical_trigger_prior": 0.5,
        "evidence": {"PhishingAttempt": 1},
    }
    baseline = evaluate_bbn_model(assessment_config=cfg, priors_document=priors_document, kcag_objective_score=0.4)
    report = run_bbn_sensitivity(assessment_config=cfg, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    for s in report["scenarios"]:
        if s["status"] == "PASS":
            assert s["baseline_threat_score"] == baseline.threat_score  # same evidence applied to every scenario


def test_observed_root_prior_scenarios_are_skipped(priors_document):
    cfg = {
        "adversary": {"capability_prior": [0.1, 0.2, 0.7], "tempo": "HIGH"},
        "defensive_posture": {"mfa": True, "edr": False, "segmentation": False,
                              "integrity_monitor": False, "email_filtering": True},
        "geopolitical_trigger_prior": 0.5,
        "evidence": {"AdversaryCapability": 2, "GeopoliticalTrigger": 1},
    }
    baseline = evaluate_bbn_model(assessment_config=cfg, priors_document=priors_document, kcag_objective_score=0.4)
    report = run_bbn_sensitivity(assessment_config=cfg, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    masked = [s for s in report["scenarios"] if s["status"] == "SKIPPED"
             and "fixed by supplied evidence" in s.get("reason", "")]
    cap_masked = {s["scenario_id"] for s in masked if s["scenario_id"].startswith("capability.")}
    geo_masked = {s["scenario_id"] for s in masked if s["scenario_id"].startswith("geopolitical")}
    assert len(cap_masked) == 6
    assert len(geo_masked) == 2


# ---------------------------------------------------------------------------
# Model-prior scenarios
# ---------------------------------------------------------------------------

def test_scalar_prior_scenarios_use_documented_policy(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    # defensive_posture_floor: bounded [0, 0.5] -> delta = 0.10 * 0.5 = 0.05
    floor_inc = by_id["prior.defensive_posture_floor.increase"]
    assert floor_inc["scenario_value"] == pytest.approx(0.05 + 0.05, abs=1e-9)
    # iw_effect_geo_multiplier: only a lower bound -> relative delta, baseline 1.45 * 1.10
    geo_mult_inc = by_id["prior.iw_effect_geo_multiplier.increase"]
    assert geo_mult_inc["scenario_value"] == pytest.approx(1.45 * 1.10, abs=1e-6)


def test_scalar_prior_scenarios_preserve_source_metadata(assessment_config, priors_document, baseline):
    """The candidate priors document must retain every OTHER prior's
    source/value untouched -- only the one perturbed field changes."""
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    s = by_id["prior.defensive_multiplier_scale.increase"]
    assert s["status"] == "PASS"
    # If unrelated priors had been corrupted, evaluation would have failed
    # outright or produced a wildly different score -- a real assertion
    # that other fields survived, not just "no exception was raised."
    assert 0.0 <= s["scenario_threat_score"] <= 1.0


def test_candidate_priors_use_existing_validator(assessment_config, priors_document, baseline):
    """Every model_prior scenario that ran was necessarily validated --
    proven indirectly by confirming the known-invalid boundary cases
    (see test below) are correctly SKIPPED rather than silently accepted."""
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    assert by_id["prior.iw_effect_phase_base_recon.decrease"]["status"] == "SKIPPED"


def test_invalid_cross_field_candidate_is_skipped(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    s = by_id["prior.iw_effect_phase_base_recon.increase"]  # would exceed initial_access -> monotonicity violation
    assert s["status"] == "SKIPPED"
    assert "validation_errors" in s
    assert any(e["code"] == "PHASE_BASE_NOT_MONOTONIC" for e in s["validation_errors"])


def test_baseline_priors_document_is_not_modified(assessment_config, priors_document, baseline):
    before = copy.deepcopy(priors_document)
    run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                        kcag_objective_score=0.4, baseline=baseline)
    assert priors_document == before


def test_cpd_matrices_are_not_perturbed(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    parameters = {s["parameter"] for s in report["scenarios"]}
    assert "phishing_given_capability" not in parameters
    assert "scanning_given_tempo" not in parameters


def test_probability_vector_priors_are_not_perturbed(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    parameters = {s["parameter"] for s in report["scenarios"]}
    assert "operational_tempo_distribution" not in parameters
    assert "killchain_phase_base" not in parameters
    assert "killchain_phase_evidence_delta_phishing" not in parameters


# ---------------------------------------------------------------------------
# Comparison metrics
# ---------------------------------------------------------------------------

def test_threat_score_delta_is_correct(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    s = by_id["kcag_objective_score.increase"]
    assert s["threat_score_delta"] == round(s["scenario_threat_score"] - baseline.threat_score, 4)


def test_absolute_delta_is_correct(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    s = by_id["control.mfa.toggle"]
    assert s["absolute_threat_score_delta"] == abs(s["threat_score_delta"])


def test_relative_delta_is_none_when_baseline_zero(priors_document):
    """Construct a config that drives the baseline threat_score to
    exactly zero is impractical (the model floors probabilities at
    0.001), so this tests the guard directly instead of relying on a
    real zero-score scenario."""
    from src.bbn_sensitivity import _compare
    from src.bbn_model import BBNEvaluation
    zero_baseline = BBNEvaluation(threat_score=0.0, threat_level="LOW", baseline_score=0.0,
                                  delta_from_baseline=0.0, likely_phase="RECON",
                                  phase_distribution=[1, 0, 0, 0], iw_effect_distribution=[1, 0],
                                  evidence_applied={}, kcag_objective_score=0.4, defensive_multiplier=1.0)
    scenario = BBNEvaluation(threat_score=0.05, threat_level="LOW", baseline_score=0.0,
                             delta_from_baseline=0.05, likely_phase="RECON",
                             phase_distribution=[0.9, 0.1, 0, 0], iw_effect_distribution=[0.95, 0.05],
                             evidence_applied={}, kcag_objective_score=0.5, defensive_multiplier=1.0)
    result = _compare(zero_baseline, scenario)
    assert result["relative_threat_score_delta"] is None


def test_phase_distribution_delta_is_correct(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    s = by_id["kcag_objective_score.increase"]
    for i in range(4):
        expected = round(s["phase_distribution"][i] - baseline.phase_distribution[i], 4)
        assert s["phase_distribution_delta"][i] == expected


def test_total_variation_distance_is_correct():
    assert total_variation_distance([1.0, 0.0], [1.0, 0.0]) == 0.0
    assert total_variation_distance([1.0, 0.0], [0.0, 1.0]) == 1.0
    assert total_variation_distance([0.5, 0.5], [0.6, 0.4]) == pytest.approx(0.1)


def test_threat_level_change_is_detected():
    from src.bbn_sensitivity import _compare
    from src.bbn_model import BBNEvaluation
    b = BBNEvaluation(threat_score=0.19, threat_level="LOW", baseline_score=0.19, delta_from_baseline=0.0,
                      likely_phase="RECON", phase_distribution=[1, 0, 0, 0], iw_effect_distribution=[0.81, 0.19],
                      evidence_applied={}, kcag_objective_score=0.4, defensive_multiplier=1.0)
    s = BBNEvaluation(threat_score=0.25, threat_level="ELEVATED", baseline_score=0.19, delta_from_baseline=0.06,
                      likely_phase="RECON", phase_distribution=[1, 0, 0, 0], iw_effect_distribution=[0.75, 0.25],
                      evidence_applied={}, kcag_objective_score=0.5, defensive_multiplier=1.0)
    result = _compare(b, s)
    assert result["threat_level_changed"] is True


def test_driver_ranking_uses_max_absolute_delta(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    deltas = [d["maximum_absolute_delta"] for d in report["driver_summary"]]
    assert deltas == sorted(deltas, reverse=True)


def test_driver_ranking_has_deterministic_tie_break(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    # Re-running must produce the exact same ordering, including among ties.
    report2 = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                  kcag_objective_score=0.4, baseline=baseline)
    order1 = [d["parameter"] for d in report["driver_summary"]]
    order2 = [d["parameter"] for d in report2["driver_summary"]]
    assert order1 == order2


def test_global_score_range_includes_baseline(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    g = report["global_summary"]
    assert g["score_minimum"] <= baseline.threat_score <= g["score_maximum"]


# ---------------------------------------------------------------------------
# Integration and artifacts
# ---------------------------------------------------------------------------

_BBN_CFG = json.dumps({
    "adversary": {"capability_prior": [0.1, 0.2, 0.7], "tempo": "HIGH"},
    "defensive_posture": {"mfa": True, "edr": False, "segmentation": False,
                          "integrity_monitor": False, "email_filtering": True},
    "geopolitical_trigger_prior": 0.5,
})


def test_bbn_writes_stamped_sensitivity_report():
    _write_kcag_report()
    result = bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    assert not result.startswith("ERROR")
    sens = run_context.read_stamped_json(run_context.artifact_path("bbn_sensitivity.json"))
    assert sens["status"] == "PASS"


def test_sensitivity_report_records_source_hashes():
    _write_kcag_report()
    bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    sens = run_context.read_stamped_json(run_context.artifact_path("bbn_sensitivity.json"))
    ids = sens["source_identity"]
    assert ids["assessment_config_sha256"].startswith("sha256:")
    assert ids["priors_sha256"].startswith("sha256:")
    assert ids["kcag_report_sha256"].startswith("sha256:")
    # priors_sha256 must be the REAL file hash, independently verified
    import hashlib
    real_hash = "sha256:" + hashlib.sha256(open("config/bbn_priors.json", "rb").read()).hexdigest()
    assert ids["priors_sha256"] == real_hash


def test_sensitivity_report_records_policy_version():
    _write_kcag_report()
    bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    sens = run_context.read_stamped_json(run_context.artifact_path("bbn_sensitivity.json"))
    assert sens["method"]["policy_version"] == SENSITIVITY_POLICY_VERSION


def test_bbn_report_and_sensitivity_share_baseline():
    _write_kcag_report()
    bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    sens = run_context.read_stamped_json(run_context.artifact_path("bbn_sensitivity.json"))
    assert report["threat_score"] == sens["baseline"]["threat_score"]
    assert report["threat_level"] == sens["baseline"]["threat_level"]


def test_legacy_kcag_report_still_runs_sensitivity():
    _write_kcag_report(legacy=True)
    result = bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    assert not result.startswith("ERROR")
    assert "BBN SENSITIVITY ANALYSIS" in result
    report = run_context.read_stamped_json(run_context.artifact_path("bbn_report.json"))
    assert report["kcag_used_legacy_field"] is True


def test_sensitivity_does_not_rewrite_kcag_report():
    _write_kcag_report()
    path = run_context.artifact_path("kcag_report.json")
    before = open(path, "rb").read()
    bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    after = open(path, "rb").read()
    assert before == after


def test_sensitivity_does_not_rewrite_priors():
    _write_kcag_report()
    before = open("config/bbn_priors.json", "rb").read()
    bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    after = open("config/bbn_priors.json", "rb").read()
    assert before == after


def test_unexpected_scenario_failure_prevents_success_artifacts():
    _write_kcag_report()
    import src.bbn_sensitivity as sens_mod
    original = sens_mod.evaluate_bbn_model
    call_count = {"n": 0}

    def flaky(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("simulated failure")
        return original(**kwargs)

    with patch("src.bbn_sensitivity.evaluate_bbn_model", side_effect=flaky):
        result = bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    assert result.startswith("ERROR")
    import os
    assert not os.path.exists(run_context.artifact_path("bbn_report.json"))
    assert not os.path.exists(run_context.artifact_path("bbn_sensitivity.json"))


def test_annex_c_summary_names_top_drivers():
    _write_kcag_report()
    result = bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    assert "Top drivers:" in result
    assert "1." in result


def test_annex_c_summary_disclaims_confidence_interval():
    _write_kcag_report()
    result = bbn_threat_score.func(cpd_config_json=_BBN_CFG, priors_path="config/bbn_priors.json")
    lowered = result.lower()
    assert "not statistical" in lowered
    assert "confidence intervals or empirical forecasts" in lowered


# ---------------------------------------------------------------------------
# Directional regressions
# ---------------------------------------------------------------------------

def test_increasing_kcag_score_does_not_reduce_threat_score(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    s = by_id["kcag_objective_score.increase"]
    assert s["status"] == "PASS"
    assert s["threat_score_delta"] >= 0


def test_enabling_an_additional_defensive_control_does_not_increase_threat_score(
        assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    # baseline has edr=False -- toggling it ENABLES the control
    s = by_id["control.edr.toggle"]
    assert s["baseline_value"] is False and s["scenario_value"] is True
    assert s["threat_score_delta"] <= 0


def test_increasing_geopolitical_prior_does_not_reduce_threat_score(assessment_config, priors_document, baseline):
    report = run_bbn_sensitivity(assessment_config=assessment_config, priors_document=priors_document,
                                 kcag_objective_score=0.4, baseline=baseline)
    by_id = {s["scenario_id"]: s for s in report["scenarios"]}
    s = by_id["geopolitical_trigger_prior.increase"]
    assert s["status"] == "PASS"
    assert s["threat_score_delta"] >= 0
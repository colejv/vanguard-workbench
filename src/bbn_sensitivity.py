"""
Deterministic one-way sensitivity analysis for the Annex C BBN.

Method: change exactly one input or model parameter, rebuild the complete
BBN via the pure evaluator (src.bbn_model.evaluate_bbn_model), run
inference with the SAME evidence as the baseline, compare against the
baseline, then move to the next scenario. No Monte Carlo, no sampling, no
Sobol indices, no correlated variation, no LLM-generated ranges -- those
all require defensible parameter distributions and dependency assumptions
this codebase does not yet have.

These are deterministic stress perturbations, not confidence intervals,
error margins, standard deviations, or credible intervals. Do not describe
them that way anywhere in this module or its output.
"""
import copy
import json
import math
from typing import Any

from src.bbn_model import evaluate_bbn_model, BBNEvaluation
from src.state import canonical_json_sha256
from src.bbn_validation import (
    validate_bbn_assessment_config,
    validate_bbn_priors_document,
    SCALAR_PRIOR_RULES,
)


# ============================================================================
#  SENSITIVITY POLICY -- versioned, since the perturbation rules are
#  themselves modeling assumptions
# ============================================================================
SENSITIVITY_POLICY_VERSION = 1
PROBABILITY_ABSOLUTE_DELTA = 0.10          # geopolitical_trigger_prior, kcag_objective_score
BOUNDED_PRIOR_RANGE_FRACTION = 0.10        # scalar priors with both min and max
POSITIVE_MULTIPLIER_RELATIVE_DELTA = 0.10  # scalar priors with only a lower bound
CAPABILITY_SIMPLEX_SHIFT = 0.10            # adversary.capability_prior

EVIDENCE_MASK_NODES = {
    "capability": "AdversaryCapability",
    "geopolitical_trigger_prior": "GeopoliticalTrigger",
}


# ============================================================================
#  NUMERIC HELPERS
# ============================================================================

def shift_probability_mass(vector: list, *, target_index: int, delta: float):
    """Shift probability mass toward or away from one simplex state,
    preserving sum==1 and every value in [0,1].

    Positive delta increases the target state, taking mass proportionally
    from the other states (proportional to their current share of the
    non-target mass). Negative delta decreases the target state and
    distributes the released mass proportionally across the other states
    -- EXCEPT when the other states currently sum to exactly zero (the
    target is at 1.0), in which case there is no existing proportion to
    preserve and the released mass is split equally instead. That
    fallback is a deliberate, documented policy for an otherwise
    undefined 0/0 case, not an accidental default.

    Returns None if the requested direction is already at its simplex
    boundary (target already 1.0 for a positive delta, already 0.0 for a
    negative delta) -- callers use this to skip the scenario.
    """
    n = len(vector)
    other_indices = [i for i in range(n) if i != target_index]
    target = vector[target_index]
    other_total = sum(vector[i] for i in other_indices)

    if delta > 0:
        if target >= 1.0 or other_total <= 0.0:
            return None
        actual_shift = min(delta, other_total)
        new_vector = list(vector)
        new_vector[target_index] = target + actual_shift
        for i in other_indices:
            share = vector[i] / other_total
            new_vector[i] = vector[i] - actual_shift * share
        return new_vector

    if delta < 0:
        if target <= 0.0:
            return None
        actual_shift = min(-delta, target)
        new_vector = list(vector)
        new_vector[target_index] = target - actual_shift
        if other_total > 0.0:
            for i in other_indices:
                share = vector[i] / other_total
                new_vector[i] = vector[i] + actual_shift * share
        else:
            equal_share = actual_shift / len(other_indices)
            for i in other_indices:
                new_vector[i] = vector[i] + equal_share
        return new_vector

    return None


def total_variation_distance(baseline: list, scenario: list) -> float:
    """0.5 * L1 distance between two discrete distributions of equal
    length. Descriptive only -- no LOW/MEDIUM/HIGH label is assigned."""
    return 0.5 * sum(abs(c - o) for o, c in zip(baseline, scenario))


def _round_list(values: list, ndigits: int = 4) -> list:
    return [round(v, ndigits) for v in values]


# ============================================================================
#  SCENARIO GENERATION
# ============================================================================
# Every generator returns a list of scenario "specs" -- either already
# marked SKIPPED (boundary reached at generation time), or carrying a
# mutated_config / mutated_priors_document / mutated_kcag_score to be
# evaluated. Exactly one of these three is non-None per generated (not
# pre-skipped) scenario -- every other input stays at its baseline value,
# consistent with one-way sensitivity analysis.

def _skip_spec(scenario_id, group, parameter, direction, reason):
    return {"scenario_id": scenario_id, "group": group, "parameter": parameter,
           "direction": direction, "status": "SKIPPED", "reason": reason,
           "mutated_config": None, "mutated_priors_document": None, "mutated_kcag_score": None}


def _live_spec(scenario_id, group, parameter, direction, baseline_value, scenario_value,
               mutated_config=None, mutated_priors_document=None, mutated_kcag_score=None):
    return {"scenario_id": scenario_id, "group": group, "parameter": parameter,
           "direction": direction, "status": None,
           "baseline_value": baseline_value, "scenario_value": scenario_value,
           "mutated_config": mutated_config, "mutated_priors_document": mutated_priors_document,
           "mutated_kcag_score": mutated_kcag_score}


def _generate_capability_scenarios(assessment_config: dict) -> list:
    specs = []
    cap_prior = assessment_config["adversary"]["capability_prior"]
    labels = ["hacktivist", "criminal", "nation_state"]
    for i, label in enumerate(labels):
        for direction, delta in (("increase", CAPABILITY_SIMPLEX_SHIFT),
                                 ("decrease", -CAPABILITY_SIMPLEX_SHIFT)):
            scenario_id = f"capability.{label}.{direction}"
            parameter = f"adversary.capability_prior.{label}"
            new_vec = shift_probability_mass(cap_prior, target_index=i, delta=delta)
            if new_vec is None:
                boundary = "upper" if direction == "increase" else "lower"
                specs.append(_skip_spec(scenario_id, "assessment_input", parameter, direction,
                                        f"capability_prior[{label}] is already at the {boundary} "
                                        f"simplex boundary."))
                continue
            mutated_config = copy.deepcopy(assessment_config)
            mutated_config["adversary"]["capability_prior"] = new_vec
            specs.append(_live_spec(scenario_id, "assessment_input", parameter, direction,
                                    baseline_value=list(cap_prior), scenario_value=new_vec,
                                    mutated_config=mutated_config))
    # Deduplicate (defensive -- shift_probability_mass is deterministic per
    # input, so true duplicates would only arise from a degenerate baseline
    # vector, e.g. two states already equal at a boundary).
    seen = set()
    deduped = []
    for spec in specs:
        key = (spec["parameter"], spec["direction"],
              tuple(spec.get("scenario_value")) if spec.get("scenario_value") else None)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def _generate_tempo_scenarios(assessment_config: dict) -> list:
    specs = []
    baseline_tempo = assessment_config["adversary"]["tempo"]
    for alt in ("LOW", "MEDIUM", "HIGH"):
        if alt == baseline_tempo:
            continue
        mutated_config = copy.deepcopy(assessment_config)
        mutated_config["adversary"]["tempo"] = alt
        specs.append(_live_spec(f"tempo.{alt}", "assessment_input", "adversary.tempo", "alternative",
                                baseline_value=baseline_tempo, scenario_value=alt,
                                mutated_config=mutated_config))
    return specs


def _generate_posture_scenarios(assessment_config: dict) -> list:
    specs = []
    posture = assessment_config["defensive_posture"]
    for control in sorted(posture.keys()):
        baseline_value = posture[control]
        mutated_config = copy.deepcopy(assessment_config)
        mutated_config["defensive_posture"][control] = not baseline_value
        specs.append(_live_spec(f"control.{control}.toggle", "assessment_input",
                                f"defensive_posture.{control}", "toggle",
                                baseline_value=baseline_value, scenario_value=not baseline_value,
                                mutated_config=mutated_config))
    return specs


def _generate_geopolitical_scenarios(assessment_config: dict) -> list:
    specs = []
    baseline = float(assessment_config["geopolitical_trigger_prior"])
    low = max(0.0, baseline - PROBABILITY_ABSOLUTE_DELTA)
    high = min(1.0, baseline + PROBABILITY_ABSOLUTE_DELTA)
    for direction, value in (("decrease", low), ("increase", high)):
        if value == baseline:
            specs.append(_skip_spec(f"geopolitical_trigger_prior.{direction}", "assessment_input",
                                    "geopolitical_trigger_prior", direction,
                                    f"Clipping to [0,1] produces the baseline value ({baseline}); "
                                    f"no distinct scenario to run."))
            continue
        mutated_config = copy.deepcopy(assessment_config)
        mutated_config["geopolitical_trigger_prior"] = value
        specs.append(_live_spec(f"geopolitical_trigger_prior.{direction}", "assessment_input",
                                "geopolitical_trigger_prior", direction,
                                baseline_value=baseline, scenario_value=value,
                                mutated_config=mutated_config))
    return specs


def _generate_kcag_scenarios(kcag_objective_score: float) -> list:
    specs = []
    baseline = float(kcag_objective_score)
    low = max(0.0, baseline - PROBABILITY_ABSOLUTE_DELTA)
    high = min(1.0, baseline + PROBABILITY_ABSOLUTE_DELTA)
    for direction, value in (("decrease", low), ("increase", high)):
        if value == baseline:
            specs.append(_skip_spec(f"kcag_objective_score.{direction}", "assessment_input",
                                    "kcag_objective_score", direction,
                                    f"Clipping to [0,1] produces the baseline value ({baseline}); "
                                    f"no distinct scenario to run."))
            continue
        specs.append(_live_spec(f"kcag_objective_score.{direction}", "assessment_input",
                                "kcag_objective_score", direction,
                                baseline_value=baseline, scenario_value=value,
                                mutated_kcag_score=value))
    return specs


def _generate_scalar_prior_scenarios(priors_document: dict) -> list:
    specs = []
    priors = priors_document["priors"]
    for field, rules in SCALAR_PRIOR_RULES.items():
        entry = priors.get(field)
        if not isinstance(entry, dict) or "value" not in entry:
            # Should never happen against an already-validated document,
            # but a scenario generator must not raise on a malformed
            # priors document -- record it as an unexpected-shape skip.
            specs.append(_skip_spec(f"prior.{field}.increase", "model_prior", field, "increase",
                                    "Prior entry missing or malformed; cannot generate a scenario."))
            specs.append(_skip_spec(f"prior.{field}.decrease", "model_prior", field, "decrease",
                                    "Prior entry missing or malformed; cannot generate a scenario."))
            continue

        baseline = float(entry["value"])
        if "min" in rules and "max" in rules:
            delta = BOUNDED_PRIOR_RANGE_FRACTION * (rules["max"] - rules["min"])
        else:
            delta = POSITIVE_MULTIPLIER_RELATIVE_DELTA * abs(baseline)

        for direction, candidate_value in (("decrease", baseline - delta), ("increase", baseline + delta)):
            scenario_id = f"prior.{field}.{direction}"
            mutated_priors = copy.deepcopy(priors_document)
            mutated_priors["priors"][field]["value"] = candidate_value
            specs.append(_live_spec(scenario_id, "model_prior", field, direction,
                                    baseline_value=baseline, scenario_value=candidate_value,
                                    mutated_priors_document=mutated_priors))
    return specs


def _evidence_mask_reason(spec: dict, evidence: dict) -> str:
    for prefix, node in EVIDENCE_MASK_NODES.items():
        if spec["scenario_id"].startswith(prefix + ".") and node in evidence:
            return f"{node} is fixed by supplied evidence."
    return None


# ============================================================================
#  COMPARISON METRICS
# ============================================================================

def _compare(baseline: BBNEvaluation, scenario: BBNEvaluation) -> dict:
    threat_score_delta = round(scenario.threat_score - baseline.threat_score, 4)
    relative_delta = (None if baseline.threat_score == 0
                      else round(threat_score_delta / baseline.threat_score, 4))
    return {
        "baseline_threat_score": baseline.threat_score,
        "scenario_threat_score": scenario.threat_score,
        "threat_score_delta": threat_score_delta,
        "absolute_threat_score_delta": round(abs(threat_score_delta), 4),
        "relative_threat_score_delta": relative_delta,
        "baseline_threat_level": baseline.threat_level,
        "scenario_threat_level": scenario.threat_level,
        "threat_level_changed": baseline.threat_level != scenario.threat_level,
        "phase_distribution": _round_list(scenario.phase_distribution),
        "phase_distribution_delta": _round_list(
            [s - b for b, s in zip(baseline.phase_distribution, scenario.phase_distribution)]),
        "phase_total_variation": round(
            total_variation_distance(baseline.phase_distribution, scenario.phase_distribution), 4),
        "iw_effect_distribution": _round_list(scenario.iw_effect_distribution),
        "iw_effect_distribution_delta": _round_list(
            [s - b for b, s in zip(baseline.iw_effect_distribution, scenario.iw_effect_distribution)]),
        "iw_effect_total_variation": round(
            total_variation_distance(baseline.iw_effect_distribution, scenario.iw_effect_distribution), 4),
    }


# ============================================================================
#  ORCHESTRATION
# ============================================================================

def run_bbn_sensitivity(*, assessment_config: dict, priors_document: dict,
                        kcag_objective_score: float, baseline: BBNEvaluation) -> dict:
    """Run the full deterministic one-way sensitivity suite against an
    already-computed baseline. Performs no filesystem writes and does not
    mutate assessment_config, priors_document, or baseline.

    Every scenario's status is exactly one of PASS / SKIPPED / FAIL.
    SKIPPED covers every EXPECTED reason a scenario doesn't run (simplex
    boundary, evidence masking, clipping to baseline, failed validation
    against the same validators bbn_threat_score itself uses). FAIL means
    something the caller did not expect -- model construction failure,
    check_model() failure, inference raising, or a non-finite result --
    and the caller (bbn_threat_score) treats an overall FAIL status as an
    ERROR, writing neither success artifact.
    """
    evidence = assessment_config.get("evidence", {})

    all_specs = (
        _generate_capability_scenarios(assessment_config)
        + _generate_tempo_scenarios(assessment_config)
        + _generate_posture_scenarios(assessment_config)
        + _generate_geopolitical_scenarios(assessment_config)
        + _generate_kcag_scenarios(kcag_objective_score)
        + _generate_scalar_prior_scenarios(priors_document)
    )

    scenarios = []
    overall_status = "PASS"

    for spec in all_specs:
        result = {
            "scenario_id": spec["scenario_id"],
            "group": spec["group"],
            "parameter": spec["parameter"],
            "direction": spec["direction"],
        }

        if spec["status"] == "SKIPPED":
            result["status"] = "SKIPPED"
            result["reason"] = spec["reason"]
            scenarios.append(result)
            continue

        mask_reason = _evidence_mask_reason(spec, evidence)
        if mask_reason:
            result["status"] = "SKIPPED"
            result["reason"] = mask_reason
            scenarios.append(result)
            continue

        cfg_to_use = spec["mutated_config"] if spec["mutated_config"] is not None else assessment_config
        priors_to_use = (spec["mutated_priors_document"] if spec["mutated_priors_document"] is not None
                         else priors_document)
        kcag_to_use = (spec["mutated_kcag_score"] if spec["mutated_kcag_score"] is not None
                       else kcag_objective_score)

        if spec["mutated_config"] is not None:
            cfg_validation = validate_bbn_assessment_config(cfg_to_use)
            if not cfg_validation["is_valid"]:
                result["status"] = "SKIPPED"
                result["reason"] = "Perturbation violates validated model invariants."
                result["validation_errors"] = cfg_validation["errors"]
                scenarios.append(result)
                continue

        if spec["mutated_priors_document"] is not None:
            priors_validation = validate_bbn_priors_document(priors_to_use)
            if not priors_validation["is_valid"]:
                result["status"] = "SKIPPED"
                result["reason"] = "Perturbation violates validated model invariants."
                result["validation_errors"] = priors_validation["errors"]
                scenarios.append(result)
                continue

        result["baseline_value"] = spec["baseline_value"]
        result["scenario_value"] = spec["scenario_value"]

        try:
            evaluation = evaluate_bbn_model(assessment_config=cfg_to_use, priors_document=priors_to_use,
                                            kcag_objective_score=kcag_to_use)
            if not all(math.isfinite(v) for v in
                      [evaluation.threat_score] + evaluation.phase_distribution + evaluation.iw_effect_distribution):
                raise ValueError("Scenario produced a non-finite result.")
        except Exception as exc:
            result["status"] = "FAIL"
            result["reason"] = f"Unexpected scenario failure: {exc}"
            scenarios.append(result)
            overall_status = "FAIL"
            continue

        result["status"] = "PASS"
        result.update(_compare(baseline, evaluation))
        scenarios.append(result)

    # ---- Aggregate by driver (parameter), ranked by max absolute delta ----
    by_parameter: dict = {}
    for s in scenarios:
        if s["status"] != "PASS":
            continue
        by_parameter.setdefault(s["parameter"], []).append(s)

    driver_summary = []
    for parameter, results in by_parameter.items():
        threat_scores = [r["scenario_threat_score"] for r in results]
        max_abs = max(r["absolute_threat_score_delta"] for r in results)
        most_influential = max(results, key=lambda r: r["absolute_threat_score_delta"])["scenario_id"]
        driver_summary.append({
            "parameter": parameter,
            "scenario_count": len(results),
            "minimum_threat_score": min(threat_scores),
            "maximum_threat_score": max(threat_scores),
            "threat_score_span": round(max(threat_scores) - min(threat_scores), 4),
            "maximum_absolute_delta": max_abs,
            "classification_stable": not any(r["threat_level_changed"] for r in results),
            "most_influential_scenario": most_influential,
        })
    driver_summary.sort(key=lambda d: (-d["maximum_absolute_delta"], d["parameter"]))

    # ---- Global summary ----
    passed = [s for s in scenarios if s["status"] == "PASS"]
    all_scores = [baseline.threat_score] + [s["scenario_threat_score"] for s in passed]
    all_levels = sorted({baseline.threat_level} | {s["scenario_threat_level"] for s in passed})
    global_summary = {
        "score_minimum": min(all_scores),
        "score_maximum": max(all_scores),
        "score_span": round(max(all_scores) - min(all_scores), 4),
        "threat_levels_observed": all_levels,
        "classification_stable": not any(s["threat_level_changed"] for s in passed),
        "top_drivers": [d["parameter"] for d in driver_summary[:5]],
    }

    if overall_status == "FAIL":
        status = "FAIL"
    else:
        status = "PASS"

    return {
        "schema_version": 1,
        "status": status,
        "method": {
            "name": "deterministic_one_way_sensitivity",
            "policy_version": SENSITIVITY_POLICY_VERSION,
            "probability_absolute_delta": PROBABILITY_ABSOLUTE_DELTA,
            "capability_simplex_shift": CAPABILITY_SIMPLEX_SHIFT,
            "bounded_prior_range_fraction": BOUNDED_PRIOR_RANGE_FRACTION,
            "positive_multiplier_relative_delta": POSITIVE_MULTIPLIER_RELATIVE_DELTA,
            "evidence_policy": "fixed",
        },
        "baseline": {
            "threat_score": baseline.threat_score,
            "threat_level": baseline.threat_level,
            "phase_distribution": _round_list(baseline.phase_distribution),
            "iw_effect_distribution": _round_list(baseline.iw_effect_distribution),
        },
        "scenarios": scenarios,
        "driver_summary": driver_summary,
        "global_summary": global_summary,
        "limitations": [
            "One parameter or input is varied at a time.",
            "Interactions between uncertain inputs are not measured.",
            "Perturbation intervals are deterministic stress ranges, not confidence intervals.",
            "Observed evidence is held fixed.",
            "CPD matrices and probability-vector priors are not perturbed in schema version 1.",
        ],
    }
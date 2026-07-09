"""
Deterministic numeric validation for Annex C BBN inputs: per-assessment
configuration (cpd_config_json) and the structural priors document
(config/bbn_priors.json).

Both preflight_check.py and bbn_threat_score() call the SAME functions
here -- there is intentionally no second, independent validation
implementation in preflight. A PASS from preflight means the real gate
in bbn_threat_score will also pass, not just preflight's own guess.

This module never constructs a pgmpy model and never touches the
filesystem itself (callers load the JSON; these functions validate
already-parsed Python objects). It validates shape, type, range, and
sum/cross-field invariants only -- it does not decide whether a
correctly-shaped value is analytically reasonable for a given
assessment; that remains an analyst/reviewer judgment.
"""
import math
from numbers import Real
from typing import Any


# ============================================================================
#  NUMERIC PRIMITIVES
# ============================================================================

PROBABILITY_SUM_TOLERANCE = 1e-9
DELTA_SUM_TOLERANCE = 1e-9


def _is_real_number(value: Any) -> bool:
    """True for int/float, explicitly False for bool -- Python's bool is
    a subclass of int, so isinstance(True, Real) is True unless excluded
    here. A boolean is never an acceptable stand-in for a probability or
    scalar prior, even though it would silently pass isinstance/int/float
    checks otherwise."""
    return isinstance(value, Real) and not isinstance(value, bool)


def _validate_finite_number(value: Any, *, path: str,
                            minimum: float = None, maximum: float = None,
                            exclusive_min: float = None) -> list:
    """Validate a single scalar. Returns a list of error dicts (empty if
    valid). Rejects booleans and numeric strings -- "0.5" is a
    configuration error to be fixed at the source, not silently coerced."""
    if not _is_real_number(value):
        return [{"path": path, "code": "NOT_NUMERIC",
                 "message": "Value must be a real number, not a boolean or string."}]

    numeric = float(value)

    if not math.isfinite(numeric):
        return [{"path": path, "code": "NON_FINITE_NUMBER",
                 "message": "Value must be finite."}]

    errors = []
    if minimum is not None and numeric < minimum:
        errors.append({"path": path, "code": "BELOW_MINIMUM",
                       "message": f"Value must be at least {minimum}."})
    if maximum is not None and numeric > maximum:
        errors.append({"path": path, "code": "ABOVE_MAXIMUM",
                       "message": f"Value must be at most {maximum}."})
    if exclusive_min is not None and numeric <= exclusive_min:
        errors.append({"path": path, "code": "NOT_ABOVE_EXCLUSIVE_MINIMUM",
                       "message": f"Value must be strictly greater than {exclusive_min}."})
    return errors


def _validate_probability_vector(value: Any, *, path: str, expected_length: int) -> list:
    """A list of `expected_length` values in [0,1] summing to 1.0 within
    PROBABILITY_SUM_TOLERANCE. Uses math.fsum (not builtin sum) for
    deterministic, numerically stable summation. Never silently
    normalizes a vector that doesn't sum to 1 -- that's a caller error to
    fix at the source, not a validator's job to repair."""
    if not isinstance(value, list):
        return [{"path": path, "code": "NOT_A_LIST",
                 "message": "Probability vector must be a list."}]

    errors = []
    if len(value) != expected_length:
        errors.append({"path": path, "code": "INVALID_LENGTH",
                       "message": f"Expected {expected_length} values; received {len(value)}."})

    for index, item in enumerate(value):
        errors.extend(_validate_finite_number(item, path=f"{path}[{index}]",
                                              minimum=0.0, maximum=1.0))

    if errors:
        return errors

    total = math.fsum(float(item) for item in value)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=PROBABILITY_SUM_TOLERANCE):
        errors.append({"path": path, "code": "PROBABILITY_SUM",
                       "message": f"Probability vector must sum to 1.0; received {total:.17g}."})
    return errors


def _validate_delta_vector(value: Any, *, path: str, expected_length: int) -> list:
    """A finite numeric vector in [-1,1] summing to 0.0 -- probability-mass
    REALLOCATION, so negative values are legitimate (unlike a probability
    vector) but the total mass must be conserved."""
    if not isinstance(value, list):
        return [{"path": path, "code": "NOT_A_LIST",
                 "message": "Delta vector must be a list."}]

    errors = []
    if len(value) != expected_length:
        errors.append({"path": path, "code": "INVALID_LENGTH",
                       "message": f"Expected {expected_length} values; received {len(value)}."})

    for index, item in enumerate(value):
        errors.extend(_validate_finite_number(item, path=f"{path}[{index}]",
                                              minimum=-1.0, maximum=1.0))

    if errors:
        return errors

    total = math.fsum(float(item) for item in value)
    if not math.isclose(total, 0.0, rel_tol=0.0, abs_tol=DELTA_SUM_TOLERANCE):
        errors.append({"path": path, "code": "DELTA_SUM",
                       "message": f"Delta vector must sum to 0.0; received {total:.17g}."})
    return errors


def _validate_cpd_matrix(value: Any, *, path: str, rows: int, columns: int) -> list:
    """A pgmpy-shaped CPD matrix: `rows` outer lists, each of length
    `columns`. Every value finite and in [0,1]. Each COLUMN (not row)
    sums to 1.0 -- a pgmpy TabularCPD's columns are the conditional
    distributions; validating row sums here would be a real, silent
    correctness bug, not just a stricter check."""
    if not isinstance(value, list):
        return [{"path": path, "code": "NOT_A_LIST",
                 "message": "CPD matrix must be a list of rows."}]

    errors = []
    if len(value) != rows:
        errors.append({"path": path, "code": "INVALID_ROW_COUNT",
                       "message": f"Expected {rows} rows; received {len(value)}."})
        return errors

    for r, row in enumerate(value):
        if not isinstance(row, list):
            errors.append({"path": f"{path}[{r}]", "code": "NOT_A_LIST",
                           "message": "Each CPD row must be a list."})
            continue
        if len(row) != columns:
            errors.append({"path": f"{path}[{r}]", "code": "INVALID_COLUMN_COUNT",
                           "message": f"Expected {columns} columns; received {len(row)}."})
            continue
        for c, item in enumerate(row):
            errors.extend(_validate_finite_number(item, path=f"{path}[{r}][{c}]",
                                                  minimum=0.0, maximum=1.0))

    if errors:
        return errors

    for c in range(columns):
        col_total = math.fsum(float(value[r][c]) for r in range(rows))
        if not math.isclose(col_total, 1.0, rel_tol=0.0, abs_tol=PROBABILITY_SUM_TOLERANCE):
            errors.append({"path": f"{path}[:][{c}]", "code": "CPD_COLUMN_SUM",
                           "message": f"Column {c} sums to {col_total:.17g} rather than 1.0."})
    return errors


def _result(errors: list, warnings: list, checked_fields: int, label: str) -> dict:
    is_valid = not errors
    return {
        "is_valid": is_valid,
        "status": "PASS" if is_valid else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "checked_fields": checked_fields,
        "summary": (f"{label}: PASS ({checked_fields} field(s) checked)." if is_valid
                    else f"{label}: FAIL ({len(errors)} error(s), {checked_fields} field(s) checked)."),
    }


def format_bbn_validation_error(label: str, validation: dict) -> str:
    """Render a validation result (from either validator) as the
    ERROR: ... string bbn_threat_score returns -- concise, but every
    detected issue included, not just the first."""
    lines = [f"ERROR: {label} failed numeric validation.", ""]
    for err in validation["errors"]:
        lines.append(f"- {err['path']} [{err['code']}]:")
        lines.append(f"  {err['message']}")
    lines.append("")
    lines.append("Refusing to construct the Bayesian network.")
    return "\n".join(lines)


# ============================================================================
#  PER-ASSESSMENT CONFIGURATION VALIDATION
# ============================================================================

EXPECTED_DEFENSIVE_CONTROLS = {
    "mfa", "edr", "segmentation", "integrity_monitor", "email_filtering",
}

EVIDENCE_STATE_CARDINALITY = {
    "GeopoliticalTrigger": 2,
    "AdversaryCapability": 3,
    "PhishingAttempt": 2,
    "ScanningDetected": 2,
    "AuthAnomaly": 2,
}

REQUIRED_ASSESSMENT_TOP_LEVEL = {"adversary", "defensive_posture", "geopolitical_trigger_prior"}
OPTIONAL_ASSESSMENT_TOP_LEVEL = {"evidence", "kcag_report_path"}


def validate_bbn_assessment_config(config: Any) -> dict:
    """Validate the per-assessment cpd_config_json structure BEFORE any
    field is read into a calculation. Does not touch the filesystem
    (kcag_report_path existence is a separate, runtime artifact-boundary
    check, not this validator's job)."""
    errors = []
    warnings = []
    checked = 0

    if not isinstance(config, dict):
        errors.append({"path": "$", "code": "NOT_AN_OBJECT",
                       "message": "Configuration root must be a JSON object."})
        return _result(errors, warnings, checked, "per-assessment configuration")

    missing_top = REQUIRED_ASSESSMENT_TOP_LEVEL - set(config.keys())
    for field in sorted(missing_top):
        errors.append({"path": field, "code": "MISSING_REQUIRED_FIELD",
                       "message": "This field is required and has no default."})
    checked += len(REQUIRED_ASSESSMENT_TOP_LEVEL)

    unknown_top = set(config.keys()) - REQUIRED_ASSESSMENT_TOP_LEVEL - OPTIONAL_ASSESSMENT_TOP_LEVEL
    for field in sorted(unknown_top):
        warnings.append({"path": field, "code": "UNKNOWN_FIELD",
                         "message": "Field is not part of the recognized schema; ignored."})

    # ---- adversary.capability_prior / adversary.tempo ----
    adversary = config.get("adversary")
    checked += 1
    if adversary is None and "adversary" not in missing_top:
        errors.append({"path": "adversary", "code": "MISSING_REQUIRED_FIELD",
                       "message": "This field is required and has no default."})
    elif adversary is not None:
        if not isinstance(adversary, dict):
            errors.append({"path": "adversary", "code": "NOT_AN_OBJECT",
                           "message": "adversary must be an object."})
        else:
            checked += 1
            if "capability_prior" not in adversary:
                errors.append({"path": "adversary.capability_prior", "code": "MISSING_REQUIRED_FIELD",
                               "message": "This field is required and has no default."})
            else:
                errors.extend(_validate_probability_vector(
                    adversary["capability_prior"], path="adversary.capability_prior", expected_length=3))

            checked += 1
            if "tempo" not in adversary:
                errors.append({"path": "adversary.tempo", "code": "MISSING_REQUIRED_FIELD",
                               "message": "This field is required and has no default."})
            else:
                tempo = adversary["tempo"]
                if tempo not in ("LOW", "MEDIUM", "HIGH"):
                    errors.append({"path": "adversary.tempo", "code": "INVALID_ENUM",
                                   "message": "Must be exactly one of 'LOW', 'MEDIUM', 'HIGH' "
                                              "(case-sensitive, no automatic correction)."})

    # ---- defensive_posture ----
    posture = config.get("defensive_posture")
    checked += 1
    if posture is None and "defensive_posture" not in missing_top:
        errors.append({"path": "defensive_posture", "code": "MISSING_REQUIRED_FIELD",
                       "message": "This field is required and has no default."})
    elif posture is not None:
        if not isinstance(posture, dict):
            errors.append({"path": "defensive_posture", "code": "NOT_AN_OBJECT",
                           "message": "defensive_posture must be an object."})
        else:
            missing_controls = EXPECTED_DEFENSIVE_CONTROLS - set(posture.keys())
            unknown_controls = set(posture.keys()) - EXPECTED_DEFENSIVE_CONTROLS
            for control in sorted(missing_controls):
                errors.append({"path": f"defensive_posture.{control}", "code": "MISSING_CONTROL",
                               "message": "This control is required and has no default."})
            for control in sorted(unknown_controls):
                errors.append({"path": f"defensive_posture.{control}", "code": "UNKNOWN_CONTROL",
                               "message": "This control is not part of the recognized schema."})
            for control in sorted(EXPECTED_DEFENSIVE_CONTROLS & set(posture.keys())):
                checked += 1
                if type(posture[control]) is not bool:
                    errors.append({"path": f"defensive_posture.{control}", "code": "NOT_BOOLEAN",
                                   "message": "Control state must be exactly true or false."})

    # ---- geopolitical_trigger_prior ----
    checked += 1
    if "geopolitical_trigger_prior" in config:
        errors.extend(_validate_finite_number(
            config["geopolitical_trigger_prior"], path="geopolitical_trigger_prior",
            minimum=0.0, maximum=1.0))

    # ---- evidence (optional) ----
    if "evidence" in config:
        evidence = config["evidence"]
        checked += 1
        if not isinstance(evidence, dict):
            errors.append({"path": "evidence", "code": "NOT_AN_OBJECT",
                           "message": "evidence must be an object."})
        else:
            for key, val in evidence.items():
                checked += 1
                if key not in EVIDENCE_STATE_CARDINALITY:
                    errors.append({"path": f"evidence.{key}", "code": "UNKNOWN_EVIDENCE_NODE",
                                   "message": f"'{key}' is not a recognized evidence node."})
                    continue
                cardinality = EVIDENCE_STATE_CARDINALITY[key]
                if type(val) is bool or not isinstance(val, int):
                    errors.append({"path": f"evidence.{key}", "code": "STATE_NOT_INTEGER",
                                   "message": "Evidence state must be an integer, not a boolean or other type."})
                    continue
                if not 0 <= val < cardinality:
                    errors.append({"path": f"evidence.{key}", "code": "STATE_OUT_OF_RANGE",
                                   "message": f"Expected an integer from 0 through {cardinality - 1}; "
                                              f"received {val}."})

    # ---- kcag_report_path (optional) ----
    if "kcag_report_path" in config and config["kcag_report_path"] is not None:
        checked += 1
        path_val = config["kcag_report_path"]
        if not isinstance(path_val, str) or not path_val.strip():
            errors.append({"path": "kcag_report_path", "code": "INVALID_PATH",
                           "message": "When supplied, kcag_report_path must be a nonempty string. "
                                      "(File existence is checked separately at runtime.)"})

    return _result(errors, warnings, checked, "per-assessment configuration")


# ============================================================================
#  PRIORS DOCUMENT VALIDATION
# ============================================================================

SCALAR_PRIOR_RULES = {
    "defensive_posture_floor": {"min": 0.0, "max": 0.5},
    "defensive_multiplier_floor": {"min": 0.0, "max": 1.0},
    "defensive_multiplier_scale": {"min": 0.0, "max": 1.0},
    "iw_effect_phase_base_recon": {"min": 0.0, "max": 1.0},
    "iw_effect_phase_base_initial_access": {"min": 0.0, "max": 1.0},
    "iw_effect_phase_base_lateral": {"min": 0.0, "max": 1.0},
    "iw_effect_objective_convergence_factor": {"exclusive_min": 0.0},
    "iw_effect_objective_cap": {"min": 0.0, "max": 1.0},
    "iw_effect_posture_multiplier_strong": {"min": 0.0, "max": 1.0},
    "iw_effect_posture_multiplier_moderate": {"min": 0.0, "max": 1.0},
    "iw_effect_geo_multiplier": {"min": 0.0},
    "iw_effect_geo_cap": {"min": 0.0, "max": 1.0},
}


def _get_prior_entry(priors: dict, *path, errors: list, checked: list) -> dict:
    """Walk a dotted path into the priors dict, validating the
    {value, source} leaf structure. Returns the entry dict ({"value":
    ..., "source": ...}) or None if missing/malformed (with an error
    already appended)."""
    node = priors
    dotted = ".".join(path)
    checked[0] += 1
    for i, key in enumerate(path):
        if not isinstance(node, dict) or key not in node:
            errors.append({"path": ".".join(path[:i + 1]), "code": "MISSING_REQUIRED_PRIOR",
                           "message": "This prior is required and has no default."})
            return None
        node = node[key]

    if not isinstance(node, dict):
        errors.append({"path": dotted, "code": "MALFORMED_PRIOR_ENTRY",
                       "message": "Prior entry must be an object with 'value' and 'source'."})
        return None
    if "value" not in node:
        errors.append({"path": f"{dotted}.value", "code": "MISSING_VALUE",
                       "message": "Prior entry is missing its 'value' field."})
        return None
    if "source" not in node or not isinstance(node["source"], str) or not node["source"].strip():
        errors.append({"path": f"{dotted}.source", "code": "EMPTY_SOURCE",
                       "message": "Every prior requires nonempty provenance."})
        return None
    return node


def validate_bbn_priors_document(document: Any) -> dict:
    """Validate config/bbn_priors.json in full: every required prior's
    presence, provenance, shape, range, and sum -- plus cross-field
    invariants and all 24 derived KillChainPhase combinations, all
    BEFORE any pgmpy model is constructed from this data."""
    errors = []
    warnings = []
    checked = [0]  # mutable box so the helper can increment it

    if not isinstance(document, dict):
        errors.append({"path": "$", "code": "NOT_AN_OBJECT",
                       "message": "Priors document root must be a JSON object."})
        return _result(errors, warnings, checked[0], "priors document")

    if "priors" not in document or not isinstance(document["priors"], dict):
        errors.append({"path": "priors", "code": "MISSING_TOP_LEVEL_PRIORS",
                       "message": "Document must contain a top-level 'priors' object."})
        return _result(errors, warnings, checked[0], "priors document")

    priors = document["priors"]
    values = {}  # path-string -> extracted numeric value(s), for cross-field checks below

    def get(*path):
        entry = _get_prior_entry(priors, *path, errors=errors, checked=checked)
        return entry["value"] if entry is not None else None

    # ---- Probability vectors ----
    for tempo in ("LOW", "MEDIUM", "HIGH"):
        v = get("operational_tempo_distribution", tempo)
        if v is not None:
            errs = _validate_probability_vector(v, path=f"operational_tempo_distribution.{tempo}", expected_length=3)
            errors.extend(errs)
            if not errs:
                values[f"tempo_dist_{tempo}"] = v

    v = get("auth_anomaly_root")
    if v is not None:
        errors.extend(_validate_probability_vector(v, path="auth_anomaly_root", expected_length=2))

    for actor in ("nation_state", "criminal", "hacktivist"):
        v = get("killchain_phase_base", actor)
        if v is not None:
            errs = _validate_probability_vector(v, path=f"killchain_phase_base.{actor}", expected_length=4)
            errors.extend(errs)
            if not errs:
                values[f"phase_base_{actor}"] = v

    # ---- CPD matrices ----
    v = get("phishing_given_capability")
    if v is not None:
        errors.extend(_validate_cpd_matrix(v, path="phishing_given_capability", rows=2, columns=3))
    v = get("scanning_given_tempo")
    if v is not None:
        errors.extend(_validate_cpd_matrix(v, path="scanning_given_tempo", rows=2, columns=3))

    # ---- Evidence deltas ----
    for name in ("phishing", "scanning", "auth_anomaly"):
        v = get(f"killchain_phase_evidence_delta_{name}")
        if v is not None:
            errs = _validate_delta_vector(v, path=f"killchain_phase_evidence_delta_{name}", expected_length=4)
            errors.extend(errs)
            if not errs:
                values[f"delta_{name}"] = v

    # ---- Scalar priors (field-specific bounds) ----
    _RULE_KEY_MAP = {"min": "minimum", "max": "maximum", "exclusive_min": "exclusive_min"}
    for field, rules in SCALAR_PRIOR_RULES.items():
        v = get(field)
        if v is not None:
            mapped_rules = {_RULE_KEY_MAP[k]: val for k, val in rules.items()}
            errs = _validate_finite_number(v, path=field, **mapped_rules)
            errors.extend(errs)
            if not errs:
                values[field] = float(v)

    # ---- Cross-field invariants (only meaningful if their inputs were individually valid) ----

    # Posture multipliers: strong <= moderate <= 1.0
    if "iw_effect_posture_multiplier_strong" in values and "iw_effect_posture_multiplier_moderate" in values:
        strong = values["iw_effect_posture_multiplier_strong"]
        moderate = values["iw_effect_posture_multiplier_moderate"]
        if not (strong <= moderate <= 1.0):
            errors.append({"path": "iw_effect_posture_multiplier_strong/moderate",
                           "code": "POSTURE_MULTIPLIER_ORDER",
                           "message": f"Require strong ({strong}) <= moderate ({moderate}) <= 1.0."})

    # Phase bases: recon <= initial_access <= lateral
    phase_keys = ("iw_effect_phase_base_recon", "iw_effect_phase_base_initial_access",
                  "iw_effect_phase_base_lateral")
    if all(k in values for k in phase_keys):
        recon, ia, lat = (values[k] for k in phase_keys)
        if not (recon <= ia <= lat):
            errors.append({"path": "/".join(phase_keys), "code": "PHASE_BASE_NOT_MONOTONIC",
                           "message": f"Require recon ({recon}) <= initial_access ({ia}) <= lateral ({lat})."})

    # Defensive multiplier formula, boundary coverage values
    if "defensive_multiplier_floor" in values and "defensive_multiplier_scale" in values:
        floor = values["defensive_multiplier_floor"]
        scale = values["defensive_multiplier_scale"]
        for coverage in (0.0, 1.0):
            dm = max(floor, 1.0 - coverage * scale)
            if not (math.isfinite(dm) and 0.0 <= dm <= 1.0):
                errors.append({"path": "defensive_multiplier_floor/scale", "code": "DEFENSIVE_MULTIPLIER_FORMULA",
                               "message": f"defensive multiplier formula produces {dm} at coverage={coverage}, "
                                          f"outside [0,1] or non-finite."})

    # Objective formula, boundary KCAG scores
    if "iw_effect_objective_convergence_factor" in values and "iw_effect_objective_cap" in values:
        conv = values["iw_effect_objective_convergence_factor"]
        cap = values["iw_effect_objective_cap"]
        for kcag_score in (0.0, 1.0):
            obj = min(cap, kcag_score * conv)
            if not (math.isfinite(obj) and 0.0 <= obj <= 1.0):
                errors.append({"path": "iw_effect_objective_convergence_factor/iw_effect_objective_cap",
                               "code": "OBJECTIVE_FORMULA",
                               "message": f"objective formula produces {obj} at kcag_score={kcag_score}, "
                                          f"outside [0,1] or non-finite."})

    # Geopolitical effect formula, boundary base values
    if "iw_effect_geo_multiplier" in values and "iw_effect_geo_cap" in values:
        geo_mult = values["iw_effect_geo_multiplier"]
        geo_cap = values["iw_effect_geo_cap"]
        for base in (0.0, 1.0):
            geo = min(geo_cap, base * geo_mult)
            if not (math.isfinite(geo) and 0.0 <= geo <= 1.0):
                errors.append({"path": "iw_effect_geo_multiplier/iw_effect_geo_cap", "code": "GEO_FORMULA",
                               "message": f"geopolitical effect formula produces {geo} at base={base}, "
                                          f"outside [0,1] or non-finite."})

    # ---- All 24 derived KillChainPhase combinations ----
    phase_bases_ok = all(f"phase_base_{a}" in values for a in ("nation_state", "criminal", "hacktivist"))
    deltas_ok = all(f"delta_{n}" in values for n in ("phishing", "scanning", "auth_anomaly"))
    if phase_bases_ok and deltas_ok:
        actor_index = {0: "hacktivist", 1: "criminal", 2: "nation_state"}
        for cap_i in range(3):
            base_vec = values[f"phase_base_{actor_index[cap_i]}"]
            for ph in (0, 1):
                for sc in (0, 1):
                    for au in (0, 1):
                        candidate = list(base_vec)
                        if ph:
                            candidate = [b + d for b, d in zip(candidate, values["delta_phishing"])]
                        if sc:
                            candidate = [b + d for b, d in zip(candidate, values["delta_scanning"])]
                        if au:
                            candidate = [b + d for b, d in zip(candidate, values["delta_auth_anomaly"])]

                        combo_path = (f"killchain_phase_base.{actor_index[cap_i]}"
                                     f"+phishing={ph}+scanning={sc}+auth={au}")
                        if not all(math.isfinite(b) for b in candidate):
                            errors.append({"path": combo_path, "code": "COMBINED_PHASE_NON_FINITE",
                                           "message": f"Combined phase vector is non-finite: {candidate}."})
                            continue
                        if any(b < 0.0 for b in candidate):
                            errors.append({"path": combo_path, "code": "COMBINED_PHASE_NEGATIVE",
                                           "message": f"Combined phase vector has a negative component "
                                                      f"before runtime clipping: {candidate}."})
                            continue
                        total = math.fsum(candidate)
                        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
                            errors.append({"path": combo_path, "code": "COMBINED_PHASE_SUM",
                                           "message": f"Combined phase vector sums to {total:.6g} rather "
                                                      f"than 1.0: {candidate}."})

    return _result(errors, warnings, checked[0], "priors document")
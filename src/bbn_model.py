"""
Pure BBN model construction and evaluation, extracted from bbn_threat_score
so sensitivity analysis can evaluate many scenarios without duplicating the
Bayesian-network mathematics or calling the CrewAI tool repeatedly.

evaluate_bbn_model() performs NO filesystem writes and does NOT mutate its
inputs. It assumes assessment_config and priors_document have already been
validated (src.bbn_validation) -- it is not itself a validation gate.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BBNEvaluation:
    threat_score: float
    threat_level: str
    baseline_score: float          # IWEffectAchieved with NO evidence applied
    delta_from_baseline: float
    likely_phase: str
    phase_distribution: list       # [RECON, INITIAL ACCESS, LATERAL/PIVOT, OBJECTIVE], sums to 1.0
    iw_effect_distribution: list   # [P(no effect), P(effect achieved)], sums to 1.0
    evidence_applied: dict
    kcag_objective_score: float
    defensive_multiplier: float
    node_posteriors: dict = field(default_factory=dict)
    cpd_audit_log: list = field(default_factory=list)


PHASE_LABELS = {0: "RECON", 1: "INITIAL ACCESS", 2: "LATERAL / PIVOT", 3: "OBJECTIVE"}
THREAT_LEVEL_THRESHOLDS = [(0.20, "LOW"), (0.50, "ELEVATED"), (0.75, "HIGH"), (1.01, "CRITICAL")]


def _threat_level(score: float) -> str:
    for threshold, label in THREAT_LEVEL_THRESHOLDS:
        if score < threshold:
            return label
    return "CRITICAL"


def evaluate_bbn_model(*, assessment_config: dict, priors_document: dict,
                       kcag_objective_score: float) -> BBNEvaluation:
    """Construct, validate, and evaluate one complete BBN instance.

    assessment_config and priors_document must already be valid per
    src.bbn_validation.validate_bbn_assessment_config() /
    validate_bbn_priors_document() -- this function does not re-run those
    validators and does not fail closed on malformed input the way
    bbn_threat_score() does; it raises LookupError/KeyError/ValueError
    directly if something required is actually missing, since callers
    (bbn_threat_score for the baseline, run_bbn_sensitivity for every
    scenario) are expected to have validated already and to decide for
    themselves how an unexpected internal failure should be reported.

    Builds a FRESH pgmpy model on every call -- nothing is cached or
    reused between calls, so scenario evaluations can never leak state
    into each other or into the baseline.
    """
    from pgmpy.models import DiscreteBayesianNetwork
    from pgmpy.factors.discrete import TabularCPD
    from pgmpy.inference import VariableElimination

    priors = priors_document["priors"]
    AUDIT: list = []

    def log(node, value, source):
        AUDIT.append({"node": node, "value": value, "source": source})
        return value

    def prior(*path):
        node = priors
        for i, key in enumerate(path):
            if not isinstance(node, dict) or key not in node:
                raise LookupError(f"required prior '{'.'.join(path[:i + 1])}' missing from priors document")
            node = node[key]
        if not (isinstance(node, dict) and "value" in node):
            raise LookupError(f"prior '{'.'.join(path)}' is missing its 'value' field")
        return node["value"], node.get("source", "(no source field in priors file)")

    adversary = assessment_config["adversary"]
    cap_prior = adversary["capability_prior"]
    tempo = adversary["tempo"]
    posture = assessment_config["defensive_posture"]
    geo_prior = float(assessment_config["geopolitical_trigger_prior"])
    evidence = assessment_config.get("evidence", {})

    # ---- Defensive multiplier --------------------------------------------
    dm_floor, dm_floor_src = prior("defensive_multiplier_floor")
    dm_scale, dm_scale_src = prior("defensive_multiplier_scale")
    active = sum(1 for v in posture.values() if v)
    total = max(1, len(posture))
    dm = max(dm_floor, 1.0 - (active / total) * dm_scale)
    log("DefensiveMultiplier", round(dm, 4),
        f"{active}/{total} controls active; floor={dm_floor} ({dm_floor_src}); "
        f"scale={dm_scale} ({dm_scale_src})")

    # ---- Build the DAG -----------------------------------------------------
    # Layer 1 priors -> Layer 2 observables -> Layer 3 phase -> Layer 5 outcome
    model = DiscreteBayesianNetwork([
        ("AdversaryCapability", "PhishingAttempt"),
        ("OperationalTempo", "ScanningDetected"),
        ("AdversaryCapability", "KillChainPhase"),
        ("PhishingAttempt", "KillChainPhase"),
        ("ScanningDetected", "KillChainPhase"),
        ("AuthAnomaly", "KillChainPhase"),
        ("KillChainPhase", "IWEffectAchieved"),
        ("DefensivePosture", "IWEffectAchieved"),
        ("GeopoliticalTrigger", "IWEffectAchieved"),
    ])

    cpds = []

    # AdversaryCapability (root, 3 states) -- analyst-supplied, required.
    # Assumed already validated by the caller -- no floor/renormalize here.
    # A valid analyst-supplied zero is meaningful and stays exactly zero.
    cap = [float(p) for p in cap_prior]
    cpds.append(TabularCPD("AdversaryCapability", 3, [[cap[0]], [cap[1]], [cap[2]]]))
    log("AdversaryCapability", cap, "adversary.capability_prior (analyst-supplied, required)")

    # OperationalTempo (root, 3 states) -- distribution from priors file
    tempo_dist, tempo_src = prior("operational_tempo_distribution", tempo)
    cpds.append(TabularCPD("OperationalTempo", 3, [[p] for p in tempo_dist]))
    log("OperationalTempo", tempo_dist, f"adversary.tempo={tempo}; {tempo_src}")

    # PhishingAttempt | AdversaryCapability -- from priors file
    phish_cpd, phish_src = prior("phishing_given_capability")
    cpds.append(TabularCPD(
        "PhishingAttempt", 2, phish_cpd,
        evidence=["AdversaryCapability"], evidence_card=[3]))
    log("PhishingAttempt|cap", phish_cpd, phish_src)

    # ScanningDetected | OperationalTempo -- from priors file
    scan_cpd, scan_src = prior("scanning_given_tempo")
    cpds.append(TabularCPD(
        "ScanningDetected", 2, scan_cpd,
        evidence=["OperationalTempo"], evidence_card=[3]))
    log("ScanningDetected|tempo", scan_cpd, scan_src)

    # AuthAnomaly (root observable) -- from priors file
    auth_root, auth_src = prior("auth_anomaly_root")
    cpds.append(TabularCPD("AuthAnomaly", 2, [[auth_root[0]], [auth_root[1]]]))
    log("AuthAnomaly", auth_root, auth_src)

    # GeopoliticalTrigger (root) -- analyst-supplied, required
    cpds.append(TabularCPD("GeopoliticalTrigger", 2, [[1 - geo_prior], [geo_prior]]))
    log("GeopoliticalTrigger", [1 - geo_prior, geo_prior],
        "geopolitical_trigger_prior (analyst-supplied, required)")

    # DefensivePosture (root, 3 states weak/moderate/strong from active count)
    dp_floor, dp_floor_src = prior("defensive_posture_floor")
    frac = active / total
    dp = [max(dp_floor, 1 - frac), 0.0, max(dp_floor, frac)]
    dp[1] = max(0.0, 1 - dp[0] - dp[2])
    s = sum(dp)
    dp = [p / s for p in dp]
    cpds.append(TabularCPD("DefensivePosture", 3, [[dp[0]], [dp[1]], [dp[2]]]))
    log("DefensivePosture", dp, f"{active}/{total} controls active; floor={dp_floor} ({dp_floor_src})")

    # KillChainPhase | cap(3) x phish(2) x scan(2) x auth(2) = 24 cols, 4 states
    kcp_base = {
        2: prior("killchain_phase_base", "nation_state"),
        1: prior("killchain_phase_base", "criminal"),
        0: prior("killchain_phase_base", "hacktivist"),
    }
    delta_phish, delta_phish_src = prior("killchain_phase_evidence_delta_phishing")
    delta_scan, delta_scan_src = prior("killchain_phase_evidence_delta_scanning")
    delta_auth, delta_auth_src = prior("killchain_phase_evidence_delta_auth_anomaly")

    def phase_probs(cap_i, phish, scan, auth):
        base = list(kcp_base[cap_i][0])
        if phish:
            base = [b + d for b, d in zip(base, delta_phish)]
        if scan:
            base = [b + d for b, d in zip(base, delta_scan)]
        if auth:
            base = [b + d for b, d in zip(base, delta_auth)]
        base[2] *= dm
        base[3] *= dm * kcag_objective_score
        base = [max(0.001, b) for b in base]
        t = sum(base)
        return [b / t for b in base]

    rows = [[], [], [], []]
    for ci in range(3):
        for ph in range(2):
            for sc in range(2):
                for au in range(2):
                    pr = phase_probs(ci, ph, sc, au)
                    for k in range(4):
                        rows[k].append(pr[k])
    cpds.append(TabularCPD(
        "KillChainPhase", 4, rows,
        evidence=["AdversaryCapability", "PhishingAttempt", "ScanningDetected", "AuthAnomaly"],
        evidence_card=[3, 2, 2, 2]))
    log("KillChainPhase", "computed",
        f"base rates: nation_state=({kcp_base[2][1]}), criminal=({kcp_base[1][1]}), "
        f"hacktivist=({kcp_base[0][1]}); deltas: phishing=({delta_phish_src}), "
        f"scanning=({delta_scan_src}), auth_anomaly=({delta_auth_src}); KCAG-anchored")

    # IWEffectAchieved | phase(4) x posture(3) x geo(2) = 24 cols, 2 states
    recon_base, recon_src = prior("iw_effect_phase_base_recon")
    ia_base, ia_src = prior("iw_effect_phase_base_initial_access")
    lat_base, lat_src = prior("iw_effect_phase_base_lateral")
    conv_factor, conv_src = prior("iw_effect_objective_convergence_factor")
    obj_cap, obj_cap_src = prior("iw_effect_objective_cap")
    strong_mult, strong_src = prior("iw_effect_posture_multiplier_strong")
    mod_mult, mod_src = prior("iw_effect_posture_multiplier_moderate")
    geo_mult, geo_mult_src = prior("iw_effect_geo_multiplier")
    geo_cap, geo_cap_src = prior("iw_effect_geo_cap")

    obj_base = round(min(obj_cap, kcag_objective_score * conv_factor), 4)
    PHASE_BASE = [
        log("IWEffect|Recon", recon_base, recon_src),
        log("IWEffect|InitAccess", ia_base, ia_src),
        log("IWEffect|Lateral", lat_base, lat_src),
        log("IWEffect|Objective", obj_base, f"{conv_src} capped by ({obj_cap_src})"),
    ]

    def iw_probs(phase, dposture, geo):
        p = PHASE_BASE[phase]
        if dposture == 2:
            p *= strong_mult
        elif dposture == 1:
            p *= mod_mult
        if geo:
            p = min(geo_cap, p * geo_mult)
        p = min(0.999, max(0.001, p))
        return [1 - p, p]

    no_, yes_ = [], []
    for ph in range(4):
        for dpz in range(3):
            for g in range(2):
                a, b = iw_probs(ph, dpz, g)
                no_.append(a)
                yes_.append(b)
    cpds.append(TabularCPD(
        "IWEffectAchieved", 2, [no_, yes_],
        evidence=["KillChainPhase", "DefensivePosture", "GeopoliticalTrigger"],
        evidence_card=[4, 3, 2]))
    log("IWEffectAchieved", "computed",
        f"phase x posture ({strong_src}; {mod_src}) x geopolitical "
        f"({geo_mult_src}; capped {geo_cap_src})")

    model.add_cpds(*cpds)
    if not model.check_model():
        raise ValueError("BBN failed validation (cyclic or malformed CPDs).")

    infer = VariableElimination(model)

    valid_nodes = set(model.nodes())
    ev = {k: int(v) for k, v in evidence.items() if k in valid_nodes}

    score = float(infer.query(["IWEffectAchieved"], evidence=ev).values[1])
    phase_dist = infer.query(["KillChainPhase"], evidence=ev).values
    phase_idx = int(phase_dist.argmax())
    base_score = float(infer.query(["IWEffectAchieved"]).values[1])

    phase_distribution = [float(phase_dist[i]) for i in range(4)]
    iw_effect_distribution = [1.0 - score, score]

    return BBNEvaluation(
        threat_score=round(score, 4),
        threat_level=_threat_level(score),
        baseline_score=round(base_score, 4),
        delta_from_baseline=round(score - base_score, 4),
        likely_phase=PHASE_LABELS[phase_idx],
        phase_distribution=[round(v, 4) for v in phase_distribution],
        iw_effect_distribution=[round(v, 4) for v in iw_effect_distribution],
        evidence_applied=ev,
        kcag_objective_score=round(kcag_objective_score, 4),
        defensive_multiplier=round(dm, 4),
        node_posteriors={
            "KillChainPhase": [round(v, 4) for v in phase_distribution],
            "IWEffectAchieved": [round(v, 4) for v in iw_effect_distribution],
        },
        cpd_audit_log=AUDIT,
    )
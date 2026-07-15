"""
Annex C prior-derivation subsystem.

The analyst runs this pipeline BECAUSE deriving the four BBN priors from the
frozen PAI/OSINT corpus IS the analytical work — they never hand-author
annexc_inputs. But the pipeline must never fabricate a prior to proceed
(that is the same "optimize to pass" failure as the RT-003 technique swap).
This module reconciles the two: an LLM proposes each prior WITH cited,
quote-level corpus evidence; a deterministic validator confirms every quote
actually exists in the frozen normalized text and every citation binds to a
real frozen source hash; a per-prior no-evidence policy decides what happens
when support is absent; and a hash-bound analyst approval gate governs
whether the derived configuration may feed scoring.

This module OWNS derivation only. It does not construct a pgmpy model and it
does not alter the Bayesian topology or mathematics. It compiles a candidate
assessment configuration and hands it to the EXISTING
validate_bbn_assessment_config(); the existing scoring runs unchanged.

Public surface:
    derive_annexc_inputs(...)          -- orchestrate LLM proposal + policy
    validate_derivation(...)           -- deterministic citation/policy checks
    compile_bbn_assessment_config(...) -- derivation -> validator-shaped config
    annexc_derivation_hash(...)        -- canonical hash of the review subject
    evaluate_derivation_approval(...)  -- hash-bound approval gate decision
    require_approved_derivation(...)   -- raise unless the gate is satisfied

The module accepts explicit inputs and returns plain objects. No hidden
global state.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping

from src.state import canonical_json_sha256
from src.bbn_validation import (
    validate_bbn_assessment_config, EXPECTED_DEFENSIVE_CONTROLS,
)


# ---- constants ----

FOUR_PRIORS = (
    "capability_prior",
    "tempo",
    "defensive_posture",
    "geopolitical_trigger_prior",
)

ALLOWED_STATUSES = {"SUPPORTED", "DEFAULTED", "BLOCKED"}
ALLOWED_SOURCE_MODES = {"CORPUS", "ASSESSMENT_CONFIG", "POLICY_DEFAULT", "ANALYST_JUDGMENT"}
ALLOWED_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}
ALLOWED_TEMPO = {"LOW", "MEDIUM", "HIGH"}

REQUIRED_RECORD_FIELDS = (
    "value", "status", "source_mode", "confidence", "reasoning", "evidence",
)


class DerivationError(Exception):
    """Raised for structural problems in a derivation the pipeline authored."""


class DerivationApprovalBlocked(Exception):
    """Raised (via require_approved_derivation) when the approval gate is not
    satisfied. Distinct from an analytical failure."""


# ---- text normalization for deterministic quote verification ----

def _normalize_text(text: str) -> str:
    """Collapse whitespace so a cited quote is matched against the frozen
    source the same way regardless of line wrapping. Deterministic; no
    semantic transformation."""
    return " ".join((text or "").split())


def quote_is_present(quote: str, frozen_text: str) -> bool:
    """True iff the normalized quote appears verbatim in the normalized
    frozen source text. Deterministic substring check — no fuzzy/semantic
    matching, which is exactly what keeps a citation honest."""
    q = _normalize_text(quote)
    if not q:
        return False
    return q in _normalize_text(frozen_text)


# ---- policy loading ----

def load_derivation_policy(policy_path: str) -> dict:
    with open(policy_path) as f:
        policy = json.load(f)
    # Minimal shape guard — the policy is a trusted repo artifact, but a
    # malformed one must fail loudly, not silently default.
    if "no_evidence" not in policy or "policy_version" not in policy:
        raise DerivationError(
            f"Derivation policy at {policy_path} is missing no_evidence/policy_version.")
    return policy


# ---- per-prior no-evidence policy application ----

def apply_no_evidence_policy(field: str, policy: dict) -> dict:
    """Return the derivation record for a prior that has NO supporting
    evidence, per the versioned policy. capability_prior and
    geopolitical_trigger_prior DEFAULT (visibly, LOW confidence); tempo and
    defensive_posture BLOCK (absence of info must never become a substantive
    assessment via an existing enum/boolean)."""
    ne = policy["no_evidence"]

    if field == "capability_prior":
        return {
            "field": "adversary.capability_prior",
            "value": list(ne["capability_prior"]),
            "status": "DEFAULTED",
            "source_mode": "POLICY_DEFAULT",
            "confidence": "LOW",
            "reasoning": ("No corpus evidence resolved adversary capability. A uniform "
                          "distribution expresses unresolved uncertainty without equating "
                          "'no evidence' with 'low capability'."),
            "evidence": [{
                "source_type": "POLICY_DEFAULT",
                "source_file": "config/annexc_derivation_policy.json",
                "policy_version": policy["policy_version"],
            }],
        }

    if field == "geopolitical_trigger_prior":
        spec = ne["geopolitical_trigger_prior"]
        return {
            "field": "geopolitical_trigger_prior",
            "value": float(spec["value"]),
            "status": "DEFAULTED",
            "source_mode": "POLICY_DEFAULT",
            "confidence": "LOW",
            "reasoning": ("No corpus evidence resolved a geopolitical trigger. Using the "
                          "explicit analyst-policy base rate, not an empirical finding."),
            "evidence": [{
                "source_type": "POLICY_DEFAULT",
                "source_file": "config/annexc_derivation_policy.json",
                "policy_version": policy["policy_version"],
            }],
        }

    # tempo and defensive_posture BLOCK.
    field_path = "adversary.tempo" if field == "tempo" else "defensive_posture"
    return {
        "field": field_path,
        "value": None,
        "status": "BLOCKED",
        "source_mode": "POLICY_DEFAULT",
        "confidence": "LOW",
        "reasoning": (f"No evidence resolved {field_path}, and policy forbids defaulting it: "
                      "selecting an existing value would turn absence of information into a "
                      "substantive assessment. Requires quote-supported corpus evidence or an "
                      "explicit analyst judgment."),
        "evidence": [{
            "source_type": "POLICY_DEFAULT",
            "source_file": "config/annexc_derivation_policy.json",
            "policy_version": policy["policy_version"],
        }],
    }


# ---- deterministic derivation validation ----

def _validate_record_shape(field: str, record: dict) -> list:
    errors = []
    for f in REQUIRED_RECORD_FIELDS:
        if f not in record:
            errors.append({"path": f"{field}.{f}", "code": "MISSING_RECORD_FIELD",
                           "message": f"Prior record missing required field {f!r}."})
    if record.get("status") not in ALLOWED_STATUSES:
        errors.append({"path": f"{field}.status", "code": "INVALID_STATUS",
                       "message": f"status must be one of {sorted(ALLOWED_STATUSES)}."})
    if record.get("source_mode") not in ALLOWED_SOURCE_MODES:
        errors.append({"path": f"{field}.source_mode", "code": "INVALID_SOURCE_MODE",
                       "message": f"source_mode must be one of {sorted(ALLOWED_SOURCE_MODES)}."})
    if record.get("confidence") not in ALLOWED_CONFIDENCE:
        errors.append({"path": f"{field}.confidence", "code": "INVALID_CONFIDENCE",
                       "message": f"confidence must be one of {sorted(ALLOWED_CONFIDENCE)}."})
    if not (record.get("reasoning") or "").strip():
        errors.append({"path": f"{field}.reasoning", "code": "MISSING_REASONING",
                       "message": "Concise reasoning is mandatory."})
    return errors


def _validate_corpus_evidence(field: str, record: dict,
                              frozen_sources: Mapping) -> list:
    """For a CORPUS-mode record: at least one citation with a quote that is
    found deterministically in the frozen normalized source whose hash
    matches the manifest. A missing/stale/unverifiable citation turns a
    proposed SUPPORTED record into a hard error (caller downgrades to
    BLOCKED), never a warning."""
    errors = []
    evidence = record.get("evidence") or []
    corpus_cites = [e for e in evidence if e.get("source_type") == "CORPUS"]
    if not corpus_cites:
        errors.append({"path": f"{field}.evidence", "code": "NO_CORPUS_CITATION",
                       "message": "A CORPUS-derived value requires at least one corpus citation."})
        return errors

    any_verified = False
    for i, cite in enumerate(corpus_cites):
        p = f"{field}.evidence[{i}]"
        src_file = cite.get("source_file")
        src_hash = cite.get("source_sha256")
        quote = cite.get("quote")

        if not quote or not _normalize_text(quote):
            errors.append({"path": p, "code": "MISSING_QUOTE",
                           "message": "Each corpus citation must contain a quote."})
            continue
        if not src_file:
            errors.append({"path": p, "code": "MISSING_SOURCE_FILE",
                           "message": "Citation must identify the frozen source item."})
            continue

        frozen = frozen_sources.get(src_file)
        if frozen is None:
            errors.append({"path": p, "code": "UNKNOWN_SOURCE_FILE",
                           "message": f"Cited source {src_file!r} is not in the frozen corpus."})
            continue

        # Frozen source hash must match the citation's claimed hash.
        if src_hash is not None and frozen.get("sha256") not in (src_hash, None):
            if frozen.get("sha256") != src_hash:
                errors.append({"path": p, "code": "SOURCE_HASH_MISMATCH",
                               "message": "Citation source_sha256 does not match the frozen source hash."})
                continue

        if not quote_is_present(quote, frozen.get("text", "")):
            errors.append({"path": p, "code": "QUOTE_NOT_FOUND",
                           "message": "Cited quote was not found in the frozen normalized source text."})
            continue

        any_verified = True

    if not any_verified and not errors:
        errors.append({"path": f"{field}.evidence", "code": "NO_VERIFIED_CITATION",
                       "message": "No citation could be verified against the frozen corpus."})
    return errors


def _validate_assessment_config_evidence(field: str, record: dict) -> list:
    """For an ASSESSMENT_CONFIG-mode record (defensive_posture): evidence must
    point to the exact configuration field / approved assessment artifact. A
    corpus quote is neither required nor preferred."""
    errors = []
    evidence = record.get("evidence") or []
    ac = [e for e in evidence if e.get("source_type") == "ASSESSMENT_CONFIG"]
    if not ac:
        errors.append({"path": f"{field}.evidence", "code": "NO_ASSESSMENT_CONFIG_EVIDENCE",
                       "message": "An assessment-owned value must cite ASSESSMENT_CONFIG evidence."})
        return errors
    for i, e in enumerate(ac):
        if not e.get("config_field") and not e.get("source_file"):
            errors.append({"path": f"{field}.evidence[{i}]", "code": "UNBOUND_ASSESSMENT_EVIDENCE",
                           "message": "ASSESSMENT_CONFIG evidence must name a config_field or artifact."})
    return errors


def validate_derivation(derivation: dict, *, frozen_sources: Mapping,
                        policy: dict) -> dict:
    """Deterministically validate a full derivation (all four priors).
    Returns {is_valid, errors, priors:{field: resolved_status}}. Enforces
    record shape, per-mode evidence rules, and the no-BLOCKED requirement is
    left to the caller (the gate) — this reports status truthfully.
    """
    errors = []
    priors = derivation.get("priors") or {}
    resolved = {}

    for field in FOUR_PRIORS:
        record = priors.get(field)
        if record is None:
            errors.append({"path": field, "code": "MISSING_PRIOR",
                           "message": f"Derivation is missing prior {field!r}."})
            resolved[field] = "MISSING"
            continue

        shape_errors = _validate_record_shape(field, record)
        errors.extend(shape_errors)
        if shape_errors:
            resolved[field] = "INVALID"
            continue

        status = record["status"]
        mode = record["source_mode"]

        if status == "SUPPORTED":
            if mode == "CORPUS":
                ev_errors = _validate_corpus_evidence(field, record, frozen_sources)
            elif mode == "ASSESSMENT_CONFIG":
                ev_errors = _validate_assessment_config_evidence(field, record)
            elif mode == "ANALYST_JUDGMENT":
                # Analyst override: rationale mandatory, never corpus-supported.
                ev_errors = []
                if not (record.get("reasoning") or "").strip():
                    ev_errors.append({"path": f"{field}.reasoning", "code": "MISSING_RATIONALE",
                                      "message": "Analyst judgment requires a rationale."})
            else:  # POLICY_DEFAULT can't be SUPPORTED
                ev_errors = [{"path": f"{field}.source_mode", "code": "SUPPORTED_REQUIRES_EVIDENCE_MODE",
                              "message": "A SUPPORTED value cannot have source_mode POLICY_DEFAULT."}]
            if ev_errors:
                errors.extend(ev_errors)
                # A SUPPORTED record whose citation fails becomes BLOCKED.
                resolved[field] = "BLOCKED"
            else:
                resolved[field] = "SUPPORTED"

        elif status == "DEFAULTED":
            # Only capability_prior and geopolitical_trigger_prior may default.
            if field not in ("capability_prior", "geopolitical_trigger_prior"):
                errors.append({"path": f"{field}.status", "code": "DEFAULT_NOT_ALLOWED",
                               "message": f"{field} may not be DEFAULTED; policy requires BLOCK."})
                resolved[field] = "BLOCKED"
            else:
                resolved[field] = "DEFAULTED"

        else:  # BLOCKED
            resolved[field] = "BLOCKED"

    return {
        "is_valid": not errors,
        "errors": errors,
        "priors": resolved,
    }


# ---- compile derivation -> validator-shaped config ----

def compile_bbn_assessment_config(derivation: dict) -> dict:
    """Turn a derivation into the exact shape validate_bbn_assessment_config
    expects: {adversary:{capability_prior, tempo}, defensive_posture:{...},
    geopolitical_trigger_prior: float}. Reads ONLY the derived values; adds
    nothing. A BLOCKED prior yields a config the existing validator will
    reject (its value is absent/None), which is the intended fail path."""
    priors = derivation.get("priors") or {}

    def _val(field):
        rec = priors.get(field) or {}
        return rec.get("value")

    return {
        "adversary": {
            "capability_prior": _val("capability_prior"),
            "tempo": _val("tempo"),
        },
        "defensive_posture": _val("defensive_posture"),
        "geopolitical_trigger_prior": _val("geopolitical_trigger_prior"),
    }


# ---- review-subject hash ----

def annexc_derivation_hash(derivation: dict, *, corpus_manifest_hash: str) -> str:
    """Canonical hash over ONLY the analytically meaningful review subject:
    schema/policy version, corpus hash, the priors, and the compiled config.
    Excludes unstable metadata (generated_at, latency, token counts, temp
    paths) so re-serialization or timing noise doesn't change the hash an
    approval is bound to."""
    subject = {
        "schema_version": derivation.get("schema_version", "1.0"),
        "policy_version": derivation.get("policy_version"),
        "corpus_manifest_hash": corpus_manifest_hash,
        "priors": derivation.get("priors", {}),
        "compiled_config": derivation.get("compiled_config", {}),
    }
    return canonical_json_sha256(subject)


# ---- approval gate ----

REQUIRED_APPROVAL_FIELDS = (
    "approval_id", "decision", "approved_by", "reviewer_role", "approved_at",
    "rationale", "run_id", "corpus_manifest_hash", "policy_version",
    "review_subject_hash",
)


class DerivationGateDecision:
    def __init__(self, *, allowed: bool, code: str, reason: str, detail: dict):
        self.allowed = allowed
        self.code = code
        self.reason = reason
        self.detail = detail

    def audit_record(self) -> dict:
        return {"gate": "annexc_derivation_approval", "allowed": self.allowed,
                "code": self.code, "reason": self.reason, "detail": self.detail}

    def require_allowed(self) -> None:
        if not self.allowed:
            raise DerivationApprovalBlocked(f"{self.code}\n{self.reason}")


def evaluate_derivation_approval(
    *, derivation: dict, derivation_validation: dict, config_validation: dict,
    approval: dict | None, run_id: str, corpus_manifest_hash: str,
    policy_version: str,
) -> DerivationGateDecision:
    """Annex C scoring may begin only when ALL ten conditions hold (see spec
    Decision 4). Deterministic; side-effect-free."""
    detail = {}

    # 3+4: every prior SUPPORTED or DEFAULTED; none BLOCKED/MISSING/INVALID.
    resolved = derivation_validation.get("priors", {})
    bad = {f: s for f, s in resolved.items() if s not in ("SUPPORTED", "DEFAULTED")}
    if not derivation_validation.get("is_valid") or bad:
        return DerivationGateDecision(
            allowed=False, code="DERIVATION_NOT_RESOLVED",
            reason=("Derivation has unresolved priors or validation errors "
                    f"(non-passing: {bad or 'see errors'}). Annex C is blocked."),
            detail={"priors": resolved})

    # 5: compiled config passes the EXISTING validator.
    if not config_validation.get("is_valid"):
        return DerivationGateDecision(
            allowed=False, code="CONFIG_INVALID",
            reason="Compiled BBN assessment config failed validate_bbn_assessment_config().",
            detail={"config_errors": config_validation.get("errors")})

    # 1+2 assumed done by caller (artifact readable, run-stamped, corpus match).
    # 6-10: approval present, APPROVED, and every bound identity matches.
    if not isinstance(approval, Mapping):
        return DerivationGateDecision(
            allowed=False, code="NO_APPROVAL",
            reason="No analyst approval record present; Annex C requires an approved derivation.",
            detail={})

    missing = [f for f in REQUIRED_APPROVAL_FIELDS if not approval.get(f)]
    if missing:
        return DerivationGateDecision(
            allowed=False, code="APPROVAL_INCOMPLETE",
            reason=f"Approval missing required field(s): {missing}.", detail={})

    decision = str(approval.get("decision")).upper()
    if decision == "REJECTED":
        return DerivationGateDecision(
            allowed=False, code="APPROVAL_REJECTED",
            reason="Analyst REJECTED the derivation; Annex C is blocked.", detail={})
    if decision != "APPROVED":
        return DerivationGateDecision(
            allowed=False, code="APPROVAL_NOT_APPROVED",
            reason=f"Approval decision is {approval.get('decision')!r}, not APPROVED.", detail={})

    if approval.get("run_id") != run_id:
        return DerivationGateDecision(
            allowed=False, code="APPROVAL_RUN_MISMATCH",
            reason="Approval run_id does not match the active run.", detail={})
    if approval.get("corpus_manifest_hash") != corpus_manifest_hash:
        return DerivationGateDecision(
            allowed=False, code="APPROVAL_CORPUS_MISMATCH",
            reason="Approval corpus_manifest_hash does not match the active corpus.", detail={})
    if approval.get("policy_version") != policy_version:
        return DerivationGateDecision(
            allowed=False, code="APPROVAL_POLICY_MISMATCH",
            reason="Approval policy_version does not match the derivation policy.", detail={})

    current_subject_hash = annexc_derivation_hash(
        derivation, corpus_manifest_hash=corpus_manifest_hash)
    if approval.get("review_subject_hash") != current_subject_hash:
        return DerivationGateDecision(
            allowed=False, code="APPROVAL_STALE",
            reason=("Approval review_subject_hash does not match the current derivation — "
                    "the derivation changed since it was approved."),
            detail={"expected": current_subject_hash,
                    "approval": approval.get("review_subject_hash")})

    return DerivationGateDecision(
        allowed=True, code="DERIVATION_APPROVED",
        reason="Derivation is fully resolved, config-valid, and approved for this run.",
        detail={"approval_id": approval.get("approval_id"),
                "review_subject_hash": current_subject_hash})


def require_approved_derivation(**kwargs) -> DerivationGateDecision:
    """Convenience: evaluate and raise unless allowed. Returns the decision on
    success so the caller can record it."""
    decision = evaluate_derivation_approval(**kwargs)
    decision.require_allowed()
    return decision


# ---- top-level orchestration ----

def derive_annexc_inputs(
    *, corpus_sources: Mapping, policy: dict,
    propose_priors: Callable[[Mapping], dict],
    assessment_config: Mapping | None = None,
) -> dict:
    """Orchestrate the LLM proposal + per-prior no-evidence policy into a
    derivation dict (not yet validated). propose_priors is injected (the LLM
    call) so this module holds no model/HTTP logic and stays unit-testable.

    propose_priors(corpus_sources) -> {field: record | None}. A None (or
    absent) proposal for a field triggers that field's no-evidence policy.
    """
    proposed = propose_priors(corpus_sources) or {}
    priors = {}
    for field in FOUR_PRIORS:
        record = proposed.get(field)
        if record is None:
            priors[field] = apply_no_evidence_policy(field, policy)
        else:
            priors[field] = record

    derivation = {
        "schema_version": "1.0",
        "policy_version": policy["policy_version"],
        "priors": priors,
    }
    derivation["compiled_config"] = compile_bbn_assessment_config(derivation)
    return derivation


# ---- corpus loading + prior proposer (stub) --------------------------------

def load_frozen_corpus_sources(out_dir: str) -> dict:
    """Load the frozen corpus as {source_file: {sha256, text}} for citation
    verification. Reads the run's frozen manifest + normalized scratch text.
    Kept tolerant: a missing manifest yields an empty mapping, which makes
    every CORPUS citation fail verification (fail closed) rather than crash."""
    sources = {}
    manifest_candidates = [
        os.path.join(out_dir, "corpus_manifest.json"),
        os.path.join("corpus-index", "frozen_manifest.json"),
    ]
    manifest = None
    for mc in manifest_candidates:
        if os.path.exists(mc):
            try:
                manifest = json.load(open(mc))
                break
            except (json.JSONDecodeError, OSError):
                continue
    if not manifest:
        return sources

    entries = manifest.get("files") or manifest.get("sources") or []
    for entry in entries:
        name = entry.get("source_file") or entry.get("file") or entry.get("name")
        if not name:
            continue
        text = entry.get("normalized_text") or entry.get("text") or ""
        if not text:
            scratch = os.path.join(out_dir, "scratch", f"{name}.txt")
            if os.path.exists(scratch):
                try:
                    text = open(scratch).read()
                except OSError:
                    text = ""
        sources[name] = {
            "sha256": entry.get("sha256") or entry.get("source_sha256"),
            "text": text,
        }
    return sources


def make_prior_proposer(frozen_sources: Mapping, llm,
                        live: bool = True,
                        diagnostics_out_dir: str | None = None) -> Callable[[Mapping], dict]:
    """Return a propose_priors(corpus_sources) callable.

    live=True (default): delegates to the two-phase live proposer
    (annexc_proposer.propose_priors_from_corpus) -- per-chunk extraction,
    deterministic quote verification, then per-prior synthesis over verified
    evidence only. A prior with no verified corpus support is omitted, so the
    caller's per-prior no-evidence policy applies.

    live=False: proposes NOTHING (every prior -> no-evidence policy). Used to
    verify the pipeline wiring deterministically without invoking a model.

    diagnostics_out_dir: when supplied (live=True only), the full
    instrumented-run artifact set is written run-local under
    <diagnostics_out_dir>/annexc_proposer/ -- see annexc_diagnostics.py. Pass
    the active run's out_dir so the first live run is fully classifiable.

    The injection point and contract are identical either way, so the caller
    (derive_annexc_inputs) is unchanged.
    """
    if not live or llm is None:
        def _propose_stub(corpus_sources: Mapping) -> dict:
            return {}
        return _propose_stub

    def _propose_live(corpus_sources: Mapping) -> dict:
        # Import here so the deterministic core has no hard dependency on the
        # model-facing module (keeps unit tests of the core model-free).
        from src.annexc_proposer import propose_priors_from_corpus
        return propose_priors_from_corpus(frozen_sources=corpus_sources, llm=llm,
                                          diagnostics_out_dir=diagnostics_out_dir)
    return _propose_live


# ---- two-phase pipeline gate --------------------------------------------

def run_annexc_derivation_gate(*, state, run_id, out_dir, corpus_manifest_hash,
                               run_context, set_stage_status, save_assessment_state,
                               StageStatus, policy_path="config/annexc_derivation_policy.json"):
    """Two-phase Annex C derivation + approval gate, called before the
    analysis crew.

    Phase 1 (no derivation yet): derive priors from the frozen corpus, compile
    + validate the config, persist annexc_derivation.json and
    annexc_assessment_config.json, then STOP (raise) for analyst review.

    Phase 2 (derivation exists): enforce the hash-bound approval gate; only an
    APPROVED derivation matching this run/corpus/policy/subject-hash lets the
    caller proceed. Records the gate decision in state.gate_decisions.

    All I/O collaborators are injected so this stays importable/testable and
    crew.py stays thin.
    """
    derivation_path = run_context.artifact_path("annexc_derivation.json")
    config_path = run_context.artifact_path("annexc_assessment_config.json")
    approval_path = run_context.artifact_path("annexc_derivation_approval.json")

    policy = load_derivation_policy(policy_path)
    frozen_sources = load_frozen_corpus_sources(out_dir)

    if not os.path.exists(derivation_path):
        # PHASE 1: derive, persist, STOP for analyst review.
        try:
            from config.llm import reason_llm
        except Exception:
            reason_llm = None
        derivation = derive_annexc_inputs(
            corpus_sources=frozen_sources, policy=policy,
            propose_priors=make_prior_proposer(frozen_sources, reason_llm,
                                               diagnostics_out_dir=out_dir),
        )
        cfg = compile_bbn_assessment_config(derivation)
        cv = validate_bbn_assessment_config(cfg)
        derivation["config_validation"] = cv
        derivation["review_subject_hash"] = annexc_derivation_hash(
            derivation, corpus_manifest_hash=corpus_manifest_hash)
        run_context.write_stamped_json(derivation_path, derivation)
        run_context.write_stamped_json(config_path, cfg)
        state.current_stage = "annexc_derivation"
        save_assessment_state(state, run_id)
        raise DerivationApprovalBlocked(
            "ANNEXC_DERIVATION_AWAITING_APPROVAL\n"
            f"Annex C priors were derived and written to {derivation_path}. "
            "An analyst must review the derivation and evidence, then write "
            f"{approval_path} (decision APPROVED/REJECTED) before Annex C can score. "
            f"Run audit trail: {out_dir}/assessment_state.json")

    # PHASE 2: enforce the approval gate.
    derivation = run_context.read_stamped_json(derivation_path)
    dv = validate_derivation(derivation, frozen_sources=frozen_sources, policy=policy)
    cfg = run_context.read_stamped_json(config_path)
    cv = validate_bbn_assessment_config(cfg)
    approval = None
    if os.path.exists(approval_path):
        try:
            approval = run_context.read_stamped_json(approval_path)
        except Exception:
            approval = None
    decision = evaluate_derivation_approval(
        derivation=derivation, derivation_validation=dv, config_validation=cv,
        approval=approval, run_id=run_id, corpus_manifest_hash=corpus_manifest_hash,
        policy_version=policy["policy_version"])
    if isinstance(getattr(state, "gate_decisions", None), list):
        state.gate_decisions.append(decision.audit_record())
    if not decision.allowed:
        state.current_stage = "annexc_derivation"
        save_assessment_state(state, run_id)
        raise DerivationApprovalBlocked(
            f"{decision.code}\n{decision.reason}\n"
            f"Run audit trail: {out_dir}/assessment_state.json")
    return decision
"""
Deterministic validation for the structured Stage 3 test plan
(stage3_test_plan.json) against the real Stage 2 graph, the real KCAG
report, and the real technique index -- plus a cross-artifact consistency
check against the human-reviewed prose (stage3.md).

This is intentionally a HARD GATE, run by crew.py after analysis_crew
completes, once every input artifact (Stage 2, Annex B, Stage 3) is
final. An LLM-generated plan that references a nonexistent graph node,
edge, or technique ID must never reach Stage 4 merely because its prose
reads convincingly -- write_stage3_test_plan() (the writer tool) only
performs shallow, writer-time checks (schema shape, size, placeholders);
this module owns every referential and cross-artifact check.

The assessment-wide Category 2/3 safety review is validated here AND
separately by tools.py's prose-based check_stage3_safety_gate(). That
duplication is intentional, not redundant: this module validates the
STRUCTURED artifact; check_stage3_safety_gate() remains an independent
defense-in-depth check over the human-readable prose, and continues to
run and gate Stage 4 on its own, after this module's checks pass.
"""
import re
from typing import Any

from pydantic import ValidationError

from src.stage3_schema import Stage3TestPlan
from src.tools import (
    _strip_markdown_emphasis,
    STAGE3_CATEGORY_LINE,
    STAGE3_NO_GATE_REQUIRED,
    STAGE3_INVALID_VALUES,
)

STAGE3_TEST_HEADING = re.compile(r"^#{2,6}\s+(RT-\d{3})\b.*$", re.IGNORECASE | re.MULTILINE)

# Framework technique IDs as they appear in prose: ATT&CK (T1234[.001]),
# ATLAS (AML.T0099[.000]), CAPEC (CAPEC-628), EMB3D (EMB.T-xxxx),
# SPARTA (SV-xx-x). Deterministic extraction — no NL equivalence judgment.
STAGE3_TECHNIQUE_IN_PROSE = re.compile(
    r"\b(AML\.T\d{4}(?:\.\d{3})?|CAPEC-\d+|EMB\.T-?\d+|SV-\d+-\d+|T\d{4}(?:\.\d{3})?)\b"
)


def stage3_candidate_hash(plan: dict) -> str:
    """sha256:<hex> of the Stage 3 plan's canonical (sorted-key, compact)
    JSON. Hashes the PLAN DATA, not the stamped file's bytes, so it is
    stable across re-stamps of identical content (the stamped file's _meta
    carries a generated_at timestamp that changes on rewrite). This single
    function is the source of truth for both the hash recorded in the
    validation report and the hash compared during resume-state checks, so
    the two can never diverge."""
    import hashlib
    import json
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def build_stage3_validation_report(
    *, plan: dict, plan_validation: dict, consistency: dict,
    artifact_path: str,
) -> dict:
    """Assemble the Stage 3 validation report, binding it to the exact
    candidate it validated via a canonical-JSON hash. A later resume can
    then confirm report_candidate_hash == current_candidate_hash and refuse
    to treat a stale passing report as validating a changed candidate."""
    return {
        "is_valid": plan_validation["is_valid"] and consistency["is_consistent"],
        "plan_validation": plan_validation,
        "artifact_consistency": consistency,
        "validated_artifact": {
            "path": artifact_path,
            "sha256": stage3_candidate_hash(plan),
        },
    }
_TEST_ID_PATTERN = re.compile(r"^RT-\d{3}$")
_MIN_TEXT_LENGTH = 8

_REQUIRED_LIST_FIELDS = (
    "stage2_vector_ids", "kcag_path", "preconditions", "expected_effects",
    "success_criteria", "abort_criteria", "rollback_or_recovery_steps",
    "telemetry_requirements", "assumptions",
)
_REQUIRED_STRING_FIELDS = ("title", "objective", "mechanism_summary")


def _err(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message}


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in STAGE3_INVALID_VALUES


def validate_directed_path(path: list, *, node_ids: set, directed_edges: set, goal_ids: set) -> list:
    """Validate one KCAG path against the real Stage 2 graph. Returns a
    list of (code, message) tuples -- UNPREFIXED, since callers attach
    the concept-specific path prefix."""
    errors = []
    if len(path) < 2:
        errors.append(("PATH_TOO_SHORT", "kcag_path must contain at least two nodes."))
        return errors
    if path[0] != "ADV_START":
        errors.append(("PATH_MUST_START_AT_ADV_START", f"kcag_path must start at ADV_START, got '{path[0]}'."))
    if path[-1] not in goal_ids:
        errors.append(("PATH_MUST_END_AT_GOAL", f"kcag_path must end at a goal node, got '{path[-1]}'."))
    for node in path:
        if node not in node_ids:
            errors.append(("UNKNOWN_PATH_NODE", f"Node '{node}' does not exist in stage2_vectors.json."))
    for i in range(len(path) - 1):
        if (path[i], path[i + 1]) not in directed_edges:
            errors.append(("MISSING_DIRECTED_EDGE",
                          f"No directed edge '{path[i]}' -> '{path[i + 1]}' exists in stage2_vectors.json."))
    return errors


def validate_stage3_test_plan(*, plan: dict, stage2_vectors: dict, kcag_report: dict,
                              technique_index: dict) -> dict:
    """Validate the structured Stage 3 test plan against the real,
    already-verified Stage 2 graph, KCAG report, and technique index.
    Does not mutate any of its inputs.
    """
    errors: list = []
    warnings: list = []

    try:
        parsed = Stage3TestPlan.model_validate(plan)
    except ValidationError as exc:
        return {
            "is_valid": False, "status": "FAIL", "checked_test_concepts": 0,
            "errors": [_err("$", "SCHEMA_INVALID", str(exc))],
            "warnings": [],
            "summary": "Stage 3 test plan failed schema re-validation.",
        }

    nodes = {n["id"]: n for n in stage2_vectors.get("nodes", [])}
    node_ids = set(nodes.keys())
    goal_ids = {nid for nid, n in nodes.items() if n.get("node_type") == "goal"}
    edges = stage2_vectors.get("edges", [])
    vector_edges = {e["vec"]: e for e in edges if isinstance(e, dict) and "vec" in e}
    directed_edges = {(e["source"], e["target"]) for e in edges if isinstance(e, dict)}
    priority_path = (kcag_report.get("priority_path") or {}).get("path", [])

    checked = 0

    for concept in parsed.test_concepts:
        checked += 1
        p = f"test_concepts[{concept.test_id}]"

        # ---- Categories ----
        if not concept.categories:
            errors.append(_err(f"{p}.categories", "EMPTY_CATEGORIES", "At least one category is required."))
        if len(concept.categories) != len(set(concept.categories)):
            errors.append(_err(f"{p}.categories", "DUPLICATE_CATEGORY", "Category values must not repeat."))
        has_2_3 = bool({2, 3} & set(concept.categories))

        # ---- Stage 2 vector references ----
        if not concept.stage2_vector_ids:
            errors.append(_err(f"{p}.stage2_vector_ids", "EMPTY_STAGE2_VECTORS",
                               "At least one Stage 2 vector reference is required."))
        if len(concept.stage2_vector_ids) != len(set(concept.stage2_vector_ids)):
            errors.append(_err(f"{p}.stage2_vector_ids", "DUPLICATE_STAGE2_VECTOR",
                               "Stage 2 vector references must not repeat within one concept."))
        for i, vid in enumerate(concept.stage2_vector_ids):
            if vid not in vector_edges:
                errors.append(_err(f"{p}.stage2_vector_ids[{i}]", "UNKNOWN_STAGE2_VECTOR",
                                   f"Vector '{vid}' does not exist in stage2_vectors.json."))

        # ---- KCAG path ----
        for code, message in validate_directed_path(concept.kcag_path, node_ids=node_ids,
                                                     directed_edges=directed_edges, goal_ids=goal_ids):
            errors.append(_err(f"{p}.kcag_path", code, message))

        if concept.path_relationship == "PRIORITY_PATH" and concept.kcag_path != priority_path:
            errors.append(_err(f"{p}.path_relationship", "PRIORITY_PATH_MISMATCH",
                               "path_relationship is PRIORITY_PATH but kcag_path does not match "
                               "kcag_report.json's priority_path."))

        # ---- Target nodes ----
        for i, tid in enumerate(concept.target_node_ids):
            if tid not in node_ids:
                errors.append(_err(f"{p}.target_node_ids[{i}]", "UNKNOWN_TARGET_NODE",
                                   f"Node '{tid}' does not exist in stage2_vectors.json."))
            elif tid not in concept.kcag_path:
                errors.append(_err(f"{p}.target_node_ids[{i}]", "TARGET_NODE_NOT_ON_PATH",
                                   f"Node '{tid}' is not on the declared kcag_path."))

        # ---- Execution technique references ----
        path_edge_pairs = set(zip(concept.kcag_path, concept.kcag_path[1:]))
        for i, ref in enumerate(concept.execution_techniques):
            tp = f"{p}.execution_techniques[{i}]"
            if ref.vector_id not in concept.stage2_vector_ids:
                errors.append(_err(f"{tp}.vector_id", "TECHNIQUE_VECTOR_NOT_IN_CONCEPT",
                                   f"'{ref.vector_id}' is not one of this concept's stage2_vector_ids."))
            edge = vector_edges.get(ref.vector_id)
            if edge is not None and (edge.get("source"), edge.get("target")) not in path_edge_pairs:
                errors.append(_err(f"{tp}.vector_id", "VECTOR_EDGE_NOT_ON_PATH",
                                   f"The edge for vector '{ref.vector_id}' is not on the declared kcag_path."))

            if ref.technique_id == "[UNMAPPED]":
                if not ref.rationale or len(ref.rationale.strip()) < _MIN_TEXT_LENGTH:
                    errors.append(_err(f"{tp}.rationale", "UNMAPPED_WITHOUT_RATIONALE",
                                       "[UNMAPPED] requires a rationale explaining why no framework "
                                       "entry was found."))
                else:
                    warnings.append({**_err(f"{tp}.technique_id", "UNMAPPED_TECHNIQUE",
                                            "Concept requires explicit human review."),
                                     "severity": "WARNING"})
            elif ref.technique_id not in technique_index:
                errors.append(_err(f"{tp}.technique_id", "UNKNOWN_TECHNIQUE_ID",
                                   f"'{ref.technique_id}' was not found in technique_index.json and is "
                                   f"not the exact '[UNMAPPED]' marker."))

        # ---- Placeholder / quality checks (defense in depth -- the writer
        # already checks this, but a resumed run may read an artifact this
        # module never saw written) ----
        for field in _REQUIRED_STRING_FIELDS:
            value = getattr(concept, field)
            if _is_placeholder(value):
                errors.append(_err(f"{p}.{field}", "PLACEHOLDER_VALUE", f"'{value}' is a placeholder value."))
        for field in _REQUIRED_LIST_FIELDS:
            values = getattr(concept, field)
            if not values:
                errors.append(_err(f"{p}.{field}", "EMPTY_REQUIRED_LIST", "At least one entry is required."))
            for item in values:
                if _is_placeholder(item):
                    errors.append(_err(f"{p}.{field}", "PLACEHOLDER_VALUE", f"'{item}' is a placeholder value."))
            normalized = [v.strip().lower() for v in values]
            if len(normalized) != len(set(normalized)):
                errors.append(_err(f"{p}.{field}", "DUPLICATE_LIST_ITEM",
                                   "Duplicate entries (after normalization) are not allowed."))

        success_norm = {s.strip().lower() for s in concept.success_criteria}
        abort_norm = {s.strip().lower() for s in concept.abort_criteria}
        overlap = success_norm & abort_norm
        if overlap:
            errors.append(_err(f"{p}.success_criteria/abort_criteria", "IDENTICAL_SUCCESS_ABORT_CRITERIA",
                               f"success_criteria and abort_criteria share identical entries: {sorted(overlap)}."))

        # ---- Category 2/3 safety controls ----
        if has_2_3:
            if concept.safety_controls is None:
                errors.append(_err(f"{p}.safety_controls", "MISSING_SAFETY_CONTROLS",
                                   "Category 2 or 3 requires safety_controls."))
            else:
                sc = concept.safety_controls
                if not sc.affected_assets:
                    errors.append(_err(f"{p}.safety_controls.affected_assets", "EMPTY_AFFECTED_ASSETS",
                                       "At least one affected asset is required."))
                if not sc.required_approving_roles:
                    errors.append(_err(f"{p}.safety_controls.required_approving_roles", "EMPTY_APPROVING_ROLES",
                                       "At least one approving role is required."))
                if _is_placeholder(sc.safety_authority):
                    errors.append(_err(f"{p}.safety_controls.safety_authority", "PLACEHOLDER_VALUE",
                                       f"'{sc.safety_authority}' is a placeholder value."))
                if _is_placeholder(sc.abort_authority):
                    errors.append(_err(f"{p}.safety_controls.abort_authority", "PLACEHOLDER_VALUE",
                                       f"'{sc.abort_authority}' is a placeholder value."))
                if _is_placeholder(sc.rollback_or_recovery_procedure):
                    errors.append(_err(f"{p}.safety_controls.rollback_or_recovery_procedure", "PLACEHOLDER_VALUE",
                                       f"'{sc.rollback_or_recovery_procedure}' is a placeholder value."))
        else:
            if concept.safety_controls is not None:
                errors.append(_err(f"{p}.safety_controls", "UNEXPECTED_SAFETY_CONTROLS",
                                   "safety_controls must be null for concepts with no Category 2/3."))

    # ---- Assessment-wide safety review consistency ----
    category_2_3_ids = {c.test_id for c in parsed.test_concepts if {2, 3} & set(c.categories)}
    review = parsed.assessment_safety_review
    rp = "assessment_safety_review"

    if category_2_3_ids:
        if not review.category_2_3_present:
            errors.append(_err(f"{rp}.category_2_3_present", "SAFETY_REVIEW_FLAG_MISMATCH",
                               "category_2_3_present must be true when any concept carries Category 2/3."))
        covered = set(review.covered_test_ids)
        missing = category_2_3_ids - covered
        extra = covered - category_2_3_ids
        if missing:
            errors.append(_err(f"{rp}.covered_test_ids", "MISSING_COVERED_TEST_ID",
                               f"covered_test_ids is missing: {sorted(missing)}."))
        if extra:
            errors.append(_err(f"{rp}.covered_test_ids", "EXTRA_COVERED_TEST_ID",
                               f"covered_test_ids includes test IDs with no Category 2/3: {sorted(extra)}."))
        if not review.required_approving_roles:
            errors.append(_err(f"{rp}.required_approving_roles", "EMPTY_APPROVING_ROLES",
                               "At least one approving role is required."))
        if not review.safety_authority or _is_placeholder(review.safety_authority):
            errors.append(_err(f"{rp}.safety_authority", "PLACEHOLDER_OR_MISSING", "safety_authority is required."))
        if not review.abort_authority or _is_placeholder(review.abort_authority):
            errors.append(_err(f"{rp}.abort_authority", "PLACEHOLDER_OR_MISSING", "abort_authority is required."))
        if not review.abort_criteria:
            errors.append(_err(f"{rp}.abort_criteria", "EMPTY_ABORT_CRITERIA", "At least one entry is required."))
        if not review.maximum_termination_seconds or review.maximum_termination_seconds <= 0:
            errors.append(_err(f"{rp}.maximum_termination_seconds", "INVALID_TERMINATION_TIME",
                               "maximum_termination_seconds must be a positive integer."))
        if not review.rollback_or_recovery_procedure or _is_placeholder(review.rollback_or_recovery_procedure):
            errors.append(_err(f"{rp}.rollback_or_recovery_procedure", "PLACEHOLDER_OR_MISSING",
                               "rollback_or_recovery_procedure is required."))
        if not review.release_condition:
            errors.append(_err(f"{rp}.release_condition", "MISSING_RELEASE_CONDITION",
                               "release_condition is required."))
        else:
            lowered = review.release_condition.lower()
            if not any(phrase in lowered for phrase in ("may not begin", "must not begin", "shall not begin")):
                errors.append(_err(f"{rp}.release_condition", "WEAK_RELEASE_CONDITION",
                                   "release_condition must contain blocking language "
                                   "('may not begin' / 'must not begin' / 'shall not begin')."))
        if review.not_required_statement:
            errors.append(_err(f"{rp}.not_required_statement", "CONTRADICTORY_NOT_REQUIRED_STATEMENT",
                               "not_required_statement must be null when Category 2/3 concepts exist."))
    else:
        if review.category_2_3_present:
            errors.append(_err(f"{rp}.category_2_3_present", "SAFETY_REVIEW_FLAG_MISMATCH",
                               "category_2_3_present must be false when no concept carries Category 2/3."))
        if review.covered_test_ids:
            errors.append(_err(f"{rp}.covered_test_ids", "UNEXPECTED_COVERED_TEST_ID",
                               "covered_test_ids must be empty when no concept carries Category 2/3."))
        if (review.not_required_statement or "").strip() != STAGE3_NO_GATE_REQUIRED:
            errors.append(_err(f"{rp}.not_required_statement", "MISSING_NOT_REQUIRED_STATEMENT",
                               f"not_required_statement must be exactly '{STAGE3_NO_GATE_REQUIRED}'."))

    is_valid = not errors
    return {
        "is_valid": is_valid,
        "status": "PASS" if is_valid else "FAIL",
        "checked_test_concepts": checked,
        "errors": errors,
        "warnings": warnings,
        "summary": (f"Stage 3 test-plan validation {'PASS' if is_valid else 'FAIL'}: "
                   f"{checked} concept(s) checked, {len(errors)} error(s), {len(warnings)} warning(s)."),
    }


def check_stage3_artifact_consistency(*, stage3_text: str, test_plan: dict) -> dict:
    """Deterministic anchors only -- no natural-language equivalence
    judgment. Confirms the prose and structured artifacts describe the
    SAME set of test concepts and agree on category numbers and the
    overall Category 2/3 conclusion; does not evaluate whether either
    artifact's content is itself well-written."""
    errors: list = []
    stripped = _strip_markdown_emphasis(stage3_text or "")

    prose_ids = set(STAGE3_TEST_HEADING.findall(stripped))
    json_ids = {c["test_id"] for c in test_plan.get("test_concepts", [])}

    missing_from_prose = json_ids - prose_ids
    missing_from_json = prose_ids - json_ids
    if missing_from_prose:
        errors.append(_err("test_concepts", "TEST_ID_MISSING_FROM_PROSE",
                           f"Structured test ID(s) have no matching '### {{{{id}}}}' heading in stage3.md: "
                           f"{sorted(missing_from_prose)}."))
    if missing_from_json:
        errors.append(_err("stage3.md", "TEST_ID_MISSING_FROM_JSON",
                           f"Prose heading(s) have no matching structured test concept: "
                           f"{sorted(missing_from_json)}."))

    # Per-test-concept category agreement: extract the prose section for
    # each shared test ID and compare its Category line(s) to the JSON.
    headings = list(STAGE3_TEST_HEADING.finditer(stripped))
    for match_index, m in enumerate(headings):
        test_id = m.group(1)
        if test_id not in json_ids:
            continue
        section_start = m.end()
        section_end = headings[match_index + 1].start() if match_index + 1 < len(headings) else len(stripped)
        section_text = stripped[section_start:section_end]
        prose_categories = set()
        for value in STAGE3_CATEGORY_LINE.findall(section_text):
            prose_categories.update(int(n) for n in re.findall(r"\b[1-4]\b", value))

        json_concept = next((c for c in test_plan["test_concepts"] if c["test_id"] == test_id), None)
        json_categories = set(json_concept["categories"]) if json_concept else set()

        if prose_categories and prose_categories != json_categories:
            errors.append(_err(f"test_concepts[{test_id}].categories", "CATEGORY_MISMATCH",
                               f"Prose declares categories {sorted(prose_categories)} but JSON declares "
                               f"{sorted(json_categories)} for {test_id}."))

        # Per-concept technique-ID agreement (prose vs JSON). This catches the
        # RT-003 failure: prose said AML.T0099 while JSON said CAPEC-628, yet
        # consistency previously passed. Deterministic exact comparison — no
        # LLM equivalence judgment. Every technique the JSON concept binds
        # must actually appear in that concept's prose section, and every
        # framework technique ID mentioned in the prose section must be one
        # the JSON concept binds. A disagreement is a hard failure.
        if json_concept is not None:
            json_techs = set()
            for et in (json_concept.get("execution_techniques") or []):
                tid = et.get("technique_id") if isinstance(et, dict) else None
                if tid and tid != "[UNMAPPED]":
                    json_techs.add(tid)
            for t in (json_concept.get("technique_ids") or []):
                if t:
                    json_techs.add(t)

            prose_techs = set(STAGE3_TECHNIQUE_IN_PROSE.findall(section_text))

            # Only compare when the prose section actually names techniques;
            # an absent prose technique line is a separate (documentation)
            # concern, not a contradiction.
            if prose_techs:
                json_not_in_prose = json_techs - prose_techs
                prose_not_in_json = prose_techs - json_techs
                if json_not_in_prose or prose_not_in_json:
                    errors.append(_err(
                        f"test_concepts[{test_id}].execution_techniques",
                        "PROSE_JSON_TECHNIQUE_MISMATCH",
                        f"{test_id} technique bindings disagree between artifacts — "
                        f"prose: {sorted(prose_techs)}, json: {sorted(json_techs)}."))

    json_has_2_3 = any({2, 3} & set(c.get("categories", [])) for c in test_plan.get("test_concepts", []))
    if json_has_2_3 and STAGE3_NO_GATE_REQUIRED.lower() in stripped.lower():
        errors.append(_err("stage3.md", "PROSE_NO_GATE_CONTRADICTS_JSON",
                           "JSON declares Category 2/3 concepts, but stage3.md contains the "
                           "'NO CATEGORY 2/3 PAYLOADS' statement."))

    is_consistent = not errors
    return {
        "is_consistent": is_consistent,
        "status": "PASS" if is_consistent else "FAIL",
        "errors": errors,
        "summary": (f"Stage 3 cross-artifact consistency {'PASS' if is_consistent else 'FAIL'}: "
                   f"{len(errors)} error(s)."),
    }
"""
Direct Stage 3 structured-output compiler.

Same serialization failure class as Stage 1: write_stage3_test_plan
receives a large nested JSON string through CrewAI's agent executor and
Ollama's native-tool parser truncates/mangles it. Stage 3 instead
requests schema-constrained structured output through Ollama's native
/api/chat endpoint (see src/structured_output.py), validates it against
the Stage3TestPlan Pydantic model, and passes the validated JSON string
to the deterministic writer tool before it becomes authoritative.

NOTE the interface difference from Stage 1: write_stage3_test_plan takes
a single test_plan_json STRING parameter (and validates it internally),
not **kwargs. So this compiler generates against the Stage3TestPlan
schema directly, validates, and hands the writer the JSON string.

This module owns only the Stage-3-specific concerns: the prompt, the
correction-feedback retry loop, the writer invocation, and artifact
read-back. The generic HTTP/normalize mechanics live in
src/structured_output.py.
"""
import json
import os
import re

from src import run_context
from src.structured_output import generate_structured_json


# Reuse the EXACT doctrinal label regexes and invalid-value set the prose
# safety gate already enforces (tools.py), so the deterministic overlay and
# the prose gate never diverge on what "a valid safety review" means.
from src.tools import STAGE3_REQUIRED_SAFETY_FIELDS, STAGE3_INVALID_VALUES

# Two additional header labels in the ## PRE-STAGE-4 SAFETY REVIEW block
# that the concept-level field set doesn't cover.
_SAFETY_CAT_PRESENT_RE = re.compile(
    r"^\s*(?:[-+]\s*)?category 2/3 concepts present\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE)
_SAFETY_COVERED_IDS_RE = re.compile(
    r"^\s*(?:[-+]\s*)?covered test concepts\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE)
_SAFETY_SECTION_HEADING_RE = re.compile(
    r"^\s*##\s+PRE-STAGE-4 SAFETY REVIEW\s*$", re.IGNORECASE)



_STAGE3_PROSE_TEST_HEADING = re.compile(
    r"^#{2,6}\s+(RT-\d{3})\b.*$",
    re.IGNORECASE | re.MULTILINE,
)

_STAGE3_PROSE_CATEGORY_LINE = re.compile(
    r"^\s*(?:\*\*)?"
    r"(?:Category|Categories)"
    r"(?:\*\*)?\s*:\s*"
    r"(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_prose_concept_identities(
    stage3_prose: str,
) -> list[dict]:
    """
    Extract authoritative test IDs and categories from approved Stage 3 prose.
    """

    if not isinstance(stage3_prose, str):
        raise ValueError(
            "Approved Stage 3 prose must be a string."
        )

    headings = list(
        _STAGE3_PROSE_TEST_HEADING.finditer(
            stage3_prose
        )
    )

    if not headings:
        raise ValueError(
            "Approved Stage 3 prose contains no "
            "RT-NNN test headings."
        )

    identities = []
    seen_ids = set()

    for index, match in enumerate(headings):
        test_id = match.group(1).upper()

        if test_id in seen_ids:
            raise ValueError(
                "Approved Stage 3 prose contains "
                f"duplicate test ID {test_id}."
            )

        seen_ids.add(test_id)

        section_start = match.end()
        section_end = (
            headings[index + 1].start()
            if index + 1 < len(headings)
            else len(stage3_prose)
        )
        section_text = stage3_prose[
            section_start:section_end
        ]

        categories = set()

        for category_text in (
            _STAGE3_PROSE_CATEGORY_LINE.findall(
                section_text
            )
        ):
            categories.update(
                int(number)
                for number in re.findall(
                    r"\b[1-4]\b",
                    category_text,
                )
            )

        if not categories:
            raise ValueError(
                f"Approved Stage 3 prose test "
                f"{test_id} has no parseable "
                "Category line."
            )

        identities.append(
            {
                "test_id": test_id,
                "categories": sorted(categories),
            }
        )

    return identities


def _apply_prose_identity_overlay(
    parsed: dict,
    stage3_prose: str,
) -> None:
    """
    Copy test IDs and categories deterministically from approved prose.
    """

    if not isinstance(parsed, dict):
        raise ValueError(
            "Stage 3 candidate must be an object."
        )

    concepts = parsed.get("test_concepts")

    if not isinstance(concepts, list):
        raise ValueError(
            "Stage 3 candidate test_concepts "
            "must be an array."
        )

    # Some compiler callers and unit tests provide only a minimal prose
    # context without authoritative RT-NNN concept headings. In that case,
    # there is no prose identity contract to overlay.
    #
    # Real Stage 3 artifacts contain RT-NNN headings, so those artifacts
    # continue through strict ID/category extraction and validation.
    if not _STAGE3_PROSE_TEST_HEADING.search(
        stage3_prose or ""
    ):
        return

    identities = _extract_prose_concept_identities(
        stage3_prose
    )

    if len(concepts) != len(identities):
        raise ValueError(
            "Stage 3 candidate concept count does "
            "not match approved prose: "
            f"candidate={len(concepts)}, "
            f"prose={len(identities)}."
        )

    for index, identity in enumerate(identities):
        concept = concepts[index]

        if not isinstance(concept, dict):
            raise ValueError(
                f"Stage 3 candidate concept {index} "
                "must be an object."
            )

        concept["test_id"] = identity["test_id"]
        concept["categories"] = identity["categories"]


def _duration_to_seconds(value: str) -> int:
    """Convert a duration string ('15 minutes', '900 seconds', '2 hours',
    '900') to an integer number of seconds. Raises ValueError if it can't
    be parsed — never guesses."""
    v = value.strip().lower()
    m = re.fullmatch(r"(\d+)\s*(second|seconds|sec|s|minute|minutes|min|m|hour|hours|hr|h)?", v)
    if not m:
        raise ValueError(f"Cannot parse duration to seconds: {value!r}")
    n = int(m.group(1))
    unit = m.group(2) or "seconds"
    if unit in ("second", "seconds", "sec", "s"):
        return n
    if unit in ("minute", "minutes", "min", "m"):
        return n * 60
    if unit in ("hour", "hours", "hr", "h"):
        return n * 3600
    raise ValueError(f"Unrecognized duration unit in {value!r}")


def _split_list(value: str) -> list:
    """Split a comma-separated label value into a clean list of items."""
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_pre_stage4_safety_review(stage3_prose: str) -> tuple:
    """Deterministically extract the ## PRE-STAGE-4 SAFETY REVIEW block from
    the approved Stage 3 prose and return (assessment_review, concept_controls):

      assessment_review   -> dict for the top-level assessment_safety_review
      concept_controls    -> dict of safety_controls fields to overlay onto
                             each covered Category 2/3 concept

    These are safety-GOVERNANCE values (approving roles, safety/abort
    authority, abort criteria, release condition). They are parsed from the
    analyst-approved prose, NOT generated by the model — letting the LLM copy
    them is exactly what dropped them before. This parser NEVER invents a
    value: if Category 2/3 concepts are present and any required label is
    missing or holds a placeholder value, it raises ValueError (fail closed).

    Reuses the same label regexes as the prose safety gate (tools.py), so the
    two checks cannot diverge on the doctrinal requirement.

    Returns (None, None) when the block reports no Category 2/3 concepts —
    the caller then leaves the model-generated not_required_statement path
    intact rather than overlaying governance fields.
    """
    lines = stage3_prose.splitlines()

    # Locate the section heading.
    start = None
    for i, line in enumerate(lines):
        if _SAFETY_SECTION_HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        raise ValueError(
            "No '## PRE-STAGE-4 SAFETY REVIEW' section found in Stage 3 prose."
        )

    # Read Label: value lines until the next heading.
    section = []
    for line in lines[start:]:
        if line.lstrip().startswith("## "):
            break
        section.append(line)
    section_text = "\n".join(section)

    def _match_field(field_key, regex_pattern):
        pat = re.compile(regex_pattern, re.IGNORECASE | re.MULTILINE)
        m = pat.search(section_text)
        return m.group(1).strip() if m else None

    # Is Category 2/3 present?
    cat_present_raw = None
    m = _SAFETY_CAT_PRESENT_RE.search(section_text)
    if m:
        cat_present_raw = m.group(1).strip()
    category_2_3_present = bool(cat_present_raw) and cat_present_raw.strip().lower() in (
        "yes", "true", "y")

    if not category_2_3_present:
        # No Cat 2/3 — nothing to overlay; caller keeps the not-required path.
        return None, None

    # Covered test IDs.
    covered_m = _SAFETY_COVERED_IDS_RE.search(section_text)
    if not covered_m:
        raise ValueError("Category 2/3 present but 'Covered test concepts' label missing.")
    covered_ids = _split_list(covered_m.group(1))
    if not covered_ids:
        raise ValueError("Category 2/3 present but no covered test concept IDs listed.")

    # Extract every doctrinal field using the SHARED regexes.
    raw = {}
    for key, pattern in STAGE3_REQUIRED_SAFETY_FIELDS.items():
        val = _match_field(key, pattern)
        if val is None or val.strip().lower() in STAGE3_INVALID_VALUES:
            raise ValueError(
                f"Category 2/3 present but required safety field '{key}' is "
                f"missing or a placeholder in the PRE-STAGE-4 SAFETY REVIEW block."
            )
        raw[key] = val.strip()

    # Release condition is a separate required top-level field.
    rc_val = _match_field("release_condition",
                          STAGE3_REQUIRED_SAFETY_FIELDS["release_condition"])
    if rc_val is None or rc_val.strip().lower() in STAGE3_INVALID_VALUES:
        raise ValueError(
            "Category 2/3 present but 'Release condition' is missing or a placeholder."
        )

    # Convert the duration deterministically.
    try:
        termination_seconds = _duration_to_seconds(raw["termination_time"])
    except ValueError as exc:
        raise ValueError(f"Could not convert termination time to seconds: {exc}")

    # Top-level assessment_safety_review. not_required_statement MUST be null
    # when Category 2/3 concepts exist (the deep validator requires this).
    assessment_review = {
        "category_2_3_present": True,
        "covered_test_ids": covered_ids,
        "required_approving_roles": _split_list(raw["approving_roles"]),
        "safety_authority": raw["safety_authority"],
        "abort_authority": raw["abort_authority"],
        "abort_criteria": _split_list(raw["abort_criteria"]),
        "maximum_termination_seconds": termination_seconds,
        "rollback_or_recovery_procedure": raw["rollback"],
        "release_condition": raw["release_condition"],
        "not_required_statement": None,
    }

    # Concept-level safety_controls overlay. Only fields the SafetyControls
    # schema actually defines — abort_criteria / release_condition live only
    # at the top level, NOT here.
    concept_controls = {
        "affected_assets": _split_list(raw["affected_assets"]),
        "required_approving_roles": _split_list(raw["approving_roles"]),
        "safety_authority": raw["safety_authority"],
        "abort_authority": raw["abort_authority"],
        "maximum_termination_seconds": termination_seconds,
        "rollback_or_recovery_procedure": raw["rollback"],
    }

    return assessment_review, concept_controls


STAGE3_WRITE_MAX_RETRIES = 3


def build_referential_context(*, stage2_vectors: dict, kcag_report: dict) -> str:
    """Deterministically derive the compact set of valid references the
    Stage 3 plan may cite, from the stamped stage2_vectors.json and
    kcag_report.json — NOT from any LLM summary.

    Exposes the graph STRUCTURALLY, not just as flat ID lists, so the
    compiler can build path-consistent concepts:

      {
        "edges": [
          {"vec": "V-02", "source": "ADV_START",
           "target": "CAPEC-628", "technique_id": "CAPEC-628"},
          ...
        ],
        "approved_paths": [
          ["ADV_START", "CAPEC-628", "G_CDL_ALL"],   # priority path first
          ...
        ],
        "valid_technique_ids": ["AML.T0080", "CAPEC-628", ...],
        "min_cut_nodes": [...]
      }

    Flat ID lists alone caused the RT-002/RT-003 failures: the model had
    real vector IDs and real nodes but no way to know which edge connects
    which nodes, so it attached a target/vector to a path they don't lie
    on. Edge membership + ordered paths give it enough to construct
    path-consistent concepts. This does NOT validate — that stays
    validate_stage3_test_plan's job; it only supplies the real structure.
    """
    raw_edges = stage2_vectors.get("edges", []) or []
    nodes = stage2_vectors.get("nodes", []) or []

    edges = []
    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        vec = e.get("vec")
        source = e.get("source")
        target = e.get("target")
        if not (vec and source and target):
            continue
        edges.append({
            "vec": vec,
            "source": source,
            "target": target,
            "technique_id": e.get("technique"),
        })
    edges.sort(key=lambda x: x["vec"])

    technique_ids = sorted({e["technique_id"] for e in edges if e["technique_id"]})
    node_ids = sorted({n.get("id") for n in nodes
                       if isinstance(n, dict) and n.get("id")})

    # Approved paths: ordered node sequences. priority_path first (it's the
    # highest-score path), then the remaining top_paths, de-duplicated while
    # preserving order.
    def _path_nodes(entry):
        if isinstance(entry, dict):
            return entry.get("path", []) or []
        if isinstance(entry, list):
            return entry
        return []

    approved_paths = []
    seen = set()

    priority = _path_nodes(kcag_report.get("priority_path"))
    if priority:
        approved_paths.append(priority)
        seen.add(tuple(priority))

    for entry in kcag_report.get("top_paths", []) or []:
        p = _path_nodes(entry)
        if p and tuple(p) not in seen:
            approved_paths.append(p)
            seen.add(tuple(p))

    min_cut_nodes = []
    minimum_cut = kcag_report.get("minimum_cut")
    if isinstance(minimum_cut, dict):
        min_cut_nodes = sorted(minimum_cut.get("aggregate_cut_nodes", []) or [])

    context = {
        "edges": edges,
        "approved_paths": approved_paths,
        "valid_graph_node_ids": node_ids,
        "valid_technique_ids": technique_ids,
        "min_cut_nodes": min_cut_nodes,
    }
    return json.dumps(context, sort_keys=True, separators=(",", ":"))

STAGE3_WRITE_SYSTEM = (
    "Return exactly one JSON object matching the supplied schema. "
    "The root object must contain schema_version, plan_title, "
    "test_concepts, and assessment_safety_review. "
    "Do not wrap the object in test_plan, plan, data, result, output, "
    "or any other container. "
    "Do not use stage in place of schema_version. "
    "Do not emit prose or a tool call."
)

STAGE3_WRITE_PROMPT_TEMPLATE = (
    "Translate the approved Stage 3 test plan prose below into a single "
    "JSON document matching the supplied schema. Do NOT invent new test "
    "concepts, vector IDs, KCAG paths, graph nodes, or technique IDs — "
    "use only what the prose and the referential context below already "
    "establish.\n\n"
    "ROOT SHAPE — REQUIRED:\n"
    "- The JSON root itself IS the Stage3TestPlan object.\n"
    "- Required root keys: schema_version, plan_title, test_concepts, "
    "assessment_safety_review.\n"
    "- Use schema_version (an integer), NOT stage.\n"
    '- Do not return {{"test_plan": {{...}}}} or any other wrapper.\n\n'
    "STRICT SCHEMA CONSTANTS:\n"
    "- schema_version MUST be the integer 1. It is the schema version, "
    "not the assessment stage number (do not use 3).\n"
    "- path_relationship MUST be exactly PRIORITY_PATH or "
    "ALTERNATE_VALID_PATH (uppercase, underscore — not 'Priority Path').\n"
    "- Inside safety_controls: maximum_termination_seconds MUST be an "
    "integer number of seconds (not a string like '15 minutes', and not "
    "a field named maximum_termination_time).\n"
    "- rollback_or_recovery_procedure is REQUIRED whenever safety_controls "
    "is present.\n"
    "- assessment_safety_review must contain ONLY schema-defined fields. "
    "Do NOT add approval_record or any other field not in the schema — "
    "prose authorization statements do not belong in this object.\n\n"
    "PATH CONSISTENCY RULES (the referential context gives edges and "
    "approved_paths — use them):\n"
    "- Each concept's kcag_path MUST exactly equal one entry in "
    "approved_paths (same nodes, same order).\n"
    "- Every target_node_id MUST appear in that concept's kcag_path.\n"
    "- Every execution_technique.vector_id MUST be the vec of an edge whose "
    "source and target are two CONSECUTIVE nodes in that kcag_path.\n"
    "- Do NOT combine a target or vector from one path with a different "
    "path. Pick one approved_path first, then draw the concept's targets "
    "and vectors only from the edges along that path.\n\n"
    "FIELD RULES:\n"
    "- Every test_concept needs: test_id (RT-NNN format), title, "
    "objective, stage2_vector_ids (LIST of vector ID strings that appear "
    "in the referential context), kcag_path (LIST of graph node ID "
    "strings), path_relationship, target_node_ids (LIST), categories "
    "(LIST of ints), execution_techniques (LIST of objects with "
    "technique_id, vector_id, rationale), defensive_concepts (LIST), "
    "mechanism_summary, preconditions (LIST), expected_effects (LIST), "
    "success_criteria (LIST), abort_criteria (LIST — must NOT be "
    "identical to success_criteria), rollback_or_recovery_steps (LIST), "
    "telemetry_requirements (LIST), assumptions (LIST), and "
    "safety_controls (object, REQUIRED for any concept whose categories "
    "include 2 or 3, null otherwise).\n"
    "- assessment_safety_review is required: category_2_3_present "
    "(boolean), covered_test_ids (LIST), and either an approval record or "
    "a not_required_statement.\n"
    "- Keep list-item strings concise; do not restate the prose "
    "narrative.\n\n"
    "REFERENTIAL CONTEXT (the only valid vector IDs, graph nodes, and "
    "technique IDs — do not reference anything outside this):\n"
    "{referential_context}\n\n"
    "APPROVED STAGE 3 PROSE:\n\n{stage3_prose}"
)


def _generate_stage3_plan_json(
    *,
    stage3_prose: str,
    referential_context: str,
    llm,
    writer_tool,
    correction_feedback: str = "",
    timeout_seconds: int = 600,
) -> str:
    """Request Stage 3 structured output via the shared Ollama primitive,
    validate it against the Stage3TestPlan schema, and return the
    validated JSON STRING ready to hand to write_stage3_test_plan
    (which takes test_plan_json: str and re-validates internally).

    correction_feedback, when non-empty, is appended to the prompt so a
    retry after a deterministic writer rejection sees what was wrong.
    """
    from src.stage3_schema import Stage3TestPlan

    schema = Stage3TestPlan.model_json_schema()

    prompt = STAGE3_WRITE_PROMPT_TEMPLATE.format(
        referential_context=referential_context,
        stage3_prose=stage3_prose,
    )
    if correction_feedback:
        prompt += (
            "\n\nPREVIOUS OUTPUT WAS REJECTED BY THE DETERMINISTIC "
            "VALIDATOR. Correct these errors:\n"
            f"{correction_feedback}"
        )

    normalized_content = generate_structured_json(
        llm=llm,
        schema=schema,
        prompt=prompt,
        system_message=STAGE3_WRITE_SYSTEM,
        timeout_seconds=timeout_seconds,
    )
    # The model deterministically wraps its output as {"test_plan": {...}}
    # despite the flat schema. Unwrap ONLY that exact single-key shape
    # before validation — this does not weaken the schema, since the inner
    # object must still satisfy every Stage3TestPlan rule. Anything else
    # (extra keys, non-dict value, a different wrapper name) is left
    # untouched so it validates/fails exactly as before.
    parsed = json.loads(normalized_content)
    if (isinstance(parsed, dict)
            and set(parsed.keys()) == {"test_plan"}
            and isinstance(parsed["test_plan"], dict)):
        parsed = parsed["test_plan"]

    # ---- DETERMINISTIC SAFETY OVERLAY ----
    # Safety-governance fields (approving roles, safety/abort authority,
    # abort criteria, termination seconds, rollback, release condition) are
    # extracted verbatim from the analyst-approved PRE-STAGE-4 SAFETY REVIEW
    # prose and OVERLAID onto the candidate — never left to the model to
    # copy, since letting it copy them is exactly what dropped them before.
    # This runs before validation so the candidate is authoritative-safe.
    _apply_prose_identity_overlay(
        parsed,
        stage3_prose,
    )
    _apply_safety_overlay(
        parsed,
        stage3_prose,
    )

    # Validate against the schema here so a malformed generation consumes a
    # retry with feedback, rather than only failing inside the writer.
    validated = Stage3TestPlan.model_validate(parsed)
    # Return the re-serialized, schema-valid JSON string for the writer.
    return validated.model_dump_json()


def _apply_safety_overlay(parsed: dict, stage3_prose: str) -> None:
    """Overlay the deterministically-parsed PRE-STAGE-4 SAFETY REVIEW onto
    the candidate dict IN PLACE, before Pydantic validation.

    When Category 2/3 concepts are present, this REPLACES the model's
    assessment_safety_review with the parsed one (the model routinely
    dropped or misfiled these), and overlays safety_controls onto each
    covered concept. When no Category 2/3 concepts are present, the parser
    returns (None, None) and this is a no-op — the model's
    not_required_statement path is left intact.

    Only mutates the candidate if parsing succeeds. A parse failure (a
    genuinely incomplete/placeholder safety block) propagates as ValueError
    so it becomes an analyst gap, not a silently partial plan.
    """
    if not isinstance(parsed, dict):
        return

    # Does the candidate actually contain any Category 2/3 concept? If not,
    # no safety review is required and a missing PRE-STAGE-4 SAFETY REVIEW
    # section is legitimate — leave the model's not_required path intact.
    has_cat_2_3 = False
    for concept in parsed.get("test_concepts", []) or []:
        if isinstance(concept, dict):
            cats = concept.get("categories") or []
            if any(c in (2, 3) for c in cats):
                has_cat_2_3 = True
                break
    if not has_cat_2_3:
        return

    review, concept_controls = parse_pre_stage4_safety_review(stage3_prose)
    if review is None:
        # Candidate HAS Cat 2/3 concepts but the prose block reports none —
        # a contradiction. Fail closed rather than leave safety unpopulated.
        raise ValueError(
            "Candidate contains Category 2/3 concepts but the PRE-STAGE-4 "
            "SAFETY REVIEW prose block reports no Category 2/3 concepts."
        )

    parsed["assessment_safety_review"] = review

    covered = set(review.get("covered_test_ids", []))
    for concept in parsed.get("test_concepts", []) or []:
        if not isinstance(concept, dict):
            continue
        if concept.get("test_id") not in covered:
            continue
        existing = concept.get("safety_controls") or {}
        if not isinstance(existing, dict):
            existing = {}
        # Overlay only the schema-defined SafetyControls fields.
        existing.update(concept_controls)
        concept["safety_controls"] = existing


def _record_validation_feedback(feedback_by_path: dict, exc) -> None:
    """Accumulate Pydantic validation errors keyed by field path, so a
    later attempt is reminded of EVERY constraint it has violated across
    all prior attempts — not just the most recent one. Re-violating a
    field updates its message; a field the model later fixes simply stops
    generating new errors (its prior entry stays, which is harmless — it
    just keeps reminding the model of a rule it's now satisfying)."""
    for error in exc.errors():
        path = ".".join(str(part) for part in error["loc"])
        feedback_by_path[path] = error["msg"]


def _render_feedback(feedback_by_path: dict, writer_feedback: list) -> str:
    """Render the accumulated per-field validation constraints and any
    deterministic writer rejections into a single correction block."""
    parts = []
    if feedback_by_path:
        parts.append("\n".join(
            f"- {path}: {message}"
            for path, message in sorted(feedback_by_path.items())
        ))
    if writer_feedback:
        parts.append("WRITER REJECTIONS:\n" + "\n".join(
            f"- {message}" for message in writer_feedback))
    return "\n\n".join(parts)


def compile_stage3_structured_output(
    *,
    stage3_prose: str,
    referential_context: str,
    llm,
    writer_tool,
    artifact_path: str,
    max_retries: int = STAGE3_WRITE_MAX_RETRIES,
    external_feedback: str = "",
) -> None:
    """Generate the Stage 3 structured test plan via Ollama's constrained
    decoding, validate against Stage3TestPlan, then invoke the real
    write_stage3_test_plan tool deterministically.

    external_feedback carries semantic-repair feedback from a PRIOR deep
    validation failure (the stage3_flow orchestrator passes it in). It is
    prepended to this compile's own schema-level correction feedback, so
    every attempt here also honors the referential/path/safety constraints
    the deep validator flagged on the previous candidate. This compiler
    never imports or runs the deep validator itself — it only receives its
    errors as text.

    Raises RuntimeError if all attempts fail.
    """
    from pydantic import ValidationError

    feedback_by_path: dict = {}
    writer_feedback: list = []

    for attempt in range(1, max_retries + 1):
        print(f"Stage 3 structured write: attempt {attempt}/{max_retries} "
              f"(Ollama structured output, not native tool call)...",
              flush=True)

        correction_feedback = _render_feedback(feedback_by_path, writer_feedback)
        if external_feedback:
            # Semantic (deep-validation) feedback from a prior candidate goes
            # first, so path/referential/safety constraints are never lost to
            # a schema-level retry within this compile.
            prefix = (
                "DEEP VALIDATION REJECTED A PREVIOUS CANDIDATE. You MUST also "
                "fix these referential/path/safety-review errors:\n"
                f"{external_feedback}"
            )
            correction_feedback = (
                prefix + "\n\n" + correction_feedback
                if correction_feedback else prefix
            )

        # ---- Generate + schema-validate the plan JSON ----
        try:
            plan_json = _generate_stage3_plan_json(
                stage3_prose=stage3_prose,
                referential_context=referential_context,
                llm=llm,
                writer_tool=writer_tool,
                correction_feedback=correction_feedback,
            )
        except ValidationError as exc:
            # Accumulate every field-level constraint so later attempts
            # keep ALL prior corrections, not just the newest error.
            _record_validation_feedback(feedback_by_path, exc)
            print(f"  Structured generation/validation failed: "
                  f"ValidationError: {exc}", flush=True)
            continue
        except Exception as exc:
            writer_feedback.append(f"{type(exc).__name__}: {exc}"[:2000])
            print(f"  Structured generation failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue

        # ---- Invoke the real writer tool (re-validates + writes) ----
        try:
            write_result = writer_tool.func(test_plan_json=plan_json)
        except Exception as exc:
            print(f"  Writer invocation raised "
                  f"{type(exc).__name__}: {exc}", flush=True)
            writer_feedback.append(f"{type(exc).__name__}: {exc}"[:2000])
            continue

        write_result_text = (
            write_result if isinstance(write_result, str)
            else repr(write_result)
        )
        print(f"  Writer result: {write_result_text[:120]}", flush=True)

        if write_result_text.startswith("WRITTEN"):
            if not os.path.exists(artifact_path):
                print(f"  Writer returned WRITTEN but {artifact_path} "
                      f"does not exist.", flush=True)
                continue
            try:
                run_context.read_stamped_json(artifact_path)
            except Exception as exc:
                print(f"  Written artifact failed stamped read-back: "
                      f"{type(exc).__name__}: {exc}", flush=True)
                continue
            print(f"  Stage 3 structured write SUCCEEDED on attempt "
                  f"{attempt}.", flush=True)
            return
        else:
            print(f"  REJECTED by validator: {write_result_text[:200]}",
                  flush=True)
            writer_feedback.append(write_result_text[:2000])

    raise RuntimeError(
        f"Stage 3 structured write failed after {max_retries} attempts. "
        f"See terminal output above for per-attempt details."
    )
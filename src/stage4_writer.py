"""
Direct Stage 4 structured-output compiler.

Same migration as Stage 1 and Stage 3: write_stage4_execution_plan
receives a large nested JSON string through CrewAI's agent executor and
Ollama's native-tool parser truncates/mangles it (schema-shape drift:
missing required phase/action fields, wrong Phase 0 field names). Stage 4
instead requests schema-constrained structured output through Ollama's
native /api/chat endpoint (src/structured_output.py), validates it against
Stage4ExecutionPlan, and passes the validated JSON string to the
deterministic writer tool.

Interface parity with Stage 3: write_stage4_execution_plan takes a single
execution_plan_json STRING (and re-validates internally), so this compiler
generates against Stage4ExecutionPlan directly, validates, and hands the
writer the JSON string.

PHASE 0 SAFETY GATE OVERLAY: the phase0_safety_gate is safety-governance
content and is NOT left to the model. It is derived deterministically from
the VALIDATED Stage 3 test plan's assessment_safety_review (the artifact
already deep-validated and hash-bound at Stage 3) — NOT by reparsing
stage3.md — so Stage 4's gate is provably identical to what Stage 3
validated. Overlaid onto the candidate before Pydantic validation.

This module owns only the Stage-4-specific concerns (prompt, feedback
loop, Phase 0 overlay, writer invocation, read-back). The generic
HTTP/normalize mechanics live in src/structured_output.py; the semantic
repair loop lives in src/stage4_flow.py.
"""
import json
import os

from src import run_context
from src.structured_output import generate_structured_json


STAGE4_WRITE_MAX_RETRIES = 3


def build_stage4_phase0_gate(stage3_test_plan: dict) -> dict:
    """Derive the Stage 4 phase0_safety_gate deterministically from the
    VALIDATED Stage 3 test plan's assessment_safety_review.

    The Stage 3 review and the Stage 4 gate share nine fields verbatim
    (approving roles, safety/abort authority, abort criteria, termination
    seconds, rollback, release condition, covered_test_ids,
    not_required_statement). Two Stage-4-only fields are derived:
      required           <- category_2_3_present
      execution_release  <- release_condition (the "may not begin before
                            clearance" statement), or a standard
                            not-required note when no Cat 2/3 concepts.

    Accepts either the stamped artifact shape ({"data": {...}, "_meta": ...})
    or the bare plan dict. Never invents governance values.
    """
    plan = stage3_test_plan.get("data", stage3_test_plan) \
        if isinstance(stage3_test_plan, dict) else {}
    review = plan.get("assessment_safety_review") or {}

    required = bool(review.get("category_2_3_present"))

    if not required:
        return {
            "required": False,
            "covered_test_ids": review.get("covered_test_ids", []) or [],
            "required_approving_roles": [],
            "safety_authority": None,
            "abort_authority": None,
            "abort_criteria": [],
            "maximum_termination_seconds": None,
            "rollback_or_recovery_procedure": None,
            "release_condition": None,
            # No Cat 2/3 payloads -> the gate does not apply.
            "execution_release": "NOT_APPLICABLE",
            "not_required_statement": review.get("not_required_statement"),
        }

    release_condition = review.get("release_condition")
    return {
        "required": True,
        "covered_test_ids": review.get("covered_test_ids", []) or [],
        "required_approving_roles": review.get("required_approving_roles", []) or [],
        "safety_authority": review.get("safety_authority"),
        "abort_authority": review.get("abort_authority"),
        "abort_criteria": review.get("abort_criteria", []) or [],
        "maximum_termination_seconds": review.get("maximum_termination_seconds"),
        "rollback_or_recovery_procedure": review.get("rollback_or_recovery_procedure"),
        # The operative release sentence stays in release_condition; the
        # execution_release STATUS flag is BLOCKED until sign-off, since this
        # planning artifact never itself authorizes execution.
        "release_condition": release_condition,
        "execution_release": "BLOCKED_PENDING_SIGNOFF",
        "not_required_statement": None,
    }


def _apply_phase0_overlay(parsed: dict, stage3_test_plan: dict) -> None:
    """Overlay the deterministically-derived phase0_safety_gate onto the
    candidate IN PLACE, before Pydantic validation. Always replaces the
    model's phase0_safety_gate — the model routinely emits the wrong field
    names (rso_coordination/max_termination_time/statement) for this
    nested object, and the authoritative values come from the validated
    Stage 3 plan regardless."""
    if not isinstance(parsed, dict):
        return
    parsed["phase0_safety_gate"] = build_stage4_phase0_gate(stage3_test_plan)


STAGE4_WRITE_SYSTEM = (
    "Return exactly one JSON object matching the supplied schema. "
    "The root object must contain schema_version, plan_id, plan_title, "
    "artifact_role, execution_authorization, source_stage3_test_ids, "
    "phase0_safety_gate, test_bindings, phases, global_opsec_measures, "
    "assumptions, and limitations. "
    "Do not wrap the object in execution_plan, plan, data, result, output, "
    "or any other container. "
    "Do not emit prose or a tool call."
)

STAGE4_WRITE_PROMPT_TEMPLATE = (
    "Translate the approved Stage 4 mission-plan prose below into a single "
    "JSON document matching the supplied schema. Use only the test IDs, "
    "vector IDs, KCAG paths, and technique IDs already established by the "
    "Stage 3 test plan and referential context — do NOT invent new ones.\n\n"
    "ROOT SHAPE — REQUIRED:\n"
    "- The JSON root itself IS the Stage4ExecutionPlan object.\n"
    "- Required root keys: schema_version, plan_id, plan_title, "
    "artifact_role, execution_authorization, source_stage3_test_ids, "
    "phase0_safety_gate, test_bindings, phases, global_opsec_measures, "
    "assumptions, limitations.\n"
    "- Use schema_version (integer 1), NOT stage.\n"
    '- Do not return {{"execution_plan": {{...}}}} or any other wrapper.\n\n'
    "STRICT SCHEMA CONSTANTS:\n"
    "- schema_version MUST be the integer 1.\n"
    "- artifact_role MUST be exactly 'HUMAN_REVIEWED_MISSION_PLAN_DRAFT'.\n"
    "- execution_authorization MUST be exactly 'NOT_GRANTED' (this is a "
    "planning product; it does not authorize execution).\n"
    "- Each phase REQUIRES: phase_id, sequence (integer), name, purpose, "
    "entry_criteria (list), exit_criteria (list), actions (list).\n"
    "- Each action REQUIRES: action_id, test_id, action_summary, "
    "responsible_roles (list), preconditions (list), success_criteria "
    "(list), abort_criteria (list), rollback_or_recovery_steps (list — "
    "this exact field name, NOT recovery_steps), telemetry_requirements "
    "(list), alert_triggers (list), opsec_measures (list).\n"
    "- global_opsec_measures, assumptions, and limitations are REQUIRED "
    "root-level lists.\n"
    "- Do NOT emit phase0_safety_gate content yourself: emit "
    "phase0_safety_gate as an empty object {{}} — its authoritative values "
    "are injected deterministically from the validated Stage 3 plan.\n\n"
    "REFERENTIAL CONTEXT (valid test IDs, vectors, nodes, techniques):\n"
    "{referential_context}\n\n"
    "APPROVED STAGE 4 MISSION-PLAN PROSE:\n\n{stage4_prose}"
)


def _record_validation_feedback(feedback_by_path: dict, exc) -> None:
    """Accumulate Pydantic validation errors keyed by field path, so a
    later attempt keeps EVERY prior constraint (same anti-lossy-feedback
    discipline as Stage 3)."""
    for error in exc.errors():
        path = ".".join(str(part) for part in error["loc"])
        feedback_by_path[path] = error["msg"]


def _render_feedback(feedback_by_path: dict, writer_feedback: list) -> str:
    parts = []
    if feedback_by_path:
        parts.append("\n".join(
            f"- {path}: {message}"
            for path, message in sorted(feedback_by_path.items())))
    if writer_feedback:
        parts.append("WRITER REJECTIONS:\n" + "\n".join(
            f"- {message}" for message in writer_feedback))
    return "\n\n".join(parts)


def _generate_stage4_plan_json(
    *,
    stage4_prose: str,
    referential_context: str,
    stage3_test_plan: dict,
    llm,
    correction_feedback: str = "",
    timeout_seconds: int = 600,
) -> str:
    """Request Stage 4 structured output, apply the deterministic Phase 0
    overlay, validate against Stage4ExecutionPlan, and return the validated
    JSON string ready for write_stage4_execution_plan."""
    from src.stage4_schema import Stage4ExecutionPlan

    schema = Stage4ExecutionPlan.model_json_schema()

    prompt = STAGE4_WRITE_PROMPT_TEMPLATE.format(
        referential_context=referential_context,
        stage4_prose=stage4_prose,
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
        system_message=STAGE4_WRITE_SYSTEM,
        timeout_seconds=timeout_seconds,
    )

    parsed = json.loads(normalized_content)
    if (isinstance(parsed, dict)
            and set(parsed.keys()) == {"execution_plan"}
            and isinstance(parsed["execution_plan"], dict)):
        parsed = parsed["execution_plan"]

    # ---- DETERMINISTIC PHASE 0 SAFETY-GATE OVERLAY ----
    # Derived from the validated Stage 3 plan, never the model.
    _apply_phase0_overlay(parsed, stage3_test_plan)

    validated = Stage4ExecutionPlan.model_validate(parsed)
    return validated.model_dump_json()


def compile_stage4_structured_output(
    *,
    stage4_prose: str,
    referential_context: str,
    stage3_test_plan: dict,
    llm,
    writer_tool,
    artifact_path: str,
    max_retries: int = STAGE4_WRITE_MAX_RETRIES,
    external_feedback: str = "",
) -> None:
    """Generate the Stage 4 structured execution plan via Ollama's
    constrained decoding, overlay the Phase 0 gate deterministically,
    validate against Stage4ExecutionPlan, then invoke the real
    write_stage4_execution_plan tool.

    external_feedback carries semantic-repair feedback from a prior deep
    validation failure (the stage4_flow orchestrator passes it in). This
    compiler never imports or runs the deep validator itself.

    Raises RuntimeError if all attempts fail.
    """
    from pydantic import ValidationError

    feedback_by_path: dict = {}
    writer_feedback: list = []

    for attempt in range(1, max_retries + 1):
        print(f"Stage 4 structured write: attempt {attempt}/{max_retries} "
              f"(Ollama structured output, not native tool call)...",
              flush=True)

        correction_feedback = _render_feedback(feedback_by_path, writer_feedback)
        if external_feedback:
            prefix = (
                "DEEP VALIDATION REJECTED A PREVIOUS CANDIDATE. You MUST also "
                "fix these referential/consistency errors:\n"
                f"{external_feedback}"
            )
            correction_feedback = (
                prefix + "\n\n" + correction_feedback
                if correction_feedback else prefix
            )

        try:
            plan_json = _generate_stage4_plan_json(
                stage4_prose=stage4_prose,
                referential_context=referential_context,
                stage3_test_plan=stage3_test_plan,
                llm=llm,
                correction_feedback=correction_feedback,
            )
        except ValidationError as exc:
            _record_validation_feedback(feedback_by_path, exc)
            print(f"  Structured generation/validation failed: "
                  f"ValidationError: {exc}", flush=True)
            continue
        except Exception as exc:
            writer_feedback.append(f"{type(exc).__name__}: {exc}"[:2000])
            print(f"  Structured generation failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue

        try:
            write_result = writer_tool.func(execution_plan_json=plan_json)
        except Exception as exc:
            print(f"  Writer invocation raised "
                  f"{type(exc).__name__}: {exc}", flush=True)
            writer_feedback.append(f"{type(exc).__name__}: {exc}"[:2000])
            continue

        write_result_text = (
            write_result if isinstance(write_result, str) else repr(write_result))
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
            print(f"  Stage 4 structured write SUCCEEDED on attempt "
                  f"{attempt}.", flush=True)
            return
        else:
            print(f"  REJECTED by validator: {write_result_text[:200]}",
                  flush=True)
            writer_feedback.append(write_result_text[:2000])

    raise RuntimeError(
        f"Stage 4 structured write failed after {max_retries} attempts. "
        f"See terminal output above for per-attempt details."
    )
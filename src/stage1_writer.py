"""
Direct Stage 1 structured-output compiler.

Gemma can generate the Stage 1 content, but Ollama's Gemma native-tool
parser fails to serialize the large call as valid JSON (unquoted keys,
single-quoted strings, = instead of :, null bytes). Stage 1 therefore
requests schema-constrained structured output through Ollama's native
/api/chat endpoint. The response is normalized (including optional
Markdown code-fence stripping), validated with the writer's Pydantic
schema, and passed through the deterministic writer before becoming
authoritative.

Extracted from crew.py so the retry logic, argument validation, and
artifact verification are independently testable without loading a
full Crew.
"""
import json
import os
import urllib.request

from src import run_context


def _normalize_json_content(content: str) -> str:
    """Accept raw JSON or one complete ```json ... ``` wrapper only.
    Does not use a broad regex that would extract JSON from surrounding
    prose — only a strict, structurally complete fence is accepted."""
    normalized = content.strip()
    if not normalized.startswith("```"):
        if "```" in normalized:
            raise ValueError(
                "Structured output contains a code fence that is not at the "
                "start — possible surrounding prose."
            )
        return normalized
    lines = normalized.splitlines()
    if len(lines) < 3:
        raise ValueError("Incomplete fenced JSON response.")
    opening = lines[0].strip().lower()
    closing = lines[-1].strip()
    if opening not in {"```", "```json"}:
        raise ValueError(
            f"Unsupported structured-output fence: {lines[0]!r}"
        )
    if closing != "```":
        raise ValueError("Structured-output fence is not closed.")
    inner = "\n".join(lines[1:-1]).strip()
    if "```" in inner:
        raise ValueError(
            "Structured output contains nested or additional fences."
        )
    if not inner:
        raise ValueError("Structured output fence is empty.")
    return inner


STAGE1_WRITE_MAX_RETRIES = 3

STAGE1_WRITE_SYSTEM = (
    "Return only a JSON document matching the supplied schema. "
    "Do not emit a tool call or prose."
)

STAGE1_WRITE_PROMPT_TEMPLATE = (
    "Translate the Stage 1 three-layer decomposition below into a single "
    "JSON document matching the supplied schema.\n\n"
    "FIELD RULES:\n"
    "- technical_nodes / procedural_nodes: each entry needs component_id "
    "(C-T-NN / C-P-NN), layer (must match the list), name, "
    "asset_control_levels (a JSON LIST of strings like "
    '[\"No Access\", \"API Reach\"] — NOT an arrow-joined string), '
    "information_flows (string), downstream_dependencies (LIST of "
    "component ID strings, e.g. [\"C-T-02\"] — NOT names or descriptions), "
    "is_gap (boolean).\n"
    "- cognitive_nodes: component_id (C-C-NN), hierarchy_stage (one of "
    "Data/Information/Knowledge/Understanding/Decision/Behavior), "
    "feeds (string), corrupts (string), downstream_effect (string), "
    "detection_probability (HIGH/MEDIUM/LOW), is_center_of_gravity "
    "(boolean), is_gap (boolean).\n"
    "- trust_boundaries: boundary_id (TB-NN), from_component (a component "
    "ID like C-T-01, NOT a name), to_component (a component ID), "
    "description (string).\n\n"
    "SIZE LIMITS:\n"
    "- 8-10 technical nodes.\n"
    "- 8-10 procedural nodes.\n"
    "- Up to 6 cognitive hierarchy nodes when supported by the "
    "decomposition.\n"
    "- 5-8 trust boundaries.\n"
    "- Roughly 25-30 total component nodes.\n"
    "- Keep information_flows, feeds, corrupts, downstream_effect, and "
    "descriptions brief (under ~10 words each).\n"
    "- Do not add components absent from the decomposition.\n\n"
    "DECOMPOSITION:\n\n{stage1_prose}"
)


def _generate_structured_arguments(
    *,
    stage1_prose: str,
    llm,
    writer_tool,
    correction_feedback: str = "",
    timeout_seconds: int = 600,
) -> dict:
    """Call Ollama's native /api/chat with schema-constrained structured
    output (``format: <json_schema>``), bypassing the native-tool-call
    parser entirely. Returns validated, model_dump()'d arguments ready
    for writer_tool.func(**args).

    correction_feedback, when non-empty, is appended to the prompt so a
    retry after a deterministic writer rejection sees what was wrong —
    essential because temperature=0 makes an identical prompt reproduce
    the identical rejected output.

    Uses urllib directly rather than the OpenAI SDK because ``format``
    with a JSON schema is an Ollama-native feature not exposed through
    the /v1 compatibility layer's response_format parameter (which only
    supports ``{"type": "json_object"}`` without a schema).
    """
    schema = writer_tool.args_schema.model_json_schema()

    # Resolve Ollama's native base URL from the LLM's configured base_url,
    # which may point at /v1 due to CrewAI's forced routing.
    base_url = str(llm.base_url).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    model = str(llm.model).removeprefix("ollama/")

    prompt = STAGE1_WRITE_PROMPT_TEMPLATE.format(stage1_prose=stage1_prose)
    if correction_feedback:
        prompt += (
            "\n\nPREVIOUS OUTPUT WAS REJECTED BY THE DETERMINISTIC "
            "VALIDATOR. Correct these errors:\n"
            f"{correction_feedback}"
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": STAGE1_WRITE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "format": schema,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 16384,
        },
    }

    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))

    if not body.get("done"):
        raise RuntimeError("Ollama returned an incomplete response.")

    content = body.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned empty structured Stage 1 content.")

    normalized_content = _normalize_json_content(content)
    validated = writer_tool.args_schema.model_validate_json(normalized_content)
    return validated.model_dump()


def compile_stage1_structured_output(
    *,
    stage1_prose: str,
    llm,
    writer_tool,
    artifact_path: str,
    max_retries: int = STAGE1_WRITE_MAX_RETRIES,
) -> None:
    """Generate Stage 1 structured output via Ollama's constrained
    decoding, validate with the writer tool's Pydantic schema, then
    invoke the real writer tool deterministically.

    Raises RuntimeError if all attempts fail.
    """
    feedback = ""
    for attempt in range(1, max_retries + 1):
        print(f"Stage 1 structured write: attempt {attempt}/{max_retries} "
              f"(Ollama structured output, not native tool call)...",
              flush=True)

        # ---- Generate structured arguments ----
        try:
            validated_args = _generate_structured_arguments(
                stage1_prose=stage1_prose,
                llm=llm,
                writer_tool=writer_tool,
                correction_feedback=feedback,
            )
        except Exception as exc:
            print(f"  Structured generation failed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue

        node_count = sum(
            len(validated_args.get(k, []))
            for k in ("technical_nodes", "procedural_nodes",
                      "cognitive_nodes", "trust_boundaries")
        )
        print(f"  Structured JSON received and validated — invoking "
              f"{writer_tool.name} with {node_count} total entries...",
              flush=True)

        # ---- Invoke the real writer tool ----
        try:
            write_result = writer_tool.func(**validated_args)
        except Exception as exc:
            print(f"  Writer invocation raised "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue

        write_result_text = (
            write_result if isinstance(write_result, str)
            else repr(write_result)
        )
        print(f"  Writer result: {write_result_text[:120]}", flush=True)

        if write_result_text.startswith("WRITTEN"):
            # Verify the artifact actually exists and passes stamped read-back
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
            print(f"  Stage 1 structured write SUCCEEDED on attempt "
                  f"{attempt}.", flush=True)
            return
        else:
            # REJECTED — feed the exact validator message back into the
            # next attempt's prompt. Essential at temperature=0, where an
            # unchanged prompt reproduces the identical rejected output.
            print(f"  REJECTED by validator: {write_result_text[:200]}",
                  flush=True)
            feedback = write_result_text[:4000]

    raise RuntimeError(
        f"Stage 1 structured write failed after {max_retries} attempts. "
        f"See terminal output above for per-attempt details."
    )
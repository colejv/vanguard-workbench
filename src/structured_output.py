"""
Shared low-level Ollama structured-output primitive.

Gemma can generate large structured content, but Ollama's Gemma
native-tool parser fails to serialize big tool calls as valid JSON
(unquoted keys, single-quoted strings, = instead of :, null bytes).
Requesting schema-constrained structured output through Ollama's native
/api/chat endpoint (``format: <json_schema>``) bypasses that parser
entirely.

This module handles ONLY the generic mechanics shared by every stage
that uses this approach:
  - strip /v1 from the Ollama base URL (CrewAI forces ollama models
    through /v1, but the native format= feature lives on /api/chat);
  - POST /api/chat with format=<schema>, stream:False, think:False;
  - check the response's ``done`` flag;
  - normalize an optional, strict Markdown JSON fence;
  - return normalized structured content for caller-owned validation;
  - enforce a timeout.

Stage-specific concerns — the prompt, the system message, correction
feedback wording, which writer tool to invoke, artifact read-back, and
domain rules — stay OUT of this module, in the per-stage writer modules
(stage1_writer.py, stage3_writer.py, ...). This keeps the fragile HTTP
logic in one place without an oversized "generic writer" abstraction
that has to understand every stage.
"""
import json
import urllib.request


DEFAULT_SYSTEM_MESSAGE = (
    "Return only a JSON document matching the supplied schema. "
    "Do not emit a tool call or prose."
)


def normalize_json_content(content: str) -> str:
    """Accept raw JSON or exactly one complete ```json ... ``` (or bare
    ``` ... ```) wrapper. Rejects surrounding prose, unclosed fences,
    nested/extra fences, and empty fences. Does NOT use a broad regex
    that would extract JSON from arbitrary surrounding text — the wrapper
    must be structurally complete and the only thing present."""
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
        raise ValueError(f"Unsupported structured-output fence: {lines[0]!r}")
    if closing != "```":
        raise ValueError("Structured-output fence is not closed.")
    inner = "\n".join(lines[1:-1]).strip()
    if "```" in inner:
        raise ValueError("Structured output contains nested or additional fences.")
    if not inner:
        raise ValueError("Structured output fence is empty.")
    return inner


def resolve_ollama_native(llm) -> tuple:
    """From a CrewAI LLM object, return (base_url_without_v1, model_without_ollama_prefix)
    suitable for a direct Ollama /api/chat call."""
    base_url = str(llm.base_url).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    model = str(llm.model).removeprefix("ollama/")
    return base_url, model


def generate_structured_json(
    *,
    llm,
    schema: dict,
    prompt: str,
    system_message: str = DEFAULT_SYSTEM_MESSAGE,
    num_predict: int = 16384,
    timeout_seconds: int = 600,
) -> str:
    """Request schema-constrained structured output from Ollama and return
    the NORMALIZED JSON string (fence-stripped), NOT yet validated against
    any Pydantic model — the caller owns validation so it can attach
    stage-specific error handling and feedback.

    Raises RuntimeError on an incomplete (`done` != True) or empty
    response, and ValueError (from normalize_json_content) on a malformed
    fence. Network/timeout errors from urllib propagate uncaught for the
    caller's retry loop to handle.
    """
    base_url, model = resolve_ollama_native(llm)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ],
        "format": schema,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": num_predict,
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
        raise RuntimeError("Ollama returned empty structured content.")

    return normalize_json_content(content)
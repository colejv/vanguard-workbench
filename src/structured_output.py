"""
Shared low-level Ollama structured-output primitive.

Requests schema-constrained JSON through Ollama's native /api/chat endpoint.
The socket timeout protects individual socket operations; the POSIX alarm
adds a whole-call deadline so a response that trickles data indefinitely
cannot hold the pipeline forever.
"""

from __future__ import annotations

import json
import signal
import socket
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager


DEFAULT_SYSTEM_MESSAGE = (
    "Return only a JSON document matching the supplied schema. "
    "Do not emit a tool call or prose."
)


class StructuredOutputTimeout(TimeoutError):
    """Raised when an Ollama structured-output call exceeds its deadline."""


def normalize_json_content(content: str) -> str:
    """
    Accept raw JSON or exactly one complete JSON code fence.

    Reject surrounding prose, incomplete fences, nested fences, and empty
    fenced content.
    """

    normalized = content.strip()

    if not normalized.startswith("```"):
        if "```" in normalized:
            raise ValueError(
                "Structured output contains a code fence that is not at "
                "the start — possible surrounding prose."
            )

        return normalized

    lines = normalized.splitlines()

    if len(lines) < 3:
        raise ValueError(
            "Incomplete fenced JSON response."
        )

    opening = lines[0].strip().lower()
    closing = lines[-1].strip()

    if opening not in {
        "```",
        "```json",
    }:
        raise ValueError(
            "Unsupported structured-output fence: "
            f"{lines[0]!r}"
        )

    if closing != "```":
        raise ValueError(
            "Structured-output fence is not closed."
        )

    inner = "\n".join(
        lines[1:-1]
    ).strip()

    if "```" in inner:
        raise ValueError(
            "Structured output contains nested or additional fences."
        )

    if not inner:
        raise ValueError(
            "Structured output fence is empty."
        )

    return inner


def resolve_ollama_native(
    llm,
) -> tuple[str, str]:
    """
    Resolve a CrewAI LLM object to an Ollama native base URL and model name.
    """

    base_url = str(
        llm.base_url
    ).rstrip("/")

    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    model = str(
        llm.model
    ).removeprefix("ollama/")

    return base_url, model


@contextmanager
def _whole_call_deadline(
    timeout_seconds: float,
):
    """
    Enforce a whole-call deadline on POSIX when running in the main thread.

    urllib's timeout covers socket operations. This alarm additionally
    covers the entire request and response lifecycle.
    """

    if timeout_seconds <= 0:
        raise ValueError(
            "timeout_seconds must be greater than zero"
        )

    supports_alarm = (
        hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
        and threading.current_thread()
        is threading.main_thread()
    )

    if not supports_alarm:
        yield
        return

    previous_handler = signal.getsignal(
        signal.SIGALRM
    )
    previous_timer = signal.getitimer(
        signal.ITIMER_REAL
    )

    def _raise_timeout(
        signum,
        frame,
    ):
        del signum
        del frame

        raise StructuredOutputTimeout(
            "Ollama structured-output call exceeded "
            f"{timeout_seconds:g} seconds."
        )

    signal.signal(
        signal.SIGALRM,
        _raise_timeout,
    )
    signal.setitimer(
        signal.ITIMER_REAL,
        float(timeout_seconds),
    )

    try:
        yield
    finally:
        signal.setitimer(
            signal.ITIMER_REAL,
            0,
        )
        signal.signal(
            signal.SIGALRM,
            previous_handler,
        )

        if previous_timer[0] > 0:
            signal.setitimer(
                signal.ITIMER_REAL,
                previous_timer[0],
                previous_timer[1],
            )


def generate_structured_json(
    *,
    llm,
    schema: dict,
    prompt: str,
    system_message: str = DEFAULT_SYSTEM_MESSAGE,
    num_predict: int = 16384,
    timeout_seconds: int = 600,
) -> str:
    """
    Request schema-constrained output from Ollama.

    Returns normalized JSON text. The caller remains responsible for parsing
    and domain validation.
    """

    base_url, model = resolve_ollama_native(
        llm
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_message,
            },
            {
                "role": "user",
                "content": prompt,
            },
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
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Connection": "close",
        },
        method="POST",
    )

    try:
        with _whole_call_deadline(
            timeout_seconds
        ):
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                raw_body = response.read()

    except StructuredOutputTimeout:
        raise

    except socket.timeout as exc:
        raise StructuredOutputTimeout(
            "Ollama socket timed out after "
            f"{timeout_seconds} seconds."
        ) from exc

    except urllib.error.URLError as exc:
        if isinstance(
            exc.reason,
            socket.timeout,
        ):
            raise StructuredOutputTimeout(
                "Ollama request timed out after "
                f"{timeout_seconds} seconds."
            ) from exc

        raise

    try:
        body = json.loads(
            raw_body.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError(
            "Ollama returned an invalid HTTP JSON response."
        ) from exc

    if not body.get("done"):
        raise RuntimeError(
            "Ollama returned an incomplete response."
        )
    
    done_reason = body.get(
        "done_reason"
    )

    if done_reason == "length":
        raise RuntimeError(
            "Ollama stopped because the output token "
            "limit was reached."
        )

    content = (
        body.get("message", {})
        .get("content")
    )

    if (
        not isinstance(content, str)
        or not content.strip()
    ):
        raise RuntimeError(
            "Ollama returned empty structured content."
        )

    return normalize_json_content(
        content
    )
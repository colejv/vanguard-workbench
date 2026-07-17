"""Tests for the structured-output whole-call deadline."""

from __future__ import annotations

import time

import pytest

import src.structured_output as structured_output


class _FakeLLM:
    base_url = "http://localhost:11434"
    model = "ollama/test-model"


class _BlockingResponse:
    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    def read(self):
        time.sleep(5)

        return b'{"done": true}'


def test_whole_call_deadline_interrupts_blocking_read(
    monkeypatch,
):
    monkeypatch.setattr(
        structured_output.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (
            _BlockingResponse()
        ),
    )

    started_at = time.monotonic()

    with pytest.raises(
        structured_output.StructuredOutputTimeout,
        match="exceeded",
    ):
        structured_output.generate_structured_json(
            llm=_FakeLLM(),
            schema={
                "type": "object",
            },
            prompt="test",
            timeout_seconds=0.1,
        )

    assert (
        time.monotonic()
        - started_at
    ) < 2
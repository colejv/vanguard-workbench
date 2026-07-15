"""
Tests for the direct Stage 1 structured-output compiler
(src/stage1_writer.py), especially the validator-feedback retry loop.

The essential scenario the reviewer specified:
  attempt 1 -> deterministic writer returns REJECTED
  attempt 2 prompt -> contains the exact rejection feedback
  attempt 2 -> valid output
  artifact -> written and verified

These mock urllib.request.urlopen (the helper calls Ollama's /api/chat
directly via urllib, not the OpenAI SDK) so no real model or server is
needed and the flow is deterministic. Each fake response returns one
queued JSON body; the prompts sent are captured so the test can assert
attempt 2 actually received attempt 1's rejection text.
"""
import io
import json
from contextlib import contextmanager
from unittest import mock

import pytest

from src import run_context
from src.tools import write_stage1_output
from src.stage1_writer import compile_stage1_structured_output


@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    run_context.reset_active_run()
    run_context.set_active_run("test-run", "sha256:test", str(tmp_path / "out"))
    yield
    run_context.reset_active_run()


class _FakeLLM:
    model = "ollama/gemma4-12b-tool"
    base_url = "http://localhost:11434/v1"


def _valid_stage1_args():
    return {
        "technical_nodes": [{
            "component_id": "C-T-01", "layer": "technical", "name": "CDL",
            "asset_control_levels": ["No Access"], "information_flows": "x",
            "downstream_dependencies": [], "is_gap": False,
        }],
        "procedural_nodes": [],
        "cognitive_nodes": [],
        "trust_boundaries": [],
    }


def _bad_layer_stage1_args():
    args = _valid_stage1_args()
    args["technical_nodes"][0]["layer"] = "Technical"  # wrong case -> writer REJECTED
    return args


def _ollama_body(content_obj):
    """Build a fake Ollama /api/chat response body wrapping content as JSON."""
    return {
        "done": True,
        "message": {"role": "assistant", "content": json.dumps(content_obj)},
    }


@contextmanager
def _fake_urlopen(queued_bodies, captured_prompts):
    """Patch urllib.request.urlopen to return queued bodies in order,
    capturing the user-message prompt from each request."""
    bodies = list(queued_bodies)

    def _fake(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        user_msg = next(m["content"] for m in payload["messages"] if m["role"] == "user")
        captured_prompts.append(user_msg)
        body = bodies.pop(0)

        class _Resp:
            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
            def read(self_): return json.dumps(body).encode("utf-8")
        return _Resp()

    with mock.patch("src.structured_output.urllib.request.urlopen", _fake):
        yield


def test_direct_stage1_writer_accepts_valid_tool_call():
    captured = []
    with _fake_urlopen([_ollama_body(_valid_stage1_args())], captured):
        compile_stage1_structured_output(
            stage1_prose="# Stage 1\nDecomposition.",
            llm=_FakeLLM(),
            writer_tool=write_stage1_output,
            artifact_path=run_context.artifact_path("stage1_output.json"),
        )
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage1_output.json"))
    assert artifact["technical_nodes"][0]["component_id"] == "C-T-01"


def test_direct_stage1_writer_feeds_rejection_into_next_prompt():
    """The core feedback-loop scenario: attempt 1 rejected, attempt 2's
    prompt contains the exact rejection text, attempt 2 succeeds."""
    captured = []
    bodies = [
        _ollama_body(_bad_layer_stage1_args()),   # attempt 1 -> writer REJECTED
        _ollama_body(_valid_stage1_args()),        # attempt 2 -> WRITTEN
    ]
    with _fake_urlopen(bodies, captured):
        compile_stage1_structured_output(
            stage1_prose="# Stage 1\nDecomposition.",
            llm=_FakeLLM(),
            writer_tool=write_stage1_output,
            artifact_path=run_context.artifact_path("stage1_output.json"),
        )

    assert len(captured) == 2, "expected exactly two attempts"
    # Attempt 1 prompt must NOT contain feedback.
    assert "PREVIOUS OUTPUT WAS REJECTED" not in captured[0]
    # Attempt 2 prompt MUST contain the rejection feedback with the real
    # validator message about the wrong layer.
    assert "PREVIOUS OUTPUT WAS REJECTED" in captured[1]
    assert "wrong layer" in captured[1]
    # And the artifact was ultimately written.
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage1_output.json"))
    assert artifact["technical_nodes"][0]["layer"] == "technical"


def test_direct_stage1_writer_retries_markdown_fenced_json():
    """Attempt 1 returns fenced JSON that fails normalization... actually
    fences ARE handled by _normalize_json_content, so a fenced-but-valid
    body should succeed on attempt 1."""
    captured = []
    fenced_body = {
        "done": True,
        "message": {"role": "assistant",
                    "content": "```json\n" + json.dumps(_valid_stage1_args()) + "\n```"},
    }
    with _fake_urlopen([fenced_body], captured):
        compile_stage1_structured_output(
            stage1_prose="# Stage 1",
            llm=_FakeLLM(),
            writer_tool=write_stage1_output,
            artifact_path=run_context.artifact_path("stage1_output.json"),
        )
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage1_output.json"))
    assert artifact["technical_nodes"][0]["component_id"] == "C-T-01"


def test_direct_stage1_writer_fails_closed_after_retry_limit():
    """All attempts rejected -> RuntimeError, no artifact written."""
    captured = []
    bodies = [_ollama_body(_bad_layer_stage1_args())] * 3
    with _fake_urlopen(bodies, captured):
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            compile_stage1_structured_output(
                stage1_prose="# Stage 1",
                llm=_FakeLLM(),
                writer_tool=write_stage1_output,
                artifact_path=run_context.artifact_path("stage1_output.json"),
            )
    assert len(captured) == 3
    import os
    assert not os.path.exists(run_context.artifact_path("stage1_output.json"))


def test_direct_stage1_writer_retries_empty_content():
    """An empty/incomplete Ollama response consumes a retry, then succeeds."""
    captured = []
    empty_body = {"done": True, "message": {"role": "assistant", "content": ""}}
    bodies = [empty_body, _ollama_body(_valid_stage1_args())]
    with _fake_urlopen(bodies, captured):
        compile_stage1_structured_output(
            stage1_prose="# Stage 1",
            llm=_FakeLLM(),
            writer_tool=write_stage1_output,
            artifact_path=run_context.artifact_path("stage1_output.json"),
        )
    assert len(captured) == 2
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage1_output.json"))
    assert artifact["technical_nodes"][0]["component_id"] == "C-T-01"
"""
Tests for the direct Stage 3 structured-output compiler
(src/stage3_writer.py), mirroring the Stage 1 tests plus the deeper-schema
cases the reviewer requested (Stage3TestPlan is substantially more nested
than Stage1Output).

Mocks src.structured_output.urllib.request.urlopen so no real model or
server is needed and each response is deterministic.
"""
import json
from contextlib import contextmanager
from unittest import mock

import pytest

from src import run_context
from src.tools import write_stage3_test_plan
from src.stage3_writer import compile_stage3_structured_output


@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import os
    os.makedirs("corpus-index", exist_ok=True)
    json.dump(
        {"T1078": {"id": "T1078", "name": "Valid Accounts", "description": "x"},
         "T1565.001": {"id": "T1565.001", "name": "Stored Data Manipulation", "description": "x"},
         "T1190": {"id": "T1190", "name": "Exploit Public-Facing App", "description": "x"},
         "CAPEC-628": {"id": "CAPEC-628", "name": "GPS Spoofing", "description": "x"}},
        open("corpus-index/technique_index.json", "w"),
    )
    run_context.reset_active_run()
    run_context.set_active_run("test-run", "sha256:test", str(tmp_path / "out"))
    yield
    run_context.reset_active_run()


class _FakeLLM:
    model = "ollama/gemma4-12b-tool"
    base_url = "http://localhost:11434/v1"


def _concept(test_id="RT-001", categories=None):
    return {
        "test_id": test_id, "title": "Auth flow assessment",
        "objective": "Test authentication bypass path",
        "stage2_vector_ids": ["V-01", "V-02"],
        "kcag_path": ["ADV_START", "N1", "G1"],
        "path_relationship": "PRIORITY_PATH",
        "target_node_ids": ["N1"],
        "categories": categories or [1],
        "execution_techniques": [
            {"technique_id": "T1078", "vector_id": "V-01",
             "rationale": "Valid accounts used for initial access"},
        ],
        "defensive_concepts": ["MFA enforcement"],
        "mechanism_summary": "Adversary uses stolen credentials to access the C2 relay",
        "preconditions": ["Credentials obtained via phishing"],
        "expected_effects": ["Unauthorized access to C2 relay"],
        "success_criteria": ["Access confirmed via audit log"],
        "abort_criteria": ["Unexpected system instability observed"],
        "rollback_or_recovery_steps": ["Revoke test credentials"],
        "telemetry_requirements": ["Auth log monitoring"],
        "assumptions": ["MFA is not enforced on this endpoint"],
        "safety_controls": None,
    }


def _plan(concepts=None):
    return {
        "schema_version": 1, "plan_title": "Test Plan",
        "test_concepts": concepts or [_concept()],
        "assessment_safety_review": {
            "category_2_3_present": False, "covered_test_ids": [],
            "not_required_statement": "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.",
        },
    }


def _ollama_body(content_str):
    return {"done": True, "message": {"role": "assistant", "content": content_str}}


@contextmanager
def _fake_urlopen(queued_bodies, captured_prompts):
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


_REF = "vectors: V-01,V-02,V-03,V-04; nodes: ADV_START,N1,N2,G1; techniques: T1078"


def _run(bodies, captured):
    with _fake_urlopen(bodies, captured):
        compile_stage3_structured_output(
            stage3_prose="# Stage 3\nApproved test plan prose.",
            referential_context=_REF,
            llm=_FakeLLM(),
            writer_tool=write_stage3_test_plan,
            artifact_path=run_context.artifact_path("stage3_test_plan.json"),
        )


def test_valid_stage3_response_writes_artifact():
    captured = []
    _run([_ollama_body(json.dumps(_plan()))], captured)
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert artifact["test_concepts"][0]["test_id"] == "RT-001"


def test_fenced_json_is_accepted():
    captured = []
    fenced = "```json\n" + json.dumps(_plan()) + "\n```"
    _run([_ollama_body(fenced)], captured)
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert artifact["test_concepts"][0]["test_id"] == "RT-001"


def test_pydantic_invalid_response_consumes_retry():
    """A syntactically valid JSON that omits a deeply required field
    (execution_techniques inside a test_concept) must fail schema
    validation, consume a retry, and then succeed."""
    captured = []
    bad_plan = _plan()
    del bad_plan["test_concepts"][0]["execution_techniques"]  # deeply nested required field
    bodies = [_ollama_body(json.dumps(bad_plan)), _ollama_body(json.dumps(_plan()))]
    _run(bodies, captured)
    assert len(captured) == 2
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert artifact["test_concepts"][0]["test_id"] == "RT-001"


def test_writer_rejection_feedback_appears_in_next_prompt():
    """A schema-valid plan that the deterministic WRITER rejects (duplicate
    test_id — a check the shallow writer actually performs) must feed that
    rejection into the next prompt. NOTE: identical success/abort criteria
    is NOT a writer-level rejection — that's caught later by the referential
    validate_stage3_test_plan gate, which this compiler does not run — so
    this uses a duplicate test_id, which write_stage3_test_plan does reject
    at write time."""
    captured = []
    dup_plan = _plan(concepts=[_concept(test_id="RT-001"), _concept(test_id="RT-001")])
    bodies = [
        _ollama_body(json.dumps(dup_plan)),
        _ollama_body(json.dumps(_plan())),
    ]
    _run(bodies, captured)
    assert len(captured) == 2
    assert "PREVIOUS OUTPUT WAS REJECTED" not in captured[0]
    assert "PREVIOUS OUTPUT WAS REJECTED" in captured[1]
    assert "duplicate test_id" in captured[1].lower()


def test_retry_exhaustion_leaves_no_artifact():
    import os
    captured = []
    bad_plan = _plan()
    del bad_plan["test_concepts"][0]["objective"]  # required field, always invalid
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        _run([_ollama_body(json.dumps(bad_plan))] * 3, captured)
    assert len(captured) == 3
    assert not os.path.exists(run_context.artifact_path("stage3_test_plan.json"))


def test_empty_response_consumes_retry():
    captured = []
    empty = {"done": True, "message": {"role": "assistant", "content": ""}}
    _run([empty, _ollama_body(json.dumps(_plan()))], captured)
    assert len(captured) == 2
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert artifact["test_concepts"][0]["test_id"] == "RT-001"


def test_compile_only_resume_migrates_legacy_unstamped_prose():
    """Regression: a compile-only resume of a run whose stage3.md predates
    prose stamping (written by an older pipeline, no run-isolation header)
    must MIGRATE it — preserving a .legacy_unstamped backup, stamping, and
    re-verifying — not fail. Reproduces the exact failure hit resuming
    vaf_20260714_165237: 'has no run-isolation header — refusing to trust
    an unstamped artifact.'"""
    import os
    stage3_path = run_context.artifact_path("stage3.md")
    os.makedirs(os.path.dirname(stage3_path), exist_ok=True)
    with open(stage3_path, "w") as f:
        f.write("# STAGE 3\n\n### RT-001 — Test\nProse without a header.\n")

    # Plain read_stamped_prose refuses the unstamped file.
    with pytest.raises(ValueError, match="no run-isolation header"):
        run_context.read_stamped_prose(stage3_path)

    # The migration helper migrates it: backup preserved, header added, read OK.
    body = run_context.read_or_migrate_legacy_stamped_prose(stage3_path)
    assert "RT-001" in body
    assert os.path.exists(stage3_path + ".legacy_unstamped"), "legacy backup not created"

    # Re-reading now succeeds directly (it's stamped for this run).
    assert "RT-001" in run_context.read_stamped_prose(stage3_path)


def test_legacy_migration_hard_fails_wrong_run_id():
    """A prose file whose header belongs to a DIFFERENT run must remain a
    hard failure — never migrated/rewritten. Cross-run contamination is
    not a legacy artifact."""
    import os
    stage3_path = run_context.artifact_path("stage3.md")
    os.makedirs(os.path.dirname(stage3_path), exist_ok=True)
    # Header for a different run than the active test-run.
    with open(stage3_path, "w") as f:
        f.write("<!-- run_id: vaf_SOMEONE_ELSE | corpus_hash: sha256:test "
                "| generated_at: 2026-01-01T00:00:00Z | schema_version: 1.0 -->\n"
                "# STAGE 3\nx\n")
    with pytest.raises(ValueError, match="belongs to run"):
        run_context.read_or_migrate_legacy_stamped_prose(stage3_path)
    # No backup should have been written on a non-legacy hard failure.
    assert not os.path.exists(stage3_path + ".legacy_unstamped")


def test_exact_test_plan_wrapper_is_unwrapped_and_accepted():
    """The model deterministically emits {"test_plan": {...}} despite the
    flat schema. The compiler must unwrap that exact single-key shape and
    accept the inner object (which still satisfies the full schema)."""
    captured = []
    wrapped = {"test_plan": _plan()}
    _run([_ollama_body(json.dumps(wrapped))], captured)
    assert len(captured) == 1  # accepted on first attempt, no retry needed
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert artifact["test_concepts"][0]["test_id"] == "RT-001"


def test_wrapper_with_invalid_inner_object_is_still_rejected_and_retried():
    """Unwrapping does not weaken the schema: a {"test_plan": {...}} whose
    INNER object is invalid (missing a required root key) must still fail
    validation, consume a retry, and then succeed on a clean attempt."""
    captured = []
    bad_inner = _plan()
    del bad_inner["plan_title"]  # inner object missing a required root key
    bodies = [
        _ollama_body(json.dumps({"test_plan": bad_inner})),
        _ollama_body(json.dumps(_plan())),
    ]
    _run(bodies, captured)
    assert len(captured) == 2  # first rejected, second accepted
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert artifact["test_concepts"][0]["test_id"] == "RT-001"


def test_retry_feedback_accumulates_across_attempts():
    """Regression for the lossy-feedback bug seen on vaf_20260714_165237:
    attempt 1 had 8 errors, attempt 2 fixed 7 (leaving one), attempt 3
    regressed to all 8 because feedback was REPLACED with only the latest
    error. Feedback must ACCUMULATE by field path, so attempt 3's prompt
    reminds the model of every prior constraint at once.

    Setup:
      attempt 1 -> schema_version + path_relationship errors
      attempt 2 -> those fixed, but a NEW forbidden field (approval_record)
      attempt 3 -> must be told about BOTH the old and new constraints,
                   then produces a clean plan that writes the artifact.
    """
    captured = []

    # Attempt 1: wrong schema_version (3) and wrong path_relationship spelling
    bad1 = _plan()
    bad1["schema_version"] = 3
    bad1["test_concepts"][0]["path_relationship"] = "Priority Path"

    # Attempt 2: schema_version + path fixed, but an extra forbidden field
    bad2 = _plan()
    bad2["assessment_safety_review"]["approval_record"] = "Approved by Safety Officer."

    # Attempt 3: fully valid
    good = _plan()

    bodies = [
        _ollama_body(json.dumps(bad1)),
        _ollama_body(json.dumps(bad2)),
        _ollama_body(json.dumps(good)),
    ]
    _run(bodies, captured)

    assert len(captured) == 3, "expected exactly three attempts"

    # Attempt 3's prompt must carry BOTH the attempt-1 field constraints
    # AND the attempt-2 constraint — the whole point of accumulation.
    p3 = captured[2]
    assert "schema_version" in p3, "attempt 3 lost the schema_version constraint"
    assert "path_relationship" in p3, "attempt 3 lost the path_relationship constraint"
    assert "approval_record" in p3, "attempt 3 lost the approval_record constraint"

    # And it ultimately wrote the artifact.
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage3_test_plan.json"))
    assert artifact["test_concepts"][0]["test_id"] == "RT-001"


def test_external_feedback_is_threaded_into_prompt():
    """The stage3_flow orchestrator passes deep-validation errors via
    external_feedback; they must appear in the compile prompt so the model
    fixes referential/path/safety issues from a prior rejected candidate."""
    captured = []
    with _fake_urlopen([_ollama_body(json.dumps(_plan()))], captured):
        compile_stage3_structured_output(
            stage3_prose="# Stage 3\nprose.",
            referential_context=_REF,
            llm=_FakeLLM(),
            writer_tool=write_stage3_test_plan,
            artifact_path=run_context.artifact_path("stage3_test_plan.json"),
            external_feedback="- RT-002 target CAPEC-628 is not on kcag_path.",
        )
    assert "DEEP VALIDATION REJECTED" in captured[0]
    assert "CAPEC-628 is not on kcag_path" in captured[0]
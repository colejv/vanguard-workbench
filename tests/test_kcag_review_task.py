"""
Tests for the read-only Quantitative KCAG Review commit:
build_kcag_review_task(), build_analysis_tasks(), and
finalize_kcag_review_artifact() in src/tasks.py.

The review is advisory in this version: it cannot mutate the Stage 2
graph, cannot block Annex B, and Annex B never receives it as CrewAI
context, so its prose can never influence the deterministic KCAG math.
What IS enforced is the artifact's existence and run/corpus identity
when the review was required to run.

Known limitation, documented in detail in build_kcag_review_task's own
docstring and tested explicitly below (test_review_task_tools_reflect_
crewai_fallback_not_true_isolation): CrewAI's own Task model
unconditionally falls back to the assigned agent's tools whenever a
task's own tools list is empty (crewai/task.py, check_tools()). Since
this task uses agent=modeler, and modeler owns kcag_min_cut and
bbn_threat_score, the task ends up with both tools available at runtime
regardless of the tools=[] passed to it -- confirmed directly against
the installed crewai version, not assumed. "Read-only" is enforced at
the prompt level for this task, not mechanically. A test asserting
task.tools == [] would be asserting something false about the real
object; the test below documents the actual, verified behavior instead.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import json

import pytest

from src import run_context
from src.agents import modeler
from src.tasks import (
    build_kcag_review_task,
    build_analysis_tasks,
    finalize_kcag_review_artifact,
)
from crewai import Task


VALID_GRAPH = {
    "nodes": [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ],
    "edges": [
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
    ],
}
VALID_REPORT = {"is_valid": True, "status": "PASS", "root": "ADV_START"}


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------

def test_review_task_requires_stage2_graph():
    with pytest.raises(ValueError, match="verified Stage 2 graph"):
        build_kcag_review_task("/tmp/x", stage2_graph={}, validation_report=VALID_REPORT)


def test_review_task_requires_validation_report():
    with pytest.raises(ValueError, match="deterministic validation report"):
        build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH, validation_report={})


def test_review_task_rejects_failed_validation_report():
    with pytest.raises(ValueError, match="failed deterministic validation"):
        build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH,
                               validation_report={"is_valid": False})


def test_review_task_uses_quantitative_modeler():
    t = build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH, validation_report=VALID_REPORT)
    assert t.agent is modeler
    assert t.agent.role == "Quantitative Threat Modeler"


def test_review_task_tools_reflect_crewai_fallback_not_true_isolation():
    """Documents the real, verified behavior rather than a false claim:
    tools=[] is passed at construction, but CrewAI's own Task model
    (check_tools validator) falls back to the agent's tools whenever the
    task's own tool list is empty. This is a framework-level constraint,
    not a bug in build_kcag_review_task -- confirmed by inspecting the
    installed crewai package directly, not assumed. "Read-only" for this
    task is a prompt-level instruction, not a mechanical restriction."""
    t = build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH, validation_report=VALID_REPORT)
    tool_names = {tool.name for tool in t.tools}
    assert tool_names == {"kcag_min_cut", "bbn_threat_score"}, (
        "if this ever fails because CrewAI stops doing this fallback, that's "
        "GOOD NEWS -- update this test's expectation, and consider whether "
        "tools=[] now actually achieves isolation."
    )


def test_review_task_has_no_live_context():
    t = build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH, validation_report=VALID_REPORT)
    assert not t.context


def test_review_task_is_not_human_input():
    t = build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH, validation_report=VALID_REPORT)
    assert t.human_input is False


def test_review_task_writes_model_assumptions():
    t = build_kcag_review_task("outputs/some-run", stage2_graph=VALID_GRAPH, validation_report=VALID_REPORT)
    assert t.output_file == "outputs/some-run/model_assumptions.md"


# ---------------------------------------------------------------------------
# Prompt-contract tests
# ---------------------------------------------------------------------------

def _review_description():
    t = build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH, validation_report=VALID_REPORT)
    return t.description.lower()


def test_review_prompt_prohibits_graph_mutation():
    d = _review_description()
    assert "must not add, remove, rewrite, repair, or reorder" in d


def test_review_prompt_prohibits_id_reverification():
    d = _review_description()
    assert "do not repeat framework-id verification" in d


def test_review_prompt_prohibits_networkx_recalculation():
    d = _review_description()
    assert "do not call kcag_min_cut or bbn_threat_score" in d
    assert "networkx" in d


def test_review_prompt_requires_exact_graph_ids():
    d = _review_description()
    assert "cite the exact node ids, edge endpoints, and vector ids" in d
    # Confirm the ACTUAL graph content is embedded, not just an instruction
    # to cite IDs in the abstract.
    assert '"adv_start"' in d


def test_review_prompt_requires_assumptions():
    d = _review_description()
    assert "state explicit assumptions and their basis" in d


def test_review_prompt_requires_limitations():
    d = _review_description()
    assert "what the graph's topology alone cannot establish" in d


def test_review_prompt_requires_disposition():
    d = _review_description()
    assert "accept with caveats" in d
    assert "recommend stage 2 regeneration" in d
    assert d.count("accept") >= 2  # ACCEPT and ACCEPT WITH CAVEATS both present


def test_review_prompt_calls_scores_heuristic():
    d = _review_description()
    assert "heuristic scores, not calibrated probabilities" in d or "heuristic score" in d


# ---------------------------------------------------------------------------
# Artifact tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    run_context.reset_active_run()
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.set_active_run("test-run", "sha256:test-corpus-hash", str(out_dir))
    yield out_dir
    run_context.reset_active_run()


def test_model_assumptions_artifact_is_stamped():
    path = run_context.artifact_path("model_assumptions.md")
    open(path, "w").write("# KCAG Quantitative Review\n\n## Review Disposition\n\nACCEPT\n")
    finalize_kcag_review_artifact(review_was_required=True)
    # stamp_prose_file prepends a header comment, not JSON -- verify via
    # read_stamped_prose, the same function finalize_kcag_review_artifact
    # itself uses to confirm the stamp.
    body = run_context.read_stamped_prose(path)
    assert "ACCEPT" in body


def test_model_assumptions_rejects_cross_run_read():
    path = run_context.artifact_path("model_assumptions.md")
    open(path, "w").write("# review\nACCEPT\n")
    run_context.stamp_prose_file(path)
    run_context.reset_active_run()
    run_context.set_active_run("different-run", "sha256:different-corpus",
                               str(path).rsplit("/", 1)[0])
    with pytest.raises(ValueError, match="belongs to run"):
        run_context.read_stamped_prose(path)


def test_missing_model_assumptions_fails_when_review_was_required():
    with pytest.raises(RuntimeError, match="did not produce"):
        finalize_kcag_review_artifact(review_was_required=True)


def test_finalize_is_noop_when_review_not_required():
    """When Annex B was already done on resume (review_was_required=False),
    finalize must not raise even though no model_assumptions.md exists --
    there was nothing to produce this invocation."""
    result = finalize_kcag_review_artifact(review_was_required=False)
    assert result is None


# ---------------------------------------------------------------------------
# Crew-order tests (build_analysis_tasks -- real production function)
# ---------------------------------------------------------------------------

def _dummy_task(name):
    return Task(description=name, expected_output="x", agent=modeler)


def test_review_precedes_annexb_when_annexb_not_done():
    t_review, t_b, t_c, t_s3 = (_dummy_task(n) for n in ("review", "b", "c", "s3"))
    tasks = build_analysis_tasks(t_kcag_review=t_review, t_annexB=t_b, t_annexC=t_c,
                                 t_stage3=t_s3, annexB_done=False, annexC_done=False)
    assert tasks.index(t_review) < tasks.index(t_b)
    assert t_review in tasks


def test_review_skipped_when_annexb_already_done():
    t_b, t_c, t_s3 = (_dummy_task(n) for n in ("b", "c", "s3"))
    tasks = build_analysis_tasks(t_kcag_review=None, t_annexB=t_b, t_annexC=t_c,
                                 t_stage3=t_s3, annexB_done=True, annexC_done=False)
    assert t_b not in tasks
    assert None not in tasks
    assert tasks == [t_c, t_s3]


def test_stage3_prose_task_included_when_prose_not_done():
    t_b, t_c, t_s3 = (_dummy_task(n) for n in ("b", "c", "s3"))
    tasks = build_analysis_tasks(t_kcag_review=None, t_annexB=t_b, t_annexC=t_c,
                                 t_stage3=t_s3, annexB_done=True, annexC_done=True,
                                 stage3_prose_done=False)
    assert t_s3 in tasks


def test_stage3_prose_task_skipped_when_prose_done():
    """When stage3.md already exists, its prose task must not be re-added
    to the crew — the structured plan is compiled separately outside the
    crew from the existing prose."""
    t_b, t_c, t_s3 = (_dummy_task(n) for n in ("b", "c", "s3"))
    tasks = build_analysis_tasks(t_kcag_review=None, t_annexB=t_b, t_annexC=t_c,
                                 t_stage3=t_s3, annexB_done=True, annexC_done=True,
                                 stage3_prose_done=True)
    assert t_s3 not in tasks
    assert tasks == []


def test_stage3_prose_done_defaults_to_included():
    """Backward-compatible default: omitting stage3_prose_done keeps the
    prose task in the list (fresh-run behavior)."""
    t_b, t_c, t_s3 = (_dummy_task(n) for n in ("b", "c", "s3"))
    tasks = build_analysis_tasks(t_kcag_review=None, t_annexB=t_b, t_annexC=t_c,
                                 t_stage3=t_s3, annexB_done=True, annexC_done=True)
    assert t_s3 in tasks


def test_review_does_not_replace_stage2_artifact():
    """Immutability: constructing the review task must never touch
    stage2_vectors.json -- the function only ever READS the two dicts
    passed to it, it never has a path to that file at all."""
    path = run_context.artifact_path("stage2_vectors.json")
    run_context.write_stamped_json(path, VALID_GRAPH)
    before = open(path, "rb").read()

    build_kcag_review_task("/tmp/x", stage2_graph=VALID_GRAPH, validation_report=VALID_REPORT)

    after = open(path, "rb").read()
    assert after == before


def test_review_does_not_change_stage2_status():
    """finalize_kcag_review_artifact never touches AssessmentState/
    StageStatus at all -- confirmed by signature (it doesn't even accept
    a state object) rather than by behavior alone."""
    import inspect
    params = inspect.signature(finalize_kcag_review_artifact).parameters
    assert "state" not in params, (
        "finalize_kcag_review_artifact must not be able to touch stage2's "
        "status -- it shouldn't even receive an AssessmentState to begin with"
    )
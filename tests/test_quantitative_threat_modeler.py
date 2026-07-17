"""
Tests for the Quantitative Threat Modeler upgrade (agents.py rename +
analytical-discipline prompt changes to t_annexB / t_annexC in tasks.py).

This is a role-clarity and prompt-discipline commit, not an architectural
one: the Python variable name (modeler), its tool list, task assignments,
and crew.py are all unchanged. Only role/goal/backstory (agents.py) and
the Annex B/C task descriptions (tasks.py) changed.

Terminology note: the original proposal's illustrative examples used
"[MODEL INPUT GAP]" as the bracketed tag for an untraceable required
input. I used "BLOCKING GAP" instead, matching the exact term already
used in agents.py's backstory ("a blocking gap you report") -- keeping
one consistent term across agents.py and tasks.py rather than
introducing a synonym. Tests below check for "blocking gap", not "model
input gap".

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
from src.agents import modeler
from src.tasks import build_tasks


def test_modeler_is_quantitative_threat_modeler():
    assert modeler.role == "Quantitative Threat Modeler"


def test_modeler_retains_quantitative_tools():
    tool_names = {tool.name for tool in modeler.tools}
    assert "kcag_min_cut" in tool_names
    assert "bbn_threat_score" in tool_names


def test_modeler_tool_set_does_not_expand_yet():
    """This first pass is role-clarity and prompt discipline only -- no
    new tool (e.g. a future validate_kcag) should be attached yet. This
    test is EXPECTED to need updating when that commit lands; that's the
    point of having it."""
    tool_names = {tool.name for tool in modeler.tools}
    assert tool_names == {"kcag_min_cut", "bbn_threat_score"}


def test_modeler_prohibits_invented_probabilities():
    """Checks the actual evaluated Agent object's goal/backstory strings,
    not raw source text -- Python's adjacent-string-literal concatenation
    only happens at parse/execution time, so a regex over the .py file's
    raw text would see the individual line fragments, not the real
    strings CrewAI actually receives."""
    text = f"{modeler.role} {modeler.goal} {modeler.backstory}".lower()
    assert "do not" in text
    assert "invent priors" in text
    assert "heuristic" in text
    assert "calibrated probability" in text


def test_modeler_does_not_claim_kcag_validation():
    """Explicit non-claim: this commit must not describe the agent as
    validating, correcting, or auditing graph SEMANTICS -- that capability
    doesn't exist yet (it's the next commit, validate_kcag). The agent may
    audit numerical INPUT provenance; it must not claim to audit or
    validate the graph itself."""
    text = f"{modeler.goal} {modeler.backstory}".lower()
    for overclaim in ("validate the graph", "validates the graph", "graph validation",
                       "semantic validation", "corrects the graph", "repairs the graph"):
        assert overclaim not in text, f"overclaims capability not yet implemented: {overclaim!r}"


def test_annexb_requires_tool_result_and_heuristic_language():
    tasks = build_tasks("/tmp/test-run")
    description = tasks["t_annexB"].description.lower()
    assert "do not author" in description
    assert "heuristic" in description
    assert "calibrated probability" in description


def test_annexc_requires_input_provenance():
    # The Annex C contract CHANGED: the modeler no longer AUTHORS the config
    # (that is now the derivation subsystem's job). It must instead score the
    # analyst-APPROVED config. This test enforces the new contract.
    tasks = build_tasks("/tmp/test-run")
    description = tasks["t_annexC"].description.lower()
    assert "approved" in description
    assert "annexc_assessment_config.json" in description
    assert "approved_config_path" in description
    assert "do not supply your own config" in description
    assert "do not author" in description or "do not author the per-assessment" in description


def test_annexb_task_still_assigned_to_modeler_with_unchanged_tools():
    """Confirms the non-negotiable "what should not change" list: task
    assignment and tool wiring are untouched, only the prompt text."""
    tasks = build_tasks("/tmp/test-run")
    assert tasks["t_annexB"].agent is modeler
    assert {t.name for t in tasks["t_annexB"].tools} == {"kcag_min_cut"}
    assert tasks["t_annexC"].agent is modeler
    assert {t.name for t in tasks["t_annexC"].tools} == {"bbn_threat_score"}


def test_annexb_annexc_context_chain_unchanged():
    """Confirms crew.py's resume-injection contract (built in an earlier
    commit) still holds: t_annexB depends on t_stage2, t_annexC depends
    on t_annexB, in a fresh (non-resumed) build."""
    tasks = build_tasks("/tmp/test-run")
    assert tasks["t_annexB"].context == [tasks["t_stage2"]]
    assert tasks["t_annexC"].context == [tasks["t_annexB"]]


def test_stage2_requires_chained_paths_through_declared_nodes():
    """Pins the Stage 2 KCAG-connectivity fix: ADV_START must be sole root,
    every declared node must be used in an edge, and vectors must route
    THROUGH identified components rather than a flat ADV_START->goal edge
    that merely mentions a technique. Regression guard for the
    vaf_20260714_155844 orphan-property-node defect (C-T-02/03/05 declared
    but never wired into the edge chain)."""
    tasks = build_tasks("/tmp/test-run")
    description = tasks["t_stage2"].description.lower()
    assert "sole entry node" in description
    assert "must be the source or target of at least one edge" in description
    assert "intermediate hop" in description
    assert "not a direct adv_start-to-goal edge" in description
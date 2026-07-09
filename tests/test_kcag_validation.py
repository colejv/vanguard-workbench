"""
Tests for validate_kcag() -- the deterministic KCAG structural gate.

Verifies graph structure and internal consistency (ADV_START as sole
root, goal reachability, no duplicate directed edges, valid enums) as a
SEPARATE, non-overlapping check from verify_stage2_vectors() (framework
technique-ID verification only). Neither gate mutates stage2_vectors.json
-- Annex B always reads the same original stamped artifact regardless of
which gates ran.

Discovery note: validate_kcag(), its crew.py wiring (running after
verify_stage2_vectors, before analysis_crew is constructed, with Stage 2
promoted to PASS only after both gates succeed), and the ADV_START
hardening in kcag_min_cut all already existed in the codebase before this
test file was written -- built during an earlier part of this session
that predates this file's own creation. This file is the first formal
pytest packaging of that already-implemented and already
(informally/manually) verified functionality, not a from-scratch build.
Every test below was run against the real, unmodified production
functions and independently re-verified here.

I have not seen this project's existing tests/ directory or its fixture
conventions -- this file uses plain pytest with no external fixtures, so
it should drop in cleanly, but import paths or naming may need a small
adjustment to match whatever conventions are already established there.
"""
import json

import pytest

from src import run_context
from src.tools import validate_kcag, kcag_min_cut


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    """Fresh run-scoped output directory per test."""
    run_context.reset_active_run()
    out_dir = tmp_path / "outputs" / "test-run"
    run_context.set_active_run(
        run_id="test-run",
        corpus_manifest_hash="sha256:test-corpus-hash",
        out_dir=str(out_dir),
    )
    yield out_dir
    run_context.reset_active_run()


def _write_graph(nodes, edges):
    """Write a stamped stage2_vectors.json under the active run and
    return the path, mirroring exactly what write_stage2_vectors() would
    produce."""
    path = run_context.artifact_path("stage2_vectors.json")
    run_context.write_stamped_json(path, {"nodes": nodes, "edges": edges})
    return path


def _valid_graph_data():
    """A minimal graph that should pass every check cleanly."""
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "N1", "difficulty": "LOW", "effect": "DISRUPT", "vec": "V-01"},
        {"source": "N1", "target": "G1", "difficulty": "MEDIUM", "effect": "DEGRADE", "vec": "V-02"},
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Core validity
# ---------------------------------------------------------------------------

def test_valid_kcag_passes():
    nodes, edges = _valid_graph_data()
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is True
    assert r["status"] == "PASS"
    assert r["root"] == "ADV_START"
    assert r["goals"] == ["G1"]
    assert r["reachable_goals"] == ["G1"]
    assert r["errors"] == []


def test_report_records_source_artifact_hash():
    nodes, edges = _valid_graph_data()
    path = _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["source_artifact"] == path
    assert r["source_artifact_sha256"] is not None
    assert r["source_artifact_sha256"].startswith("sha256:")
    # Confirm it's the REAL hash of the file, not a placeholder.
    import hashlib
    expected = "sha256:" + hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert r["source_artifact_sha256"] == expected


def test_missing_active_run_fails_closed():
    run_context.reset_active_run()
    with pytest.raises(RuntimeError, match="No active run set"):
        validate_kcag()


def test_cross_run_artifact_is_rejected():
    nodes, edges = _valid_graph_data()
    path = _write_graph(nodes, edges)  # stamped under "test-run"
    run_context.reset_active_run()
    run_context.set_active_run("different-run", "sha256:different-corpus",
                               str(path).rsplit("/", 1)[0])
    with pytest.raises(ValueError, match="belongs to run"):
        validate_kcag(path)


# ---------------------------------------------------------------------------
# Node integrity
# ---------------------------------------------------------------------------

def test_missing_adv_start_fails():
    nodes = [
        {"id": "NOT_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [{"source": "NOT_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("ADV_START" in e and "missing" in e.lower() for e in r["errors"])


def test_adv_start_wrong_type_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "technique", "criticality": 1},  # wrong type
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [{"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("privilege" in e for e in r["errors"])


def test_adv_start_with_incoming_edge_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "N1", "target": "ADV_START", "difficulty": "LOW", "effect": None, "vec": "V-01"},  # into ADV_START
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-02"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("incoming edges" in e for e in r["errors"])


def test_multiple_roots_fail():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "DECOY_ROOT", "node_type": "technique", "criticality": 3},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "DECOY_ROOT", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-02"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert "DECOY_ROOT" in r["roots"]
    assert any("sole root" in e for e in r["errors"])


def test_missing_goal_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
    ]
    edges = [{"source": "ADV_START", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("goal" in e.lower() for e in r["errors"])


def test_unreachable_goal_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
        {"id": "G2_UNREACHABLE", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "N1", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-02"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert "G2_UNREACHABLE" in r["unreachable_goals"]
    assert "G1" in r["reachable_goals"]


def test_unreachable_non_goal_node_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
        {"id": "ORPHAN", "node_type": "technique", "criticality": 2},
    ]
    edges = [
        {"source": "ADV_START", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "N1", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-02"},
        {"source": "ORPHAN", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-03"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    # ORPHAN itself has an incoming-edge count of 0 too, so it would also
    # register as an extra root -- confirm it's flagged as unreachable
    # (the specific error text may come from either check, both correctly fail).
    assert "ORPHAN" in r["unreachable_nodes"] or "ORPHAN" in r["roots"]


def test_goal_with_outgoing_edge_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
        {"id": "N1", "node_type": "technique", "criticality": 5},
    ]
    edges = [
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "G1", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-02"},  # goal has outgoing edge
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("terminal" in e.lower() for e in r["errors"])


def test_duplicate_node_id_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
        {"id": "G1", "node_type": "goal", "criticality": 5},  # duplicate
    ]
    edges = [{"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("duplicate node" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# Edge integrity
# ---------------------------------------------------------------------------

def test_unknown_edge_source_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [{"source": "GHOST", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("source" in e and "undeclared" in e for e in r["errors"])


def test_unknown_edge_target_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [{"source": "ADV_START", "target": "GHOST", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("target" in e and "undeclared" in e for e in r["errors"])


def test_duplicate_directed_edge_fails():
    """The exact concern nx.DiGraph itself can't catch -- two edges with
    the same (source, target) pair would silently collapse into one edge
    if loaded straight into a DiGraph. This check must run against the
    RAW edge list before graph construction."""
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "ADV_START", "target": "G1", "difficulty": "HIGH", "effect": None, "vec": "V-02"},  # dup pair
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("duplicate directed edge" in e.lower() for e in r["errors"])


def test_self_loop_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "N1", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-02"},  # self-loop
        {"source": "N1", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-03"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert "N1" in r["self_loops"]


def test_invalid_node_type_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "objective", "criticality": 10},  # invalid type
    ]
    edges = [{"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("invalid node_type" in e for e in r["errors"])


def test_invalid_criticality_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 99},  # out of 1-10 range
    ]
    edges = [{"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("criticality" in e for e in r["errors"])


def test_invalid_difficulty_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [{"source": "ADV_START", "target": "G1", "difficulty": "IMPOSSIBLE", "effect": None, "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("difficulty" in e for e in r["errors"])


def test_invalid_effect_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [{"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": "OBLITERATE", "vec": "V-01"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("effect" in e for e in r["errors"])


def test_invalid_vector_id_fails():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [{"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "not-a-vec-id"}]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is False
    assert any("vec" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# Warnings (do not fail the graph)
# ---------------------------------------------------------------------------

def test_cycle_is_reported_but_does_not_fail():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "N1", "node_type": "technique", "criticality": 5},
        {"id": "N2", "node_type": "technique", "criticality": 5},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "N1", "target": "N2", "difficulty": "LOW", "effect": None, "vec": "V-02"},
        {"source": "N2", "target": "N1", "difficulty": "LOW", "effect": None, "vec": "V-03"},  # cycle N1<->N2
        {"source": "N1", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-04"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is True, f"a cycle alone must not fail the graph: {r['errors']}"
    assert len(r["cycles"]) > 0
    assert any("cycle" in w.lower() for w in r["warnings"])


def test_non_goal_sink_is_warning():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "DEAD_END", "node_type": "technique", "criticality": 3},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "DEAD_END", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-02"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is True, f"a dead end alone must not fail the graph: {r['errors']}"
    assert "DEAD_END" in r["dead_end_nodes"]
    assert any("sink" in w.lower() for w in r["warnings"])


def test_countermeasure_dead_end_is_warning():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "CM1", "node_type": "countermeasure", "criticality": 2},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "CM1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-02"},
    ]
    _write_graph(nodes, edges)
    r = validate_kcag()
    assert r["is_valid"] is True, f"an isolated countermeasure alone must not fail the graph: {r['errors']}"
    assert len(r["countermeasure_warnings"]) > 0
    assert any("CM1" in w for w in r["countermeasure_warnings"])


def test_validation_report_is_run_stamped():
    nodes, edges = _valid_graph_data()
    _write_graph(nodes, edges)
    r = validate_kcag()
    report_path = run_context.artifact_path("kcag_validation.json")
    run_context.write_stamped_json(report_path, r)
    envelope = json.loads(open(report_path).read())
    assert envelope["_meta"]["run_id"] == "test-run"
    assert envelope["_meta"]["corpus_manifest_hash"] == "sha256:test-corpus-hash"
    assert envelope["data"]["is_valid"] is True


# ---------------------------------------------------------------------------
# kcag_min_cut regression: adversarial node ordering
# ---------------------------------------------------------------------------

def test_kcag_min_cut_rejects_decoy_root_regardless_of_insertion_order():
    """Direct regression test for the sources[0] non-determinism concern:
    deliberately place a decoy zero-indegree node BEFORE ADV_START in the
    node list. The tool must reject the graph (via its own defense-in-depth
    check) rather than silently picking whichever root happened to be
    inserted first."""
    nodes = [
        {"id": "DECOY_ROOT", "node_type": "technique", "criticality": 3},  # inserted FIRST
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "DECOY_ROOT", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-01"},
        {"source": "ADV_START", "target": "G1", "difficulty": "LOW", "effect": None, "vec": "V-02"},
    ]
    _write_graph(nodes, edges)
    result = kcag_min_cut._run()
    assert isinstance(result, str)
    assert result.startswith("ERROR:")
    assert "DECOY_ROOT" in result or "sole" in result.lower()
"""
Tests for the Stage 2 vec-placeholder fix: the live-run failure where Gemma
copied the instruction's 'V-NN' notation as literal data for every edge, and
"exactly once" prevented repair after rejection.
"""
import pytest
from src import run_context
from src.tools import write_stage2_vectors
from src.tasks import build_tasks


def _valid_nodes():
    return [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 10},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]


def _valid_edge(vec):
    return {"source": "ADV_START", "target": "G1", "technique": "T1078",
            "difficulty": "HIGH", "effect": "DECEIVE", "vec": vec}


@pytest.fixture(autouse=True)
def _run(tmp_path):
    run_context.reset_active_run()
    run_context.set_active_run("test-run", "sha256:x", str(tmp_path))
    yield
    run_context.reset_active_run()


def test_stage2_prompt_never_uses_bare_vec_placeholder():
    tasks = build_tasks("/tmp/test-run")
    description = tasks["t_stage2"].description
    assert "vec (V-NN)" not in description
    assert "you MUST call `write_stage2_vectors` exactly once" not in description
    assert "V-01" in description and "V-02" in description
    assert "Never emit the literal placeholders" in description


def test_stage2_prompt_requires_retry_until_written():
    tasks = build_tasks("/tmp/test-run")
    description = tasks["t_stage2"].description
    assert "REJECTED" in description
    assert "WRITTEN:" in description
    assert "at most 3 write attempts" in description


def test_writer_rejects_literal_vec_placeholder_actionably():
    result = write_stage2_vectors.func(
        nodes=_valid_nodes(),
        edges=[_valid_edge("V-NN"), _valid_edge("V-NN")],
    )
    assert result.startswith("REJECTED:")
    assert "placeholder" in result.lower()
    assert "V-01" in result and "V-02" in result
    path = run_context.artifact_path("stage2_vectors.json")
    import os
    assert not os.path.exists(path)


def test_writer_rejects_all_six_edge_placeholder_case_with_sequenced_fix():
    """The exact scenario from the live run: 6 edges, all vec='V-NN'."""
    nodes = _valid_nodes() + [{"id": "G2", "node_type": "goal", "criticality": 9}]
    edges = [_valid_edge("V-NN") for _ in range(6)]
    result = write_stage2_vectors.func(nodes=nodes, edges=edges)
    assert result.startswith("REJECTED:")
    assert "All 6 of 6" in result
    for i in range(1, 7):
        assert f"V-{i:02d}" in result


def test_writer_accepts_unique_canonical_vec_ids():
    result = write_stage2_vectors.func(
        nodes=_valid_nodes(), edges=[_valid_edge("V-01")],
    )
    assert result.startswith("WRITTEN:")


def test_writer_still_catches_v1_v01_collision_after_normalization():
    """The pre-existing normalization-collision check must still work --
    the placeholder check must not have displaced it."""
    nodes = _valid_nodes() + [{"id": "G2", "node_type": "goal", "criticality": 9}]
    edges = [_valid_edge("V-1"), {**_valid_edge("V-01"), "target": "G2"}]
    result = write_stage2_vectors.func(nodes=nodes, edges=edges)
    assert result.startswith("REJECTED:")
    assert "duplicate vec" in result.lower()


def test_other_placeholder_variants_also_rejected():
    for placeholder in ("V-N", "V-XX", "V-00"):
        result = write_stage2_vectors.func(
            nodes=_valid_nodes(), edges=[_valid_edge(placeholder)],
        )
        assert result.startswith("REJECTED:"), f"{placeholder} should be rejected"
        assert "placeholder" in result.lower()


# ---- unused-declared-node rejection (16-node/9-unused live-run failure) ----

def test_writer_rejects_unused_declared_node():
    """Reproduces the live-run failure: a node declared in `nodes` but never
    used as an edge source/target must be rejected -- otherwise it becomes
    an extra root AND dead end that only the deeper KCAG gate would catch."""
    nodes = _valid_nodes() + [
        {"id": "C-UNUSED", "node_type": "property", "criticality": 5},
    ]
    result = write_stage2_vectors.func(nodes=nodes, edges=[_valid_edge("V-01")])
    assert result.startswith("REJECTED"), result
    assert "declared node(s) are unused" in result
    assert "C-UNUSED" in result
    assert "remove" in result.lower()
    assert "connected by an edge" in result
    import os
    path = run_context.artifact_path("stage2_vectors.json")
    assert not os.path.exists(path)


def test_writer_rejects_all_nine_unused_nodes_from_live_run():
    """The exact live-run shape: 16 declared nodes, only 7 incident to the
    6 real edges; 9 nodes copied wholesale from Stage 1 and never used."""
    used = ["ADV_START", "C-T-02", "C-T-05", "C-P-03",
            "G_OP_BIAS", "G_FORCE_POSTURE", "G_DATA_POISONING"]
    unused = ["C-T-01", "C-T-03", "C-T-04", "C-P-01", "C-P-02",
              "C-C-01", "C-C-02", "C-C-03", "C-C-04"]
    nodes = []
    for nid in used + unused:
        nt = "goal" if nid.startswith("G_") else ("privilege" if nid == "ADV_START" else "property")
        nodes.append({"id": nid, "node_type": nt, "criticality": 8})
    edges = [
        {"source": "ADV_START", "target": "C-T-02", "technique": "AML.T0080",
         "difficulty": "HIGH", "effect": "DECEIVE", "vec": "V-01"},
        {"source": "C-T-02", "target": "G_OP_BIAS", "technique": "CAPEC-271",
         "difficulty": "MEDIUM", "effect": "DECEIVE", "vec": "V-02"},
        {"source": "ADV_START", "target": "C-T-05", "technique": "T0857",
         "difficulty": "HIGH", "effect": "DESTROY", "vec": "V-03"},
        {"source": "C-T-05", "target": "G_FORCE_POSTURE", "technique": "EX-0010.03",
         "difficulty": "MEDIUM", "effect": "DISRUPT", "vec": "V-04"},
        {"source": "ADV_START", "target": "C-P-03", "technique": "T1565",
         "difficulty": "HIGH", "effect": "DEGRADE", "vec": "V-05"},
        {"source": "C-P-03", "target": "G_DATA_POISONING", "technique": "AML.T0020",
         "difficulty": "MEDIUM", "effect": "DECEIVE", "vec": "V-06"},
    ]
    result = write_stage2_vectors.func(nodes=nodes, edges=edges)
    assert result.startswith("REJECTED"), result
    for nid in unused:
        assert nid in result
    unused_clause = result.split("unused and must either be removed or connected by an edge: ")[1]
    for nid in used:
        assert nid not in unused_clause


def test_writer_accepts_when_every_node_is_incident():
    result = write_stage2_vectors.func(nodes=_valid_nodes(), edges=[_valid_edge("V-01")])
    assert result.startswith("WRITTEN"), result


def test_writer_accepts_connected_intermediate_node():
    nodes = [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 10},
        {"id": "C-T-02", "node_type": "property", "criticality": 9},
        {"id": "G1", "node_type": "goal", "criticality": 10},
    ]
    edges = [
        {"source": "ADV_START", "target": "C-T-02", "technique": "AML.T0080",
         "difficulty": "HIGH", "effect": "DECEIVE", "vec": "V-01"},
        {"source": "C-T-02", "target": "G1", "technique": "AML.T0080",
         "difficulty": "HIGH", "effect": "DECEIVE", "vec": "V-02"},
    ]
    result = write_stage2_vectors.func(nodes=nodes, edges=edges)
    assert result.startswith("WRITTEN"), result


def test_stage2_prompt_forbids_copying_full_stage1_inventory():
    tasks = build_tasks("/tmp/test-run")
    description = tasks["t_stage2"].description
    assert "Declare ONLY nodes that are used by the final edge list" in description
    assert "Do not copy the complete Stage 1 component inventory" in description
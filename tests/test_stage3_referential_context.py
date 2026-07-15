"""
Tests for build_referential_context (src/stage3_writer.py) — the rich,
structural referential context (edges + approved_paths) that replaces the
old flat ID lists, so the compiler can build path-consistent concepts.
"""
import json

from src.stage3_writer import build_referential_context


_STAGE2 = {
    "nodes": [
        {"criticality": 10, "id": "ADV_START", "node_type": "privilege"},
        {"criticality": 9, "id": "AML.T0080", "node_type": "technique"},
        {"criticality": 10, "id": "CAPEC-628", "node_type": "technique"},
        {"criticality": 8, "id": "AML.T0099", "node_type": "technique"},
        {"criticality": 10, "id": "G_FIRES_WRONG", "node_type": "goal"},
        {"criticality": 10, "id": "G_CDL_ALL", "node_type": "goal"},
    ],
    "edges": [
        {"source": "ADV_START", "target": "AML.T0080", "technique": "AML.T0080", "vec": "V-01"},
        {"source": "ADV_START", "target": "CAPEC-628", "technique": "CAPEC-628", "vec": "V-02"},
        {"source": "ADV_START", "target": "AML.T0099", "technique": "AML.T0099", "vec": "V-03"},
        {"source": "AML.T0080", "target": "G_FIRES_WRONG", "technique": "AML.T0080", "vec": "V-04"},
        {"source": "CAPEC-628", "target": "G_CDL_ALL", "technique": "CAPEC-628", "vec": "V-05"},
    ],
}

_KCAG = {
    "priority_path": {"path": ["ADV_START", "CAPEC-628", "G_CDL_ALL"], "score": 0.9},
    "top_paths": [
        {"path": ["ADV_START", "CAPEC-628", "G_CDL_ALL"], "score": 0.9},
        {"path": ["ADV_START", "AML.T0080", "G_FIRES_WRONG"], "score": 0.7},
    ],
    "minimum_cut": {"aggregate_cut_nodes": ["ADV_START"]},
}


def _ctx():
    return json.loads(build_referential_context(stage2_vectors=_STAGE2, kcag_report=_KCAG))


def test_edges_are_exposed_structurally():
    ctx = _ctx()
    assert "edges" in ctx
    v02 = next(e for e in ctx["edges"] if e["vec"] == "V-02")
    assert v02["source"] == "ADV_START"
    assert v02["target"] == "CAPEC-628"
    assert v02["technique_id"] == "CAPEC-628"


def test_all_edges_present_and_sorted_by_vec():
    ctx = _ctx()
    vecs = [e["vec"] for e in ctx["edges"]]
    assert vecs == ["V-01", "V-02", "V-03", "V-04", "V-05"]


def test_approved_paths_are_ordered_node_sequences():
    ctx = _ctx()
    assert ["ADV_START", "CAPEC-628", "G_CDL_ALL"] in ctx["approved_paths"]
    assert ["ADV_START", "AML.T0080", "G_FIRES_WRONG"] in ctx["approved_paths"]


def test_priority_path_is_first_approved_path():
    ctx = _ctx()
    assert ctx["approved_paths"][0] == ["ADV_START", "CAPEC-628", "G_CDL_ALL"]


def test_approved_paths_deduplicated():
    # priority_path duplicates top_paths[0]; must appear once.
    ctx = _ctx()
    count = ctx["approved_paths"].count(["ADV_START", "CAPEC-628", "G_CDL_ALL"])
    assert count == 1


def test_path_consistency_is_derivable_from_context():
    """The whole point: from the context, one can verify that testing
    CAPEC-628 requires path [ADV_START, CAPEC-628, G_CDL_ALL] via edges
    V-02 then V-05 — the info the model previously lacked."""
    ctx = _ctx()
    path = ["ADV_START", "CAPEC-628", "G_CDL_ALL"]
    assert path in ctx["approved_paths"]
    # Every consecutive node pair must have an edge in the context.
    edges_by_pair = {(e["source"], e["target"]): e["vec"] for e in ctx["edges"]}
    assert edges_by_pair[("ADV_START", "CAPEC-628")] == "V-02"
    assert edges_by_pair[("CAPEC-628", "G_CDL_ALL")] == "V-05"


def test_technique_and_node_ids_present():
    ctx = _ctx()
    assert set(ctx["valid_technique_ids"]) == {"AML.T0080", "AML.T0099", "CAPEC-628"}
    assert "CAPEC-628" in ctx["valid_graph_node_ids"]


def test_handles_priority_path_as_bare_list():
    kcag = {"priority_path": ["ADV_START", "G_CDL_ALL"], "top_paths": []}
    ctx = json.loads(build_referential_context(stage2_vectors=_STAGE2, kcag_report=kcag))
    assert ctx["approved_paths"] == [["ADV_START", "G_CDL_ALL"]]


def test_handles_empty_kcag_gracefully():
    ctx = json.loads(build_referential_context(stage2_vectors=_STAGE2, kcag_report={}))
    assert ctx["approved_paths"] == []
    assert len(ctx["edges"]) == 5  # edges still come from stage2
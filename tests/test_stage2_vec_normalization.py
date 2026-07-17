"""
Tests for single-digit vec ID normalization in write_stage2_vectors
(V-1 -> V-01), reconciling model output against the canonical
KCAG_VECTOR_ID_PATTERN (^V-\\d{2,}$).

The normalization is deliberately narrow: it only zero-pads the exact
pattern V-<one digit>. Already-canonical, multi-digit, and malformed
values pass through unchanged so they are still validated/rejected
downstream exactly as before. Because normalization can CREATE a
collision (both V-1 and V-01 become V-01), duplicate-vec detection runs
on the normalized values.
"""
import json

import pytest

from src import run_context
from src.tools import write_stage2_vectors, normalize_vec_id
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_active_run(tmp_path):
    run_context.reset_active_run()
    run_context.set_active_run("test-run", "sha256:test", str(tmp_path / "out"))
    yield
    run_context.reset_active_run()


def _nodes():
    return [
        {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
        {"id": "G1", "node_type": "goal", "criticality": 10},
        {"id": "N1", "node_type": "technique", "criticality": 5},
    ]


def _edge(vec, source="ADV_START", target="G1"):
    return {"source": source, "target": target, "technique": "T1078",
            "difficulty": "LOW", "effect": None, "vec": vec}


def _written_vecs():
    artifact = run_context.read_stamped_json(run_context.artifact_path("stage2_vectors.json"))
    return [e["vec"] for e in artifact["edges"]]

def _writer_status():
    return run_context.read_stamped_json(
        run_context.artifact_path(
            "stage2_writer_status.json"
        )
    )

# ---- normalize_vec_id unit tests ----

def test_normalize_v_1_to_v_01():
    assert normalize_vec_id("V-1") == "V-01"


def test_normalize_v_9_to_v_09():
    assert normalize_vec_id("V-9") == "V-09"


def test_preserves_v_10():
    assert normalize_vec_id("V-10") == "V-10"


def test_preserves_v_01():
    assert normalize_vec_id("V-01") == "V-01"


def test_preserves_v_001():
    assert normalize_vec_id("V-001") == "V-001"


def test_preserves_non_numeric():
    # Malformed values are left untouched (to be rejected downstream)
    assert normalize_vec_id("VEC1") == "VEC1"
    assert normalize_vec_id("V-") == "V-"
    assert normalize_vec_id("") == ""


# ---- write_stage2_vectors integration tests ----

def test_stage2_writer_normalizes_v_1_to_v_01():
    result = write_stage2_vectors.func(
        nodes=_nodes(),
        edges=[_edge("V-1", target="N1"), _edge("V-2", source="N1")],
    )
    assert result.startswith("WRITTEN"), result
    assert _written_vecs() == ["V-01", "V-02"]


def test_stage2_writer_normalizes_v_9_to_v_09():
    result = write_stage2_vectors.func(
        nodes=_nodes(), edges=[_edge("V-9", target="N1"), _edge("V-8", source="N1")],
    )
    assert result.startswith("WRITTEN"), result
    assert set(_written_vecs()) == {"V-09", "V-08"}


def test_stage2_writer_preserves_v_10():
    result = write_stage2_vectors.func(
        nodes=_nodes(), edges=[_edge("V-10", target="N1"), _edge("V-11", source="N1")],
    )
    assert result.startswith("WRITTEN"), result
    assert set(_written_vecs()) == {"V-10", "V-11"}


def test_stage2_writer_preserves_v_001():
    result = write_stage2_vectors.func(
        nodes=_nodes(), edges=[_edge("V-001", target="N1"), _edge("V-002", source="N1")],
    )
    assert result.startswith("WRITTEN"), result
    assert set(_written_vecs()) == {"V-001", "V-002"}


def test_stage2_writer_rejects_collision_after_vec_normalization():
    # V-1 normalizes to V-01, colliding with an explicit V-01 in the same payload
    result = write_stage2_vectors.func(
        nodes=_nodes(), edges=[_edge("V-1", target="N1"), _edge("V-01", source="N1")],
    )
    assert result.startswith("REJECTED"), result
    assert "duplicate vec 'V-01'" in result
    assert "normalization" in result


def test_stage2_artifact_contains_only_canonical_vec_ids():
    write_stage2_vectors.func(
        nodes=_nodes(),
        edges=[_edge("V-1", target="N1"), _edge("V-2", source="N1")],
    )
    import re
    pattern = re.compile(r"^V-\d{2,}$")
    for vec in _written_vecs():
        assert pattern.fullmatch(vec), f"non-canonical vec written: {vec}"

def test_stage2_writer_rejects_literal_vec_placeholder():
    result = write_stage2_vectors.func(
        nodes=_nodes(),
        edges=[
            _edge(
                "V-NN",
                source="ADV_START",
                target="G1",
            )
        ],
    )

    assert result.startswith("REJECTED"), result
    assert "placeholder vec value" in result
    assert "All 1 of 1 edge(s)" in result
    assert "edge[0] = V-01" in result
    assert "call write_stage2_vectors again" in result

    artifact_path = Path(
        run_context.artifact_path("stage2_vectors.json")
    )
    assert not artifact_path.exists()


def test_stage2_writer_rejects_missing_difficulty():
    edge = _edge(
        "V-01",
        source="ADV_START",
        target="G1",
    )
    del edge["difficulty"]

    result = write_stage2_vectors.func(
        nodes=_nodes(),
        edges=[edge],
    )

    assert result.startswith("REJECTED"), result
    assert "missing required field(s): difficulty" in result

    artifact_path = Path(
        run_context.artifact_path("stage2_vectors.json")
    )
    assert not artifact_path.exists()


def test_stage2_writer_rejects_missing_vec():
    edge = _edge(
        "V-01",
        source="ADV_START",
        target="G1",
    )
    del edge["vec"]

    result = write_stage2_vectors.func(
        nodes=_nodes(),
        edges=[edge],
    )

    assert result.startswith("REJECTED"), result
    assert "missing required field(s): vec" in result

    artifact_path = Path(
        run_context.artifact_path("stage2_vectors.json")
    )
    assert not artifact_path.exists()


def test_stage2_writer_rejects_invalid_vec_format():
    result = write_stage2_vectors.func(
        nodes=_nodes(),
        edges=[
            _edge(
                "VECTOR-1",
                source="ADV_START",
                target="G1",
            )
        ],
    )

    assert result.startswith("REJECTED"), result
    assert "concrete vector ID" in result
    assert "VECTOR-1" in result


def test_stage2_writer_accepts_complete_canonical_edge():
    result = write_stage2_vectors.func(
        nodes=[
            {"id": "ADV_START", "node_type": "privilege", "criticality": 1},
            {"id": "G1", "node_type": "goal", "criticality": 10},
        ],
        edges=[
            _edge(
                "V-01",
                source="ADV_START",
                target="G1",
            )
        ],
    )

    assert result.startswith("WRITTEN"), result

    assert result.startswith("WRITTEN"), result

    artifact = run_context.read_stamped_json(
        run_context.artifact_path("stage2_vectors.json")
    )
    assert artifact["edges"][0]["difficulty"] == "LOW"
    assert artifact["edges"][0]["vec"] == "V-01"
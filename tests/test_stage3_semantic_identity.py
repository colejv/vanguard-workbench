"""
Acceptance tests for semantic-identity immutability (src/stage3_identity.py)
and prose<->JSON technique consistency (src/stage3_validation.py).

These directly encode the RT-003 failure the review identified: the repair
loop changed AML.T0099 -> CAPEC-628 to force a KCAG path, and the mutated
plan passed every validator. The machinery must now REFUSE that, not repair
around it.
"""
import pytest

from src.stage3_identity import (
    capture_identity_baseline, assert_identity_preserved,
    concept_identity, SemanticIdentityMutation,
)
from src.stage3_validation import check_stage3_artifact_consistency


def _rt003(technique="AML.T0099", vector="V-03", target="AML.T0099", cats=(1, 4)):
    return {
        "test_id": "RT-003", "categories": list(cats),
        "target_node_ids": [target], "stage2_vector_ids": [vector],
        "execution_techniques": [{"technique_id": technique, "vector_id": vector, "rationale": "x"}],
    }


# ---- Semantic identity ----

def test_technique_swap_during_repair_is_mutation():
    """AML.T0099 -> CAPEC-628 during repair FAILS: SEMANTIC_IDENTITY_MUTATION."""
    baseline = capture_identity_baseline({"test_concepts": [_rt003()]})
    repaired = {"test_concepts": [_rt003(technique="CAPEC-628", vector="V-02", target="CAPEC-628")]}
    with pytest.raises(SemanticIdentityMutation, match="SEMANTIC_IDENTITY_MUTATION"):
        assert_identity_preserved(baseline, repaired)


def test_technique_swap_names_the_concept_and_change():
    baseline = capture_identity_baseline({"test_concepts": [_rt003()]})
    repaired = {"test_concepts": [_rt003(technique="CAPEC-628", vector="V-02", target="CAPEC-628")]}
    with pytest.raises(SemanticIdentityMutation) as exc:
        assert_identity_preserved(baseline, repaired)
    msg = str(exc.value)
    assert "RT-003" in msg
    assert "AML.T0099" in msg and "CAPEC-628" in msg


def test_category_change_during_repair_is_mutation():
    baseline = capture_identity_baseline({"test_concepts": [_rt003(cats=(1, 4))]})
    repaired = {"test_concepts": [_rt003(cats=(3, 4))]}
    with pytest.raises(SemanticIdentityMutation, match="categories"):
        assert_identity_preserved(baseline, repaired)


def test_dropping_a_concept_during_repair_is_mutation():
    baseline = capture_identity_baseline({"test_concepts": [_rt003(), {"test_id": "RT-001", "categories": [4]}]})
    repaired = {"test_concepts": [_rt003()]}  # RT-001 dropped
    with pytest.raises(SemanticIdentityMutation, match="RT-001 was dropped"):
        assert_identity_preserved(baseline, repaired)


def test_adding_a_concept_during_repair_is_mutation():
    baseline = capture_identity_baseline({"test_concepts": [_rt003()]})
    repaired = {"test_concepts": [_rt003(), {"test_id": "RT-009", "categories": [4],
                                            "execution_techniques": [{"technique_id": "T1078"}]}]}
    with pytest.raises(SemanticIdentityMutation, match="RT-009 was added"):
        assert_identity_preserved(baseline, repaired)


def test_repair_adding_telemetry_preserves_identity():
    """Repair fills a missing field without touching identity -> PASS."""
    baseline = capture_identity_baseline({"test_concepts": [_rt003()]})
    c = _rt003()
    c["telemetry_requirements"] = ["memory access logs"]
    assert_identity_preserved(baseline, {"test_concepts": [c]})  # no raise


def test_reordering_only_preserves_identity():
    """Whitespace/ordering-only change -> PASS (identity is sorted)."""
    baseline = capture_identity_baseline({"test_concepts": [
        {"test_id": "RT-003", "categories": [4, 1], "target_node_ids": ["AML.T0099"],
         "stage2_vector_ids": ["V-03"],
         "execution_techniques": [{"technique_id": "AML.T0099", "vector_id": "V-03"}]}]})
    reordered = {"test_concepts": [
        {"test_id": "RT-003", "categories": [1, 4], "target_node_ids": ["AML.T0099"],
         "stage2_vector_ids": ["V-03"],
         "execution_techniques": [{"technique_id": "AML.T0099", "vector_id": "V-03"}]}]}
    assert_identity_preserved(baseline, reordered)  # no raise


# ---- prose <-> JSON technique consistency ----

def test_prose_json_technique_mismatch_fails():
    prose = "### RT-003 — Tool Data Poisoning\nUses AML.T0099 against the Inventory tool.\nCategory: 1, 4\n"
    plan = {"test_concepts": [{"test_id": "RT-003", "categories": [1, 4],
            "execution_techniques": [{"technique_id": "CAPEC-628", "vector_id": "V-02"}]}]}
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert r["is_consistent"] is False
    assert any(e["code"] == "PROSE_JSON_TECHNIQUE_MISMATCH" for e in r["errors"])


def test_prose_json_technique_agreement_passes():
    prose = "### RT-003 — Tool Data Poisoning\nUses AML.T0099 against the Inventory tool.\nCategory: 1, 4\n"
    plan = {"test_concepts": [{"test_id": "RT-003", "categories": [1, 4],
            "execution_techniques": [{"technique_id": "AML.T0099", "vector_id": "V-03"}]}]}
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert not any(e["code"] == "PROSE_JSON_TECHNIQUE_MISMATCH" for e in r["errors"])


def test_prose_without_technique_ids_is_not_a_mismatch():
    # Absent prose technique mention is a documentation concern, not a
    # contradiction — no PROSE_JSON_TECHNIQUE_MISMATCH raised.
    prose = "### RT-003 — Tool Data Poisoning\nSome description with no framework ID.\nCategory: 1, 4\n"
    plan = {"test_concepts": [{"test_id": "RT-003", "categories": [1, 4],
            "execution_techniques": [{"technique_id": "AML.T0099", "vector_id": "V-03"}]}]}
    r = check_stage3_artifact_consistency(stage3_text=prose, test_plan=plan)
    assert not any(e["code"] == "PROSE_JSON_TECHNIQUE_MISMATCH" for e in r["errors"])


def test_baseline_survives_resume(tmp_path):
    """The persisted baseline must survive resume: a resumed process whose
    FIRST candidate is already mutated must load the original baseline, not
    recapture from the mutated candidate."""
    from src.stage3_identity import load_or_capture_baseline

    import json as _json
    bpath = str(tmp_path / "baseline.json")
    def _read(p):
        with open(p) as f: return _json.load(f)
    def _write(p, v):
        with open(p, "w") as f: _json.dump(v, f)

    correct = {"test_concepts": [_rt003(technique="AML.T0099")]}
    b1 = load_or_capture_baseline(plan=correct, baseline_path=bpath,
                                  read_stamped_json=_read, write_stamped_json=_write)
    assert b1["RT-003"]["technique_ids"] == ["AML.T0099"]

    # Resume: first candidate seen is already swapped to CAPEC-628.
    mutated = {"test_concepts": [_rt003(technique="CAPEC-628", vector="V-02", target="CAPEC-628")]}
    b2 = load_or_capture_baseline(plan=mutated, baseline_path=bpath,
                                  read_stamped_json=_read, write_stamped_json=_write)
    # Loaded the persisted baseline, NOT recaptured from the mutated candidate.
    assert b2["RT-003"]["technique_ids"] == ["AML.T0099"]
    with pytest.raises(SemanticIdentityMutation):
        assert_identity_preserved(b2, mutated)
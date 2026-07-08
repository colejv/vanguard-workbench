"""
Tests for the Stage 0 / Stage 1 schemas added to src/schemas.py.

Run with: pytest tests/test_schemas_stage01.py -v
No pipeline, no crew, no LLM calls — pure model validation against
fixtures shaped like what t_synthesize_stage0 / t_stage1 actually produce.
"""

import pytest
from pydantic import ValidationError

from src.schemas import (
    Stage0Output,
    Signature,
    SignatureCategory,
    ConfidenceLevel,
    Stage1Output,
    TechnicalProceduralNode,
    CognitiveNode,
    TrustBoundary,
    DecompositionLayer,
    CognitiveHierarchyStage,
)


# ---------- Signature / Stage0Output ----------

def test_signature_minimal_valid():
    sig = Signature(
        signature_id="S-T-01",
        category="technical",
        description="Legacy TLS 1.1 endpoint on C2 relay",
        confidence="HIGH",
        deceive_candidate=False,
    )
    assert sig.category == SignatureCategory.TECHNICAL
    assert sig.confidence == ConfidenceLevel.HIGH
    assert sig.is_gap is False  # default


def test_signature_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        Signature(signature_id="S-T-01", category="technical", description="x",
                   confidence="SORT_OF", deceive_candidate=False)


def test_signature_rejects_invalid_category():
    with pytest.raises(ValidationError):
        Signature(signature_id="S-T-01", category="financial", description="x",
                   confidence="HIGH", deceive_candidate=False)


def test_signature_all_four_categories_accepted():
    for cat in ("technical", "procedural", "cognitive", "social_personnel"):
        sig = Signature(signature_id="S-X-01", category=cat, description="x",
                         confidence="LOW", deceive_candidate=False)
        assert sig.category == cat


def test_stage0_output_gap_count_autocomputed_not_trusted_from_input():
    """gap_count should reflect actual is_gap flags, not whatever the caller passes."""
    s0 = Stage0Output(
        signatures=[
            Signature(signature_id="S-T-01", category="technical", description="a",
                       confidence="HIGH", deceive_candidate=False, is_gap=False),
            Signature(signature_id="S-P-01", category="procedural", description="[GAP] b",
                       confidence="LOW", deceive_candidate=False, is_gap=True),
        ],
        gap_count=999,  # deliberately wrong — should be overwritten
    )
    assert s0.gap_count == 1


def test_stage0_output_empty_signatures_list_is_valid():
    """An empty list is structurally valid — a fully-gapped Stage 0 is still
    a real (if weak) output, not a schema violation."""
    s0 = Stage0Output(signatures=[])
    assert s0.gap_count == 0


def test_stage0_output_round_trips_through_json():
    original = Stage0Output(signatures=[
        Signature(signature_id="S-C-01", category="cognitive",
                   description="Analyst over-trust in fused AI confidence score",
                   confidence="MEDIUM", deceive_candidate=True),
    ])
    reloaded = Stage0Output.model_validate_json(original.model_dump_json())
    assert reloaded == original
    assert reloaded.signatures[0].deceive_candidate is True


# ---------- TechnicalProceduralNode ----------

def test_technical_node_valid():
    node = TechnicalProceduralNode(
        component_id="C-T-01", layer="technical", name="C2 Relay",
        asset_control_levels=["No Access", "API Reach", "Write Access"],
        information_flows="telemetry -> fused track",
        downstream_dependencies=["C-T-02"],
    )
    assert node.layer == DecompositionLayer.TECHNICAL
    assert len(node.asset_control_levels) == 3


def test_procedural_node_uses_same_shape_as_technical():
    """Task description: 'Same fields (C-P-NN)' — this is intentionally the
    same model as technical, just layer='procedural'."""
    node = TechnicalProceduralNode(
        component_id="C-P-01", layer="procedural", name="Patch cycle",
        asset_control_levels=["No Access", "Read Access"],
        information_flows="CVE feed -> patch queue",
        downstream_dependencies=[],
    )
    assert node.layer == DecompositionLayer.PROCEDURAL


def test_technical_node_rejects_cognitive_layer():
    """Cognitive nodes have a different shape (hierarchy_stage, not
    asset_control_levels) — layer='cognitive' must be rejected here so a
    cognitive-hierarchy node can never be silently stored with the wrong
    field set."""
    with pytest.raises(ValidationError):
        TechnicalProceduralNode(
            component_id="C-C-01", layer="cognitive", name="x",
            asset_control_levels=[], information_flows="x", downstream_dependencies=[],
        )


# ---------- CognitiveNode ----------

def test_cognitive_node_valid_with_center_of_gravity_flag():
    node = CognitiveNode(
        component_id="C-C-01", hierarchy_stage="Understanding",
        feeds="fused sensor picture", corrupts="false track injection",
        downstream_effect="wrong engagement decision",
        detection_probability="LOW", is_center_of_gravity=True,
    )
    assert node.hierarchy_stage == CognitiveHierarchyStage.UNDERSTANDING
    assert node.is_center_of_gravity is True


def test_cognitive_node_all_six_hierarchy_stages_accepted():
    stages = ["Data", "Information", "Knowledge", "Understanding", "Decision", "Behavior"]
    for stage in stages:
        node = CognitiveNode(
            component_id="C-C-01", hierarchy_stage=stage,
            feeds="x", corrupts="x", downstream_effect="x",
            detection_probability="MEDIUM",
        )
        assert node.hierarchy_stage == stage


def test_cognitive_node_rejects_invalid_hierarchy_stage():
    with pytest.raises(ValidationError):
        CognitiveNode(
            component_id="C-C-01", hierarchy_stage="Vibes",
            feeds="x", corrupts="x", downstream_effect="x",
            detection_probability="MEDIUM",
        )


# ---------- TrustBoundary ----------

def test_trust_boundary_valid():
    tb = TrustBoundary(boundary_id="TB-01", from_component="C-T-01",
                         to_component="C-C-01", description="relay feeds fused picture, no re-validation")
    assert tb.from_component == "C-T-01"


# ---------- Stage1Output ----------

def _sample_stage1() -> Stage1Output:
    return Stage1Output(
        technical_nodes=[TechnicalProceduralNode(
            component_id="C-T-01", layer="technical", name="C2 Relay",
            asset_control_levels=["No Access", "API Reach"],
            information_flows="telemetry -> fused track",
            downstream_dependencies=["C-T-02"])],
        procedural_nodes=[TechnicalProceduralNode(
            component_id="C-P-01", layer="procedural", name="Patch cycle",
            asset_control_levels=["No Access"], information_flows="CVE -> queue",
            downstream_dependencies=[])],
        cognitive_nodes=[CognitiveNode(
            component_id="C-C-01", hierarchy_stage="Understanding",
            feeds="sensor picture", corrupts="false injection",
            downstream_effect="wrong decision", detection_probability="LOW",
            is_center_of_gravity=True)],
        trust_boundaries=[TrustBoundary(
            boundary_id="TB-01", from_component="C-T-01", to_component="C-C-01",
            description="no re-validation across boundary")],
    )


def test_stage1_output_gap_count_aggregates_all_three_layers():
    s1 = _sample_stage1()
    s1.technical_nodes[0].is_gap = True
    s1 = Stage1Output.model_validate(s1.model_dump())  # re-trigger post_init
    assert s1.gap_count == 1


def test_stage1_output_all_component_ids_spans_three_layers():
    s1 = _sample_stage1()
    ids = s1.all_component_ids()
    assert ids == {"C-T-01", "C-P-01", "C-C-01"}


def test_stage1_output_flagged_cognitive_touchpoints_found():
    s1 = _sample_stage1()
    flagged = s1.flagged_cognitive_touchpoints()
    assert len(flagged) == 1
    assert flagged[0].component_id == "C-C-01"


def test_stage1_output_flagged_cognitive_touchpoints_empty_if_none_flagged():
    """Zero flagged is a valid, often-correct outcome — e.g. when the real
    COG is a Technical-layer chokepoint (see CDL_WRITE precedent), not a
    cognitive-layer node at all."""
    s1 = _sample_stage1()
    s1.cognitive_nodes[0].is_center_of_gravity = False
    assert s1.flagged_cognitive_touchpoints() == []


def test_stage1_output_flagged_cognitive_touchpoints_allows_multiple():
    """Multiple flags are permitted — this is advisory, not a single-winner field."""
    s1 = _sample_stage1()
    s1.cognitive_nodes.append(CognitiveNode(
        component_id="C-C-02", hierarchy_stage="Decision",
        feeds="x", corrupts="x", downstream_effect="x",
        detection_probability="MEDIUM", is_center_of_gravity=True))
    flagged = s1.flagged_cognitive_touchpoints()
    assert {n.component_id for n in flagged} == {"C-C-01", "C-C-02"}


def test_stage1_output_requires_all_four_layer_fields():
    with pytest.raises(ValidationError):
        Stage1Output(technical_nodes=[], procedural_nodes=[], cognitive_nodes=[])
        # missing trust_boundaries


def test_stage1_output_empty_layers_are_structurally_valid():
    """An all-[GAP] Stage 1 (nothing traceable) is still valid shape-wise;
    that's a content/attribution problem for the gate, not a schema problem."""
    s1 = Stage1Output(technical_nodes=[], procedural_nodes=[], cognitive_nodes=[], trust_boundaries=[])
    assert s1.all_component_ids() == set()
    assert s1.flagged_cognitive_touchpoints() == []


def test_stage1_output_round_trips_through_json():
    original = _sample_stage1()
    reloaded = Stage1Output.model_validate_json(original.model_dump_json())
    assert reloaded == original
    assert reloaded.all_component_ids() == original.all_component_ids()
"""
Pydantic schemas for VAF inter-agent handoffs and the run-level assessment
state / audit trail.

Conventions (matching src/tools.py verify_stage2_vectors / write_stage2_vectors):
  - Plain, deterministic, no I/O side effects inside the models themselves.
  - GAP markers are first-class, not an afterthought.
  - Everything that gets hashed/verified is a distinct artifact on disk;
    this file does not duplicate stage content, only points at it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StageStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"      # agent produced output, not yet gated/verified
    PASS = "PASS"            # deterministic gate confirmed the output
    FAIL = "FAIL"            # deterministic gate rejected the output
    BLOCKED = "BLOCKED"      # a prerequisite transition gate was not satisfied
    #                          (missing/blocked input) -- NOT an analytical
    #                          failure of this stage's own output


STAGE_NAMES = ("stage0", "stage1", "stage2", "stage3", "stage4")


# ---------------------------------------------------------------------------
# Stage 0 — Reverse IPB (t_synthesize_stage0)
# ---------------------------------------------------------------------------

class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SignatureCategory(str, Enum):
    TECHNICAL = "technical"
    PROCEDURAL = "procedural"
    COGNITIVE = "cognitive"
    SOCIAL_PERSONNEL = "social_personnel"


class Signature(BaseModel):
    """One Reverse IPB signature. Every named entity referenced in `description`
    must trace to a scratchpad finding per the task's attribution discipline —
    that discipline is enforced by the agent/prompt, not re-validated here."""
    model_config = ConfigDict(extra="forbid")

    signature_id: str                      # e.g. "S-T-01", "S-P-03", "S-C-02"
    category: SignatureCategory
    description: str
    confidence: ConfidenceLevel
    deceive_candidate: bool                # flagged as a Stage 3 DECEIVE injection point?
    is_gap: bool = False                   # True if this entry is a [GAP] placeholder


class Stage0Output(BaseModel):
    """Structured counterpart to outputs/<run_id>/stage0.md.
    The prose narrative remains the human-readable artifact; this is the
    machine-checkable index of what it asserts, for downstream gating."""
    model_config = ConfigDict(extra="forbid")

    signatures: list[Signature]
    gap_count: int = 0

    def model_post_init(self, __context) -> None:
        # keep gap_count consistent with the actual flagged entries rather
        # than trusting a hand-set value to stay in sync
        object.__setattr__(self, "gap_count", sum(1 for s in self.signatures if s.is_gap))


# ---------------------------------------------------------------------------
# Stage 1 — Three-layer decomposition (t_stage1)
# ---------------------------------------------------------------------------

class DecompositionLayer(str, Enum):
    TECHNICAL = "technical"
    PROCEDURAL = "procedural"
    COGNITIVE = "cognitive"


class TechnicalProceduralNode(BaseModel):
    """A node in LAYER 1 (Technical, component_id C-T-NN) or
    LAYER 2 (Procedural, component_id C-P-NN). Same field shape per the
    task description ('Same fields (C-P-NN)'). Cognitive nodes use the
    separate CognitiveNode model below (different fields entirely), so
    layer='cognitive' is explicitly rejected here rather than silently
    accepted with the wrong shape."""
    model_config = ConfigDict(extra="forbid")

    component_id: str                      # C-T-NN or C-P-NN
    layer: DecompositionLayer              # TECHNICAL or PROCEDURAL only
    name: str
    asset_control_levels: list[str]        # ordered adversary states
    information_flows: str                 # inputs -> outputs, free text
    downstream_dependencies: list[str]     # component_ids that break if this is compromised
    is_gap: bool = False

    @field_validator("layer")
    @classmethod
    def _layer_must_not_be_cognitive(cls, v: DecompositionLayer) -> DecompositionLayer:
        if v == DecompositionLayer.COGNITIVE:
            raise ValueError(
                "TechnicalProceduralNode.layer cannot be 'cognitive' — "
                "use CognitiveNode for Layer 3 entries instead."
            )
        return v


class CognitiveHierarchyStage(str, Enum):
    DATA = "Data"
    INFORMATION = "Information"
    KNOWLEDGE = "Knowledge"
    UNDERSTANDING = "Understanding"
    DECISION = "Decision"
    BEHAVIOR = "Behavior"


class CognitiveNode(BaseModel):
    """A node in LAYER 3 (Cognitive, component_id C-C-NN), mapped onto the
    ADP 3-13 cognitive hierarchy."""
    model_config = ConfigDict(extra="forbid")

    component_id: str                      # C-C-NN
    hierarchy_stage: CognitiveHierarchyStage
    feeds: str                             # what feeds this stage
    corrupts: str                          # what corrupts it
    downstream_effect: str
    detection_probability: ConfidenceLevel
    is_center_of_gravity: bool = False     # ADVISORY candidate touchpoint within
                                            # this layer only — NOT the doctrinal
                                            # COG (JP 5-0/ADP 3-0 is domain-agnostic)
                                            # and NOT the graph-theoretic COG Annex B
                                            # computes from min-cut + betweenness,
                                            # which may land on any layer
    is_gap: bool = False


class TrustBoundary(BaseModel):
    """One entry in the trust-boundary inventory: a boundary between
    components where the adversary can traverse a trust relationship."""
    model_config = ConfigDict(extra="forbid")

    boundary_id: str                       # e.g. "TB-01"
    from_component: str                    # component_id
    to_component: str                      # component_id
    description: str


class Stage1Output(BaseModel):
    """Structured counterpart to outputs/<run_id>/stage1.md.
    Every component_id here must trace to a Stage 0 signature_id or a
    scratchpad finding per the task's attribution discipline (enforced by
    the agent/prompt, not re-validated here). This is the required input
    Stage 2 draws on when authoring stage2_vectors.json."""
    model_config = ConfigDict(extra="forbid")

    technical_nodes: list[TechnicalProceduralNode]
    procedural_nodes: list[TechnicalProceduralNode]
    cognitive_nodes: list[CognitiveNode]
    trust_boundaries: list[TrustBoundary]
    gap_count: int = 0

    def model_post_init(self, __context) -> None:
        gaps = sum(1 for n in self.technical_nodes if n.is_gap)
        gaps += sum(1 for n in self.procedural_nodes if n.is_gap)
        gaps += sum(1 for n in self.cognitive_nodes if n.is_gap)
        object.__setattr__(self, "gap_count", gaps)

    def all_component_ids(self) -> set[str]:
        """Every component_id across all three layers — used by Stage 2's
        attribution check (node ids must trace to a Stage 1 node)."""
        ids = {n.component_id for n in self.technical_nodes}
        ids |= {n.component_id for n in self.procedural_nodes}
        ids |= {n.component_id for n in self.cognitive_nodes}
        return ids

    def flagged_cognitive_touchpoints(self) -> list[CognitiveNode]:
        """Cognitive-layer nodes the analyst flagged as candidate touchpoints
        (is_center_of_gravity=True). Advisory only — zero, one, or many may
        be flagged, and none of this determines the actual COG. The
        doctrinal COG (JP 5-0/ADP 3-0) is domain-agnostic; the operational
        COG used downstream is computed graph-theoretically in Annex B
        (min-cut + betweenness over the full attack graph) and may fall on
        a Technical or Procedural node instead of a cognitive one."""
        return [n for n in self.cognitive_nodes if n.is_center_of_gravity]


class StageRecord(BaseModel):
    """Audit record for a single stage's output artifact."""
    model_config = ConfigDict(extra="forbid")

    status: StageStatus = StageStatus.NOT_STARTED
    output_path: Optional[str] = None
    output_hash: Optional[str] = None       # "sha256:<hex>"
    committed_at: Optional[str] = None      # ISO8601 UTC
    schema_version: Optional[str] = None
    gap_count: int = 0


class GapLogEntry(BaseModel):
    """One flagged gap, aggregated across all stages into a single list."""
    model_config = ConfigDict(extra="forbid")

    stage: str
    node_id: Optional[str] = None
    description: str
    flagged_by: str
    flagged_at: str = Field(default_factory=_utcnow_iso)
    resolved: bool = False


class AssessmentState(BaseModel):
    """
    Run-level audit trail. One instance per run_id, persisted to
    outputs/<run_id>/assessment_state.json and updated after every stage.
    """
    model_config = ConfigDict(extra="forbid")

    run_id: str
    corpus_manifest_hash: str
    started_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)
    current_stage: str = "stage0"
    stages: dict[str, StageRecord] = Field(
        default_factory=lambda: {name: StageRecord() for name in STAGE_NAMES}
    )
    gap_log: list[GapLogEntry] = Field(default_factory=list)
    gate_decisions: list[dict] = Field(default_factory=list)

    def unresolved_gaps(self) -> list[GapLogEntry]:
        return [g for g in self.gap_log if not g.resolved]

    def all_stages_passed(self, through: str) -> bool:
        """True if every stage up to and including `through` has status PASS."""
        if through not in STAGE_NAMES:
            raise ValueError(f"unknown stage '{through}'")
        idx = STAGE_NAMES.index(through)
        return all(
            self.stages[name].status == StageStatus.PASS
            for name in STAGE_NAMES[: idx + 1]
        )
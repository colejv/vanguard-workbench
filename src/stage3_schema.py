"""
Structured, machine-readable Stage 3 test-plan schema. stage3.md remains
the human-review artifact; this is the closed-schema, machine-checkable
contract Stage 4 and the deterministic validator rely on.

Deliberately excludes execution payload code, shell commands, or exploit
scripts -- Stage 3 describes authorized test CONCEPTS and control
requirements. Stage 4 owns execution sequencing; human operators remain
responsible for actual implementation.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional


class Stage3TechniqueReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technique_id: str      # a real ID from technique_index.json, or exactly "[UNMAPPED]"
    vector_id: str          # must be one of the concept's own stage2_vector_ids
    rationale: str


class Stage3SafetyControls(BaseModel):
    """Required when a concept carries Category 2 or 3, and required to
    be entirely ABSENT (None) otherwise -- see Stage3TestConcept's own
    validation. Field names deliberately match STAGE3_REQUIRED_SAFETY_
    FIELDS in tools.py's prose-based check_stage3_safety_gate(), since
    both check the same doctrinal requirement over two different
    artifact forms."""
    model_config = ConfigDict(extra="forbid")

    affected_assets: list[str]
    required_approving_roles: list[str]
    safety_authority: str
    abort_authority: str
    maximum_termination_seconds: int = Field(gt=0)
    rollback_or_recovery_procedure: str


class Stage3TestConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_id: str            # RT-NNN
    title: str
    objective: str

    stage2_vector_ids: list[str]
    kcag_path: list[str]           # ADV_START ... goal, in order
    path_relationship: Literal["PRIORITY_PATH", "ALTERNATE_VALID_PATH"]
    target_node_ids: list[str]

    categories: list[Literal[1, 2, 3, 4]]

    execution_techniques: list[Stage3TechniqueReference]
    defensive_concepts: list[str]

    mechanism_summary: str
    preconditions: list[str]
    expected_effects: list[str]

    success_criteria: list[str]
    abort_criteria: list[str]
    rollback_or_recovery_steps: list[str]

    telemetry_requirements: list[str]
    assumptions: list[str]

    safety_controls: Optional[Stage3SafetyControls] = None


class Stage3AssessmentSafetyReview(BaseModel):
    """Structured counterpart of the prose 'PRE-STAGE-4 SAFETY REVIEW'
    section check_stage3_safety_gate() already parses. Deliberately
    duplicated across both artifact forms -- see stage3_validation.py's
    module docstring for why that's intentional, not redundant."""
    model_config = ConfigDict(extra="forbid")

    category_2_3_present: bool
    covered_test_ids: list[str] = []

    required_approving_roles: list[str] = []
    safety_authority: Optional[str] = None
    abort_authority: Optional[str] = None
    abort_criteria: list[str] = []
    maximum_termination_seconds: Optional[int] = None
    rollback_or_recovery_procedure: Optional[str] = None
    release_condition: Optional[str] = None

    not_required_statement: Optional[str] = None


class Stage3TestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    plan_title: str
    test_concepts: list[Stage3TestConcept]
    assessment_safety_review: Stage3AssessmentSafetyReview
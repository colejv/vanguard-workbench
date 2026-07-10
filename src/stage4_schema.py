"""
Structured, machine-readable Stage 4 execution-plan schema.
stage4_mission_plan.md remains the human-review artifact; this is the
closed-schema, machine-checkable contract the deterministic validator and
(in a later commit) the Purple Team compiler rely on.

execution_authorization is deliberately fixed to "NOT_GRANTED": human
review of a CrewAI task is not equivalent to signed operational
authorization, and this artifact must never be interpretable by a
downstream consumer as authorization to execute. Deliberately excludes
payload code, shell commands, exploit scripts, credentials, or a
deployment command -- this remains a planning and defensive-validation
contract, not an execution one.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional


class Stage4SafetyGate(BaseModel):
    """Structured counterpart of the prose Phase 0 Safety Gate section
    check_phase0_safety_gate() already parses. Deliberately duplicated
    across both artifact forms, same reasoning as Stage3SafetyControls /
    check_stage3_safety_gate: this validates the STRUCTURED artifact;
    the existing prose check remains an independent defense-in-depth
    check and is not replaced or weakened by this schema's existence."""
    model_config = ConfigDict(extra="forbid")

    required: bool
    covered_test_ids: list[str] = []

    required_approving_roles: list[str] = []
    safety_authority: Optional[str] = None
    abort_authority: Optional[str] = None
    abort_criteria: list[str] = []
    maximum_termination_seconds: Optional[int] = Field(default=None, gt=0)
    rollback_or_recovery_procedure: Optional[str] = None
    release_condition: Optional[str] = None

    execution_release: Literal["BLOCKED_PENDING_SIGNOFF", "NOT_APPLICABLE"]

    not_required_statement: Optional[str] = None


class Stage4TestBinding(BaseModel):
    """Binds one Stage 3 test concept to the Stage 4 actions that
    implement it. categories/stage2_vector_ids/kcag_path/technique_ids
    are Stage 4's OWN restatement of what Stage 3 already declared for
    this test_id -- validate_stage4_execution_plan() checks these agree
    exactly with the authoritative Stage 3 test plan; Stage 4 may
    sequence and elaborate a concept, but may not silently change what
    it targets."""
    model_config = ConfigDict(extra="forbid")

    test_id: str
    categories: list[Literal[1, 2, 3, 4]]

    stage2_vector_ids: list[str]
    kcag_path: list[str]
    technique_ids: list[str]

    assigned_action_ids: list[str]


class Stage4Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str      # ACT-NNN
    test_id: str         # exactly one RT-NNN this action implements
    action_summary: str

    responsible_roles: list[str]
    preconditions: list[str]

    success_criteria: list[str]
    abort_criteria: list[str]
    rollback_or_recovery_steps: list[str]

    telemetry_requirements: list[str]
    alert_triggers: list[str]
    opsec_measures: list[str]


class Stage4Phase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_id: str        # PHASE-NN
    sequence: int = Field(ge=1)
    name: str
    purpose: str

    entry_criteria: list[str]
    exit_criteria: list[str]
    actions: list[Stage4Action]


class Stage4ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]

    plan_id: str          # MP-NNN
    plan_title: str

    artifact_role: Literal["HUMAN_REVIEWED_MISSION_PLAN_DRAFT"]
    execution_authorization: Literal["NOT_GRANTED"]

    source_stage3_test_ids: list[str]

    phase0_safety_gate: Stage4SafetyGate
    test_bindings: list[Stage4TestBinding]
    phases: list[Stage4Phase]

    global_opsec_measures: list[str]
    assumptions: list[str]
    limitations: list[str]
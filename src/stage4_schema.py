"""
Structured, machine-readable Stage 4 execution-plan schema.

stage4_mission_plan.md remains the human-review artifact. This module
defines the closed-schema, machine-checkable contract used by the Stage 4
compiler and deterministic validator.

A Stage 4 action may implement one or more Stage 3 test concepts through
Stage4Action.test_ids.

For migration compatibility, Stage4Action accepts the former singular
input field:

    "test_id": "RT-001"

and canonicalizes it internally to:

    "test_ids": ["RT-001"]

Canonical serialization and the generated JSON schema remain plural-only.
A multi-test action is never reduced to a singular value.

A Stage4TestBinding remains singular: each binding represents one Stage 3
test concept and lists all Stage 4 actions assigned to that concept.

Some collections intentionally permit empty lists at schema-validation
time so the deterministic semantic validator can emit the established,
specific error codes such as MISSING_STAGE3_TEST_ID and
TEST_HAS_NO_ACTION.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


_TEST_ID_PATTERN = re.compile(r"^RT-\d{3}$")
_ACTION_ID_PATTERN = re.compile(r"^ACT-\d{3}$")


def _normalize_unique_ids(
    values: list[str],
    *,
    field_name: str,
    pattern: re.Pattern[str],
    allow_empty: bool = False,
) -> list[str]:
    """
    Normalize an ID list to uppercase and reject malformed or duplicate
    identifiers.

    allow_empty exists for fields whose completeness is owned by the
    deterministic semantic validator rather than the Pydantic shape
    validator.
    """
    if not isinstance(values, list):
        raise ValueError(
            f"{field_name} must be a list"
        )

    normalized: list[str] = []

    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name}[{index}] must be a non-empty string"
            )

        normalized_value = value.strip().upper()

        if not pattern.fullmatch(normalized_value):
            raise ValueError(
                f"{field_name}[{index}] must match "
                f"{pattern.pattern}; got {value!r}"
            )

        normalized.append(normalized_value)

    if not normalized and not allow_empty:
        raise ValueError(
            f"{field_name} must contain at least one value"
        )

    if len(normalized) != len(set(normalized)):
        raise ValueError(
            f"{field_name} must not contain duplicate values"
        )

    return normalized


class Stage4SafetyGate(BaseModel):
    """
    Structured counterpart of the prose Phase 0 Safety Gate.

    covered_test_ids may be empty because an empty set can be valid when
    no Category 2/3 concepts exist, and because exact coverage is enforced
    by validate_stage4_execution_plan().
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    required: bool

    covered_test_ids: list[str] = Field(
        default_factory=list
    )

    required_approving_roles: list[str] = Field(
        default_factory=list
    )

    safety_authority: Optional[str] = None
    abort_authority: Optional[str] = None

    abort_criteria: list[str] = Field(
        default_factory=list
    )

    maximum_termination_seconds: Optional[int] = Field(
        default=None,
        gt=0,
    )

    rollback_or_recovery_procedure: Optional[str] = None
    release_condition: Optional[str] = None

    execution_release: Literal[
        "BLOCKED_PENDING_SIGNOFF",
        "NOT_APPLICABLE",
    ]

    not_required_statement: Optional[str] = None

    @field_validator("covered_test_ids")
    @classmethod
    def validate_covered_test_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        return _normalize_unique_ids(
            values,
            field_name="covered_test_ids",
            pattern=_TEST_ID_PATTERN,
            allow_empty=True,
        )


class Stage4TestBinding(BaseModel):
    """
    One binding per Stage 3 test concept.

    test_id intentionally remains singular. A multi-test action appears
    in every applicable binding through assigned_action_ids.

    assigned_action_ids permits an empty list at schema-validation time so
    the deterministic validator can report TEST_HAS_NO_ACTION and related
    assignment errors instead of collapsing them into SCHEMA_INVALID.
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    test_id: str
    categories: list[
        Literal[1, 2, 3, 4]
    ]

    stage2_vector_ids: list[str]
    kcag_path: list[str]
    technique_ids: list[str]

    assigned_action_ids: list[str]

    @field_validator("test_id")
    @classmethod
    def validate_test_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().upper()

        if not _TEST_ID_PATTERN.fullmatch(
            normalized
        ):
            raise ValueError(
                "test_id must match RT-NNN"
            )

        return normalized

    @field_validator("assigned_action_ids")
    @classmethod
    def validate_assigned_action_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        return _normalize_unique_ids(
            values,
            field_name="assigned_action_ids",
            pattern=_ACTION_ID_PATTERN,
            allow_empty=True,
        )


class Stage4Action(BaseModel):
    """
    One approved Stage 4 action.

    test_ids contains every Stage 3 test concept implemented by this
    action. It must always contain at least one unique RT-NNN identifier.

    Legacy singular test_id input is accepted only as a migration path and
    is converted to the canonical plural representation before normal
    field validation.
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    action_id: str
    test_ids: list[str] = Field(
        min_length=1
    )
    action_summary: str

    responsible_roles: list[str]
    preconditions: list[str]

    success_criteria: list[str]
    abort_criteria: list[str]
    rollback_or_recovery_steps: list[str]

    telemetry_requirements: list[str]
    alert_triggers: list[str]
    opsec_measures: list[str]

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_test_id(
        cls,
        value: Any,
    ) -> Any:
        """
        Accept the former singular action.test_id input without exposing
        that field in canonical model output.

        Examples:

            {"test_id": "RT-001"}
                -> {"test_ids": ["RT-001"]}

            {
                "test_id": "RT-001",
                "test_ids": ["RT-001"]
            }
                -> {"test_ids": ["RT-001"]}

        When both fields are present, they must describe the same singular
        assignment. A singular legacy field may not be used alongside a
        true multi-test list because doing so would be ambiguous.
        """
        if not isinstance(value, dict):
            return value

        migrated = dict(value)

        has_plural = "test_ids" in migrated
        has_singular = "test_id" in migrated

        if not has_singular:
            return migrated

        legacy_value = migrated.pop(
            "test_id"
        )

        if (
            not isinstance(legacy_value, str)
            or not legacy_value.strip()
        ):
            raise ValueError(
                "legacy test_id must be a non-empty string"
            )

        normalized_legacy = (
            legacy_value.strip().upper()
        )

        if not has_plural:
            migrated["test_ids"] = [
                normalized_legacy
            ]
            return migrated

        plural_value = migrated.get(
            "test_ids"
        )

        if not isinstance(plural_value, list):
            raise ValueError(
                "test_ids must be a list"
            )

        if not all(
            isinstance(item, str)
            and item.strip()
            for item in plural_value
        ):
            raise ValueError(
                "test_ids must contain only non-empty strings"
            )

        normalized_plural = [
            item.strip().upper()
            for item in plural_value
        ]

        if normalized_plural != [
            normalized_legacy
        ]:
            raise ValueError(
                "test_id and test_ids disagree"
            )

        migrated["test_ids"] = (
            normalized_plural
        )

        return migrated

    @field_validator("action_id")
    @classmethod
    def validate_action_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().upper()

        if not _ACTION_ID_PATTERN.fullmatch(
            normalized
        ):
            raise ValueError(
                "action_id must match ACT-NNN"
            )

        return normalized

    @field_validator("test_ids")
    @classmethod
    def validate_test_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        return _normalize_unique_ids(
            values,
            field_name="test_ids",
            pattern=_TEST_ID_PATTERN,
            allow_empty=False,
        )

    @property
    def test_id(self) -> str:
        """
        Compatibility accessor for older callers.

        The accessor only works for singular assignments. Multi-test
        callers must use action.test_ids so references cannot be silently
        discarded.
        """
        if len(self.test_ids) != 1:
            raise AttributeError(
                "This Stage 4 action references multiple test IDs; "
                "use action.test_ids."
            )

        return self.test_ids[0]


class Stage4Phase(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    phase_id: str
    sequence: int = Field(
        ge=1
    )
    name: str
    purpose: str

    entry_criteria: list[str]
    exit_criteria: list[str]
    actions: list[Stage4Action]


class Stage4ExecutionPlan(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    schema_version: Literal[1]

    plan_id: str
    plan_title: str

    artifact_role: Literal[
        "HUMAN_REVIEWED_MISSION_PLAN_DRAFT"
    ]

    execution_authorization: Literal[
        "NOT_GRANTED"
    ]

    source_stage3_test_ids: list[str]

    phase0_safety_gate: Stage4SafetyGate
    test_bindings: list[Stage4TestBinding]
    phases: list[Stage4Phase]

    global_opsec_measures: list[str]
    assumptions: list[str]
    limitations: list[str]

    @field_validator("source_stage3_test_ids")
    @classmethod
    def validate_source_stage3_test_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        """
        Empty input is schema-valid so the deterministic validator can
        report MISSING_STAGE3_TEST_ID with the established public error
        contract.
        """
        return _normalize_unique_ids(
            values,
            field_name="source_stage3_test_ids",
            pattern=_TEST_ID_PATTERN,
            allow_empty=True,
        )
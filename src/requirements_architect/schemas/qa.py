"""Testing and deployment models (Stage 10)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import FrId, NfrId, Priority, SpecIssue

CaseKey = Annotated[str, StringConstraints(pattern=r"^TC\d{1,3}$")]
CaseId = Annotated[str, StringConstraints(pattern=r"^TC-\d{3,}$")]
EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]


class QaType(StrEnum):
    UNIT = "unit"
    INTEGRATION = "integration"
    API = "api"
    E2E = "e2e"
    REGRESSION = "regression"
    PERFORMANCE = "performance"
    STRESS = "stress"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    AI_EVAL = "ai_eval"


class StrategyItem(BaseModel):
    test_type: QaType
    approach: str = Field(min_length=1, max_length=500)
    tools: list[str] = Field(default_factory=list, max_length=8)


class RawQaCase(BaseModel):
    key: CaseKey
    requirement_ids: list[FrId | NfrId] = Field(min_length=1, max_length=10)
    scenario: str = Field(min_length=1, max_length=400)
    preconditions: list[str] = Field(default_factory=list, max_length=10)
    test_data: list[str] = Field(default_factory=list, max_length=10)
    steps: list[str] = Field(min_length=1, max_length=20)
    expected_result: str = Field(min_length=1, max_length=400)
    priority: Priority
    test_type: QaType
    execution_criteria: str = Field(default="", max_length=300)


class Environment(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    purpose: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=300)


class EnvVar(BaseModel):
    """Name and purpose only. There is deliberately no value field."""

    name: EnvVarName
    purpose: str = Field(min_length=1, max_length=200)
    secret: bool = False
    required: bool = True


class Deployment(BaseModel):
    environments: list[Environment] = Field(default_factory=list, max_length=8)
    containerization: str = Field(default="", max_length=600)
    ci_cd: list[str] = Field(default_factory=list, max_length=12)
    environment_variables: list[EnvVar] = Field(default_factory=list, max_length=60)
    secrets_management: str = Field(default="", max_length=600)
    migrations: str = Field(default="", max_length=600)
    monitoring: str = Field(default="", max_length=600)
    logging: str = Field(default="", max_length=600)
    backups: str = Field(default="", max_length=600)
    rollback: str = Field(default="", max_length=600)
    recovery: str = Field(default="", max_length=600)
    scaling: str = Field(default="", max_length=600)


class RawQaOutput(BaseModel):
    strategy: list[StrategyItem] = Field(default_factory=list, max_length=12)
    test_cases: list[RawQaCase] = Field(min_length=1, max_length=200)
    deployment: Deployment
    ai_evaluation: str | None = Field(default=None, max_length=1200)

    @model_validator(mode="after")
    def _unique_keys(self) -> RawQaOutput:
        keys = [c.key for c in self.test_cases]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate test case keys")
        return self


class QaCase(BaseModel):
    id: CaseId
    requirement_ids: list[str]
    scenario: str
    preconditions: list[str]
    test_data: list[str]
    steps: list[str]
    expected_result: str
    priority: Priority
    test_type: QaType
    execution_criteria: str


class QaSpec(BaseModel):
    strategy: list[StrategyItem] = Field(default_factory=list)
    test_cases: list[QaCase] = Field(default_factory=list)
    deployment: Deployment = Field(default_factory=Deployment)
    ai_evaluation: str | None = None
    approval_candidates: list[ApprovalCandidate] = Field(default_factory=list)
    issues: list[SpecIssue] = Field(default_factory=list)

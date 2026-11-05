"""Typed, versioned project-state models shared by all analysis stages."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

QuestionId = Annotated[str, StringConstraints(pattern=r"^Q-\d{3,}$")]


class StageId(StrEnum):
    PROBLEM_UNDERSTANDING = "stage_01_problem_understanding"
    CLARIFICATION = "stage_02_clarification"
    RESEARCH = "stage_03_research"
    REQUIREMENTS = "stage_04_requirements"
    ARCHITECTURE = "stage_05_architecture"
    TECHNOLOGY = "stage_06_technology"
    DATA_API = "stage_07_database_api"
    SECURITY = "stage_08_security"
    UX = "stage_09_ux"
    QA_DEPLOY = "stage_10_testing_deployment"
    AUDIT = "stage_11_audit"
    DOCUMENTATION = "stage_12_documentation"


class OutputStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class WorkflowStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    READY_FOR_RESEARCH = "ready_for_research"
    RESEARCH_COMPLETE = "research_complete"
    REQUIREMENTS_COMPLETE = "requirements_complete"
    SPECS_COMPLETE = "specifications_complete"
    AUDIT_COMPLETE = "audit_complete"
    DOCUMENTS_COMPLETE = "documents_complete"
    FAILED = "failed"


class Dependency(BaseModel):
    stage_id: StageId
    version: int = Field(ge=1)


class OutputMeta(BaseModel):
    """Envelope carried by every persisted stage output."""

    project_id: str
    stage_id: StageId
    version: int = Field(ge=1)
    status: OutputStatus = OutputStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    depends_on: list[Dependency] = Field(default_factory=list)


class Assumption(BaseModel):
    statement: str
    basis: str = Field(
        description="Why this assumption is being made; 'none stated' if unsupported"
    )


class ProjectBrief(BaseModel):
    """Stage 1 output. Anything not stated by the user belongs in missing_information,
    not in the other fields."""

    actual_problem: str
    proposed_solution: str
    business_objectives: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    user_roles: list[str] = Field(default_factory=list)
    main_workflows: list[str] = Field(default_factory=list)
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_outcomes: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class ClarificationQuestion(BaseModel):
    id: QuestionId
    group: str = "general"
    question: str
    reason: str
    impact: str
    options: list[str] = Field(default_factory=list)
    blocking: bool
    recommended_interpretation: str | None = None


class ClarificationPlan(BaseModel):
    """Stage 2 output."""

    sufficient: bool
    rationale: str
    questions: list[ClarificationQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> ClarificationPlan:
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate question ids")
        if self.sufficient and any(q.blocking for q in self.questions):
            raise ValueError("plan cannot be 'sufficient' while blocking questions exist")
        if not self.sufficient and not any(q.blocking for q in self.questions):
            raise ValueError("plan marked insufficient must contain at least one blocking question")
        return self


class ClarificationAnswer(BaseModel):
    question_id: QuestionId
    answer: str = Field(min_length=1)
    accepted_recommendation: bool = False

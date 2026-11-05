"""Architecture models (Stage 5). Raw* = what the model proposes; others carry code-assigned ids."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import FrId, NfrId, SpecIssue

CompKey = Annotated[str, StringConstraints(pattern=r"^C\d{1,3}$")]
DecisionKey = Annotated[str, StringConstraints(pattern=r"^D\d{1,3}$")]
ComponentId = Annotated[str, StringConstraints(pattern=r"^C-\d{3,}$")]
DecisionId = Annotated[str, StringConstraints(pattern=r"^AD-\d{3,}$")]


class ArchPattern(StrEnum):
    MODULAR_MONOLITH = "modular_monolith"
    MICROSERVICES = "microservices"
    EVENT_DRIVEN = "event_driven"
    SERVERLESS = "serverless"
    MULTI_AGENT = "multi_agent"
    DISTRIBUTED = "distributed"


class ComponentKind(StrEnum):
    SERVICE = "service"
    MODULE = "module"
    DATASTORE = "datastore"
    EXTERNAL = "external"
    UI = "ui"
    QUEUE = "queue"
    WORKER = "worker"


class PatternEvaluation(BaseModel):
    pattern: ArchPattern
    suitable: bool
    rationale: str = Field(min_length=1, max_length=600)


class Alternative(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    why_rejected: str = Field(min_length=1, max_length=400)


class RawComponent(BaseModel):
    key: CompKey
    name: str = Field(min_length=1, max_length=80)
    kind: ComponentKind
    responsibility: str = Field(min_length=1, max_length=500)
    requirement_ids: list[FrId | NfrId] = Field(default_factory=list, max_length=30)
    depends_on: list[CompKey] = Field(default_factory=list, max_length=15)


class RawDataFlow(BaseModel):
    source: CompKey
    target: CompKey
    data: str = Field(min_length=1, max_length=200)


class RawSequenceStep(BaseModel):
    source: CompKey
    target: CompKey
    message: str = Field(min_length=1, max_length=150)


class RawSequence(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    steps: list[RawSequenceStep] = Field(min_length=1, max_length=20)


class RawDecision(BaseModel):
    key: DecisionKey
    title: str = Field(min_length=1, max_length=150)
    decision: str = Field(min_length=1, max_length=600)
    rationale: str = Field(min_length=1, max_length=800)
    alternatives: list[Alternative] = Field(default_factory=list, max_length=6)
    tradeoffs: list[str] = Field(default_factory=list, max_length=8)
    component_keys: list[CompKey] = Field(default_factory=list, max_length=10)
    needs_human_approval: bool = False
    approval_reason: str | None = Field(default=None, max_length=400)


class RawArchitecture(BaseModel):
    selected_pattern: ArchPattern
    pattern_evaluations: list[PatternEvaluation] = Field(min_length=1, max_length=6)
    components: list[RawComponent] = Field(min_length=1, max_length=40)
    data_flows: list[RawDataFlow] = Field(default_factory=list, max_length=60)
    sequences: list[RawSequence] = Field(default_factory=list, max_length=8)
    decisions: list[RawDecision] = Field(default_factory=list, max_length=20)
    failure_handling: list[str] = Field(default_factory=list, max_length=12)
    caching: str | None = Field(default=None, max_length=600)
    scalability: str = Field(default="", max_length=800)
    recovery_strategy: str = Field(default="", max_length=800)

    @model_validator(mode="after")
    def _unique_keys(self) -> RawArchitecture:
        for label, keys in (
            ("component", [c.key for c in self.components]),
            ("decision", [d.key for d in self.decisions]),
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} keys")
        return self


class Component(BaseModel):
    id: ComponentId
    name: str
    kind: ComponentKind
    responsibility: str
    requirement_ids: list[str]
    depends_on: list[ComponentId]


class DataFlow(BaseModel):
    source: ComponentId
    target: ComponentId
    data: str


class SequenceStep(BaseModel):
    source: ComponentId
    target: ComponentId
    message: str


class Sequence(BaseModel):
    name: str
    steps: list[SequenceStep]
    mermaid: str


class Decision(BaseModel):
    id: DecisionId
    title: str
    decision: str
    rationale: str
    alternatives: list[Alternative]
    tradeoffs: list[str]
    component_ids: list[ComponentId]
    needs_human_approval: bool = False
    approval_reason: str | None = None


class ArchitectureSpec(BaseModel):
    selected_pattern: ArchPattern
    pattern_evaluations: list[PatternEvaluation] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    data_flows: list[DataFlow] = Field(default_factory=list)
    sequences: list[Sequence] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    failure_handling: list[str] = Field(default_factory=list)
    caching: str | None = None
    scalability: str = ""
    recovery_strategy: str = ""
    context_diagram: str = ""
    component_diagram: str = ""
    dataflow_diagram: str = ""
    approval_candidates: list[ApprovalCandidate] = Field(default_factory=list)
    issues: list[SpecIssue] = Field(default_factory=list)

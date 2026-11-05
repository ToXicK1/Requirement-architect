"""UI/UX models (Stage 9)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.dataapi import EndpointId
from requirements_architect.schemas.requirements import FrId, NfrId, SpecIssue

FlowKey = Annotated[str, StringConstraints(pattern=r"^FL\d{1,3}$")]
ScreenKey = Annotated[str, StringConstraints(pattern=r"^S\d{1,3}$")]


class UiState(StrEnum):
    LOADING = "loading"
    ERROR = "error"
    EMPTY = "empty"
    POPULATED = "populated"


class Persona(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=400)
    goals: list[str] = Field(default_factory=list, max_length=8)


class StateSpec(BaseModel):
    state: UiState
    description: str = Field(min_length=1, max_length=300)


class RawFlow(BaseModel):
    key: FlowKey
    name: str = Field(min_length=1, max_length=120)
    actor: str = Field(min_length=1, max_length=100)
    steps: list[str] = Field(min_length=1, max_length=20)
    requirement_ids: list[FrId | NfrId] = Field(default_factory=list, max_length=20)


class RawScreen(BaseModel):
    key: ScreenKey
    name: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=400)
    inputs: list[str] = Field(default_factory=list, max_length=20)
    outputs: list[str] = Field(default_factory=list, max_length=20)
    states: list[StateSpec] = Field(default_factory=list, max_length=8)
    responsive: str = Field(default="", max_length=300)
    accessibility: list[str] = Field(default_factory=list, max_length=8)
    requirement_ids: list[FrId | NfrId] = Field(default_factory=list, max_length=20)
    endpoint_ids: list[EndpointId] = Field(default_factory=list, max_length=15)


class RawUx(BaseModel):
    has_ui: bool
    interface_note: str = Field(default="", max_length=1000)  # required when there is no UI
    personas: list[Persona] = Field(default_factory=list, max_length=8)
    flows: list[RawFlow] = Field(default_factory=list, max_length=20)
    screens: list[RawScreen] = Field(default_factory=list, max_length=40)
    navigation: list[str] = Field(default_factory=list, max_length=30)
    design_system: list[str] = Field(default_factory=list, max_length=20)
    accessibility_requirements: list[str] = Field(default_factory=list, max_length=15)

    @model_validator(mode="after")
    def _unique_keys(self) -> RawUx:
        for label, keys in (
            ("flow", [f.key for f in self.flows]),
            ("screen", [s.key for s in self.screens]),
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} keys")
        return self


class Flow(BaseModel):
    id: str
    name: str
    actor: str
    steps: list[str]
    requirement_ids: list[str]


class Screen(BaseModel):
    id: str
    name: str
    purpose: str
    inputs: list[str]
    outputs: list[str]
    states: list[StateSpec]
    responsive: str
    accessibility: list[str]
    requirement_ids: list[str]
    endpoint_ids: list[str]


class UxSpec(BaseModel):
    has_ui: bool
    interface_note: str = ""
    personas: list[Persona] = Field(default_factory=list)
    flows: list[Flow] = Field(default_factory=list)
    screens: list[Screen] = Field(default_factory=list)
    navigation: list[str] = Field(default_factory=list)
    design_system: list[str] = Field(default_factory=list)
    accessibility_requirements: list[str] = Field(default_factory=list)
    approval_candidates: list[ApprovalCandidate] = Field(default_factory=list)
    issues: list[SpecIssue] = Field(default_factory=list)

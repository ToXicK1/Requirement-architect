"""Request bodies. Strict limits; unknown fields are rejected."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from requirements_architect.agent.approvals import Decision
from requirements_architect.schemas.state import StageId


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(_Body):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)


class NewProject(_Body):
    name: str = Field(min_length=1, max_length=200)
    problem_statement: str = Field(min_length=10, max_length=20000)


class AnswerIn(_Body):
    question_id: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=1, max_length=4000)
    accepted_recommendation: bool = False


class Answers(_Body):
    answers: list[AnswerIn] = Field(min_length=1, max_length=40)


class DecisionIn(_Body):
    stage_id: StageId
    ref: str = Field(min_length=1, max_length=60)
    fingerprint: str = Field(min_length=64, max_length=64)
    decision: Decision
    note: str = Field(default="", max_length=2000)

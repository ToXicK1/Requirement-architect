"""ORM models. Stage outputs are append-only and versioned; nothing is silently overwritten."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from requirements_architect.storage.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    name: Mapped[str] = mapped_column(String(200))
    problem_statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class StageOutput(Base):
    __tablename__ = "stage_outputs"
    __table_args__ = (
        UniqueConstraint("project_id", "stage_id", "version", name="uq_stage_version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    stage_id: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    depends_on: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ClarificationAnswerRow(Base):
    __tablename__ = "clarification_answers"
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    answer: Mapped[str] = mapped_column(Text)
    accepted_recommendation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LLMUsageRow(Base):
    __tablename__ = "llm_usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, default=None)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    prompt_id: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[str | None] = mapped_column(
        String(32), default=None
    )  # Decimal as text
    latency_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_type: Mapped[str | None] = mapped_column(String(60), default=None)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

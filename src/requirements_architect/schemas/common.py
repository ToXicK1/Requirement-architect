"""Types shared by the design stages (5-10)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApprovalCandidate(BaseModel):
    """A decision the spec says needs human approval. The approval workflow (Phase 9) consumes these;
    stages only *flag* them and never treat anything as approved."""

    source_stage: str
    ref: str
    decision: str
    reason: str
    affected_ids: list[str] = Field(default_factory=list)

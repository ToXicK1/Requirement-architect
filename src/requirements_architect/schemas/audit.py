"""Audit models (Stage 11). Findings come from deterministic checks or from an independent
LLM review. LLM findings are judgments: they are capped below blocker but still count toward
the major-findings gate, and a human may dismiss them."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from requirements_architect.schemas.state import StageId


class AuditSeverity(StrEnum):
    BLOCKER = "blocker"  # the package must not be handed over
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class AuditCategory(StrEnum):
    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    TRACEABILITY = "traceability"
    EVIDENCE = "evidence"
    SECURITY = "security"
    AMBIGUITY = "ambiguity"
    DIAGRAM = "diagram"
    DEPENDENCY = "dependency"
    ASSUMPTION = "assumption"
    REVIEW = "review"  # LLM review


class AuditFinding(BaseModel):
    id: str = ""  # AUD-001..., assigned after sorting so output is deterministic
    source: Literal["deterministic", "llm"] = "deterministic"
    category: AuditCategory
    severity: AuditSeverity
    code: str
    message: str
    refs: list[str] = Field(default_factory=list)
    stage: StageId | None = None  # stage whose output has to change to resolve it
    # True only when regenerating `stage` (without touching requirements) could resolve it.
    auto_fixable: bool = False
    needs_human: bool = False


class RemediationTask(BaseModel):
    id: str
    finding_id: str
    action: str
    owner: Literal["auto", "human"]
    stage: StageId | None = None


class GateResult(BaseModel):
    name: str
    passed: bool
    detail: str


class AuditThresholds(BaseModel):
    max_major: int = Field(default=0, ge=0)
    require_fr_component_and_test: bool = True


class AuditRound(BaseModel):
    round: int
    findings: int
    by_severity: dict[str, int]
    regenerated: list[str] = Field(default_factory=list)


class AuditVerdict(StrEnum):
    NOT_READY = "not_ready"
    # Automated gates pass. This is NOT approval: a human must still review.
    READY_FOR_REVIEW = "ready_for_review"


class AuditReport(BaseModel):
    verdict: AuditVerdict
    findings: list[AuditFinding]
    gates: list[GateResult]
    tasks: list[RemediationTask] = Field(default_factory=list)
    rounds: list[AuditRound] = Field(default_factory=list)
    thresholds: AuditThresholds = Field(default_factory=AuditThresholds)
    llm_review: Literal["not_run", "completed", "failed"] = "not_run"
    llm_discarded: int = 0  # LLM findings dropped because they cited ids that do not exist
    limitations: list[str] = Field(default_factory=list)
    source_versions: dict[str, int] = Field(default_factory=dict)

    def count(self, severity: AuditSeverity) -> int:
        return sum(1 for f in self.findings if f.severity is severity)


class RawReviewFinding(BaseModel):
    """What the independent reviewer may say. It cannot set ids, stages or fixability."""

    kind: Literal[
        "contradiction",
        "ambiguity",
        "missing_requirement",
        "unsupported_claim",
        "security_gap",
        "incompatibility",
        "other",
    ]
    severity: Literal["major", "minor", "info"]
    message: str = Field(min_length=1, max_length=500)
    refs: list[str] = Field(default_factory=list, max_length=10)


class RawAuditReview(BaseModel):
    findings: list[RawReviewFinding] = Field(default_factory=list, max_length=30)

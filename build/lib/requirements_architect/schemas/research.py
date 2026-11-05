"""Evidence and research-report models (Stage 3)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

SourceId = Annotated[str, StringConstraints(pattern=r"^S-\d{3,}$")]
FindingId = Annotated[str, StringConstraints(pattern=r"^F-\d{3,}$")]


class SourceType(StrEnum):
    OFFICIAL_DOCS = "official_docs"
    STANDARD = "standard"
    ADVISORY = "advisory"
    PACKAGE_REGISTRY = "package_registry"
    REPOSITORY = "repository"
    WEB = "web"


class Reliability(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingKind(StrEnum):
    FACT = "fact"  # a claim about the world; needs a source and a verifiable quote
    RECOMMENDATION = "recommendation"  # engineering judgement; never "verified"
    ASSUMPTION = "assumption"  # unsupported premise; never "verified"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"  # quote found verbatim in a cited, retrieved source
    UNVERIFIED = (
        "unverified"  # recommendation/assumption, or fact whose quote could not be confirmed
    )
    UNSUPPORTED = "unsupported"  # fact with no usable source


class Source(BaseModel):
    source_id: SourceId
    url: str
    title: str
    source_type: SourceType
    retrieved_at: datetime
    content_sha256: str
    excerpt: str = Field(max_length=2000)
    reliability: Reliability
    reliability_basis: str
    injection_flags: list[str] = Field(default_factory=list)


class RawFinding(BaseModel):
    """What the LLM proposes. Verification fields are NOT accepted from the model."""

    kind: FindingKind
    claim: str = Field(min_length=1, max_length=600)
    source_ids: list[SourceId] = Field(default_factory=list, max_length=5)
    quote: str | None = Field(default=None, max_length=300)


class Finding(BaseModel):
    finding_id: FindingId
    kind: FindingKind
    claim: str
    source_ids: list[SourceId] = Field(default_factory=list)
    quote: str | None = None
    verification: VerificationStatus
    verification_note: str


class AdvisoryRef(BaseModel):
    advisory_id: str
    summary: str = ""


class PackageRef(BaseModel):
    ecosystem: str = Field(pattern=r"^(pypi|npm)$")
    name: str = Field(min_length=1, max_length=214)


class PackageFact(BaseModel):
    """Read directly from a registry API: deterministic, not LLM-generated."""

    ecosystem: str
    name: str
    latest_version: str | None = None
    license: str | None = None
    summary: str | None = None
    registry_url: str
    advisories: list[AdvisoryRef] = Field(default_factory=list)
    advisories_checked: bool = False


class ResearchPlan(BaseModel):
    queries: list[Annotated[str, StringConstraints(min_length=3, max_length=200)]] = Field(
        default_factory=list, max_length=8
    )
    github_queries: list[Annotated[str, StringConstraints(min_length=2, max_length=120)]] = Field(
        default_factory=list, max_length=4
    )
    packages: list[PackageRef] = Field(default_factory=list, max_length=12)


class SynthesisOutput(BaseModel):
    feasibility_summary: str = Field(max_length=3000)
    findings: list[RawFinding] = Field(default_factory=list, max_length=40)


class ResearchReport(BaseModel):
    sources: list[Source] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    packages: list[PackageFact] = Field(default_factory=list)
    feasibility_summary: str = ""
    queries_run: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    external_research_available: bool = False

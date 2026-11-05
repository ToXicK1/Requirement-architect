"""Technology models (Stage 6)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from requirements_architect.schemas.architecture import ComponentId
from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import SpecIssue
from requirements_architect.schemas.research import AdvisoryRef, FindingId, PackageRef

TechKey = Annotated[str, StringConstraints(pattern=r"^T\d{1,3}$")]
TechId = Annotated[str, StringConstraints(pattern=r"^TECH-\d{3,}$")]


class TechCategory(StrEnum):
    LANGUAGE = "language"
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    AI_FRAMEWORK = "ai_framework"
    LLM_PROVIDER = "llm_provider"
    ORCHESTRATION = "orchestration"
    API = "api"
    LIBRARY = "library"
    DEVOPS = "devops"
    CLOUD = "cloud"
    MONITORING = "monitoring"
    TESTING = "testing"
    SECURITY = "security"


class ClaimStatus(StrEnum):
    CONFIRMED = "confirmed"  # equals the value read from the package registry
    DIFFERS = "differs_from_registry"
    UNVERIFIED = "unverified"  # no registry evidence for this claim
    NOT_SPECIFIED = "not_specified"


class RawTechnology(BaseModel):
    key: TechKey
    name: str = Field(min_length=1, max_length=100)
    category: TechCategory
    purpose: str = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=1, max_length=600)
    alternatives: list[str] = Field(default_factory=list, max_length=8)
    advantages: list[str] = Field(default_factory=list, max_length=8)
    disadvantages: list[str] = Field(default_factory=list, max_length=8)
    dependencies: list[str] = Field(default_factory=list, max_length=10)
    compatibility: str = Field(default="", max_length=500)
    recommended_version: str | None = Field(default=None, max_length=40)
    license: str | None = Field(default=None, max_length=80)
    infrastructure: str = Field(default="", max_length=400)
    skills: list[str] = Field(default_factory=list, max_length=8)
    finding_ids: list[FindingId] = Field(default_factory=list, max_length=8)
    component_ids: list[ComponentId] = Field(default_factory=list, max_length=15)
    package: PackageRef | None = None
    vendor_lock_in: Literal["none", "low", "high"] = "none"
    significant_cost: bool = False


class RawTechnologyOutput(BaseModel):
    technologies: list[RawTechnology] = Field(min_length=1, max_length=40)


class Technology(BaseModel):
    id: TechId
    name: str
    category: TechCategory
    purpose: str
    reason: str
    alternatives: list[str]
    advantages: list[str]
    disadvantages: list[str]
    dependencies: list[str]
    compatibility: str
    recommended_version: str | None
    version_status: ClaimStatus
    registry_version: str | None = None
    license: str | None
    license_status: ClaimStatus
    registry_license: str | None = None
    advisories: list[AdvisoryRef] = Field(default_factory=list)
    advisories_checked: bool = False
    infrastructure: str
    skills: list[str]
    finding_ids: list[str]
    evidence: Literal["verified_finding", "unverified"]
    component_ids: list[str]
    package: PackageRef | None = None
    vendor_lock_in: Literal["none", "low", "high"] = "none"
    significant_cost: bool = False


class TechnologySpec(BaseModel):
    technologies: list[Technology] = Field(default_factory=list)
    approval_candidates: list[ApprovalCandidate] = Field(default_factory=list)
    issues: list[SpecIssue] = Field(default_factory=list)

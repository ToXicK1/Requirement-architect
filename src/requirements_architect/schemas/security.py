"""Security and privacy models (Stage 8)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import FrId, NfrId, SpecIssue

ControlKey = Annotated[str, StringConstraints(pattern=r"^SC\d{1,3}$")]
ThreatKey = Annotated[str, StringConstraints(pattern=r"^TH\d{1,3}$")]
ControlId = Annotated[str, StringConstraints(pattern=r"^SC-\d{3,}$")]
ThreatId = Annotated[str, StringConstraints(pattern=r"^TH-\d{3,}$")]

COMPLIANCE_STATEMENT = (
    "Framework references in this document are a mapping aid, not a statement of compliance. "
    "Meeting any legal or regulatory obligation requires review by qualified people."
)


class ThreatCategory(StrEnum):
    SPOOFING = "spoofing"
    TAMPERING = "tampering"
    REPUDIATION = "repudiation"
    INFORMATION_DISCLOSURE = "information_disclosure"
    DENIAL_OF_SERVICE = "denial_of_service"
    ELEVATION_OF_PRIVILEGE = "elevation_of_privilege"
    PROMPT_INJECTION = "prompt_injection"
    INSECURE_OUTPUT_HANDLING = "insecure_output_handling"
    SENSITIVE_INFO_DISCLOSURE = "sensitive_information_disclosure"
    DATA_POISONING = "data_poisoning"
    EXCESSIVE_AGENCY = "excessive_agency"
    TOOL_ABUSE = "tool_abuse"
    MEMORY_POISONING = "memory_poisoning"
    CROSS_AGENT_TRUST = "cross_agent_trust"


STRIDE = frozenset(list(ThreatCategory)[:6])
AI_THREATS = frozenset(list(ThreatCategory)[6:])


class Level(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Treatment(StrEnum):
    MITIGATE = "mitigate"
    ACCEPT = "accept"
    TRANSFER = "transfer"
    AVOID = "avoid"


class ControlArea(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ENCRYPTION = "encryption"
    SECRETS = "secrets"
    API = "api"
    DATABASE = "database"
    INPUT_VALIDATION = "input_validation"
    NETWORK = "network"
    INFRASTRUCTURE = "infrastructure"
    PRIVACY = "privacy"
    RETENTION = "retention"
    AUDIT = "audit"
    SUPPLY_CHAIN = "supply_chain"
    BACKUP = "backup"
    AI_SAFETY = "ai_safety"


class RawControl(BaseModel):
    key: ControlKey
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    area: ControlArea
    requirement_ids: list[FrId | NfrId] = Field(default_factory=list, max_length=30)
    framework_refs: list[str] = Field(default_factory=list, max_length=6)


class RawThreat(BaseModel):
    key: ThreatKey
    title: str = Field(min_length=1, max_length=150)
    category: ThreatCategory
    asset: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=600)
    likelihood: Level
    impact: Level
    control_keys: list[ControlKey] = Field(default_factory=list, max_length=10)
    treatment: Treatment = Treatment.MITIGATE
    residual_note: str = Field(default="", max_length=400)


class RawSecurityTestItem(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    method: str = Field(min_length=1, max_length=300)
    control_keys: list[ControlKey] = Field(default_factory=list, max_length=10)


class RawSecurityOutput(BaseModel):
    is_ai_project: bool
    handles_sensitive_data: bool
    attack_surface: list[str] = Field(default_factory=list, max_length=20)
    threats: list[RawThreat] = Field(min_length=1, max_length=50)
    controls: list[RawControl] = Field(min_length=1, max_length=50)
    test_plan: list[RawSecurityTestItem] = Field(default_factory=list, max_length=40)
    privacy_requirements: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _unique_keys(self) -> RawSecurityOutput:
        for label, keys in (
            ("threat", [t.key for t in self.threats]),
            ("control", [c.key for c in self.controls]),
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} keys")
        return self


class Control(BaseModel):
    id: ControlId
    name: str
    description: str
    area: ControlArea
    requirement_ids: list[str]
    framework_refs: list[str]


class Threat(BaseModel):
    id: ThreatId
    title: str
    category: ThreatCategory
    asset: str
    description: str
    likelihood: Level
    impact: Level
    risk_score: int
    risk_level: str
    control_ids: list[ControlId]
    treatment: Treatment
    residual_note: str
    requires_approval: bool = False


class SecurityTestItem(BaseModel):
    name: str
    method: str
    control_ids: list[ControlId]


class SecuritySpec(BaseModel):
    is_ai_project: bool
    handles_sensitive_data: bool
    attack_surface: list[str] = Field(default_factory=list)
    threats: list[Threat] = Field(default_factory=list)
    controls: list[Control] = Field(default_factory=list)
    test_plan: list[SecurityTestItem] = Field(default_factory=list)
    privacy_requirements: list[str] = Field(default_factory=list)
    compliance_statement: str = COMPLIANCE_STATEMENT
    approval_candidates: list[ApprovalCandidate] = Field(default_factory=list)
    issues: list[SpecIssue] = Field(default_factory=list)

"""Requirements models (Stage 4).

Two layers: `Raw*` models are what the LLM may propose (no ids, no approval state);
final models carry ids and flags assigned by deterministic code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from requirements_architect.schemas.research import FindingId
from requirements_architect.schemas.state import Assumption

FrId = Annotated[str, StringConstraints(pattern=r"^FR-\d{3,}$")]
NfrId = Annotated[str, StringConstraints(pattern=r"^NFR-\d{3,}$")]
StoryId = Annotated[str, StringConstraints(pattern=r"^US-\d{3,}$")]
ObjectiveId = Annotated[str, StringConstraints(pattern=r"^OBJ-\d{3,}$")]
LocalKey = Annotated[str, StringConstraints(pattern=r"^R\d{1,3}$")]


class Priority(StrEnum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"
    WONT = "wont"


class ValidationMethod(StrEnum):
    TEST = "test"
    DEMONSTRATION = "demonstration"
    INSPECTION = "inspection"
    ANALYSIS = "analysis"


class NfrCategory(StrEnum):
    PERFORMANCE = "performance"
    SCALABILITY = "scalability"
    AVAILABILITY = "availability"
    RELIABILITY = "reliability"
    MAINTAINABILITY = "maintainability"
    SECURITY = "security"
    PRIVACY = "privacy"
    ACCESSIBILITY = "accessibility"
    COMPATIBILITY = "compatibility"
    OBSERVABILITY = "observability"
    DISASTER_RECOVERY = "disaster_recovery"
    DATA_INTEGRITY = "data_integrity"


class RuleBasis(StrEnum):
    STATED = "stated"  # the user said so
    ASSUMPTION = "assumption"  # the model inferred it; must be confirmed by a human


class TargetStatus(StrEnum):
    NONE = "none"  # qualitative requirement, no numeric target
    PROPOSED = "proposed"  # suggested by the system; NOT a commitment
    USER_APPROVED = "user_approved"  # set only by approve_nfr_targets()


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class AcceptanceCriterion(BaseModel):
    given: str = Field(min_length=1, max_length=400)
    when: str = Field(min_length=1, max_length=400)
    then: str = Field(min_length=1, max_length=400)


class BusinessRule(BaseModel):
    statement: str = Field(min_length=1, max_length=400)
    basis: RuleBasis


class RawFunctionalRequirement(BaseModel):
    key: LocalKey
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1200)
    justification: str = Field(min_length=1, max_length=600)
    objective: str | None = None  # must equal one of the brief's objectives, else null
    actor: str = Field(min_length=1, max_length=120)
    trigger: str = Field(min_length=1, max_length=300)
    preconditions: list[str] = Field(default_factory=list, max_length=10)
    inputs: list[str] = Field(default_factory=list, max_length=15)
    expected_behavior: str = Field(min_length=1, max_length=1500)
    outputs: list[str] = Field(default_factory=list, max_length=15)
    business_rules: list[BusinessRule] = Field(default_factory=list, max_length=10)
    failure_scenarios: list[str] = Field(default_factory=list, max_length=10)
    depends_on: list[LocalKey] = Field(default_factory=list, max_length=10)
    priority: Priority
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1, max_length=10)
    validation_method: ValidationMethod
    finding_ids: list[FindingId] = Field(default_factory=list, max_length=8)
    depends_on_external_facts: bool = False


class RawNonFunctionalRequirement(BaseModel):
    category: NfrCategory
    statement: str = Field(min_length=1, max_length=600)
    target: str | None = Field(default=None, max_length=200)
    measurement_method: str | None = Field(default=None, max_length=300)
    rationale: str = Field(min_length=1, max_length=600)
    finding_ids: list[FindingId] = Field(default_factory=list, max_length=8)


class RawUserStory(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    want: str = Field(min_length=1, max_length=300)
    benefit: str = Field(min_length=1, max_length=300)
    requirement_keys: list[LocalKey] = Field(min_length=1, max_length=10)


class RawRequirementsOutput(BaseModel):
    functional: list[RawFunctionalRequirement] = Field(min_length=1, max_length=40)
    nonfunctional: list[RawNonFunctionalRequirement] = Field(default_factory=list, max_length=40)
    user_stories: list[RawUserStory] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def _unique_keys(self) -> RawRequirementsOutput:
        keys = [r.key for r in self.functional]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate functional requirement keys")
        return self


class Objective(BaseModel):
    id: ObjectiveId
    text: str


class FunctionalRequirement(BaseModel):
    id: FrId
    name: str
    description: str
    justification: str
    objective_id: ObjectiveId | None
    actor: str
    trigger: str
    preconditions: list[str]
    inputs: list[str]
    expected_behavior: str
    outputs: list[str]
    business_rules: list[BusinessRule]
    failure_scenarios: list[str]
    dependencies: list[FrId]
    priority: Priority
    acceptance_criteria: list[AcceptanceCriterion]
    validation_method: ValidationMethod
    finding_ids: list[FindingId]
    needs_confirmation: bool = False


class NonFunctionalRequirement(BaseModel):
    id: NfrId
    category: NfrCategory
    statement: str
    target: str | None
    target_status: TargetStatus
    measurement_method: str | None
    rationale: str
    finding_ids: list[FindingId]


class UserStory(BaseModel):
    id: StoryId
    actor: str
    want: str
    benefit: str
    requirement_ids: list[FrId]


class SpecIssue(BaseModel):
    code: str
    severity: Severity
    message: str
    ref: str | None = None


class RequirementsSpec(BaseModel):
    objectives: list[Objective] = Field(default_factory=list)
    functional: list[FunctionalRequirement] = Field(default_factory=list)
    nonfunctional: list[NonFunctionalRequirement] = Field(default_factory=list)
    user_stories: list[UserStory] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    issues: list[SpecIssue] = Field(default_factory=list)

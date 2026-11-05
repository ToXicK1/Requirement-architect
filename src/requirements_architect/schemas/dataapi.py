"""Database and API models (Stage 7)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, model_validator

from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import FrId, NfrId, SpecIssue

EntKey = Annotated[str, StringConstraints(pattern=r"^E\d{1,3}$")]
EpKey = Annotated[str, StringConstraints(pattern=r"^EP\d{1,3}$")]
EntityId = Annotated[str, StringConstraints(pattern=r"^E-\d{3,}$")]
EndpointId = Annotated[str, StringConstraints(pattern=r"^EP-\d{3,}$")]
SqlName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$")]


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class AuthType(StrEnum):
    NONE = "none"
    SESSION = "session"
    BEARER = "bearer"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"


class OnDelete(StrEnum):
    CASCADE = "cascade"
    RESTRICT = "restrict"
    SET_NULL = "set_null"
    NO_ACTION = "no_action"


class Field_(BaseModel):
    name: SqlName
    type: str = Field(min_length=1, max_length=40)
    nullable: bool = False
    primary_key: bool = False
    unique: bool = False
    default: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=300)


class Index(BaseModel):
    fields: list[SqlName] = Field(min_length=1, max_length=8)
    unique: bool = False


class RawForeignKey(BaseModel):
    field: SqlName
    references_entity: EntKey
    references_field: SqlName = "id"
    on_delete: OnDelete = OnDelete.RESTRICT


class ErrorResponse(BaseModel):
    status: int = Field(ge=400, le=599)
    meaning: str = Field(min_length=1, max_length=200)


class RawEntity(BaseModel):
    key: EntKey
    name: SqlName
    description: str = Field(min_length=1, max_length=400)
    fields: list[Field_] = Field(min_length=1, max_length=60)
    foreign_keys: list[RawForeignKey] = Field(default_factory=list, max_length=20)
    indexes: list[Index] = Field(default_factory=list, max_length=15)
    constraints: list[str] = Field(default_factory=list, max_length=15)
    retention: str | None = Field(default=None, max_length=300)
    validation_rules: list[str] = Field(default_factory=list, max_length=15)
    requirement_ids: list[FrId | NfrId] = Field(default_factory=list, max_length=30)


class RawEndpoint(BaseModel):
    key: EpKey
    method: HttpMethod
    path: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=300)
    authentication: AuthType
    authorization: str = Field(default="", max_length=300)
    request_schema: str | None = Field(default=None, max_length=100)
    response_schema: str | None = Field(default=None, max_length=100)
    validation: list[str] = Field(default_factory=list, max_length=10)
    error_responses: list[ErrorResponse] = Field(default_factory=list, max_length=10)
    success_status: int = Field(default=200, ge=200, le=299)
    rate_limit: str | None = Field(default=None, max_length=100)
    dependencies: list[str] = Field(default_factory=list, max_length=10)
    entity_keys: list[EntKey] = Field(default_factory=list, max_length=10)
    requirement_ids: list[FrId | NfrId] = Field(default_factory=list, max_length=30)


class RawDataApi(BaseModel):
    entities: list[RawEntity] = Field(default_factory=list, max_length=60)
    endpoints: list[RawEndpoint] = Field(default_factory=list, max_length=120)
    migration_strategy: str = Field(default="", max_length=800)
    interface_note: str = Field(
        default="", max_length=800
    )  # when there is no database or no HTTP API

    @model_validator(mode="after")
    def _unique_keys(self) -> RawDataApi:
        for label, keys in (
            ("entity", [e.key for e in self.entities]),
            ("endpoint", [e.key for e in self.endpoints]),
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} keys")
        return self


class ForeignKey(BaseModel):
    field: str
    references_entity: EntityId
    references_field: str
    on_delete: OnDelete


class Entity(BaseModel):
    id: EntityId
    name: str
    description: str
    fields: list[Field_]
    foreign_keys: list[ForeignKey]
    indexes: list[Index]
    constraints: list[str]
    retention: str | None
    validation_rules: list[str]
    requirement_ids: list[str]


class Endpoint(BaseModel):
    id: EndpointId
    method: HttpMethod
    path: str
    purpose: str
    authentication: AuthType
    authorization: str
    request_schema: str | None
    response_schema: str | None
    validation: list[str]
    error_responses: list[ErrorResponse]
    success_status: int
    rate_limit: str | None
    dependencies: list[str]
    entity_ids: list[str]
    requirement_ids: list[str]


class DataApiSpec(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    migration_strategy: str = ""
    interface_note: str = ""
    er_diagram: str = ""
    openapi: dict[str, Any] = Field(default_factory=dict)
    approval_candidates: list[ApprovalCandidate] = Field(default_factory=list)
    issues: list[SpecIssue] = Field(default_factory=list)

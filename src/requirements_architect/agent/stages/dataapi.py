"""Stage 7: database and API design. Code validates integrity (keys, references, uniqueness),
renders the ER diagram and generates the OpenAPI document."""

from __future__ import annotations

import re

from requirements_architect.agent.stages.common import (
    StageContext,
    base_untrusted,
    render_architecture,
    render_technology,
    run_stage,
)
from requirements_architect.generators import mermaid
from requirements_architect.generators.openapi import build_openapi, path_shape
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.dataapi import (
    AuthType,
    DataApiSpec,
    Endpoint,
    Entity,
    ForeignKey,
    HttpMethod,
    RawDataApi,
)
from requirements_architect.schemas.requirements import RequirementsSpec, Severity, SpecIssue

_PATH_OK = re.compile(r"^/[A-Za-z0-9._~\-/{}]*$")
_MUTATING = {HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE}


def _issue(
    issues: list[SpecIssue], code: str, msg: str, ref: str | None = None, *, error: bool = False
) -> None:
    issues.append(
        SpecIssue(
            code=code, severity=Severity.ERROR if error else Severity.WARNING, message=msg, ref=ref
        )
    )


def build_data_api(
    raw: RawDataApi, reqs: RequirementsSpec, project_name: str = "API"
) -> DataApiSpec:
    issues: list[SpecIssue] = []
    valid_reqs = {f.id for f in reqs.functional} | {n.id for n in reqs.nonfunctional}

    # ---- entities ------------------------------------------------------------------------------
    key_to_id: dict[str, str] = {}
    first_by_name: dict[str, str] = {}
    kept_raw = []
    for i, e in enumerate(raw.entities, 1):
        eid = f"E-{i:03d}"
        if e.name in first_by_name:
            _issue(
                issues,
                "DUPLICATE_ENTITY",
                f"{eid} reuses table name '{e.name}'; dropped",
                eid,
                error=True,
            )
            key_to_id[e.key] = first_by_name[e.name]
            continue
        first_by_name[e.name] = eid
        key_to_id[e.key] = eid
        kept_raw.append((eid, e))
    fields_of = {eid: {f.name for f in e.fields} for eid, e in kept_raw}

    entities: list[Entity] = []
    for eid, e in kept_raw:
        seen: set[str] = set()
        fields = []
        for f in e.fields:
            if f.name in seen:
                _issue(
                    issues,
                    "DUPLICATE_FIELD",
                    f"{eid} repeats field '{f.name}'; dropped",
                    eid,
                    error=True,
                )
                continue
            seen.add(f.name)
            fields.append(f)
        if not any(f.primary_key for f in fields):
            _issue(
                issues,
                "ENTITY_NO_PRIMARY_KEY",
                f"{eid} ({e.name}) has no primary key",
                eid,
                error=True,
            )
        fks: list[ForeignKey] = []
        for fk in e.foreign_keys:
            target = key_to_id.get(fk.references_entity)
            if fk.field not in seen:
                _issue(
                    issues,
                    "FK_UNKNOWN_FIELD",
                    f"{eid}: foreign key on unknown field '{fk.field}'",
                    eid,
                    error=True,
                )
            elif target is None:
                _issue(
                    issues,
                    "FK_UNKNOWN_ENTITY",
                    f"{eid}.{fk.field} references unknown entity {fk.references_entity}",
                    eid,
                    error=True,
                )
            elif fk.references_field not in fields_of[target]:
                _issue(
                    issues,
                    "FK_UNKNOWN_TARGET_FIELD",
                    f"{eid}.{fk.field} references unknown field {target}.{fk.references_field}",
                    eid,
                    error=True,
                )
            else:
                fks.append(
                    ForeignKey(
                        field=fk.field,
                        references_entity=target,
                        references_field=fk.references_field,
                        on_delete=fk.on_delete,
                    )
                )
        indexes = []
        for ix in e.indexes:
            if all(c in seen for c in ix.fields):
                indexes.append(ix)
            else:
                _issue(
                    issues,
                    "INDEX_UNKNOWN_FIELD",
                    f"{eid}: index on unknown field(s) {ix.fields}; dropped",
                    eid,
                )
        reqs_ok = [r for r in dict.fromkeys(e.requirement_ids) if r in valid_reqs]
        for r in dict.fromkeys(e.requirement_ids):
            if r not in valid_reqs:
                _issue(issues, "UNKNOWN_REQUIREMENT", f"{eid} cites unknown requirement {r}", eid)
        if not reqs_ok:
            _issue(issues, "ORPHAN_ENTITY", f"{eid} ({e.name}) serves no requirement", eid)
        entities.append(
            Entity(
                id=eid,
                name=e.name,
                description=e.description,
                fields=fields,
                foreign_keys=fks,
                indexes=indexes,
                constraints=e.constraints,
                retention=e.retention,
                validation_rules=e.validation_rules,
                requirement_ids=reqs_ok,
            )
        )

    # ---- endpoints -----------------------------------------------------------------------------
    endpoints: list[Endpoint] = []
    seen_ops: set[tuple[HttpMethod, str]] = set()
    for i, ep in enumerate(raw.endpoints, 1):
        epid = f"EP-{i:03d}"
        if not _PATH_OK.match(ep.path) or ".." in ep.path or "//" in ep.path:
            _issue(
                issues,
                "ENDPOINT_INVALID_PATH",
                f"{epid} has an invalid path; dropped",
                epid,
                error=True,
            )
            continue
        op = (ep.method, path_shape(ep.path))
        if op in seen_ops:
            _issue(
                issues,
                "DUPLICATE_ENDPOINT",
                f"{epid} duplicates {ep.method.value} {ep.path}; dropped",
                epid,
                error=True,
            )
            continue
        seen_ops.add(op)
        if ep.authentication is AuthType.NONE:
            if ep.method in _MUTATING:
                _issue(
                    issues,
                    "UNAUTHENTICATED_MUTATION",
                    f"{epid} changes data without authentication",
                    epid,
                    error=True,
                )
            if not ep.rate_limit:
                _issue(
                    issues,
                    "UNAUTHENTICATED_NO_RATE_LIMIT",
                    f"{epid} is unauthenticated and has no rate limit",
                    epid,
                )
        else:
            if not ep.authorization.strip():
                _issue(
                    issues,
                    "NO_AUTHORIZATION_RULE",
                    f"{epid} is authenticated but states no authorization rule",
                    epid,
                )
            if not {401, 403} & {e.status for e in ep.error_responses}:
                _issue(issues, "MISSING_AUTH_ERRORS", f"{epid} documents no 401/403 response", epid)
        if ep.request_schema and not {400, 422} & {e.status for e in ep.error_responses}:
            _issue(
                issues,
                "MISSING_VALIDATION_ERROR",
                f"{epid} takes input but documents no 400/422 response",
                epid,
            )
        if (ep.method is HttpMethod.GET and ep.success_status != 200) or (
            ep.method is HttpMethod.DELETE and ep.success_status not in (200, 202, 204)
        ):
            _issue(
                issues,
                "STATUS_METHOD_MISMATCH",
                f"{epid}: {ep.success_status} is unusual for {ep.method.value}",
                epid,
            )
        ents = [key_to_id[k] for k in dict.fromkeys(ep.entity_keys) if k in key_to_id]
        for k in dict.fromkeys(ep.entity_keys):
            if k not in key_to_id:
                _issue(issues, "UNKNOWN_ENTITY", f"{epid} cites unknown entity {k}", epid)
        reqs_ok = [r for r in dict.fromkeys(ep.requirement_ids) if r in valid_reqs]
        for r in dict.fromkeys(ep.requirement_ids):
            if r not in valid_reqs:
                _issue(issues, "UNKNOWN_REQUIREMENT", f"{epid} cites unknown requirement {r}", epid)
        if not reqs_ok:
            _issue(issues, "ORPHAN_ENDPOINT", f"{epid} serves no requirement", epid)
        endpoints.append(
            Endpoint(
                id=epid,
                method=ep.method,
                path=ep.path,
                purpose=ep.purpose,
                authentication=ep.authentication,
                authorization=ep.authorization,
                request_schema=ep.request_schema,
                response_schema=ep.response_schema,
                validation=ep.validation,
                error_responses=ep.error_responses,
                success_status=ep.success_status,
                rate_limit=ep.rate_limit,
                dependencies=ep.dependencies,
                entity_ids=ents,
                requirement_ids=reqs_ok,
            )
        )

    if endpoints:
        used = {x for e in endpoints for x in e.entity_ids}
        for en in entities:
            if en.id not in used:
                _issue(
                    issues,
                    "ENTITY_NO_ENDPOINT",
                    f"{en.id} ({en.name}) is not touched by any endpoint",
                    en.id,
                )
    if not entities and not endpoints and not raw.interface_note.strip():
        _issue(
            issues,
            "NO_INTERFACE_DEFINED",
            "no entities, endpoints or interface note were provided",
            error=True,
        )

    er = (
        mermaid.er_diagram(
            [(e.name, [(f.type, f.name) for f in e.fields]) for e in entities],
            [
                (e.name, next(x.name for x in entities if x.id == fk.references_entity), fk.field)
                for e in entities
                for fk in e.foreign_keys
            ],
        )
        if entities
        else ""
    )
    return DataApiSpec(
        entities=entities,
        endpoints=endpoints,
        migration_strategy=raw.migration_strategy,
        interface_note=raw.interface_note,
        er_diagram=er,
        openapi=build_openapi(project_name, endpoints) if endpoints else {},
        issues=issues,
    )


async def generate_data_api(gateway: LLMGateway, ctx: StageContext) -> DataApiSpec:
    tech_txt = render_technology(ctx.extras.get("technology"))
    untrusted = base_untrusted(ctx) | {
        "architecture": render_architecture(ctx.architecture),
        "technology": tech_txt,
    }
    raw = await run_stage(gateway, "data_api", ctx, RawDataApi, untrusted)
    return build_data_api(raw, ctx.requirements, ctx.brief.actual_problem[:60] or "API")

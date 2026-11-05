from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable
from requirements_architect.schemas.technology import ClaimStatus


def render(i: DocInputs) -> list[Doc]:
    t, api = i.technology, i.data_api
    stack = md.join(
        md.table(
            [
                "ID",
                "Name",
                "Category",
                "Purpose",
                "Version",
                "Version status",
                "License",
                "License status",
                "Evidence",
            ],
            [
                (
                    x.id,
                    x.name,
                    x.category.value,
                    x.purpose,
                    x.recommended_version or "not specified",
                    x.version_status.value,
                    x.license or "not specified",
                    x.license_status.value,
                    x.evidence,
                )
                for x in t.technologies
            ],
        ),
        "Only versions with status `confirmed` were checked against a package registry. "
        "Other versions are suggestions and must be verified before use.",
        *[
            md.join(
                md.section(f"{x.id} - {x.name}", level=3),
                f"**Reason:** {md.text(x.reason)}",
                f"**Alternatives:** {md.text(', '.join(x.alternatives) or 'none recorded')}",
                "**Advantages:**\n\n" + (md.bullets(x.advantages) or "none recorded"),
                "**Disadvantages:**\n\n" + (md.bullets(x.disadvantages) or "none recorded"),
                f"**Vendor lock-in:** {x.vendor_lock_in}; **significant cost:** {'yes' if x.significant_cost else 'no'}",
                f"**Components:** {', '.join(x.component_ids) or 'none'}",
            )
            for x in t.technologies
        ],
    )
    dep_rows = [
        (
            x.name,
            ", ".join(x.dependencies) or "-",
            x.recommended_version or "-",
            x.license or "-",
            ("none known" if not x.advisories else ", ".join(a.advisory_id for a in x.advisories))
            if x.advisories_checked
            else "not checked",
        )
        for x in t.technologies
    ]
    deps = md.join(
        md.table(["Technology", "Depends on", "Version", "License", "Advisories"], dep_rows),
        "`not checked` means no vulnerability database was consulted for that technology; "
        "it does not mean the package is free of vulnerabilities.",
    )
    unconfirmed = [x.name for x in t.technologies if x.license_status is not ClaimStatus.CONFIRMED]
    if unconfirmed:
        deps += (
            "\nLicenses not confirmed against a registry: " + md.text(", ".join(unconfirmed)) + "\n"
        )

    docs = [
        Doc("04_TECHNICAL_SPECIFICATIONS/TECHNOLOGY_STACK.md", "Technology Stack", stack),
        Doc("04_TECHNICAL_SPECIFICATIONS/DEPENDENCIES.md", "Dependencies", deps),
    ]
    if api.entities:
        ents = []
        for e in api.entities:
            ents.append(
                md.join(
                    md.section(f"{e.id} - {e.name}", md.text(e.description), level=2),
                    md.table(
                        ["Field", "Type", "Nullable", "PK", "Unique", "Default", "Description"],
                        [
                            (
                                f.name,
                                f.type,
                                f.nullable,
                                f.primary_key,
                                f.unique,
                                f.default or "-",
                                f.description,
                            )
                            for f in e.fields
                        ],
                    ),
                    (
                        "**Foreign keys:**\n\n"
                        + md.bullets(
                            f"{k.field} -> {k.references_entity}.{k.references_field} (on delete {k.on_delete.value})"
                            for k in e.foreign_keys
                        )
                    )
                    if e.foreign_keys
                    else "",
                    (
                        "**Indexes:**\n\n"
                        + md.bullets(
                            f"({', '.join(x.fields)}){' unique' if x.unique else ''}"
                            for x in e.indexes
                        )
                    )
                    if e.indexes
                    else "",
                    ("**Constraints:**\n\n" + md.bullets(e.constraints)) if e.constraints else "",
                    ("**Validation rules:**\n\n" + md.bullets(e.validation_rules))
                    if e.validation_rules
                    else "",
                    f"**Retention:** {md.text(e.retention or 'not specified')}",
                    f"**Requirements:** {', '.join(e.requirement_ids) or 'none'}",
                )
            )
        docs.append(
            Doc(
                "04_TECHNICAL_SPECIFICATIONS/DATABASE_SCHEMA.md",
                "Database Schema",
                md.join(
                    md.section("Entity-relationship diagram", md.mermaid(api.er_diagram)),
                    *ents,
                    md.section(
                        "Migration strategy", md.text(api.migration_strategy or "Not specified.")
                    ),
                ),
            )
        )
    else:
        docs.append(
            not_applicable(
                "04_TECHNICAL_SPECIFICATIONS/DATABASE_SCHEMA.md",
                "Database Schema",
                api.interface_note or "No persistent data entities were identified.",
            )
        )
    if api.endpoints:
        eps = md.table(
            [
                "ID",
                "Method",
                "Path",
                "Purpose",
                "Auth",
                "Authorization",
                "Success",
                "Errors",
                "Requirements",
            ],
            [
                (
                    e.id,
                    e.method.value,
                    e.path,
                    e.purpose,
                    e.authentication.value,
                    e.authorization,
                    e.success_status,
                    ", ".join(str(x.status) for x in e.error_responses) or "-",
                    ", ".join(e.requirement_ids),
                )
                for e in api.endpoints
            ],
        )
        docs.append(
            Doc(
                "04_TECHNICAL_SPECIFICATIONS/API_SPECIFICATION.md",
                "API Specification",
                md.join(
                    eps,
                    md.section(
                        "Machine-readable specification",
                        "The OpenAPI 3.1 document is included in the package as `openapi.json`. "
                        "It was generated by code and passed a structural check only; it has not "
                        "been validated by a full OpenAPI validator.",
                    ),
                    md.section("Endpoint details", level=2),
                    *[
                        md.join(
                            md.section(f"{e.id} {e.method.value} {e.path}", level=3),
                            f"**Validation:** {md.text('; '.join(e.validation) or 'none recorded')}",
                            f"**Rate limit:** {md.text(e.rate_limit or 'not specified')}",
                            "**Errors:**\n\n"
                            + (
                                md.bullets(f"{x.status}: {x.meaning}" for x in e.error_responses)
                                or "none recorded"
                            ),
                        )
                        for e in api.endpoints
                    ],
                ),
            )
        )
    else:
        docs.append(
            not_applicable(
                "04_TECHNICAL_SPECIFICATIONS/API_SPECIFICATION.md",
                "API Specification",
                api.interface_note or "No HTTP API endpoints were identified.",
            )
        )
    external = [c for c in i.architecture.components if c.kind.value == "external"]
    ext_tech = [x for x in t.technologies if x.category.value in {"llm_provider", "api", "cloud"}]
    if external or ext_tech:
        docs.append(
            Doc(
                "04_TECHNICAL_SPECIFICATIONS/INTEGRATIONS.md",
                "Integrations",
                md.join(
                    md.section(
                        "External components",
                        md.table(
                            ["ID", "Name", "Responsibility"],
                            [(c.id, c.name, c.responsibility) for c in external],
                        )
                        or "None.",
                    ),
                    md.section(
                        "External services and providers",
                        md.table(
                            ["ID", "Name", "Category", "Purpose"],
                            [(x.id, x.name, x.category.value, x.purpose) for x in ext_tech],
                        )
                        or "None.",
                    ),
                ),
            )
        )
    else:
        docs.append(
            not_applicable(
                "04_TECHNICAL_SPECIFICATIONS/INTEGRATIONS.md",
                "Integrations",
                "No external components or external service providers were identified.",
            )
        )
    return docs

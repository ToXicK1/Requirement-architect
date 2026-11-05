"""Assemble the full documentation package (Markdown tree + supporting files) from the specs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from requirements_architect.generators.docs import (
    architecture,
    business,
    implementation,
    md,
    overview,
    qa,
    security,
    software,
    technical,
    ux,
    validation,
)
from requirements_architect.generators.docs.model import Doc, DocInputs
from requirements_architect.generators.docs.tasks import Plan, build_plan
from requirements_architect.validation.traceability import TraceLink, to_csv

# Documents the target structure names but that cannot honestly be produced yet.
AUDIT_DOCUMENTS = (
    "10_VALIDATION/REQUIREMENTS_AUDIT.md",
    "10_VALIDATION/FINAL_READINESS_REPORT.md",
)
PENDING_DOCUMENTS = dict.fromkeys(AUDIT_DOCUMENTS, "the audit has not been run")

_FOLDER_RE = re.compile(r"^\d{2}_[A-Z_]+/[A-Z0-9_]+\.md$")


@dataclass
class Package:
    docs: list[Doc]  # complete Markdown text, metadata header included
    files: dict[str, bytes]  # supporting files (path relative to ROOT)
    plan: Plan
    links: list[TraceLink]
    pending: dict[str, str] = field(default_factory=dict)


def _header(doc: Doc, i: DocInputs) -> str:
    rows = [
        ("Project", i.project_name),
        ("Project ID", i.project_id),
        ("Package version", i.package_version),
        ("Generated", i.generated_at.strftime("%Y-%m-%d %H:%M UTC")),
        ("Approval status", i.approval_status),
    ]
    if not doc.applicable:
        rows.append(("Applicability", "Not applicable (reason below)"))
    return md.join(f"# {md.text(doc.title)}", md.table(["Field", "Value"], rows))


def _readme(docs: list[Doc], i: DocInputs, pending: dict[str, str]) -> str:
    rows = [
        (d.path, d.title, "yes" if d.applicable else "no (explained in document)") for d in docs
    ]
    return md.join(
        f"# {md.text(i.project_name)} - Documentation Package",
        md.table(
            ["Field", "Value"],
            [
                ("Project ID", i.project_id),
                ("Package version", i.package_version),
                ("Generated", i.generated_at.strftime("%Y-%m-%d %H:%M UTC")),
                ("Approval status", i.approval_status),
            ],
        ),
        "This package was generated from analysis stage outputs. It is a draft for human review. "
        "Items marked `proposed` or `unverified` have not been confirmed.",
        md.section("Documents", md.table(["Path", "Title", "Applicable"], rows)),
        md.section(
            "Documents not yet generated",
            md.table(["Path", "Reason"], list(pending.items())) or "None.",
        ),
    )


def build_package(i: DocInputs) -> Package:
    plan = build_plan(i)
    parts: list[Doc] = [
        *overview.render(i),
        *business.render(i),
        *software.render(i),
        *architecture.render(i),
        *technical.render(i),
        *security.render(i),
        *ux.render(i),
        *qa.render(i),
        *qa.render_infra(i),
        *implementation.render(i, plan),
        *validation.render(i, plan),
        *validation.render_audit(i),
    ]
    paths = [d.path for d in parts]
    if len(paths) != len(set(paths)) or not all(_FOLDER_RE.match(p) for p in paths):
        raise ValueError("document paths are not unique or not well formed")
    docs = [Doc(d.path, d.title, md.join(_header(d, i), d.body), d.applicable) for d in parts]
    pending = (
        {}
        if i.audit
        else dict.fromkeys(AUDIT_DOCUMENTS, i.audit_note or "the audit has not been run")
    )
    docs.insert(0, Doc("README.md", "Documentation Package", _readme(docs, i, pending)))

    links = validation.all_links(i, plan)
    files: dict[str, bytes] = {
        "traceability.csv": to_csv(i.requirements, links).encode("utf-8"),
    }
    if i.data_api.openapi:
        files["openapi.json"] = (
            json.dumps(i.data_api.openapi, indent=2, sort_keys=True) + "\n"
        ).encode()
    diagrams = {
        "context": i.architecture.context_diagram,
        "components": i.architecture.component_diagram,
        "dataflow": i.architecture.dataflow_diagram,
        "er": i.data_api.er_diagram,
    }
    for n, seq in enumerate(i.architecture.sequences, 1):
        diagrams[f"sequence_{n:02d}"] = seq.mermaid
    for name, code in diagrams.items():
        if code.strip():
            files[f"diagrams/{name}.mmd"] = (code.rstrip() + "\n").encode()
    return Package(docs, files, plan, links, pending)

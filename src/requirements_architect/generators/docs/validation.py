from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable
from requirements_architect.generators.docs.tasks import Plan, task_links
from requirements_architect.validation.design_traceability import design_links, design_targets
from requirements_architect.validation.traceability import (
    TraceKind,
    TraceLink,
    TraceReport,
    analyze,
    links_from_spec,
)

REQUIRED = (
    TraceKind.OBJECTIVE,
    TraceKind.STORY,
    TraceKind.COMPONENT,
    TraceKind.TEST,
    TraceKind.TASK,
)


def all_links(i: DocInputs, plan: Plan) -> list[TraceLink]:
    return [
        *links_from_spec(i.requirements),
        *design_links(i.architecture, i.data_api, i.security, i.qa),
        *task_links(plan),
    ]


def report(i: DocInputs, plan: Plan, links: list[TraceLink]) -> TraceReport:
    targets = design_targets(i.architecture, i.data_api, i.security, i.qa)
    targets[TraceKind.TASK] = {t.id for t in plan.tasks}
    return analyze(i.requirements, links, REQUIRED, targets)


def render(i: DocInputs, plan: Plan) -> list[Doc]:
    links = all_links(i, plan)
    rep = report(i, plan, links)
    by: dict[tuple[str, TraceKind], list[str]] = {}
    for link in links:
        by.setdefault((link.requirement_id, link.kind), []).append(link.target_id)
    kinds = [
        TraceKind.OBJECTIVE,
        TraceKind.STORY,
        TraceKind.COMPONENT,
        TraceKind.ENTITY,
        TraceKind.ENDPOINT,
        TraceKind.CONTROL,
        TraceKind.TEST,
        TraceKind.TASK,
    ]
    rows = [
        (f.id, *[", ".join(sorted(set(by.get((f.id, k), [])))) or "-" for k in kinds])
        for f in i.requirements.functional
    ]
    matrix = md.join(
        md.section(
            "Coverage",
            md.table(
                ["Link type", "Functional requirements covered"],
                [(k.value, f"{rep.coverage.get(k, 0):.0%}") for k in REQUIRED],
            ),
        ),
        md.section(
            "Matrix",
            md.table(["Requirement", *[k.value for k in kinds]], rows)
            or "No functional requirements.",
        ),
        md.section(
            "Gaps",
            md.table(
                ["Requirement", "Missing link types"],
                [(r, ", ".join(k.value for k in ks)) for r, ks in rep.uncovered.items()],
            )
            or "No requirement is missing a required link.",
            md.table(
                ["Kind", "Target never traced to a requirement"],
                [(o.kind.value, o.target_id) for o in rep.orphan_targets],
            ),
            md.table(
                ["Requirement", "Kind", "Target"],
                [(d.requirement_id, d.kind.value, d.target_id) for d in rep.dangling_links],
            ),
        ),
        "Non-functional requirements are checked through test coverage in the QA stage "
        "(`NFR_NO_TEST` issues) and are not part of this matrix. "
        "A machine-readable export is included as `traceability.csv`.",
    )
    sec = i.security
    risks = (
        md.join(
            md.table(
                [
                    "ID",
                    "Risk",
                    "Level",
                    "Score",
                    "Treatment",
                    "Controls",
                    "Residual risk",
                    "Needs approval",
                ],
                [
                    (
                        t.id,
                        t.title,
                        t.risk_level,
                        t.risk_score,
                        t.treatment.value,
                        ", ".join(t.control_ids) or "none",
                        t.residual_note or "-",
                        "yes" if t.requires_approval else "no",
                    )
                    for t in sorted(sec.threats, key=lambda x: (-x.risk_score, x.id))
                ],
            ),
            "Scores are computed from likelihood and impact by fixed rules. They are estimates "
            "made by a model and confirmed by no one.",
        )
        if sec.threats
        else None
    )
    docs = [Doc("10_VALIDATION/TRACEABILITY_MATRIX.md", "Traceability Matrix", matrix)]
    docs.append(
        Doc("10_VALIDATION/RISK_REGISTER.md", "Risk Register", risks)
        if risks
        else not_applicable(
            "10_VALIDATION/RISK_REGISTER.md",
            "Risk Register",
            "No threats were identified in the security analysis.",
        )
    )
    return docs

from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable
from requirements_architect.generators.docs.tasks import Plan, task_links
from requirements_architect.schemas.audit import AuditSeverity
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


def render_audit(i: DocInputs) -> list[Doc]:
    """REQUIREMENTS_AUDIT.md and FINAL_READINESS_REPORT.md; only when a current audit exists."""
    a = i.audit
    if a is None:
        return []
    by_sev = {s.value: a.count(s) for s in AuditSeverity}
    findings = md.table(
        ["ID", "Severity", "Category", "Source", "Code", "References", "Finding", "Resolution"],
        [
            (
                f.id,
                f.severity.value,
                f.category.value,
                f.source,
                f.code,
                ", ".join(f.refs) or "-",
                f.message,
                "regenerate automatically"
                if f.auto_fixable and not f.needs_human
                else "human decision",
            )
            for f in a.findings
        ],
    )
    audit = md.join(
        md.section("Verdict", f"**{a.verdict.value}**", md.text(_VERDICT_NOTE[a.verdict.value])),
        md.section(
            "Quality gates",
            md.table(
                ["Gate", "Result", "Detail"],
                [(g.name, "pass" if g.passed else "FAIL", g.detail) for g in a.gates],
            ),
        ),
        md.section("Findings by severity", md.table(["Severity", "Count"], list(by_sev.items()))),
        md.section("Findings", findings or "No findings."),
        md.section(
            "Remediation tasks",
            md.table(
                ["Task", "Finding", "Owner", "Action"],
                [(t.id, t.finding_id, t.owner, t.action) for t in a.tasks],
            )
            or "None.",
        ),
        md.section(
            "Audit rounds",
            md.table(
                ["Round", "Findings", "Blocker", "Major", "Minor", "Info", "Stages regenerated"],
                [
                    (
                        r.round,
                        r.findings,
                        *[r.by_severity.get(k, 0) for k in ("blocker", "major", "minor", "info")],
                        ", ".join(r.regenerated) or "-",
                    )
                    for r in a.rounds
                ],
            ),
        ),
        md.section(
            "Independent review",
            f"LLM review: {a.llm_review}. "
            + (
                f"{a.llm_discarded} model finding(s) were discarded because they cited ids that do not exist. "
                if a.llm_discarded
                else ""
            )
            + "Model findings are judgments, never auto-applied, and can be dismissed by a human.",
        ),
        md.section("Limitations", md.bullets(a.limitations)),
    )
    humans = [t for t in a.tasks if t.owner == "human"]
    approvals = [f for f in a.findings if f.code == "AWAITING_APPROVAL"]
    open_auto = [t for t in a.tasks if t.owner == "auto"]
    ready = md.join(
        md.section(
            "Readiness verdict", f"**{a.verdict.value}**", md.text(_VERDICT_NOTE[a.verdict.value])
        ),
        md.section(
            "Summary",
            md.table(
                ["Measure", "Value"],
                [
                    ("Functional requirements", len(i.requirements.functional)),
                    ("Non-functional requirements", len(i.requirements.nonfunctional)),
                    (
                        "Components / endpoints / entities",
                        f"{len(i.architecture.components)} / {len(i.data_api.endpoints)} / {len(i.data_api.entities)}",
                    ),
                    ("Test cases", len(i.qa.test_cases)),
                    (
                        "Blocker / major / minor findings",
                        f"{by_sev['blocker']} / {by_sev['major']} / {by_sev['minor']}",
                    ),
                    ("Items awaiting human approval", len(approvals)),
                    ("Remediation tasks needing a human", len(humans)),
                    ("Remediation tasks the system could still fix", len(open_auto)),
                ],
            ),
        ),
        md.section(
            "Gates not passed",
            md.bullets(f"{g.name}: {g.detail}" for g in a.gates if not g.passed)
            or "All automated gates passed.",
        ),
        md.section(
            "What a human must decide",
            md.table(
                ["Task", "Stage", "Action"],
                [(t.id, t.stage.value if t.stage else "-", t.action) for t in humans[:60]],
            )
            or "Nothing recorded.",
        ),
        md.section(
            "Awaiting approval", md.bullets(f.message for f in approvals) or "Nothing recorded."
        ),
        md.section("Limitations", md.bullets(a.limitations)),
    )
    return [
        Doc("10_VALIDATION/REQUIREMENTS_AUDIT.md", "Requirements Audit", audit),
        Doc("10_VALIDATION/FINAL_READINESS_REPORT.md", "Final Readiness Report", ready),
    ]


_VERDICT_NOTE = {
    "not_ready": "One or more automated quality gates failed. Do not hand this package to implementers until the failed gates are resolved.",
    "ready_for_review": "The automated gates passed. This is NOT approval: no human has approved this package, and the checks cannot judge whether it matches the real business need.",
}

from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable


def render(i: DocInputs) -> list[Doc]:
    a = i.architecture
    system = md.join(
        md.section("Selected pattern", f"**{a.selected_pattern.value}**"),
        md.section(
            "Pattern evaluation",
            md.table(
                ["Pattern", "Suitable", "Rationale"],
                [
                    (p.pattern.value, "yes" if p.suitable else "no", p.rationale)
                    for p in a.pattern_evaluations
                ],
            ),
        ),
        md.section("System context", md.mermaid(a.context_diagram)),
        md.section("Scalability", md.text(a.scalability) if a.scalability else "Not specified."),
        md.section("Caching", md.text(a.caching) if a.caching else "No caching is proposed."),
        md.section("Failure handling", md.bullets(a.failure_handling) or "Not specified."),
        md.section(
            "Recovery strategy",
            md.text(a.recovery_strategy) if a.recovery_strategy else "Not specified.",
        ),
    )
    comps = md.join(
        md.table(
            ["ID", "Name", "Kind", "Responsibility", "Requirements", "Depends on"],
            [
                (
                    c.id,
                    c.name,
                    c.kind.value,
                    c.responsibility,
                    ", ".join(c.requirement_ids),
                    ", ".join(c.depends_on) or "-",
                )
                for c in a.components
            ],
        ),
        md.section("Component diagram", md.mermaid(a.component_diagram)),
    )
    names = {c.id: c.name for c in a.components}
    flow = (
        md.join(
            md.table(
                ["Source", "Target", "Data"],
                [
                    (names.get(f.source, f.source), names.get(f.target, f.target), f.data)
                    for f in a.data_flows
                ],
            ),
            md.section("Data flow diagram", md.mermaid(a.dataflow_diagram)),
        )
        if a.data_flows
        else None
    )
    seq = md.join(
        *[md.join(md.section(s.name, level=2), md.mermaid(s.mermaid)) for s in a.sequences]
    )
    decisions = md.join(
        *[
            md.join(
                md.section(f"{d.id} - {d.title}", level=2),
                f"**Decision:** {md.text(d.decision)}",
                f"**Rationale:** {md.text(d.rationale)}",
                "**Alternatives considered:**\n\n"
                + (
                    md.bullets(f"{x.name}: {x.why_rejected}" for x in d.alternatives)
                    or "none recorded"
                ),
                "**Trade-offs:**\n\n" + (md.bullets(d.tradeoffs) or "none recorded"),
                f"**Components:** {', '.join(d.component_ids) or 'none'}",
                (
                    f"**Requires human approval:** yes - {md.text(d.approval_reason or 'no reason recorded')}"
                    if d.needs_human_approval
                    else "**Requires human approval:** no"
                ),
            )
            for d in a.decisions
        ]
    )
    return [
        Doc("03_ARCHITECTURE/SYSTEM_ARCHITECTURE.md", "System Architecture", system),
        Doc("03_ARCHITECTURE/COMPONENT_DESIGN.md", "Component Design", comps),
        Doc("03_ARCHITECTURE/DATA_FLOW.md", "Data Flow", flow)
        if flow
        else not_applicable(
            "03_ARCHITECTURE/DATA_FLOW.md",
            "Data Flow",
            "No data flows between components were identified.",
        ),
        Doc("03_ARCHITECTURE/SEQUENCE_DIAGRAMS.md", "Sequence Diagrams", seq)
        if a.sequences
        else not_applicable(
            "03_ARCHITECTURE/SEQUENCE_DIAGRAMS.md",
            "Sequence Diagrams",
            "No interaction sequences were identified.",
        ),
        Doc("03_ARCHITECTURE/ARCHITECTURE_DECISIONS.md", "Architecture Decisions", decisions)
        if a.decisions
        else not_applicable(
            "03_ARCHITECTURE/ARCHITECTURE_DECISIONS.md",
            "Architecture Decisions",
            "No architecture decisions were recorded.",
        ),
    ]

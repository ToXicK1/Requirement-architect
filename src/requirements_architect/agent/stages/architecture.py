"""Stage 5: system architecture. Model proposes structure; code assigns ids, validates references
and renders every diagram."""

from __future__ import annotations

from requirements_architect.agent.stages.common import (
    StageContext,
    base_untrusted,
    find_cycles,
    run_stage,
)
from requirements_architect.generators import mermaid
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.architecture import (
    ArchitectureSpec,
    Component,
    ComponentKind,
    DataFlow,
    Decision,
    RawArchitecture,
    Sequence,
    SequenceStep,
)
from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import RequirementsSpec, Severity, SpecIssue

STAGE = "stage_05_architecture"


def _issue(
    issues: list[SpecIssue], code: str, msg: str, ref: str | None = None, *, error: bool = False
) -> None:
    issues.append(
        SpecIssue(
            code=code, severity=Severity.ERROR if error else Severity.WARNING, message=msg, ref=ref
        )
    )


def build_architecture(raw: RawArchitecture, reqs: RequirementsSpec) -> ArchitectureSpec:
    issues: list[SpecIssue] = []
    valid_reqs = {f.id for f in reqs.functional} | {n.id for n in reqs.nonfunctional}
    key_to_id = {c.key: f"C-{i:03d}" for i, c in enumerate(raw.components, 1)}

    selected = [e for e in raw.pattern_evaluations if e.pattern is raw.selected_pattern]
    if not selected or not any(e.suitable for e in selected):
        _issue(
            issues,
            "PATTERN_NOT_JUSTIFIED",
            f"selected pattern {raw.selected_pattern.value} is not evaluated as suitable",
            error=True,
        )
    if len({e.pattern for e in raw.pattern_evaluations}) < 2:
        _issue(issues, "PATTERN_NOT_COMPARED", "fewer than two patterns were evaluated")

    components: list[Component] = []
    for c in raw.components:
        cid = key_to_id[c.key]
        reqs_ok = [r for r in dict.fromkeys(c.requirement_ids) if r in valid_reqs]
        for r in dict.fromkeys(c.requirement_ids):
            if r not in valid_reqs:
                _issue(issues, "UNKNOWN_REQUIREMENT", f"{cid} cites unknown requirement {r}", cid)
        deps: list[str] = []
        for d in dict.fromkeys(c.depends_on):
            if d == c.key:
                _issue(issues, "SELF_DEPENDENCY", f"{cid} depends on itself", cid)
            elif d not in key_to_id:
                _issue(issues, "UNKNOWN_DEPENDENCY", f"{cid} depends on unknown key {d}", cid)
            else:
                deps.append(key_to_id[d])
        if not reqs_ok and c.kind is not ComponentKind.EXTERNAL:
            _issue(issues, "ORPHAN_COMPONENT", f"{cid} ({c.name}) serves no requirement", cid)
        components.append(
            Component(
                id=cid,
                name=c.name,
                kind=c.kind,
                responsibility=c.responsibility,
                requirement_ids=reqs_ok,
                depends_on=deps,
            )
        )
    for cycle in find_cycles({c.id: c.depends_on for c in components}):
        _issue(
            issues, "COMPONENT_CYCLE", "component dependency cycle: " + " -> ".join(cycle), cycle[0]
        )
    served = {r for c in components for r in c.requirement_ids}
    for fr in reqs.functional:
        if fr.id not in served:
            _issue(issues, "FR_NO_COMPONENT", f"{fr.id} is not served by any component", fr.id)

    flows: list[DataFlow] = []
    for f in raw.data_flows:
        if f.source in key_to_id and f.target in key_to_id:
            flows.append(
                DataFlow(source=key_to_id[f.source], target=key_to_id[f.target], data=f.data)
            )
        else:
            _issue(
                issues,
                "UNKNOWN_FLOW_ENDPOINT",
                f"data flow '{f.data[:40]}' references an unknown component",
            )

    names = {c.id: c.name for c in components}
    sequences: list[Sequence] = []
    for s in raw.sequences:
        steps = [
            SequenceStep(source=key_to_id[x.source], target=key_to_id[x.target], message=x.message)
            for x in s.steps
            if x.source in key_to_id and x.target in key_to_id
        ]
        if len(steps) < len(s.steps):
            _issue(
                issues,
                "UNKNOWN_SEQUENCE_PARTICIPANT",
                f"sequence '{s.name[:40]}' had steps with unknown components",
            )
        if not steps:
            _issue(issues, "SEQUENCE_DROPPED", f"sequence '{s.name[:40]}' has no valid steps")
            continue
        order = list(dict.fromkeys(p for st in steps for p in (st.source, st.target)))
        diagram = mermaid.sequence(
            [(i, names[i]) for i in order], [(t.source, t.target, t.message) for t in steps]
        )
        sequences.append(Sequence(name=s.name, steps=steps, mermaid=diagram))

    decisions: list[Decision] = []
    candidates: list[ApprovalCandidate] = []
    for i, dec in enumerate(raw.decisions, 1):
        did = f"AD-{i:03d}"
        comp_ids = [key_to_id[k] for k in dict.fromkeys(dec.component_keys) if k in key_to_id]
        if not dec.alternatives:
            _issue(issues, "DECISION_NO_ALTERNATIVES", f"{did} lists no rejected alternative", did)
        if not dec.tradeoffs:
            _issue(issues, "DECISION_NO_TRADEOFFS", f"{did} lists no trade-offs", did)
        decisions.append(
            Decision(
                id=did,
                title=dec.title,
                decision=dec.decision,
                rationale=dec.rationale,
                alternatives=dec.alternatives,
                tradeoffs=dec.tradeoffs,
                component_ids=comp_ids,
                needs_human_approval=dec.needs_human_approval,
                approval_reason=dec.approval_reason,
            )
        )
        if dec.needs_human_approval:
            candidates.append(
                ApprovalCandidate(
                    source_stage=STAGE,
                    ref=did,
                    decision=dec.title,
                    reason=dec.approval_reason or "flagged by the architecture stage",
                    affected_ids=comp_ids,
                )
            )

    nodes = [(c.id, c.name) for c in components]
    comp_diagram = mermaid.flowchart(
        nodes, [(c.id, d, "uses") for c in components for d in c.depends_on]
    )
    flow_diagram = mermaid.flowchart(nodes, [(f.source, f.target, f.data) for f in flows])
    actors = list(dict.fromkeys(fr.actor for fr in reqs.functional))[:8]
    ctx_nodes = [("SYSTEM", "The system")]
    ctx_nodes += [(f"ACTOR{i}", a) for i, a in enumerate(actors, 1)]
    ctx_nodes += [(c.id, c.name) for c in components if c.kind is ComponentKind.EXTERNAL]
    ctx_edges: list[tuple[str, str, str | None]] = [
        (f"ACTOR{i}", "SYSTEM", None) for i in range(1, len(actors) + 1)
    ]
    ctx_edges += [("SYSTEM", c.id, None) for c in components if c.kind is ComponentKind.EXTERNAL]

    return ArchitectureSpec(
        selected_pattern=raw.selected_pattern,
        pattern_evaluations=raw.pattern_evaluations,
        components=components,
        data_flows=flows,
        sequences=sequences,
        decisions=decisions,
        failure_handling=raw.failure_handling,
        caching=raw.caching,
        scalability=raw.scalability,
        recovery_strategy=raw.recovery_strategy,
        context_diagram=mermaid.flowchart(ctx_nodes, ctx_edges),
        component_diagram=comp_diagram,
        dataflow_diagram=flow_diagram,
        approval_candidates=candidates,
        issues=issues,
    )


async def generate_architecture(gateway: LLMGateway, ctx: StageContext) -> ArchitectureSpec:
    raw = await run_stage(gateway, "architecture", ctx, RawArchitecture, base_untrusted(ctx))
    return build_architecture(raw, ctx.requirements)

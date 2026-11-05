"""Stage 4: functional and non-functional requirements.

The model proposes; code decides. `build_spec` assigns ids, validates every cross-reference,
routes unconfirmed business rules to assumptions, and records problems as issues instead of
silently trusting or silently fixing model output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from requirements_architect.agent.prompt_loader import load_prompt, wrap_untrusted
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.llm.types import LLMRequest, Message
from requirements_architect.schemas.requirements import (
    FunctionalRequirement,
    NfrCategory,
    NonFunctionalRequirement,
    Objective,
    RawRequirementsOutput,
    RequirementsSpec,
    RuleBasis,
    Severity,
    SpecIssue,
    TargetStatus,
    UserStory,
)
from requirements_architect.schemas.research import ResearchReport
from requirements_architect.schemas.state import (
    Assumption,
    ClarificationAnswer,
    ProjectBrief,
)

MAX_FUNCTIONAL = 40
_BASIS_NOTE = "inferred by the requirements stage; not stated by the user; needs confirmation"


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _issue(
    issues: list[SpecIssue], code: str, message: str, ref: str | None = None, *, error: bool = False
) -> None:
    issues.append(
        SpecIssue(
            code=code,
            severity=Severity.ERROR if error else Severity.WARNING,
            message=message,
            ref=ref,
        )
    )


def _find_cycles(graph: Mapping[str, Sequence[str]]) -> list[list[str]]:
    """Return one representative path for each cycle found by depth-first search."""
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(graph, white)
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        color[node] = grey
        stack.append(node)
        for nxt in graph[node]:
            if color[nxt] == grey:
                cycles.append([*stack[stack.index(nxt) :], nxt])
            elif color[nxt] == white:
                visit(nxt)
        stack.pop()
        color[node] = black

    for n in graph:
        if color[n] == white:
            visit(n)
    return cycles


def build_spec(
    raw: RawRequirementsOutput, brief: ProjectBrief, report: ResearchReport | None
) -> RequirementsSpec:
    issues: list[SpecIssue] = []
    objectives = [
        Objective(id=f"OBJ-{i:03d}", text=t) for i, t in enumerate(brief.business_objectives, 1)
    ]
    objective_by_text = {_norm(o.text): o.id for o in objectives}
    if not objectives:
        _issue(issues, "BRIEF_HAS_NO_OBJECTIVES", "the project brief lists no business objectives")
    known_findings = {f.finding_id for f in report.findings} if report else set()
    key_to_id = {r.key: f"FR-{i:03d}" for i, r in enumerate(raw.functional, 1)}
    assumptions: list[Assumption] = []
    seen_assumptions: set[str] = set()

    functional: list[FunctionalRequirement] = []
    for r in raw.functional:
        rid = key_to_id[r.key]
        objective_id: str | None = None
        if r.objective is not None:
            objective_id = objective_by_text.get(_norm(r.objective))
            if objective_id is None:
                _issue(
                    issues, "UNKNOWN_OBJECTIVE", f"{rid} cites an objective not in the brief", rid
                )
        elif objectives:
            _issue(issues, "NO_OBJECTIVE", f"{rid} is not linked to any business objective", rid)

        findings = list(dict.fromkeys(r.finding_ids))
        for fid in findings:
            if fid not in known_findings:
                _issue(issues, "UNKNOWN_FINDING", f"{rid} cites unknown finding {fid}", rid)
        findings = [f for f in findings if f in known_findings]

        needs_confirmation = False
        if r.depends_on_external_facts and not findings:
            needs_confirmation = True
            _issue(
                issues,
                "UNCITED_EXTERNAL_DEPENDENCY",
                f"{rid} depends on external facts but cites no research finding",
                rid,
                error=True,
            )
        for rule in r.business_rules:
            if rule.basis is RuleBasis.ASSUMPTION:
                needs_confirmation = True
                if _norm(rule.statement) not in seen_assumptions:
                    seen_assumptions.add(_norm(rule.statement))
                    assumptions.append(Assumption(statement=rule.statement, basis=_BASIS_NOTE))

        deps: list[str] = []
        for key in dict.fromkeys(r.depends_on):
            if key == r.key:
                _issue(issues, "SELF_DEPENDENCY", f"{rid} depends on itself", rid)
            elif key not in key_to_id:
                _issue(issues, "UNKNOWN_DEPENDENCY", f"{rid} depends on unknown key {key}", rid)
            else:
                deps.append(key_to_id[key])

        functional.append(
            FunctionalRequirement(
                id=rid,
                name=r.name,
                description=r.description,
                justification=r.justification,
                objective_id=objective_id,
                actor=r.actor,
                trigger=r.trigger,
                preconditions=r.preconditions,
                inputs=r.inputs,
                expected_behavior=r.expected_behavior,
                outputs=r.outputs,
                business_rules=r.business_rules,
                failure_scenarios=r.failure_scenarios,
                dependencies=deps,
                priority=r.priority,
                acceptance_criteria=r.acceptance_criteria,
                validation_method=r.validation_method,
                finding_ids=findings,
                needs_confirmation=needs_confirmation,
            )
        )

    for cycle in _find_cycles({fr.id: fr.dependencies for fr in functional}):
        _issue(
            issues,
            "DEPENDENCY_CYCLE",
            "requirement dependency cycle: " + " -> ".join(cycle),
            cycle[0],
            error=True,
        )

    stories: list[UserStory] = []
    covered: set[str] = set()
    for s in raw.user_stories:
        ids: list[str] = []
        for key in dict.fromkeys(s.requirement_keys):
            if key in key_to_id:
                ids.append(key_to_id[key])
            else:
                _issue(issues, "UNKNOWN_STORY_REQUIREMENT", f"a user story cites unknown key {key}")
        if not ids:
            _issue(issues, "ORPHAN_STORY_DROPPED", f"story '{s.want[:60]}' links to no requirement")
            continue
        covered.update(ids)
        stories.append(
            UserStory(
                id=f"US-{len(stories) + 1:03d}",
                actor=s.actor,
                want=s.want,
                benefit=s.benefit,
                requirement_ids=ids,
            )
        )
    for fr in functional:
        if fr.id not in covered:
            _issue(issues, "FR_NO_STORY", f"{fr.id} is not covered by any user story", fr.id)

    nonfunctional: list[NonFunctionalRequirement] = []
    for i, n in enumerate(raw.nonfunctional, 1):
        nid = f"NFR-{i:03d}"
        nfindings = list(dict.fromkeys(n.finding_ids))
        for fid in nfindings:
            if fid not in known_findings:
                _issue(issues, "UNKNOWN_FINDING", f"{nid} cites unknown finding {fid}", nid)
        has_target = bool(n.target and n.target.strip())
        if has_target and not (n.measurement_method and n.measurement_method.strip()):
            _issue(
                issues, "UNMEASURABLE_TARGET", f"{nid} has a target but no measurement method", nid
            )
        nonfunctional.append(
            NonFunctionalRequirement(
                id=nid,
                category=n.category,
                statement=n.statement,
                target=n.target if has_target else None,
                target_status=TargetStatus.PROPOSED if has_target else TargetStatus.NONE,
                measurement_method=n.measurement_method,
                rationale=n.rationale,
                finding_ids=[f for f in nfindings if f in known_findings],
            )
        )
    present = {n.category for n in nonfunctional}
    for cat in NfrCategory:
        if cat not in present:
            _issue(issues, "MISSING_NFR_CATEGORY", f"no non-functional requirement for {cat.value}")

    return RequirementsSpec(
        objectives=objectives,
        functional=functional,
        nonfunctional=nonfunctional,
        user_stories=stories,
        assumptions=assumptions,
        issues=issues,
    )


def approve_nfr_targets(spec: RequirementsSpec, nfr_ids: Sequence[str]) -> RequirementsSpec:
    """Mark proposed targets as user-approved. Only the approval flow may call this.

    Returns a new spec (the caller persists it as a new version). Unknown ids and
    requirements without a target are rejected rather than silently skipped.
    """
    by_id = {n.id: n for n in spec.nonfunctional}
    for nid in nfr_ids:
        nfr = by_id.get(nid)
        if nfr is None:
            raise ValueError(f"unknown NFR id: {nid}")
        if nfr.target_status is TargetStatus.NONE or not nfr.target:
            raise ValueError(f"{nid} has no target to approve")
    wanted = set(nfr_ids)
    updated = [
        n.model_copy(update={"target_status": TargetStatus.USER_APPROVED}) if n.id in wanted else n
        for n in spec.nonfunctional
    ]
    return spec.model_copy(update={"nonfunctional": updated})


def _render_findings(report: ResearchReport | None) -> tuple[str, str]:
    if report is None or not report.findings:
        note = (
            "no research findings are available; mark every external-technology dependency "
            "with depends_on_external_facts=true and cite nothing"
        )
        return note, "(none)"
    lines = [
        f"{f.finding_id} [{f.kind.value}, {f.verification.value}] {f.claim[:400]}"
        for f in report.findings
    ]
    note = "research findings are listed below; only 'verified' facts are confirmed against sources"
    if report.limitations:
        note += "; limitations: " + "; ".join(report.limitations)
    return note, "\n".join(lines)


async def generate_requirements(
    gateway: LLMGateway,
    project_id: str,
    problem_statement: str,
    brief: ProjectBrief,
    answers: Mapping[str, ClarificationAnswer],
    report: ResearchReport | None,
) -> RequirementsSpec:
    prompt = load_prompt("requirements")
    note, findings_txt = _render_findings(report)
    objectives_txt = "\n".join(f"- {o}" for o in brief.business_objectives) or "(none stated)"
    answers_txt = "\n".join(f"{a.question_id}: {a.answer}" for a in answers.values()) or "(none)"
    system, user = prompt.render(
        problem_statement=wrap_untrusted(problem_statement, "problem_statement"),
        brief_json=wrap_untrusted(brief.model_dump_json(indent=2), "brief"),
        answers=wrap_untrusted(answers_txt, "answers"),
        objectives=wrap_untrusted(objectives_txt, "objectives"),
        evidence_note=note,
        findings=wrap_untrusted(findings_txt, "findings"),
        max_functional=str(MAX_FUNCTIONAL),
    )
    request = LLMRequest(
        system=system,
        messages=[Message(role="user", content=user)],
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        project_id=project_id,
        max_tokens=16000,
    )
    raw, _ = await gateway.complete_structured(request, RawRequirementsOutput)
    return build_spec(raw, brief, report)

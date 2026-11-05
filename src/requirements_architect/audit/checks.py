"""Deterministic audit checks. They re-verify the final persisted specifications rather than
trusting the builders that produced them."""

from __future__ import annotations

import re
from collections.abc import Iterable

from requirements_architect.agent.stages.security import COMPLIANCE_CLAIM
from requirements_architect.audit.specset import SpecSet
from requirements_architect.generators.mermaid import node_id
from requirements_architect.schemas.audit import AuditCategory as Cat
from requirements_architect.schemas.audit import AuditFinding, AuditSeverity
from requirements_architect.schemas.audit import AuditSeverity as Sev
from requirements_architect.schemas.dataapi import AuthType
from requirements_architect.schemas.requirements import SpecIssue, TargetStatus
from requirements_architect.schemas.research import VerificationStatus
from requirements_architect.schemas.security import Treatment
from requirements_architect.schemas.state import StageId
from requirements_architect.schemas.technology import ClaimStatus
from requirements_architect.validation.design_traceability import design_links, design_targets
from requirements_architect.validation.secrets import scrub
from requirements_architect.validation.traceability import (
    TraceKind,
    analyze,
    links_from_spec,
)

DESIGN_STAGES = {
    StageId.ARCHITECTURE,
    StageId.TECHNOLOGY,
    StageId.DATA_API,
    StageId.SECURITY,
    StageId.UX,
    StageId.QA_DEPLOY,
}
_VAGUE = re.compile(
    r"\b(fast|quick(?:ly)?|user[- ]friendly|easy to use|intuitive|robust|scalable|secure|"
    r"flexible|modern|efficient(?:ly)?|appropriate(?:ly)?|as needed|if necessary|etc\.?|"
    r"and/or|tbd|to be determined|reasonable|adequate|seamless(?:ly)?)\b",
    re.IGNORECASE,
)


def _f(
    cat: Cat,
    sev: Sev,
    code: str,
    msg: str,
    refs: Iterable[str] = (),
    stage: StageId | None = None,
    *,
    fix: bool = False,
    human: bool = False,
) -> AuditFinding:
    return AuditFinding(
        category=cat,
        severity=sev,
        code=code,
        message=msg,
        refs=sorted(set(refs)),
        stage=stage,
        auto_fixable=fix and stage in DESIGN_STAGES,
        needs_human=human,
    )


# Issues the builders already report that this audit re-derives independently (avoid duplicates).
_SUPPRESSED = {"FR_NO_TEST", "NFR_NO_TEST"}
_ISSUE_CATEGORY = {
    "MISSING_NFR_CATEGORY": Cat.COMPLETENESS,
    "BRIEF_HAS_NO_OBJECTIVES": Cat.COMPLETENESS,
    "UNCITED_EXTERNAL_FACT": Cat.EVIDENCE,
    "COMPLIANCE_CLAIM": Cat.SECURITY,
    "DEPENDENCY_CYCLE": Cat.CONSISTENCY,
    "UNKNOWN_REQUIREMENT": Cat.CONSISTENCY,
}


def passthrough(spec_issues: dict[StageId, list[SpecIssue]]) -> list[AuditFinding]:
    """Surface every issue a stage builder recorded, so the audit is the one place to look."""
    out: list[AuditFinding] = []
    for stage, issues in spec_issues.items():
        for i in issues:
            if i.code in _SUPPRESSED:
                continue
            sev = Sev.MAJOR if i.severity.value == "error" else Sev.MINOR
            out.append(
                _f(
                    _ISSUE_CATEGORY.get(i.code, Cat.COMPLETENESS),
                    sev,
                    f"STAGE_{i.code}",
                    i.message,
                    [i.ref] if i.ref else [],
                    stage,
                    fix=stage in DESIGN_STAGES,
                    human=stage not in DESIGN_STAGES,
                )
            )
    return out


def check_references(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    reqs = {f.id for f in s.requirements.functional} | {n.id for n in s.requirements.nonfunctional}
    comps = {c.id for c in s.architecture.components}
    ents = {e.id for e in s.data_api.entities}
    eps = {e.id for e in s.data_api.endpoints}
    ctls = {c.id for c in s.security.controls}

    def broken(stage: StageId, owner: str, kind: str, ids: Iterable[str], known: set[str]) -> None:
        bad = sorted(set(ids) - known)
        if bad:
            out.append(
                _f(
                    Cat.CONSISTENCY,
                    Sev.MAJOR,
                    "BROKEN_REFERENCE",
                    f"{owner} references unknown {kind}: {', '.join(bad)}",
                    [owner, *bad],
                    stage,
                    fix=True,
                )
            )

    for c in s.architecture.components:
        broken(StageId.ARCHITECTURE, c.id, "requirement", c.requirement_ids, reqs)
        broken(StageId.ARCHITECTURE, c.id, "component", c.depends_on, comps)
    for d in s.architecture.decisions:
        broken(StageId.ARCHITECTURE, d.id, "component", d.component_ids, comps)
    for t in s.technology.technologies:
        broken(StageId.TECHNOLOGY, t.id, "component", t.component_ids, comps)
    for e in s.data_api.entities:
        broken(StageId.DATA_API, e.id, "requirement", e.requirement_ids, reqs)
        broken(
            StageId.DATA_API, e.id, "entity", [k.references_entity for k in e.foreign_keys], ents
        )
    for ep in s.data_api.endpoints:
        broken(StageId.DATA_API, ep.id, "requirement", ep.requirement_ids, reqs)
        broken(StageId.DATA_API, ep.id, "entity", ep.entity_ids, ents)
    for c2 in s.security.controls:
        broken(StageId.SECURITY, c2.id, "requirement", c2.requirement_ids, reqs)
    for th in s.security.threats:
        broken(StageId.SECURITY, th.id, "control", th.control_ids, ctls)
    for sc in s.ux.screens:
        broken(StageId.UX, sc.id, "requirement", sc.requirement_ids, reqs)
        broken(StageId.UX, sc.id, "endpoint", sc.endpoint_ids, eps)
    for fl in s.ux.flows:
        broken(StageId.UX, fl.id, "requirement", fl.requirement_ids, reqs)
    for tc in s.qa.test_cases:
        broken(StageId.QA_DEPLOY, tc.id, "requirement", tc.requirement_ids, reqs)
    frs = {f.id for f in s.requirements.functional}
    for f in s.requirements.functional:
        bad = sorted(set(f.dependencies) - frs)
        if bad:
            out.append(
                _f(
                    Cat.CONSISTENCY,
                    Sev.MAJOR,
                    "BROKEN_REFERENCE",
                    f"{f.id} depends on unknown requirement(s): {', '.join(bad)}",
                    [f.id, *bad],
                    StageId.REQUIREMENTS,
                    human=True,
                )
            )
    return out


def check_traceability(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    links = [
        *links_from_spec(s.requirements),
        *design_links(s.architecture, s.data_api, s.security, s.qa),
    ]
    report = analyze(
        s.requirements,
        links,
        (TraceKind.COMPONENT, TraceKind.TEST),
        design_targets(s.architecture, s.data_api, s.security, s.qa),
    )
    for rid, missing in sorted(report.uncovered.items()):
        if TraceKind.COMPONENT in missing:
            out.append(
                _f(
                    Cat.TRACEABILITY,
                    Sev.MAJOR,
                    "FR_NO_COMPONENT",
                    f"{rid} is not implemented by any component",
                    [rid],
                    StageId.ARCHITECTURE,
                    fix=True,
                )
            )
        if TraceKind.TEST in missing:
            out.append(
                _f(
                    Cat.TRACEABILITY,
                    Sev.MAJOR,
                    "FR_NO_TEST",
                    f"{rid} has no test case",
                    [rid],
                    StageId.QA_DEPLOY,
                    fix=True,
                )
            )
    for o in report.orphan_targets:
        stage = {
            TraceKind.COMPONENT: StageId.ARCHITECTURE,
            TraceKind.ENTITY: StageId.DATA_API,
            TraceKind.ENDPOINT: StageId.DATA_API,
            TraceKind.CONTROL: StageId.SECURITY,
            TraceKind.TEST: StageId.QA_DEPLOY,
        }.get(o.kind)
        out.append(
            _f(
                Cat.TRACEABILITY,
                Sev.MINOR,
                "ORPHAN_ITEM",
                f"{o.target_id} ({o.kind.value}) serves no requirement",
                [o.target_id],
                stage,
                fix=True,
            )
        )
    covered_tests = {r for c in s.qa.test_cases for r in c.requirement_ids}
    for n in s.requirements.nonfunctional:
        if n.id not in covered_tests:
            out.append(
                _f(
                    Cat.TRACEABILITY,
                    Sev.MINOR,
                    "NFR_NO_TEST",
                    f"{n.id} ({n.category.value}) has no test case",
                    [n.id],
                    StageId.QA_DEPLOY,
                    fix=True,
                )
            )
    for obj in s.requirements.objectives:
        if not any(f.objective_id == obj.id for f in s.requirements.functional):
            out.append(
                _f(
                    Cat.COMPLETENESS,
                    Sev.MAJOR,
                    "OBJECTIVE_NO_REQUIREMENT",
                    f"objective {obj.id} is served by no functional requirement",
                    [obj.id],
                    StageId.REQUIREMENTS,
                    human=True,
                )
            )
    return out


def check_completeness(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    if not s.requirements.functional:
        out.append(
            _f(
                Cat.COMPLETENESS,
                Sev.BLOCKER,
                "NO_REQUIREMENTS",
                "no functional requirements exist",
                [],
                StageId.REQUIREMENTS,
                human=True,
            )
        )
    for f in s.requirements.functional:
        if not f.acceptance_criteria:
            out.append(
                _f(
                    Cat.COMPLETENESS,
                    Sev.MAJOR,
                    "FR_NO_ACCEPTANCE_CRITERIA",
                    f"{f.id} has no acceptance criteria",
                    [f.id],
                    StageId.REQUIREMENTS,
                    human=True,
                )
            )
    if not s.requirements.user_stories:
        out.append(
            _f(
                Cat.COMPLETENESS,
                Sev.MINOR,
                "NO_USER_STORIES",
                "no user stories exist",
                [],
                StageId.REQUIREMENTS,
                human=True,
            )
        )
    if s.data_api.endpoints and not s.architecture.components:
        out.append(
            _f(
                Cat.COMPLETENESS,
                Sev.MAJOR,
                "NO_COMPONENTS",
                "endpoints exist but no components implement them",
                [],
                StageId.ARCHITECTURE,
                fix=True,
            )
        )
    if not s.qa.test_cases:
        out.append(
            _f(
                Cat.COMPLETENESS,
                Sev.BLOCKER,
                "NO_TEST_CASES",
                "no test cases exist",
                [],
                StageId.QA_DEPLOY,
                fix=True,
            )
        )
    interfaces = {r for e in s.data_api.endpoints for r in e.requirement_ids} | {
        r for sc in s.ux.screens for r in sc.requirement_ids
    }
    if s.data_api.endpoints or s.ux.screens:
        for f in s.requirements.functional:
            if f.id not in interfaces:
                out.append(
                    _f(
                        Cat.COMPLETENESS,
                        Sev.MINOR,
                        "FR_NO_INTERFACE",
                        f"{f.id} is exposed by no endpoint or screen",
                        [f.id],
                        StageId.DATA_API,
                        fix=True,
                    )
                )
    actors = " ".join(
        {f.actor.lower() for f in s.requirements.functional}
        | {u.actor.lower() for u in s.requirements.user_stories}
    )
    for role in s.brief.user_roles:
        if role.lower() not in actors and not any(
            w in actors for w in role.lower().split() if len(w) > 3
        ):
            out.append(
                _f(
                    Cat.COMPLETENESS,
                    Sev.MINOR,
                    "ROLE_NOT_COVERED",
                    f"user role '{role}' is the actor of no requirement or story",
                    [],
                    StageId.REQUIREMENTS,
                    human=True,
                )
            )
    return out


def check_consistency(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []

    def dupes(items: Iterable[tuple[str, str]], code: str, label: str, stage: StageId) -> None:
        seen: dict[str, str] = {}
        for ident, key in items:
            k = " ".join(key.lower().split())
            if k in seen:
                out.append(
                    _f(
                        Cat.CONSISTENCY,
                        Sev.MAJOR,
                        code,
                        f"{label} '{key}' is defined twice ({seen[k]}, {ident})",
                        [seen[k], ident],
                        stage,
                        fix=True,
                    )
                )
            else:
                seen[k] = ident

    dupes(
        ((c.id, c.name) for c in s.architecture.components),
        "DUPLICATE_COMPONENT",
        "component",
        StageId.ARCHITECTURE,
    )
    dupes(
        ((e.id, e.name) for e in s.data_api.entities),
        "DUPLICATE_ENTITY",
        "entity",
        StageId.DATA_API,
    )
    dupes(
        ((e.id, f"{e.method.value} {e.path}") for e in s.data_api.endpoints),
        "DUPLICATE_ENDPOINT",
        "endpoint",
        StageId.DATA_API,
    )
    dupes(
        ((t.id, t.name) for t in s.technology.technologies),
        "DUPLICATE_TECHNOLOGY",
        "technology",
        StageId.TECHNOLOGY,
    )
    dupes(
        ((f.id, f.name) for f in s.requirements.functional),
        "DUPLICATE_REQUIREMENT",
        "requirement name",
        StageId.REQUIREMENTS,
    )
    graph = {c.id: list(c.depends_on) for c in s.architecture.components}
    from requirements_architect.agent.stages.common import find_cycles

    for cyc in find_cycles(graph):
        out.append(
            _f(
                Cat.CONSISTENCY,
                Sev.MAJOR,
                "COMPONENT_CYCLE",
                "components depend on each other in a cycle: " + " -> ".join(cyc),
                cyc,
                StageId.ARCHITECTURE,
                fix=True,
            )
        )
    fr_graph = {f.id: list(f.dependencies) for f in s.requirements.functional}
    for cyc in find_cycles(fr_graph):
        out.append(
            _f(
                Cat.CONSISTENCY,
                Sev.MAJOR,
                "REQUIREMENT_CYCLE",
                "requirements depend on each other in a cycle: " + " -> ".join(cyc),
                cyc,
                StageId.REQUIREMENTS,
                human=True,
            )
        )
    # diagrams must show what the specification contains
    for c in s.architecture.components:
        if (
            s.architecture.component_diagram
            and node_id(c.id) not in s.architecture.component_diagram
        ):
            out.append(
                _f(
                    Cat.DIAGRAM,
                    Sev.MAJOR,
                    "DIAGRAM_MISSING_COMPONENT",
                    f"component diagram does not show {c.id}",
                    [c.id],
                    StageId.ARCHITECTURE,
                    fix=True,
                )
            )
    if s.architecture.components and not s.architecture.component_diagram.strip():
        out.append(
            _f(
                Cat.DIAGRAM,
                Sev.MAJOR,
                "DIAGRAM_MISSING",
                "no component diagram exists",
                [],
                StageId.ARCHITECTURE,
                fix=True,
            )
        )
    for e in s.data_api.entities:
        if node_id(e.name) not in s.data_api.er_diagram:
            out.append(
                _f(
                    Cat.DIAGRAM,
                    Sev.MAJOR,
                    "DIAGRAM_MISSING_ENTITY",
                    f"ER diagram does not show {e.id} ({e.name})",
                    [e.id],
                    StageId.DATA_API,
                    fix=True,
                )
            )
    return out


def check_security(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    sec = s.security
    ctl = {c.id for c in sec.controls}
    for t in sec.threats:
        live = [c for c in t.control_ids if c in ctl]
        if t.risk_level in {"high", "critical"} and not live and t.treatment is Treatment.MITIGATE:
            out.append(
                _f(
                    Cat.SECURITY,
                    Sev.MAJOR,
                    "HIGH_RISK_NO_CONTROL",
                    f"{t.id} ({t.risk_level}) is to be mitigated but has no control",
                    [t.id],
                    StageId.SECURITY,
                    fix=True,
                )
            )
        if t.risk_level in {"high", "critical"} and t.treatment is Treatment.ACCEPT:
            out.append(
                _f(
                    Cat.SECURITY,
                    Sev.MAJOR,
                    "HIGH_RISK_ACCEPTED",
                    f"{t.id} ({t.risk_level}) is accepted; a human must approve this",
                    [t.id],
                    StageId.SECURITY,
                    human=True,
                )
            )
    if not sec.threats:
        out.append(
            _f(
                Cat.SECURITY,
                Sev.MAJOR,
                "NO_THREAT_MODEL",
                "no threats were identified",
                [],
                StageId.SECURITY,
                fix=True,
            )
        )
    if not sec.controls:
        out.append(
            _f(
                Cat.SECURITY,
                Sev.MAJOR,
                "NO_SECURITY_CONTROLS",
                "no security controls exist",
                [],
                StageId.SECURITY,
                fix=True,
            )
        )
    sensitive = sec.handles_sensitive_data
    for e in s.data_api.endpoints:
        if e.authentication is AuthType.NONE:
            out.append(
                _f(
                    Cat.SECURITY,
                    Sev.MAJOR if sensitive else Sev.MINOR,
                    "UNAUTHENTICATED_ENDPOINT",
                    f"{e.id} {e.method.value} {e.path} requires no authentication"
                    + (" although the project handles sensitive data" if sensitive else ""),
                    [e.id],
                    StageId.DATA_API,
                    fix=True,
                )
            )
    if sensitive and not sec.privacy_requirements:
        out.append(
            _f(
                Cat.SECURITY,
                Sev.MAJOR,
                "SENSITIVE_NO_PRIVACY",
                "sensitive data is handled but no privacy requirements exist",
                [],
                StageId.SECURITY,
                fix=True,
            )
        )
    if s.data_api.endpoints and not any(
        c.area.value in {"authentication", "authorization"} for c in sec.controls
    ):
        out.append(
            _f(
                Cat.SECURITY,
                Sev.MAJOR,
                "NO_AUTH_CONTROL",
                "an HTTP API exists but no authentication or authorization control does",
                [],
                StageId.SECURITY,
                fix=True,
            )
        )
    if sec.is_ai_project and not any(
        t.category.value
        in {"prompt_injection", "excessive_agency", "tool_abuse", "insecure_output_handling"}
        for t in sec.threats
    ):
        out.append(
            _f(
                Cat.SECURITY,
                Sev.MAJOR,
                "AI_THREATS_MISSING",
                "AI project without prompt-injection or agency threats",
                [],
                StageId.SECURITY,
                fix=True,
            )
        )
    # compliance wording anywhere in the specification
    texts = (
        [(c.id, f"{c.name} {c.description}") for c in sec.controls]
        + [(t.id, f"{t.description} {t.residual_note}") for t in sec.threats]
        + [(f.id, f"{f.description} {f.expected_behavior}") for f in s.requirements.functional]
    )
    for ident, text in texts:
        if COMPLIANCE_CLAIM.search(text):
            out.append(
                _f(
                    Cat.SECURITY,
                    Sev.MAJOR,
                    "UNSUPPORTED_COMPLIANCE_CLAIM",
                    f"{ident} reads like a compliance guarantee",
                    [ident],
                    StageId.SECURITY if ident[:2] in {"SC", "TH"} else StageId.REQUIREMENTS,
                    fix=ident[:2] in {"SC", "TH"},
                    human=ident[:2] not in {"SC", "TH"},
                )
            )
    return out


def check_secrets(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    named = {
        StageId.REQUIREMENTS: s.requirements,
        StageId.ARCHITECTURE: s.architecture,
        StageId.TECHNOLOGY: s.technology,
        StageId.DATA_API: s.data_api,
        StageId.SECURITY: s.security,
        StageId.UX: s.ux,
        StageId.QA_DEPLOY: s.qa,
    }
    for stage, spec in named.items():
        _, found = scrub(spec.model_dump_json())
        if found:
            out.append(
                _f(
                    Cat.SECURITY,
                    Sev.BLOCKER,
                    "SECRET_IN_SPEC",
                    f"the {stage.value} output contains secret-looking text",
                    [],
                    stage,
                    fix=True,
                )
            )
    return out


def check_evidence(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    if s.research is None or not s.research.external_research_available:
        out.append(
            _f(
                Cat.EVIDENCE,
                Sev.MINOR,
                "NO_EXTERNAL_RESEARCH",
                "no external research was available; every external claim is unverified",
                [],
                StageId.RESEARCH,
                human=True,
            )
        )
    techs = s.technology.technologies
    unverified_v = [
        t.id
        for t in techs
        if t.recommended_version and t.version_status is not ClaimStatus.CONFIRMED
    ]
    if unverified_v:
        out.append(
            _f(
                Cat.EVIDENCE,
                Sev.MINOR,
                "TECH_VERSION_UNVERIFIED",
                f"{len(unverified_v)} of {len(techs)} technology versions are not confirmed by a registry",
                unverified_v,
                StageId.TECHNOLOGY,
                human=True,
            )
        )
    differs = [t.id for t in techs if t.version_status is ClaimStatus.DIFFERS]
    if differs:
        out.append(
            _f(
                Cat.DEPENDENCY,
                Sev.MAJOR,
                "TECH_VERSION_DIFFERS",
                "the stated version differs from the registry's: " + ", ".join(differs),
                differs,
                StageId.TECHNOLOGY,
                human=True,
            )
        )
    bad_license = [t.id for t in techs if t.license_status is not ClaimStatus.CONFIRMED]
    if bad_license:
        out.append(
            _f(
                Cat.EVIDENCE,
                Sev.MINOR,
                "TECH_LICENSE_UNVERIFIED",
                f"{len(bad_license)} license(s) are not confirmed by a registry",
                bad_license,
                StageId.TECHNOLOGY,
                human=True,
            )
        )
    unchecked = [t.id for t in techs if t.package and not t.advisories_checked]
    if unchecked:
        out.append(
            _f(
                Cat.DEPENDENCY,
                Sev.MINOR,
                "TECH_ADVISORIES_UNCHECKED",
                "no vulnerability database was consulted for: " + ", ".join(unchecked),
                unchecked,
                StageId.TECHNOLOGY,
                human=True,
            )
        )
    adv = [t.id for t in techs if t.advisories]
    if adv:
        out.append(
            _f(
                Cat.DEPENDENCY,
                Sev.MAJOR,
                "TECH_HAS_ADVISORIES",
                "known advisories exist for: " + ", ".join(adv),
                adv,
                StageId.TECHNOLOGY,
                human=True,
            )
        )
    unsupported = [t.id for t in techs if t.evidence == "unverified"]
    if unsupported:
        out.append(
            _f(
                Cat.EVIDENCE,
                Sev.MINOR,
                "TECH_CHOICE_UNSUPPORTED",
                f"{len(unsupported)} of {len(techs)} technology choices cite no verified research finding",
                unsupported,
                StageId.TECHNOLOGY,
                human=True,
            )
        )
    orphan = [t.id for t in techs if not t.component_ids]
    if orphan:
        out.append(
            _f(
                Cat.DEPENDENCY,
                Sev.MINOR,
                "TECH_NOT_USED",
                "technology serves no component: " + ", ".join(orphan),
                orphan,
                StageId.TECHNOLOGY,
                fix=True,
            )
        )
    names = {t.name.lower() for t in techs}
    for t in techs:
        missing = [d for d in t.dependencies if d.lower() not in names]
        if missing:
            out.append(
                _f(
                    Cat.DEPENDENCY,
                    Sev.INFO,
                    "TECH_DEPENDENCY_NOT_IN_STACK",
                    f"{t.id} depends on {', '.join(missing)}, which is not in the stack",
                    [t.id],
                    StageId.TECHNOLOGY,
                    fix=True,
                )
            )
    if s.research:
        verified = {
            f.finding_id
            for f in s.research.findings
            if f.verification is VerificationStatus.VERIFIED
        }
        for f in s.requirements.functional:
            weak = [x for x in f.finding_ids if x not in verified]
            if weak:
                out.append(
                    _f(
                        Cat.EVIDENCE,
                        Sev.MINOR,
                        "FR_CITES_UNVERIFIED_FINDING",
                        f"{f.id} rests on unverified finding(s): {', '.join(weak)}",
                        [f.id, *weak],
                        StageId.REQUIREMENTS,
                        human=True,
                    )
                )
    return out


def check_assumptions(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    pending = [f.id for f in s.requirements.functional if f.needs_confirmation]
    if pending:
        out.append(
            _f(
                Cat.ASSUMPTION,
                Sev.MINOR,
                "REQUIREMENTS_NEED_CONFIRMATION",
                f"{len(pending)} requirement(s) rest on assumptions a human must confirm",
                pending,
                StageId.REQUIREMENTS,
                human=True,
            )
        )
    stmts = {a.statement for a in [*s.brief.assumptions, *s.requirements.assumptions]}
    if stmts:
        out.append(
            _f(
                Cat.ASSUMPTION,
                Sev.INFO,
                "UNRESOLVED_ASSUMPTIONS",
                f"{len(stmts)} assumption(s) are recorded and unconfirmed",
                [],
                StageId.REQUIREMENTS,
                human=True,
            )
        )
    if s.brief.missing_information:
        out.append(
            _f(
                Cat.ASSUMPTION,
                Sev.MINOR,
                "MISSING_INFORMATION",
                f"{len(s.brief.missing_information)} item(s) of information are still missing",
                [],
                StageId.PROBLEM_UNDERSTANDING,
                human=True,
            )
        )
    prop = [n.id for n in s.requirements.nonfunctional if n.target_status is TargetStatus.PROPOSED]
    if prop:
        out.append(
            _f(
                Cat.ASSUMPTION,
                Sev.MINOR,
                "NFR_TARGETS_UNAPPROVED",
                f"{len(prop)} non-functional target(s) are proposals no human approved",
                prop,
                StageId.REQUIREMENTS,
                human=True,
            )
        )
    untargeted = [n.id for n in s.requirements.nonfunctional if not n.target]
    if untargeted:
        out.append(
            _f(
                Cat.COMPLETENESS,
                Sev.MINOR,
                "NFR_NO_TARGET",
                f"{len(untargeted)} non-functional requirement(s) have no measurable target",
                untargeted,
                StageId.REQUIREMENTS,
                human=True,
            )
        )
    for a in (
        s.architecture.approval_candidates
        + s.technology.approval_candidates
        + s.data_api.approval_candidates
        + s.security.approval_candidates
        + s.ux.approval_candidates
        + s.qa.approval_candidates
    ):
        out.append(
            _f(
                Cat.ASSUMPTION,
                Sev.INFO,
                "AWAITING_APPROVAL",
                f"{a.source_stage} {a.ref}: {a.decision} ({a.reason})",
                [a.ref],
                None,
                human=True,
            )
        )
    return out


def check_ambiguity(s: SpecSet) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    items = [
        (f.id, f"{f.name} {f.description} {f.expected_behavior}") for f in s.requirements.functional
    ] + [(n.id, n.statement) for n in s.requirements.nonfunctional if not n.target]
    for ident, text in items:
        hits = sorted({m.group(0).lower() for m in _VAGUE.finditer(text)})
        if hits:
            out.append(
                _f(
                    Cat.AMBIGUITY,
                    Sev.MINOR,
                    "VAGUE_WORDING",
                    f"{ident} uses unmeasurable wording: {', '.join(hits)}",
                    [ident],
                    StageId.REQUIREMENTS,
                    human=True,
                )
            )
    return out


def run_checks(s: SpecSet) -> list[AuditFinding]:
    issues = {
        StageId.REQUIREMENTS: s.requirements.issues,
        StageId.ARCHITECTURE: s.architecture.issues,
        StageId.TECHNOLOGY: s.technology.issues,
        StageId.DATA_API: s.data_api.issues,
        StageId.SECURITY: s.security.issues,
        StageId.UX: s.ux.issues,
        StageId.QA_DEPLOY: s.qa.issues,
    }
    found = [
        *passthrough(issues),
        *check_completeness(s),
        *check_references(s),
        *check_traceability(s),
        *check_consistency(s),
        *check_security(s),
        *check_secrets(s),
        *check_evidence(s),
        *check_assumptions(s),
        *check_ambiguity(s),
    ]
    return finalize(found)


def finalize(found: list[AuditFinding]) -> list[AuditFinding]:
    """Deterministic order and ids: severity, then code, refs, message."""
    order = {
        AuditSeverity.BLOCKER: 0,
        AuditSeverity.MAJOR: 1,
        AuditSeverity.MINOR: 2,
        AuditSeverity.INFO: 3,
    }
    ordered = sorted(found, key=lambda f: (order[f.severity], f.code, f.refs, f.message))
    return [f.model_copy(update={"id": f"AUD-{n:03d}"}) for n, f in enumerate(ordered, 1)]

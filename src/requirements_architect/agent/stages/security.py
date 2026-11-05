"""Stage 8: security and privacy. Code computes risk scores, enforces treatment rules, checks
coverage, and flags anything that reads like a compliance guarantee."""

from __future__ import annotations

import re

from requirements_architect.agent.stages.common import (
    StageContext,
    base_untrusted,
    render_architecture,
    render_data_api,
    render_technology,
    run_stage,
)
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import RequirementsSpec, Severity, SpecIssue
from requirements_architect.schemas.security import (
    AI_THREATS,
    STRIDE,
    Control,
    ControlArea,
    Level,
    RawSecurityOutput,
    SecuritySpec,
    SecurityTestItem,
    Threat,
    Treatment,
)

STAGE = "stage_08_security"
_LEVEL = {Level.LOW: 1, Level.MEDIUM: 2, Level.HIGH: 3}
_CORE_AREAS = (
    ControlArea.AUTHENTICATION,
    ControlArea.AUTHORIZATION,
    ControlArea.INPUT_VALIDATION,
    ControlArea.SECRETS,
    ControlArea.ENCRYPTION,
    ControlArea.AUDIT,
)
_SENSITIVE_AREAS = (ControlArea.PRIVACY, ControlArea.RETENTION, ControlArea.BACKUP)
_COMPLIANCE_CLAIM = re.compile(
    r"\b(fully compliant|guarantee[sd]? compliance|ensures? compliance|is compliant with|"
    r"are compliant with|certified|will comply with)\b",
    re.IGNORECASE,
)


def risk_level(score: int) -> str:
    return "critical" if score >= 9 else "high" if score >= 6 else "medium" if score >= 3 else "low"


def _issue(
    issues: list[SpecIssue], code: str, msg: str, ref: str | None = None, *, error: bool = False
) -> None:
    issues.append(
        SpecIssue(
            code=code, severity=Severity.ERROR if error else Severity.WARNING, message=msg, ref=ref
        )
    )


def build_security(raw: RawSecurityOutput, reqs: RequirementsSpec) -> SecuritySpec:
    issues: list[SpecIssue] = []
    valid_reqs = {f.id for f in reqs.functional} | {n.id for n in reqs.nonfunctional}
    ctrl_key = {c.key: f"SC-{i:03d}" for i, c in enumerate(raw.controls, 1)}

    controls: list[Control] = []
    for c in raw.controls:
        cid = ctrl_key[c.key]
        ok = [r for r in dict.fromkeys(c.requirement_ids) if r in valid_reqs]
        for r in dict.fromkeys(c.requirement_ids):
            if r not in valid_reqs:
                _issue(issues, "UNKNOWN_REQUIREMENT", f"{cid} cites unknown requirement {r}", cid)
        if _COMPLIANCE_CLAIM.search(f"{c.name} {c.description}"):
            _issue(issues, "COMPLIANCE_CLAIM", f"{cid} reads like a compliance guarantee", cid)
        controls.append(
            Control(
                id=cid,
                name=c.name,
                description=c.description,
                area=c.area,
                requirement_ids=ok,
                framework_refs=c.framework_refs,
            )
        )

    threats: list[Threat] = []
    candidates: list[ApprovalCandidate] = []
    mitigated_by: set[str] = set()
    for i, t in enumerate(raw.threats, 1):
        tid = f"TH-{i:03d}"
        ids = [ctrl_key[k] for k in dict.fromkeys(t.control_keys) if k in ctrl_key]
        for k in dict.fromkeys(t.control_keys):
            if k not in ctrl_key:
                _issue(issues, "UNKNOWN_CONTROL", f"{tid} cites unknown control {k}", tid)
        mitigated_by.update(ids)
        score = _LEVEL[t.likelihood] * _LEVEL[t.impact]
        level = risk_level(score)
        requires_approval = False
        if t.treatment is Treatment.MITIGATE and not ids:
            _issue(
                issues,
                "THREAT_NO_CONTROL",
                f"{tid} is to be mitigated but has no valid control",
                tid,
                error=True,
            )
        if t.treatment is Treatment.ACCEPT and score >= 6:
            requires_approval = True
            candidates.append(
                ApprovalCandidate(
                    source_stage=STAGE,
                    ref=tid,
                    decision=f"Accept {level} risk: {t.title}",
                    reason=f"risk score {score}/9 ({level}) accepted rather than treated",
                    affected_ids=ids,
                )
            )
            if score >= 9:
                _issue(
                    issues,
                    "ACCEPTED_CRITICAL_RISK",
                    f"{tid} accepts a critical risk",
                    tid,
                    error=True,
                )
        if _COMPLIANCE_CLAIM.search(f"{t.description} {t.residual_note}"):
            _issue(issues, "COMPLIANCE_CLAIM", f"{tid} reads like a compliance guarantee", tid)
        threats.append(
            Threat(
                id=tid,
                title=t.title,
                category=t.category,
                asset=t.asset,
                description=t.description,
                likelihood=t.likelihood,
                impact=t.impact,
                risk_score=score,
                risk_level=level,
                control_ids=ids,
                treatment=t.treatment,
                residual_note=t.residual_note,
                requires_approval=requires_approval,
            )
        )
    for ctl in controls:
        if ctl.id not in mitigated_by:
            _issue(issues, "ORPHAN_CONTROL", f"{ctl.id} ({ctl.name}) mitigates no threat", ctl.id)

    present_areas = {c.area for c in controls}
    needed = list(_CORE_AREAS) + (list(_SENSITIVE_AREAS) if raw.handles_sensitive_data else [])
    if raw.is_ai_project:
        needed.append(ControlArea.AI_SAFETY)
    for area in needed:
        if area not in present_areas:
            _issue(issues, "MISSING_CONTROL_AREA", f"no control covers {area.value}")
    covered = {t.category for t in threats}
    for cat in sorted(STRIDE - covered, key=lambda x: x.value):
        _issue(issues, "MISSING_STRIDE_CATEGORY", f"no threat considers {cat.value}")
    if raw.is_ai_project:
        for cat in sorted(AI_THREATS - covered, key=lambda x: x.value):
            _issue(issues, "MISSING_AI_THREAT", f"AI project has no threat for {cat.value}")
    if raw.handles_sensitive_data and not raw.privacy_requirements:
        _issue(
            issues,
            "PRIVACY_REQUIREMENTS_MISSING",
            "sensitive data is handled but no privacy requirement is given",
        )

    plan: list[SecurityTestItem] = []
    tested: set[str] = set()
    for item in raw.test_plan:
        ids = [ctrl_key[k] for k in dict.fromkeys(item.control_keys) if k in ctrl_key]
        if not ids:
            _issue(
                issues,
                "TEST_PLAN_ITEM_DROPPED",
                f"test plan item '{item.name[:50]}' covers no known control",
            )
            continue
        tested.update(ids)
        plan.append(SecurityTestItem(name=item.name, method=item.method, control_ids=ids))
    for ctl in controls:
        if ctl.id not in tested:
            _issue(
                issues,
                "CONTROL_NO_TEST",
                f"{ctl.id} ({ctl.name}) has no security test plan item",
                ctl.id,
            )

    return SecuritySpec(
        is_ai_project=raw.is_ai_project,
        handles_sensitive_data=raw.handles_sensitive_data,
        attack_surface=raw.attack_surface,
        threats=threats,
        controls=controls,
        test_plan=plan,
        privacy_requirements=raw.privacy_requirements,
        approval_candidates=candidates,
        issues=issues,
    )


async def generate_security(gateway: LLMGateway, ctx: StageContext) -> SecuritySpec:
    untrusted = base_untrusted(ctx) | {
        "architecture": render_architecture(ctx.architecture),
        "technology": render_technology(ctx.extras.get("technology")),
        "dataapi": render_data_api(ctx.extras.get("dataapi")),
    }
    raw = await run_stage(gateway, "security", ctx, RawSecurityOutput, untrusted)
    return build_security(raw, ctx.requirements)

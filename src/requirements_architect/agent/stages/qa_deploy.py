"""Stage 10: testing and deployment. Checks coverage, strips secret-looking text, never lets
a test case exist without a real requirement."""

from __future__ import annotations

from requirements_architect.agent.stages.common import (
    StageContext,
    base_untrusted,
    render_architecture,
    render_data_api,
    render_technology,
    run_stage,
)
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import (
    Deployment,
    QaCase,
    QaSpec,
    QaType,
    RawQaOutput,
)
from requirements_architect.schemas.requirements import (
    NfrCategory,
    RequirementsSpec,
    Severity,
    SpecIssue,
)
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.ux import UxSpec
from requirements_architect.validation.secrets import scrub

_ENV_MARKERS = (("development", "dev"), ("staging", "stag"), ("production", "prod"))
_DEPLOY_TEXT = (
    "secrets_management",
    "migrations",
    "monitoring",
    "logging",
    "backups",
    "rollback",
    "recovery",
    "scaling",
    "containerization",
)


def _issue(
    issues: list[SpecIssue], code: str, msg: str, ref: str | None = None, *, error: bool = False
) -> None:
    issues.append(
        SpecIssue(
            code=code, severity=Severity.ERROR if error else Severity.WARNING, message=msg, ref=ref
        )
    )


def build_qa(
    raw: RawQaOutput,
    reqs: RequirementsSpec,
    *,
    has_endpoints: bool = False,
    has_ui: bool = False,
    is_ai: bool = False,
) -> QaSpec:
    issues: list[SpecIssue] = []
    valid_reqs = {f.id for f in reqs.functional} | {n.id for n in reqs.nonfunctional}

    cases: list[QaCase] = []
    for c in raw.test_cases:
        ok = [r for r in dict.fromkeys(c.requirement_ids) if r in valid_reqs]
        for r in dict.fromkeys(c.requirement_ids):
            if r not in valid_reqs:
                _issue(
                    issues,
                    "UNKNOWN_REQUIREMENT",
                    f"test case '{c.scenario[:40]}' cites unknown requirement {r}",
                )
        if not ok:
            _issue(
                issues,
                "TEST_CASE_DROPPED",
                f"test case '{c.scenario[:50]}' verifies no known requirement",
            )
            continue
        cid = f"TC-{len(cases) + 1:03d}"
        data, leaked_data = scrub("\n".join(c.test_data))
        if leaked_data:
            _issue(
                issues,
                "SECRET_IN_TEST_DATA",
                f"{cid} test data contained secret-looking text; redacted",
                cid,
                error=True,
            )
        cases.append(
            QaCase(
                id=cid,
                requirement_ids=ok,
                scenario=c.scenario,
                preconditions=c.preconditions,
                test_data=data.split("\n") if c.test_data else [],
                steps=c.steps,
                expected_result=c.expected_result,
                priority=c.priority,
                test_type=c.test_type,
                execution_criteria=c.execution_criteria,
            )
        )

    covered = {r for case in cases for r in case.requirement_ids}
    for fr in reqs.functional:
        if fr.id not in covered:
            _issue(issues, "FR_NO_TEST", f"{fr.id} has no test case", fr.id)
    for n in reqs.nonfunctional:
        if n.id not in covered:
            _issue(issues, "NFR_NO_TEST", f"{n.id} ({n.category.value}) has no test case", n.id)

    declared = {s.test_type for s in raw.strategy}
    needed = {QaType.UNIT, QaType.INTEGRATION, QaType.SECURITY}
    if has_endpoints:
        needed.add(QaType.API)
    if has_ui:
        needed.add(QaType.ACCESSIBILITY)
    if is_ai:
        needed.add(QaType.AI_EVAL)
    if any(n.category is NfrCategory.PERFORMANCE for n in reqs.nonfunctional):
        needed.add(QaType.PERFORMANCE)
    for t in sorted(needed - declared, key=lambda x: x.value):
        _issue(issues, "MISSING_STRATEGY_TYPE", f"no test strategy for {t.value}")
    if is_ai and not (raw.ai_evaluation and raw.ai_evaluation.strip()):
        _issue(issues, "AI_EVALUATION_MISSING", "AI project has no AI evaluation plan")

    dep = raw.deployment
    names = [e.name.lower() for e in dep.environments]
    for label, marker in _ENV_MARKERS:
        if not any(marker in n for n in names):
            _issue(issues, "MISSING_ENVIRONMENT", f"no {label} environment is described")
    updates: dict[str, object] = {}
    for fld in _DEPLOY_TEXT:
        value = getattr(dep, fld)
        if not value.strip():
            _issue(issues, "DEPLOY_SECTION_EMPTY", f"deployment section '{fld}' is empty")
        clean, found = scrub(value)
        if found:
            _issue(
                issues,
                "SECRET_IN_DEPLOYMENT",
                f"deployment '{fld}' contained secret-looking text; redacted",
                fld,
                error=True,
            )
            updates[fld] = clean
    steps_clean = []
    for step in dep.ci_cd:
        clean, found = scrub(step)
        if found:
            _issue(
                issues,
                "SECRET_IN_DEPLOYMENT",
                "a CI/CD step contained secret-looking text; redacted",
                "ci_cd",
                error=True,
            )
        steps_clean.append(clean)
    updates["ci_cd"] = steps_clean
    seen: set[str] = set()
    for v in dep.environment_variables:
        if v.name in seen:
            _issue(
                issues,
                "DUPLICATE_ENV_VAR",
                f"environment variable {v.name} is listed twice",
                v.name,
            )
        seen.add(v.name)
        _, found = scrub(v.purpose)
        if found:
            _issue(
                issues,
                "SECRET_IN_DEPLOYMENT",
                f"{v.name}: purpose contained secret-looking text",
                v.name,
                error=True,
            )
    deployment = Deployment.model_validate(dep.model_copy(update=updates).model_dump())
    deployment = deployment.model_copy(
        update={
            "environment_variables": [
                v.model_copy(update={"purpose": scrub(v.purpose)[0]})
                for v in deployment.environment_variables
            ]
        }
    )

    return QaSpec(
        strategy=raw.strategy,
        test_cases=cases,
        deployment=deployment,
        ai_evaluation=raw.ai_evaluation,
        issues=issues,
    )


async def generate_qa(gateway: LLMGateway, ctx: StageContext) -> QaSpec:
    api = ctx.extras.get("dataapi")
    sec = ctx.extras.get("security")
    ux = ctx.extras.get("ux")
    sec_txt = (
        "\n".join(f"{c.id} {c.name} ({c.area.value})" for c in sec.controls)
        if isinstance(sec, SecuritySpec)
        else "(none)"
    )
    untrusted = base_untrusted(ctx) | {
        "architecture": render_architecture(ctx.architecture),
        "technology": render_technology(ctx.extras.get("technology")),
        "dataapi": render_data_api(api),
        "security": sec_txt,
    }
    raw = await run_stage(gateway, "qa_deploy", ctx, RawQaOutput, untrusted)
    return build_qa(
        raw,
        ctx.requirements,
        has_endpoints=isinstance(api, DataApiSpec) and bool(api.endpoints),
        has_ui=isinstance(ux, UxSpec) and ux.has_ui,
        is_ai=isinstance(sec, SecuritySpec) and sec.is_ai_project,
    )

"""Stage 6: technology analysis. Package versions and licenses the model names are compared with
registry facts gathered during research; they are never silently accepted."""

from __future__ import annotations

from collections.abc import Callable

from requirements_architect.agent.stages.common import (
    StageContext,
    base_untrusted,
    render_architecture,
    run_stage,
)
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.architecture import ArchitectureSpec, ComponentKind
from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import Severity, SpecIssue
from requirements_architect.schemas.research import PackageFact, ResearchReport, VerificationStatus
from requirements_architect.schemas.technology import (
    ClaimStatus,
    RawTechnologyOutput,
    Technology,
    TechnologySpec,
)

STAGE = "stage_06_technology"


def _issue(issues: list[SpecIssue], code: str, msg: str, ref: str | None = None) -> None:
    issues.append(SpecIssue(code=code, severity=Severity.WARNING, message=msg, ref=ref))


def _norm_version(v: str) -> str:
    return v.strip().lstrip("vV")


def _compare(claimed: str | None, registry: str | None, norm: Callable[[str], str]) -> ClaimStatus:
    if not claimed:
        return ClaimStatus.NOT_SPECIFIED
    if registry is None:
        return ClaimStatus.UNVERIFIED
    return ClaimStatus.CONFIRMED if norm(claimed) == norm(registry) else ClaimStatus.DIFFERS


def _fact(report: ResearchReport | None, eco: str, name: str) -> PackageFact | None:
    for f in report.packages if report else []:
        if f.ecosystem == eco and f.name.lower() == name.lower():
            return f
    return None


def build_technology(
    raw: RawTechnologyOutput, arch: ArchitectureSpec | None, report: ResearchReport | None
) -> TechnologySpec:
    issues: list[SpecIssue] = []
    findings = {f.finding_id: f for f in report.findings} if report else {}
    comp_ids = {c.id for c in arch.components} if arch else set()
    techs: list[Technology] = []
    candidates: list[ApprovalCandidate] = []
    seen_names: set[str] = set()

    for i, t in enumerate(raw.technologies, 1):
        tid = f"TECH-{i:03d}"
        if t.name.strip().lower() in seen_names:
            _issue(issues, "DUPLICATE_TECHNOLOGY", f"{tid} duplicates technology '{t.name}'", tid)
        seen_names.add(t.name.strip().lower())

        cited = list(dict.fromkeys(t.finding_ids))
        for fid in cited:
            if fid not in findings:
                _issue(issues, "UNKNOWN_FINDING", f"{tid} cites unknown finding {fid}", tid)
        cited = [f for f in cited if f in findings]
        evidence = (
            "verified_finding"
            if any(findings[f].verification is VerificationStatus.VERIFIED for f in cited)
            else "unverified"
        )
        components = [c for c in dict.fromkeys(t.component_ids) if c in comp_ids]
        for c in dict.fromkeys(t.component_ids):
            if c not in comp_ids:
                _issue(issues, "UNKNOWN_COMPONENT", f"{tid} cites unknown component {c}", tid)

        fact = _fact(report, t.package.ecosystem, t.package.name) if t.package else None
        if t.package and fact is None:
            _issue(
                issues,
                "PACKAGE_NOT_RESEARCHED",
                f"{tid}: no registry data was retrieved for {t.package.ecosystem}:{t.package.name}",
                tid,
            )
        registry_version = fact.latest_version if fact else None
        registry_license = fact.license if fact else None
        version_status = _compare(t.recommended_version, registry_version, _norm_version)
        license_status = _compare(t.license, registry_license, lambda x: x.strip().casefold())
        if version_status is ClaimStatus.DIFFERS:
            _issue(
                issues,
                "VERSION_DIFFERS_FROM_REGISTRY",
                f"{tid}: proposed {t.recommended_version}, registry latest is {registry_version}",
                tid,
            )
        if license_status is ClaimStatus.DIFFERS:
            _issue(
                issues,
                "LICENSE_DIFFERS_FROM_REGISTRY",
                f"{tid}: proposed {t.license}, registry reports {registry_license}",
                tid,
            )
        if not t.license:
            _issue(issues, "LICENSE_UNKNOWN", f"{tid} ({t.name}) has no license recorded", tid)
        if fact and fact.advisories:
            _issue(
                issues,
                "KNOWN_ADVISORIES",
                f"{tid}: {len(fact.advisories)} advisory record(s) found; check the chosen version",
                tid,
            )
        if not t.alternatives:
            _issue(issues, "TECH_NO_ALTERNATIVES", f"{tid} ({t.name}) lists no alternatives", tid)
        if not t.advantages or not t.disadvantages:
            _issue(
                issues,
                "TECH_NO_TRADEOFFS",
                f"{tid} ({t.name}) lacks advantages or disadvantages",
                tid,
            )

        if t.vendor_lock_in == "high" or t.significant_cost:
            why = ", ".join(
                x
                for x, on in (
                    ("substantial vendor lock-in", t.vendor_lock_in == "high"),
                    ("significant cost", t.significant_cost),
                )
                if on
            )
            candidates.append(
                ApprovalCandidate(
                    source_stage=STAGE,
                    ref=tid,
                    decision=f"Adopt {t.name}",
                    reason=why,
                    affected_ids=components,
                )
            )
        techs.append(
            Technology(
                id=tid,
                name=t.name,
                category=t.category,
                purpose=t.purpose,
                reason=t.reason,
                alternatives=t.alternatives,
                advantages=t.advantages,
                disadvantages=t.disadvantages,
                dependencies=t.dependencies,
                compatibility=t.compatibility,
                recommended_version=t.recommended_version,
                version_status=version_status,
                registry_version=registry_version,
                license=t.license,
                license_status=license_status,
                registry_license=registry_license,
                advisories=list(fact.advisories) if fact else [],
                advisories_checked=bool(fact and fact.advisories_checked),
                infrastructure=t.infrastructure,
                skills=t.skills,
                finding_ids=cited,
                evidence=evidence,
                component_ids=components,
                package=t.package,
                vendor_lock_in=t.vendor_lock_in,
                significant_cost=t.significant_cost,
            )
        )

    if arch:
        covered = {cid for t in techs for cid in t.component_ids}
        for comp in arch.components:
            if comp.kind is not ComponentKind.EXTERNAL and comp.id not in covered:
                _issue(
                    issues,
                    "COMPONENT_NO_TECHNOLOGY",
                    f"{comp.id} ({comp.name}) has no technology assigned",
                    comp.id,
                )
    return TechnologySpec(technologies=techs, approval_candidates=candidates, issues=issues)


def _render_packages(report: ResearchReport | None) -> str:
    lines = [
        f"{p.ecosystem}:{p.name} latest={p.latest_version} license={p.license} advisories={len(p.advisories)}"
        for p in (report.packages if report else [])
    ]
    return "\n".join(lines) or "(none)"


async def generate_technology(gateway: LLMGateway, ctx: StageContext) -> TechnologySpec:
    untrusted = base_untrusted(ctx) | {
        "architecture": render_architecture(ctx.architecture),
        "packages": _render_packages(ctx.research),
    }
    raw = await run_stage(gateway, "technology", ctx, RawTechnologyOutput, untrusted)
    return build_technology(raw, ctx.architecture, ctx.research)

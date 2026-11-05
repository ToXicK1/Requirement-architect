"""Quality gates, remediation tasks and report assembly (pure functions)."""

from __future__ import annotations

from typing import Literal

from requirements_architect.audit.checks import run_checks
from requirements_architect.audit.specset import SpecSet
from requirements_architect.schemas.audit import (
    AuditFinding,
    AuditReport,
    AuditRound,
    AuditSeverity,
    AuditThresholds,
    AuditVerdict,
    GateResult,
    RemediationTask,
)

_TRACE_CODES = {"FR_NO_COMPONENT", "FR_NO_TEST"}
_SECURITY_GATE_CODES = {
    "HIGH_RISK_NO_CONTROL",
    "HIGH_RISK_ACCEPTED",
    "UNSUPPORTED_COMPLIANCE_CLAIM",
    "NO_AUTH_CONTROL",
}


def evaluate_gates(findings: list[AuditFinding], th: AuditThresholds) -> list[GateResult]:
    def codes(*cs: str) -> list[AuditFinding]:
        return [f for f in findings if f.code in cs]

    blockers = [f for f in findings if f.severity is AuditSeverity.BLOCKER]
    majors = [f for f in findings if f.severity is AuditSeverity.MAJOR]
    trace = codes(*_TRACE_CODES)
    secrets = codes("SECRET_IN_SPEC")
    sec = codes(*_SECURITY_GATE_CODES)
    return [
        GateResult(
            name="no_blockers", passed=not blockers, detail=f"{len(blockers)} blocker finding(s)"
        ),
        GateResult(
            name="major_findings_within_limit",
            passed=len(majors) <= th.max_major,
            detail=f"{len(majors)} major finding(s); limit {th.max_major}",
        ),
        GateResult(
            name="every_requirement_has_component_and_test",
            passed=not trace or not th.require_fr_component_and_test,
            detail=f"{len(trace)} functional requirement gap(s)",
        ),
        GateResult(
            name="no_secrets_in_specifications",
            passed=not secrets,
            detail=f"{len(secrets)} occurrence(s)",
        ),
        GateResult(
            name="security_risks_addressed",
            passed=not sec,
            detail=f"{len(sec)} unaddressed high risk / missing control / compliance claim finding(s)",
        ),
    ]


def make_tasks(findings: list[AuditFinding]) -> list[RemediationTask]:
    tasks: list[RemediationTask] = []
    for f in findings:
        if f.severity is AuditSeverity.INFO:
            continue
        owner = "auto" if f.auto_fixable and not f.needs_human else "human"
        verb = "Regenerate and re-validate" if owner == "auto" else "Decide and update"
        tasks.append(
            RemediationTask(
                id=f"RT-{len(tasks) + 1:03d}",
                finding_id=f.id,
                action=f"{verb}: {f.message}",
                owner=owner,
                stage=f.stage,
            )
        )
    return tasks


def count_by_severity(findings: list[AuditFinding]) -> dict[str, int]:
    return {s.value: sum(1 for f in findings if f.severity is s) for s in AuditSeverity}


STANDING_LIMITATIONS = (
    (
        "Passing the automated gates does not mean the specification is correct or approved; a human must still review it."
    ),
    (
        "Deterministic checks find structural problems; they cannot judge whether the requirements match what the business needs."
    ),
)


def build_report(
    findings: list[AuditFinding],
    *,
    thresholds: AuditThresholds | None = None,
    rounds: list[AuditRound] | None = None,
    llm_review: Literal["not_run", "completed", "failed"] = "not_run",
    llm_discarded: int = 0,
    source_versions: dict[str, int] | None = None,
    extra_limitations: list[str] | None = None,
) -> AuditReport:
    th = thresholds or AuditThresholds()
    gates = evaluate_gates(findings, th)
    limits = list(STANDING_LIMITATIONS) + (extra_limitations or [])
    if llm_review != "completed":
        limits.append("No independent LLM review was performed; only deterministic checks ran.")
    return AuditReport(
        verdict=AuditVerdict.READY_FOR_REVIEW
        if all(g.passed for g in gates)
        else AuditVerdict.NOT_READY,
        findings=findings,
        gates=gates,
        tasks=make_tasks(findings),
        rounds=rounds or [],
        thresholds=th,
        llm_review=llm_review,
        llm_discarded=llm_discarded,
        limitations=limits,
        source_versions=source_versions or {},
    )


def audit_deterministic(
    specs: SpecSet,
    thresholds: AuditThresholds | None = None,
    source_versions: dict[str, int] | None = None,
) -> AuditReport:
    return build_report(run_checks(specs), thresholds=thresholds, source_versions=source_versions)

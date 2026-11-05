"""Run the audit: deterministic checks + optional independent LLM review, with bounded,
requirement-preserving remediation by regenerating design stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from requirements_architect.agent.design_nodes import DESIGN_STAGES, run_design_stage
from requirements_architect.audit.checks import finalize, run_checks
from requirements_architect.audit.engine import build_report, count_by_severity
from requirements_architect.audit.review import review
from requirements_architect.audit.specset import SpecSet
from requirements_architect.core.config import Settings
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.audit import (
    AuditFinding,
    AuditReport,
    AuditRound,
    AuditSeverity,
    AuditThresholds,
)
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.requirements import RequirementsSpec
from requirements_architect.schemas.research import ResearchReport
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.state import (
    Dependency,
    ProjectBrief,
    StageId,
    WorkflowStatus,
)
from requirements_architect.schemas.technology import TechnologySpec
from requirements_architect.schemas.ux import UxSpec
from requirements_architect.storage.repository import Repository

_ALLOWED = {
    WorkflowStatus.SPECS_COMPLETE.value,
    WorkflowStatus.AUDIT_COMPLETE.value,
    WorkflowStatus.DOCUMENTS_COMPLETE.value,
}
_FIXABLE_SEVERITIES = {AuditSeverity.BLOCKER, AuditSeverity.MAJOR, AuditSeverity.MINOR}


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditLimits:
    max_rounds: int = 2  # remediation rounds after the first audit
    max_stage_runs: int = 12  # total LLM stage regenerations across all rounds
    llm_review: bool = True
    thresholds: AuditThresholds = field(default_factory=AuditThresholds)

    @classmethod
    def from_settings(cls, settings: Settings) -> AuditLimits:
        return cls(
            max_rounds=settings.audit_max_rounds,
            max_stage_runs=settings.audit_max_stage_runs,
            llm_review=settings.audit_llm_review,
            thresholds=AuditThresholds(max_major=settings.audit_max_major),
        )


class AuditService:
    def __init__(
        self,
        repo: Repository,
        gateway: LLMGateway,
        limits: AuditLimits | None = None,
        review_gateway: LLMGateway | None = None,
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        # A separate gateway (another model/provider) makes the review more independent.
        self._review_gateway = review_gateway or gateway
        self._limits = limits or AuditLimits()

    async def _load(self, project_id: str) -> tuple[SpecSet, ProjectBrief, dict[str, int]]:
        versions: dict[str, int] = {}

        async def need[T: BaseModel](stage: StageId, model: type[T]) -> T:
            got = await self._repo.get_latest_output(project_id, stage, model)
            if got is None:
                raise AuditError(f"missing stage output: {stage.value}")
            versions[stage.value] = got[0].version
            return got[1]

        brief = await need(StageId.PROBLEM_UNDERSTANDING, ProjectBrief)
        specs = SpecSet(
            brief=brief,
            requirements=await need(StageId.REQUIREMENTS, RequirementsSpec),
            architecture=await need(StageId.ARCHITECTURE, ArchitectureSpec),
            technology=await need(StageId.TECHNOLOGY, TechnologySpec),
            data_api=await need(StageId.DATA_API, DataApiSpec),
            security=await need(StageId.SECURITY, SecuritySpec),
            ux=await need(StageId.UX, UxSpec),
            qa=await need(StageId.QA_DEPLOY, QaSpec),
        )
        research = await self._repo.get_latest_output(project_id, StageId.RESEARCH, ResearchReport)
        if research:
            versions[StageId.RESEARCH.value] = research[0].version
            specs = SpecSet(**{**specs.__dict__, "research": research[1]})
        return specs, brief, versions

    async def run(self, project_id: str) -> AuditReport:
        project = await self._repo.get_project(project_id)
        if project.status not in _ALLOWED:
            raise AuditError(
                f"project status is '{project.status}'; the specifications must be complete first"
            )
        lim = self._limits
        specs, brief, versions = await self._load(project_id)
        rounds: list[AuditRound] = []
        runs_left = lim.max_stage_runs
        previous_fixable: int | None = None
        notes: list[str] = []

        for round_no in range(1, lim.max_rounds + 2):
            findings = run_checks(specs)
            fixable = [
                f
                for f in findings
                if f.auto_fixable and not f.needs_human and f.severity in _FIXABLE_SEVERITIES
            ]
            record = AuditRound(
                round=round_no, findings=len(findings), by_severity=count_by_severity(findings)
            )
            rounds.append(record)
            if not fixable:
                break
            if round_no > lim.max_rounds:
                notes.append(f"remediation stopped: round limit ({lim.max_rounds}) reached")
                break
            if previous_fixable is not None and len(fixable) >= previous_fixable:
                notes.append("remediation stopped: the last round did not reduce fixable findings")
                break
            previous_fixable = len(fixable)
            start = min(_index(f) for f in fixable)
            todo = DESIGN_STAGES[start:]  # later stages consume earlier ids, so redo them all
            if len(todo) > runs_left:
                notes.append("remediation stopped: stage-run budget exhausted")
                break
            by_stage: dict[StageId, list[AuditFinding]] = {}
            for f in fixable:
                if f.stage is not None:
                    by_stage.setdefault(f.stage, []).append(f)
            for stage in todo:
                fb = "\n".join(f"- {f.code}: {f.message}" for f in by_stage.get(stage.stage_id, []))
                await run_design_stage(
                    self._gateway, self._repo, stage, project_id, brief, fb or None
                )
                runs_left -= 1
            record.regenerated = [s.name for s in todo]
            specs, brief, versions = await self._load(project_id)

        findings = run_checks(specs)
        llm_state: Literal["not_run", "completed", "failed"] = "not_run"
        discarded = 0
        if lim.llm_review:
            try:
                extra, discarded = await review(self._review_gateway, specs, project_id)
                findings = finalize([*findings, *extra])
                llm_state = "completed"
            except Exception as exc:  # noqa: BLE001 - any provider failure must not hide the audit
                llm_state = "failed"
                notes.append(f"independent LLM review failed: {type(exc).__name__}")
        report = build_report(
            findings,
            thresholds=lim.thresholds,
            rounds=rounds,
            llm_review=llm_state,
            llm_discarded=discarded,
            source_versions=versions,
            extra_limitations=notes,
        )
        deps = [Dependency(stage_id=StageId(k), version=v) for k, v in versions.items()]
        await self._repo.save_stage_output(project_id, StageId.AUDIT, report, deps)
        await self._repo.set_status(project_id, WorkflowStatus.AUDIT_COMPLETE.value)
        return report


def _index(f: AuditFinding) -> int:
    for n, s in enumerate(DESIGN_STAGES):
        if s.stage_id is f.stage:
            return n
    return 0

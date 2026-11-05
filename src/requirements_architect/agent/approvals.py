"""Human approval requests: build them from the specs, record decisions, act on them.

Decisions are append-only. A decision only counts while the request it answered is unchanged
(fingerprint), so an approved item is not asked again unless the underlying decision changes."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel, Field

from requirements_architect.agent.design_nodes import DESIGN_STAGES, run_design_stage
from requirements_architect.agent.stages.requirements import approve_nfr_targets
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.requirements import RequirementsSpec, TargetStatus
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.state import ProjectBrief, StageId
from requirements_architect.schemas.technology import TechnologySpec
from requirements_architect.schemas.ux import UxSpec
from requirements_architect.storage.approvals import ApprovalRepository
from requirements_architect.storage.repository import Repository
from requirements_architect.validation.secrets import scrub

OPTIONS = ("approve", "reject", "request_revision")
_DOCS = {
    StageId.REQUIREMENTS: ["02_SOFTWARE_REQUIREMENTS/NON_FUNCTIONAL_REQUIREMENTS.md"],
    StageId.ARCHITECTURE: [
        "03_ARCHITECTURE/ARCHITECTURE_DECISIONS.md",
        "03_ARCHITECTURE/COMPONENT_DESIGN.md",
    ],
    StageId.TECHNOLOGY: [
        "04_TECHNICAL_SPECIFICATIONS/TECHNOLOGY_STACK.md",
        "04_TECHNICAL_SPECIFICATIONS/DEPENDENCIES.md",
    ],
    StageId.DATA_API: [
        "04_TECHNICAL_SPECIFICATIONS/DATABASE_SCHEMA.md",
        "04_TECHNICAL_SPECIFICATIONS/API_SPECIFICATION.md",
    ],
    StageId.SECURITY: ["05_SECURITY/THREAT_MODEL.md", "05_SECURITY/SECURITY_REQUIREMENTS.md"],
    StageId.UX: ["06_UI_UX/SCREEN_SPECIFICATIONS.md"],
    StageId.QA_DEPLOY: [
        "07_QUALITY_ASSURANCE/TEST_STRATEGY.md",
        "08_INFRASTRUCTURE/DEPLOYMENT_PLAN.md",
    ],
}


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_REVISION = "request_revision"


_STATE_FOR = {
    Decision.APPROVE: ApprovalState.APPROVED,
    Decision.REJECT: ApprovalState.REJECTED,
    Decision.REQUEST_REVISION: ApprovalState.REVISION_REQUESTED,
}


class ApprovalRequest(BaseModel):
    stage_id: StageId
    ref: str
    kind: str  # architecture_decision | technology | threat | nfr_target | other
    decision: str
    reason: str
    options: list[str] = Field(default_factory=lambda: list(OPTIONS))
    recommended: str | None = None  # None = the system makes no recommendation
    advantages: list[str] = Field(default_factory=list)
    disadvantages: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    affected_ids: list[str] = Field(default_factory=list)
    affected_documents: list[str] = Field(default_factory=list)
    fingerprint: str
    state: ApprovalState = ApprovalState.PENDING
    note: str = ""
    decided_by: str | None = None


class ApprovalError(Exception):
    pass


def _enrich(
    req: ApprovalRequest,
    arch: ArchitectureSpec | None,
    tech: TechnologySpec | None,
    sec: SecuritySpec | None,
) -> ApprovalRequest:
    """Add the facts a reviewer needs from the spec itself. Never invents a recommendation."""
    if arch:
        for d in arch.decisions:
            if d.id == req.ref:
                req.kind = "architecture_decision"
                req.advantages = [d.rationale]
                req.disadvantages = list(d.tradeoffs)
                req.alternatives = [f"{a.name}: {a.why_rejected}" for a in d.alternatives]
    if tech:
        for t in tech.technologies:
            if t.id == req.ref:
                req.kind = "technology"
                req.advantages, req.disadvantages = list(t.advantages), list(t.disadvantages)
                req.alternatives = list(t.alternatives)
                if t.vendor_lock_in != "none":
                    req.consequences.append(f"Vendor lock-in: {t.vendor_lock_in}")
                if t.significant_cost:
                    req.consequences.append("Significant cost")
    if sec:
        for th in sec.threats:
            if th.id == req.ref:
                req.kind = "threat"
                req.consequences = [
                    f"Residual risk ({th.risk_level}): {th.residual_note or 'none stated'}"
                ]
    return req


def _fingerprint(stage: str, ref: str, decision: str, reason: str, affected: list[str]) -> str:
    raw = json.dumps([stage, ref, decision, reason, sorted(affected)], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class ApprovalService:
    def __init__(
        self, repo: Repository, approvals: ApprovalRepository, gateway: LLMGateway | None = None
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._approvals = approvals
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _requests(self, project_id: str) -> list[ApprovalRequest]:
        async def get[T: BaseModel](stage: StageId, model: type[T]) -> T | None:
            got = await self._repo.get_latest_output(project_id, stage, model)
            return got[1] if got else None

        reqs = await get(StageId.REQUIREMENTS, RequirementsSpec)
        arch = await get(StageId.ARCHITECTURE, ArchitectureSpec)
        tech = await get(StageId.TECHNOLOGY, TechnologySpec)
        api = await get(StageId.DATA_API, DataApiSpec)
        sec = await get(StageId.SECURITY, SecuritySpec)
        ux = await get(StageId.UX, UxSpec)
        qa = await get(StageId.QA_DEPLOY, QaSpec)
        out: list[ApprovalRequest] = []
        for spec in (arch, tech, api, sec, ux, qa):
            for c in spec.approval_candidates if spec else []:
                try:
                    stage = StageId(c.source_stage)
                except ValueError:
                    continue
                req = ApprovalRequest(
                    stage_id=stage,
                    ref=c.ref,
                    kind="other",
                    decision=c.decision,
                    reason=c.reason,
                    affected_ids=c.affected_ids,
                    affected_documents=_DOCS.get(stage, []),
                    fingerprint=_fingerprint(
                        stage.value, c.ref, c.decision, c.reason, c.affected_ids
                    ),
                )
                out.append(_enrich(req, arch, tech, sec))
        for n in reqs.nonfunctional if reqs else []:
            if n.target_status is TargetStatus.PROPOSED and n.target:
                decision = f"Adopt target '{n.target}' for {n.id} ({n.category.value})"
                reason = "The target was proposed by the system; the user did not state it."
                out.append(
                    ApprovalRequest(
                        stage_id=StageId.REQUIREMENTS,
                        ref=n.id,
                        kind="nfr_target",
                        decision=decision,
                        reason=reason,
                        consequences=[
                            "Approving records the target as user-approved in a new requirements version.",
                            "Tests and acceptance checks will treat the target as binding.",
                        ],
                        affected_ids=[n.id],
                        affected_documents=_DOCS[StageId.REQUIREMENTS],
                        fingerprint=_fingerprint(
                            StageId.REQUIREMENTS.value, n.id, decision, reason, [n.id]
                        ),
                    )
                )
        return out

    async def list(self, project_id: str) -> list[ApprovalRequest]:
        latest = await self._approvals.latest(project_id)
        reqs = await self._requests(project_id)
        # Approved NFR targets are no longer proposed, so they drop out of the requests; keep them
        # visible as decisions already made.
        for (stage, ref), row in latest.items():
            if (
                stage == StageId.REQUIREMENTS.value
                and not any(r.ref == ref and r.stage_id.value == stage for r in reqs)
                and row.decision == Decision.APPROVE.value
            ):
                reqs.append(
                    ApprovalRequest(
                        stage_id=StageId.REQUIREMENTS,
                        ref=ref,
                        kind="nfr_target",
                        decision=f"Target for {ref}",
                        reason="Approved earlier.",
                        fingerprint=row.fingerprint,
                        state=ApprovalState.APPROVED,
                        note=row.note,
                        decided_by=row.actor_id,
                    )
                )
        for r in reqs:
            hit = latest.get((r.stage_id.value, r.ref))
            if hit and hit.fingerprint == r.fingerprint:
                r.state = _STATE_FOR[Decision(hit.decision)]
                r.note, r.decided_by = hit.note, hit.actor_id
        return reqs

    async def states(self, project_id: str) -> dict[tuple[str, str], str]:
        return {(r.stage_id.value, r.ref): r.state.value for r in await self.list(project_id)}

    async def decide(
        self,
        project_id: str,
        stage_id: StageId,
        ref: str,
        fingerprint: str,
        decision: Decision,
        note: str,
        actor_id: str,
    ) -> ApprovalRequest:
        note, _ = scrub(note.strip()[:2000])
        async with self._locks[project_id]:
            current = {(r.stage_id, r.ref): r for r in await self.list(project_id)}
            req = current.get((stage_id, ref))
            if req is None:
                raise ApprovalError("no such approval request")
            if req.fingerprint != fingerprint:
                raise ApprovalError(
                    "the request changed since it was shown; reload and decide again"
                )
            if decision is Decision.REQUEST_REVISION and not note:
                raise ApprovalError("a revision request needs a note saying what to change")
            await self._approvals.add(
                project_id, stage_id.value, ref, fingerprint, decision.value, note, actor_id
            )
            if decision is Decision.APPROVE and req.kind == "nfr_target":
                await self._approve_nfr(project_id, ref)
            if decision is Decision.REQUEST_REVISION and req.kind != "nfr_target":
                await self._revise(project_id, stage_id, req, note)
        after = {(r.stage_id, r.ref): r for r in await self.list(project_id)}
        return after.get((stage_id, ref)) or req.model_copy(
            update={"state": _STATE_FOR[decision], "note": note}
        )

    async def _approve_nfr(self, project_id: str, nfr_id: str) -> None:
        got = await self._repo.get_latest_output(project_id, StageId.REQUIREMENTS, RequirementsSpec)
        if got is None:
            raise ApprovalError("requirements output is missing")
        meta, spec = got
        updated = approve_nfr_targets(spec, [nfr_id])
        # A new version, never an overwrite: the earlier version stays as the record.
        await self._repo.save_stage_output(
            project_id, StageId.REQUIREMENTS, updated, meta.depends_on
        )

    async def _revise(
        self, project_id: str, stage_id: StageId, req: ApprovalRequest, note: str
    ) -> None:
        if self._gateway is None:
            raise ApprovalError("a revision needs the LLM gateway, which is not configured")
        start = next((n for n, s in enumerate(DESIGN_STAGES) if s.stage_id is stage_id), None)
        if start is None:
            return
        found = await self._repo.get_latest_output(
            project_id, StageId.PROBLEM_UNDERSTANDING, ProjectBrief
        )
        if found is None:
            raise ApprovalError("project brief is missing")
        feedback = f"A human reviewer asked for a revision of {req.ref} ({req.decision}): {note}"
        for stage in DESIGN_STAGES[start:]:  # later stages consume this stage's ids
            await run_design_stage(
                self._gateway,
                self._repo,
                stage,
                project_id,
                found[1],
                feedback if stage.stage_id is stage_id else None,
            )

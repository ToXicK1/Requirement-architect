"""Workflow service: start / resume / retry / status with input validation and per-project locking."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel

from requirements_architect.schemas.state import ClarificationAnswer, WorkflowStatus
from requirements_architect.storage.repository import Repository

log = structlog.get_logger()


class WorkflowStateError(Exception):
    """Operation not valid in the workflow's current state (HTTP 409 at the API layer)."""


class AnswerValidationError(ValueError):
    """Submitted clarification answers do not match the open questions (HTTP 422)."""


class Snapshot(BaseModel):
    project_id: str
    status: str
    round: int = 0
    open_questions: list[dict[str, Any]] = []
    brief_version: int | None = None


class WorkflowService:
    def __init__(self, graph: Any, repo: Repository) -> None:
        self._graph = graph
        self._repo = repo
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)  # in-process only

    @staticmethod
    def _cfg(project_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": project_id}}

    async def snapshot(self, project_id: str) -> Snapshot:
        st = await self._graph.aget_state(self._cfg(project_id))
        vals: dict[str, Any] = st.values or {}
        waiting = any(t.interrupts for t in st.tasks)
        if waiting:
            status = WorkflowStatus.AWAITING_CLARIFICATION.value
        elif not vals:
            status = (await self._repo.get_project(project_id)).status
        elif st.next:
            # Paused mid-graph without an interrupt: either running right now, or it failed.
            persisted = (await self._repo.get_project(project_id)).status
            status = (
                persisted
                if persisted in (WorkflowStatus.RUNNING.value, WorkflowStatus.FAILED.value)
                else WorkflowStatus.FAILED.value
            )
        else:
            status = vals.get("status", WorkflowStatus.RUNNING.value)
        return Snapshot(
            project_id=project_id,
            status=status,
            round=vals.get("round", 0),
            open_questions=vals.get("open_questions", []) if waiting else [],
            brief_version=vals.get("brief_version"),
        )

    async def _run(self, project_id: str, payload: Any) -> Snapshot:
        try:
            await self._graph.ainvoke(payload, self._cfg(project_id))
        except Exception as exc:
            await self._repo.set_status(project_id, WorkflowStatus.FAILED.value)
            log.error("workflow_failed", project_id=project_id, error_type=type(exc).__name__)
            raise
        return await self.snapshot(project_id)

    async def start(self, project_id: str) -> Snapshot:
        async with self._locks[project_id]:
            project = await self._repo.get_project(project_id)
            existing = await self._graph.aget_state(self._cfg(project_id))
            if existing.values:
                raise WorkflowStateError("workflow already started; use status/resume/retry")
            return await self._run(
                project.id,
                {"project_id": project.id, "problem_statement": project.problem_statement},
            )

    @staticmethod
    def _check_answers(snap: Snapshot, answers: Sequence[ClarificationAnswer]) -> None:
        open_ids = {q["id"] for q in snap.open_questions}
        ids = [a.question_id for a in answers]
        if not answers:
            raise AnswerValidationError("no answers supplied")
        if len(ids) != len(set(ids)):
            raise AnswerValidationError("duplicate question ids in answers")
        unknown = set(ids) - open_ids
        if unknown:
            raise AnswerValidationError(f"answers for unknown/closed questions: {sorted(unknown)}")

    async def validate_answers(
        self, project_id: str, answers: Sequence[ClarificationAnswer]
    ) -> None:
        """Fail fast (before a long run is started in the background)."""
        snap = await self.snapshot(project_id)
        if snap.status != WorkflowStatus.AWAITING_CLARIFICATION.value:
            raise WorkflowStateError(f"workflow is not awaiting answers (status={snap.status})")
        self._check_answers(snap, answers)

    async def resume(self, project_id: str, answers: Sequence[ClarificationAnswer]) -> Snapshot:
        async with self._locks[project_id]:
            snap = await self.snapshot(project_id)
            if snap.status != WorkflowStatus.AWAITING_CLARIFICATION.value:
                raise WorkflowStateError(f"workflow is not awaiting answers (status={snap.status})")
            self._check_answers(snap, answers)
            payload: Command[Any] = Command(
                resume={"answers": [a.model_dump(mode="json") for a in answers]}
            )
            return await self._run(project_id, payload)

    async def retry(self, project_id: str) -> Snapshot:
        async with self._locks[project_id]:
            snap = await self.snapshot(project_id)
            if snap.status != WorkflowStatus.FAILED.value:
                raise WorkflowStateError(f"nothing to retry (status={snap.status})")
            return await self._run(project_id, None)

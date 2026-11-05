"""Persistence operations. Each public method is one transaction."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requirements_architect.llm.usage import UsageRecord
from requirements_architect.schemas.state import (
    ClarificationAnswer,
    Dependency,
    OutputMeta,
    OutputStatus,
    StageId,
)
from requirements_architect.storage.models import (
    ClarificationAnswerRow,
    LLMUsageRow,
    Project,
    StageOutput,
)


class NotFoundError(Exception):
    pass


class Repository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create_project(
        self, name: str, problem_statement: str, owner_id: str | None = None
    ) -> Project:
        async with self._factory() as s, s.begin():
            p = Project(name=name, problem_statement=problem_statement, owner_id=owner_id)
            s.add(p)
        return p

    async def get_project(self, project_id: str) -> Project:
        async with self._factory() as s:
            p = await s.get(Project, project_id)
        if p is None:
            raise NotFoundError(project_id)
        return p

    async def set_status(self, project_id: str, status: str) -> None:
        async with self._factory() as s, s.begin():
            await s.execute(update(Project).where(Project.id == project_id).values(status=status))

    async def save_stage_output(
        self,
        project_id: str,
        stage_id: StageId,
        payload: BaseModel,
        depends_on: Sequence[Dependency] = (),
    ) -> OutputMeta:
        """Append a new version; the previous latest is marked superseded (never deleted).
        The unique (project, stage, version) constraint guards against concurrent writers."""
        async with self._factory() as s, s.begin():
            current = await s.scalar(
                select(func.max(StageOutput.version)).where(
                    StageOutput.project_id == project_id, StageOutput.stage_id == stage_id.value
                )
            )
            version = (current or 0) + 1
            await s.execute(
                update(StageOutput)
                .where(
                    StageOutput.project_id == project_id,
                    StageOutput.stage_id == stage_id.value,
                    StageOutput.status == OutputStatus.DRAFT.value,
                )
                .values(status=OutputStatus.SUPERSEDED.value)
            )
            row = StageOutput(
                project_id=project_id,
                stage_id=stage_id.value,
                version=version,
                status=OutputStatus.DRAFT.value,
                payload=payload.model_dump(mode="json"),
                depends_on=[d.model_dump(mode="json") for d in depends_on],
            )
            s.add(row)
        return OutputMeta(
            project_id=project_id,
            stage_id=stage_id,
            version=version,
            status=OutputStatus.DRAFT,
            created_at=row.created_at,
            depends_on=list(depends_on),
        )

    async def get_latest_output[T: BaseModel](
        self, project_id: str, stage_id: StageId, model: type[T]
    ) -> tuple[OutputMeta, T] | None:
        async with self._factory() as s:
            row = await s.scalar(
                select(StageOutput)
                .where(StageOutput.project_id == project_id, StageOutput.stage_id == stage_id.value)
                .order_by(StageOutput.version.desc())
                .limit(1)
            )
        if row is None:
            return None
        meta = OutputMeta(
            project_id=row.project_id,
            stage_id=stage_id,
            version=row.version,
            status=OutputStatus(row.status),
            created_at=row.created_at,
            depends_on=[Dependency.model_validate(d) for d in row.depends_on],
        )
        return meta, model.model_validate(row.payload)

    async def list_versions(self, project_id: str, stage_id: StageId) -> list[int]:
        async with self._factory() as s:
            rows = await s.scalars(
                select(StageOutput.version)
                .where(StageOutput.project_id == project_id, StageOutput.stage_id == stage_id.value)
                .order_by(StageOutput.version)
            )
            return list(rows)

    async def save_answers(self, project_id: str, answers: Sequence[ClarificationAnswer]) -> None:
        async with self._factory() as s, s.begin():
            for a in answers:
                row = await s.get(ClarificationAnswerRow, (project_id, a.question_id))
                if row is None:
                    s.add(
                        ClarificationAnswerRow(
                            project_id=project_id,
                            question_id=a.question_id,
                            answer=a.answer,
                            accepted_recommendation=a.accepted_recommendation,
                        )
                    )
                else:
                    row.answer, row.accepted_recommendation = a.answer, a.accepted_recommendation

    async def get_answers(self, project_id: str) -> dict[str, ClarificationAnswer]:
        async with self._factory() as s:
            rows = await s.scalars(
                select(ClarificationAnswerRow).where(
                    ClarificationAnswerRow.project_id == project_id
                )
            )
            return {
                r.question_id: ClarificationAnswer(
                    question_id=r.question_id,
                    answer=r.answer,
                    accepted_recommendation=r.accepted_recommendation,
                )
                for r in rows
            }

    async def record_usage(self, rec: UsageRecord) -> None:
        async with self._factory() as s, s.begin():
            s.add(
                LLMUsageRow(
                    project_id=rec.project_id,
                    timestamp=rec.timestamp,
                    provider=rec.provider,
                    model=rec.model,
                    prompt_id=rec.prompt_id,
                    prompt_version=rec.prompt_version,
                    input_tokens=rec.input_tokens,
                    output_tokens=rec.output_tokens,
                    estimated_cost_usd=(
                        str(rec.estimated_cost_usd) if rec.estimated_cost_usd is not None else None
                    ),
                    latency_seconds=rec.latency_seconds,
                    success=rec.success,
                    error_type=rec.error_type,
                    attempt=rec.attempt,
                )
            )

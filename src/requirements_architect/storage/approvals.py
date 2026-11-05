from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requirements_architect.storage.models import ApprovalRow


class ApprovalRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def add(
        self,
        project_id: str,
        stage_id: str,
        ref: str,
        fingerprint: str,
        decision: str,
        note: str,
        actor_id: str,
    ) -> ApprovalRow:
        row = ApprovalRow(
            project_id=project_id,
            stage_id=stage_id,
            ref=ref,
            fingerprint=fingerprint,
            decision=decision,
            note=note,
            actor_id=actor_id,
        )
        async with self._factory() as s, s.begin():
            s.add(row)
        return row

    async def history(self, project_id: str) -> list[ApprovalRow]:
        async with self._factory() as s:
            rows = await s.scalars(
                select(ApprovalRow)
                .where(ApprovalRow.project_id == project_id)
                .order_by(ApprovalRow.created_at, ApprovalRow.id)
            )
            return list(rows.all())

    async def latest(self, project_id: str) -> dict[tuple[str, str], ApprovalRow]:
        """Current decision per (stage, ref): the most recent row."""
        out: dict[tuple[str, str], ApprovalRow] = {}
        for row in await self.history(project_id):
            out[(row.stage_id, row.ref)] = row
        return out

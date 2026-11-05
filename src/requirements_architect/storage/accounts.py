"""Users, sessions and the activity log. Separate from project data on purpose."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requirements_architect.core.security import token_hash
from requirements_architect.storage.models import AuditLogRow, SessionRow, User


class UsernameTakenError(Exception):
    pass


class AccountRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create_user(self, username: str, password_hash: str) -> User:
        user = User(username=username, password_hash=password_hash)
        try:
            async with self._factory() as s, s.begin():
                s.add(user)
        except IntegrityError as exc:
            raise UsernameTakenError(username) from exc
        return user

    async def get_user_by_username(self, username: str) -> User | None:
        async with self._factory() as s:
            return await s.scalar(select(User).where(User.username == username))

    async def count_users(self) -> int:
        async with self._factory() as s:
            return len((await s.scalars(select(User.id))).all())

    async def create_session(self, user_id: str, token: str, ttl: timedelta) -> datetime:
        expires = datetime.now(UTC) + ttl
        async with self._factory() as s, s.begin():
            s.add(SessionRow(token_hash=token_hash(token), user_id=user_id, expires_at=expires))
        return expires

    async def user_for_token(self, token: str) -> User | None:
        async with self._factory() as s:
            row = await s.get(SessionRow, token_hash(token))
            if row is None or row.revoked:
                return None
            expires = row.expires_at
            if expires.tzinfo is None:  # SQLite returns naive datetimes
                expires = expires.replace(tzinfo=UTC)
            if expires <= datetime.now(UTC):
                return None
            user = await s.get(User, row.user_id)
        return user if user is not None and user.is_active else None

    async def revoke_token(self, token: str) -> None:
        async with self._factory() as s, s.begin():
            await s.execute(
                update(SessionRow)
                .where(SessionRow.token_hash == token_hash(token))
                .values(revoked=True)
            )

    async def log(
        self,
        action: str,
        user_id: str | None = None,
        project_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        async with self._factory() as s, s.begin():
            s.add(
                AuditLogRow(
                    action=action, user_id=user_id, project_id=project_id, detail=detail or {}
                )
            )

    async def activity(self, project_id: str, limit: int = 100) -> list[AuditLogRow]:
        async with self._factory() as s:
            rows = await s.scalars(
                select(AuditLogRow)
                .where(AuditLogRow.project_id == project_id)
                .order_by(AuditLogRow.timestamp.desc())
                .limit(limit)
            )
            return list(rows.all())

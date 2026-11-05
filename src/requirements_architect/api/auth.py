"""Authentication service: registration, login with rate limiting, token authentication."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from requirements_architect.core.security import (
    DUMMY_HASH,
    RateLimiter,
    check_password_policy,
    hash_password,
    new_token,
    normalize_username,
    verify_password,
)
from requirements_architect.storage.accounts import AccountRepository
from requirements_architect.storage.models import User


class AuthError(Exception):
    """Invalid credentials or token. The message is deliberately generic."""


class RateLimitedError(Exception):
    pass


class AuthService:
    def __init__(
        self,
        accounts: AccountRepository,
        session_ttl: timedelta,
        login_limiter: RateLimiter | None = None,
    ) -> None:
        self._accounts = accounts
        self._ttl = session_ttl
        self._limiter = login_limiter or RateLimiter(limit=5, window_seconds=300)
        self._ip_limiter = RateLimiter(limit=30, window_seconds=300)

    async def register(self, username: str, password: str) -> User:
        name = normalize_username(username)
        check_password_policy(password)
        digest = await asyncio.to_thread(hash_password, password)
        user = await self._accounts.create_user(name, digest)
        await self._accounts.log("user.register", user_id=user.id)
        return user

    async def login(self, username: str, password: str, client: str) -> tuple[str, User]:
        try:
            name = normalize_username(username)
        except ValueError:
            name = ""
        key = f"{client}|{name}"
        if not self._ip_limiter.allow(client) or not self._limiter.allow(key):
            raise RateLimitedError
        user = await self._accounts.get_user_by_username(name) if name else None
        # Always do one scrypt verification so response time does not reveal valid usernames.
        ok = await asyncio.to_thread(
            verify_password, password[:200], user.password_hash if user else DUMMY_HASH
        )
        if not (user and ok and user.is_active):
            await self._accounts.log("login.failed", detail={"username_valid": user is not None})
            raise AuthError
        self._limiter.reset(key)
        token = new_token()
        await self._accounts.create_session(user.id, token, self._ttl)
        await self._accounts.log("login.ok", user_id=user.id)
        return token, user

    async def authenticate(self, token: str) -> User:
        user = await self._accounts.user_for_token(token) if token else None
        if user is None:
            raise AuthError
        return user

    async def logout(self, token: str, user: User) -> None:
        await self._accounts.revoke_token(token)
        await self._accounts.log("logout", user_id=user.id)

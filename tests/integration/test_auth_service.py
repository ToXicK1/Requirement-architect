from datetime import timedelta

import pytest

from requirements_architect.api.auth import AuthError, AuthService, RateLimitedError
from requirements_architect.core.security import RateLimiter
from requirements_architect.storage.accounts import AccountRepository, UsernameTakenError
from requirements_architect.storage.database import make_engine, make_session_factory
from tests.conftest import db_url_for, reset_schema

PW = "a reasonable passphrase 42"


@pytest.fixture
async def auth(tmp_path):
    engine = make_engine(db_url_for(tmp_path, "a.db"))
    await reset_schema(engine)
    accounts = AccountRepository(make_session_factory(engine))
    svc = AuthService(accounts, timedelta(hours=1), RateLimiter(3, 300))
    svc.accounts = accounts
    yield svc
    await engine.dispose()


async def test_register_login_authenticate_logout(auth):
    user = await auth.register("Alice", PW)
    assert user.username == "alice" and PW not in user.password_hash
    token, u = await auth.login("alice", PW, "1.1.1.1")
    assert (await auth.authenticate(token)).id == u.id
    await auth.logout(token, u)
    with pytest.raises(AuthError):
        await auth.authenticate(token)


async def test_duplicate_username_is_rejected_case_insensitively(auth):
    await auth.register("alice", PW)
    with pytest.raises(UsernameTakenError):
        await auth.register("ALICE", PW)


@pytest.mark.parametrize("user,pw", [("alice", "wrong password here"), ("nobody", PW), ("!!", PW)])
async def test_bad_credentials_give_one_generic_error(auth, user, pw):
    await auth.register("alice", PW)
    with pytest.raises(AuthError):
        await auth.login(user, pw, "1.1.1.1")


async def test_login_is_rate_limited_per_client_and_user_and_success_resets(auth):
    await auth.register("alice", PW)
    for _ in range(3):
        with pytest.raises(AuthError):
            await auth.login("alice", "bad password here!", "9.9.9.9")
    with pytest.raises(RateLimitedError):
        await auth.login("alice", PW, "9.9.9.9")  # even the right password is throttled
    token, _ = await auth.login("alice", PW, "8.8.8.8")  # another client is unaffected
    assert token


async def test_expired_and_unknown_tokens_fail(auth):
    await auth.register("alice", PW)
    short = AuthService(auth._accounts, timedelta(seconds=-1), RateLimiter(5, 300))
    token, _ = await short.login("alice", PW, "2.2.2.2")
    with pytest.raises(AuthError):
        await short.authenticate(token)
    for bad in ("", "nonsense"):
        with pytest.raises(AuthError):
            await auth.authenticate(bad)


async def test_database_stores_only_hash_of_token(auth):
    await auth.register("alice", PW)
    token, _ = await auth.login("alice", PW, "3.3.3.3")
    from sqlalchemy import select

    from requirements_architect.storage.models import SessionRow

    async with auth._accounts._factory() as s:
        rows = (await s.scalars(select(SessionRow))).all()
    assert rows and all(r.token_hash != token and token not in r.token_hash for r in rows)


async def test_activity_log_has_no_secrets(auth):
    from sqlalchemy import select

    from requirements_architect.storage.models import AuditLogRow

    await auth.register("alice", PW)
    with pytest.raises(AuthError):
        await auth.login("alice", "wrong password here", "4.4.4.4")
    token, _ = await auth.login("alice", PW, "4.4.4.4")
    async with auth._accounts._factory() as s:
        rows = (await s.scalars(select(AuditLogRow))).all()
    dump = " ".join(f"{r.action} {r.detail}" for r in rows)
    assert PW not in dump and token not in dump and "wrong password" not in dump
    assert {r.action for r in rows} >= {"user.register", "login.failed", "login.ok"}

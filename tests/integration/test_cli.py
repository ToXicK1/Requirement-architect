import io

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from requirements_architect import cli
from requirements_architect.core.config import get_settings
from requirements_architect.storage.database import Base

PW = "correct horse battery staple"


@pytest.fixture
def env(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()

    import asyncio

    async def init():
        e = create_async_engine(url)
        async with e.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await e.dispose()

    asyncio.run(init())
    yield
    get_settings.cache_clear()


def test_create_user_from_stdin_then_duplicate_and_weak(env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(PW + "\n"))
    assert cli.main(["create-user", "dana", "--password-stdin"]) == 0
    assert "created user dana" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(PW + "\n"))
    assert cli.main(["create-user", "dana", "--password-stdin"]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["create-user", "erin", "--password-stdin"]) == 2
    assert PW not in capsys.readouterr().err


def test_password_is_never_an_argument(env, capsys):
    with pytest.raises(SystemExit):
        cli.main(["create-user", "dana", "--password", PW])

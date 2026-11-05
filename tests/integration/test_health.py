import httpx
import pytest

from requirements_architect.api.app import create_app
from requirements_architect.core.config import Settings


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None, app_env="test", database_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def test_live(client):
    r = await client.get("/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_ready_with_db(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json()["database"] is True


async def test_ready_reports_db_down(tmp_path):
    settings = Settings(
        _env_file=None, app_env="test", database_url="sqlite+aiosqlite:////nonexistent_dir/x/t.db"
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.get("/health/ready")
    assert r.status_code == 503 and r.json()["database"] is False

"""Run the real FastAPI app over ASGI with a scripted LLM. Test-only."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx

from requirements_architect.api.app import create_app
from requirements_architect.api.container import assemble
from requirements_architect.audit.service import AuditLimits, AuditService
from requirements_architect.core.config import Settings
from tests.conftest import make_stack

PASSWORD = "correct horse battery staple"


@asynccontextmanager
async def api(tmp_path, script, *, llm=True, registration=False, **stack_kw):
    async with make_stack(tmp_path, script, **stack_kw) as st:
        settings = Settings(
            _env_file=None,
            app_env="test",
            allow_registration=registration,
            output_dir=str(tmp_path / "out"),
        )
        c = assemble(
            settings,
            st.repo._factory,
            st.engine,
            workflow=st.service if llm else None,
            audit=AuditService(st.repo, st.gateway, AuditLimits()) if llm else None,
            approvals_gateway=st.gateway if llm else None,
        )
        app = create_app(settings, container=c)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as client,
        ):
            yield client, c, st


async def login(client, c, username="alice"):
    await c.auth.register(username, PASSWORD)
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def wait(c):
    await c.jobs.drain()

"""FastAPI application factory with health endpoints and central error handling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from requirements_architect.api.container import Container, open_container
from requirements_architect.api.middleware import BodyLimit, SecurityHeaders
from requirements_architect.api.routes import router
from requirements_architect.core.config import AppEnv, Settings, get_settings
from requirements_architect.core.logging import configure_logging
from requirements_architect.storage.database import ping

log = structlog.get_logger()
MAX_BODY_BYTES = 256 * 1024
STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """`container` is injected by tests; production builds it from settings at startup."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if container is not None:
            app.state.container = container
            yield
            await container.jobs.drain()
            return
        async with open_container(settings) as c:
            app.state.container = c
            log.info("startup", env=settings.app_env.value, llm=settings.llm_configured)
            yield
            await c.jobs.drain()
        log.info("shutdown")

    app = FastAPI(
        title="Requirements Architect",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env is AppEnv.PRODUCTION else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env is AppEnv.PRODUCTION else "/openapi.json",
    )
    app.add_middleware(BodyLimit, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(SecurityHeaders)
    app.include_router(router)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request) -> JSONResponse:
        ok = await ping(request.app.state.container.engine)
        return JSONResponse(
            {"status": "ok" if ok else "unavailable", "database": ok},
            status_code=200 if ok else 503,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse({"error": "internal_server_error"}, status_code=500)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    return app

"""FastAPI application factory with health endpoints and central error handling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from requirements_architect.core.config import Settings, get_settings
from requirements_architect.core.logging import configure_logging
from requirements_architect.storage.database import make_engine, make_session_factory, ping

log = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        log.info("startup", env=settings.app_env.value)
        yield
        await engine.dispose()
        log.info("shutdown")

    app = FastAPI(title="Requirements Architect", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request) -> JSONResponse:
        ok = await ping(request.app.state.engine)
        return JSONResponse(
            {"status": "ok" if ok else "unavailable", "database": ok},
            status_code=200 if ok else 503,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse({"error": "internal_server_error"}, status_code=500)

    return app

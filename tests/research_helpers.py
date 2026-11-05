"""Shared builders for Stage 3 tests (test-only)."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from requirements_architect.research.fetcher import FetchLimits, HostRateLimiter, SafeFetcher
from requirements_architect.research.providers import (
    OSVAdvisories,
    PyPIRegistry,
    SearchHit,
)
from requirements_architect.research.service import ResearchLimits, ResearchService
from requirements_architect.research.url_safety import UrlPolicy
from requirements_architect.schemas.state import ClarificationAnswer, ProjectBrief

PUBLIC = "93.184.216.34"
BRIEF = ProjectBrief(actual_problem="slow onboarding", proposed_solution="an onboarding app")
ANSWERS: dict[str, ClarificationAnswer] = {}
SECRET = "tok-must-never-leak"

PAGES: dict[str, tuple[int, str, str]] = {  # "host/path" -> (status, content-type, body)
    "docs.python.org/3/asyncio": (
        200,
        "text/html",
        "<html><head><title>asyncio docs</title></head><body><p>asyncio is a library to write "
        + "concurrent code using the async/await syntax.</p></body></html>",
    ),
    "blog.example.com/post": (
        200,
        "text/html",
        "<html><title>A blog</title><body><p>FastAPI makes building APIs pleasant and quick.</p></body></html>",
    ),
}


def hit(url: str, title: str = "t", provider: str = "fake") -> SearchHit:
    return SearchHit(url=url, title=title, snippet="s", provider=provider)


def make_fetcher(pages=None, log: list[httpx.Request] | None = None) -> SafeFetcher:
    pages = PAGES if pages is None else pages

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request)
        key = request.headers["host"] + request.url.path
        status, ctype, body = pages.get(key, (404, "text/plain", "nope"))
        return httpx.Response(status, headers={"content-type": ctype}, text=body)

    async def resolver(host: str, port: int) -> list[str]:
        return [PUBLIC]

    async def nosleep(_: float) -> None:
        return None

    return SafeFetcher(
        httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False),
        UrlPolicy(),
        FetchLimits(),
        resolver,
        HostRateLimiter(0, sleep=nosleep),
    )


def make_registries(pypi: dict[str, dict | None], osv: dict | None = None):
    """PyPI + OSV adapters over mocked HTTP. pypi: name -> info dict (None = 404)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "pypi.org":
            name = request.url.path.split("/")[2]
            info = pypi.get(name)
            return httpx.Response(404) if info is None else httpx.Response(200, json={"info": info})
        if request.url.host == "api.osv.dev":
            return httpx.Response(200, json=osv or {})
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return {"pypi": PyPIRegistry(client)}, OSVAdvisories(client), seen


def make_service(
    gateway, repo, *, providers=(), fetcher=None, registries=None, advisories=None, limits=None
):
    return ResearchService(
        gateway,
        repo,
        fetcher or make_fetcher(),
        providers,
        registries,
        advisories,
        limits or ResearchLimits(),
    )


SECRET_KEY = SecretStr(SECRET)

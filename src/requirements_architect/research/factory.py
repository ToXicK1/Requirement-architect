"""Assemble a ResearchService from settings."""

from __future__ import annotations

import httpx

from requirements_architect.core.config import Settings
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.research.fetcher import FetchLimits, SafeFetcher
from requirements_architect.research.providers import (
    BraveSearchProvider,
    GitHubRepoSearch,
    NpmRegistry,
    OSVAdvisories,
    PackageRegistry,
    PyPIRegistry,
    SearchProvider,
)
from requirements_architect.research.service import ResearchLimits, ResearchService
from requirements_architect.research.url_safety import UrlPolicy
from requirements_architect.storage.repository import Repository


def build_research_service(
    settings: Settings,
    repo: Repository,
    gateway: LLMGateway,
    api_client: httpx.AsyncClient,
    fetch_client: httpx.AsyncClient,
) -> ResearchService | None:
    """`api_client` talks only to fixed provider hosts; `fetch_client` (SSRF-guarded) fetches
    arbitrary public pages. Returns None when research is disabled."""
    if not settings.research_enabled:
        return None
    providers: list[SearchProvider] = [GitHubRepoSearch(api_client, settings.github_token)]
    if settings.brave_api_key.get_secret_value():
        providers.append(BraveSearchProvider(settings.brave_api_key, api_client))
    registries: dict[str, PackageRegistry] = {
        "pypi": PyPIRegistry(api_client),
        "npm": NpmRegistry(api_client),
    }
    schemes = ("https", "http") if settings.research_allow_http else ("https",)
    fetcher = SafeFetcher(
        fetch_client,
        UrlPolicy(allowed_schemes=schemes),
        FetchLimits(
            max_bytes=settings.research_fetch_max_bytes,
            timeout_seconds=settings.research_fetch_timeout_seconds,
        ),
    )
    return ResearchService(
        gateway,
        repo,
        fetcher,
        providers,
        registries,
        OSVAdvisories(api_client),
        ResearchLimits(max_fetches=settings.research_max_fetches),
    )

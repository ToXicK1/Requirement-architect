"""Research provider adapters. Each talks to ONE fixed API host; credentials stay inside the adapter
and are never passed to, or visible to, the LLM. Responses are untrusted data.

Live behaviour of Brave, GitHub, PyPI, npm and OSV adapters follows their public API docs but has
only been exercised against mocked HTTP in this repository's tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from requirements_architect.schemas.research import AdvisoryRef, PackageFact, PackageRef

MAX_API_BYTES = 5_000_000
_PYPI_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
_NPM_NAME = re.compile(r"^(?:@[a-z0-9][a-z0-9._~-]{0,213}/)?[a-z0-9][a-z0-9._~-]{0,213}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+!_-]{0,63}$")


class ResearchProviderError(Exception):
    """Provider failure. Never contains credentials or response bodies."""


class InvalidPackageNameError(ResearchProviderError): ...


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    provider: str


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> list[SearchHit]: ...


def _s(value: Any, limit: int = 500) -> str:
    return value[:limit] if isinstance(value, str) else ""


async def _request_json(
    client: httpx.AsyncClient,
    provider: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 15.0,
    allow_404: bool = False,
) -> Any:
    try:
        resp = await client.request(
            method, url, headers=headers, params=params, json=json_body, timeout=timeout
        )
    except httpx.TimeoutException as exc:
        raise ResearchProviderError(f"{provider}: timed out") from exc
    except httpx.TransportError as exc:
        raise ResearchProviderError(f"{provider}: network error ({type(exc).__name__})") from exc
    if resp.status_code == 404 and allow_404:
        return None
    if resp.status_code == 429:
        raise ResearchProviderError(f"{provider}: rate limited")
    if resp.status_code in (401, 403):
        raise ResearchProviderError(f"{provider}: authentication/authorization failed")
    if resp.status_code >= 400:
        raise ResearchProviderError(f"{provider}: HTTP {resp.status_code}")
    if len(resp.content) > MAX_API_BYTES:
        raise ResearchProviderError(f"{provider}: response too large")
    try:
        return resp.json()
    except ValueError as exc:
        raise ResearchProviderError(f"{provider}: malformed JSON") from exc


class BraveSearchProvider:
    """Web search via the Brave Search API (requires a subscription token)."""

    name = "brave"
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, token: SecretStr, client: httpx.AsyncClient) -> None:
        self._token, self._client = token, client

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        data = await _request_json(
            self._client,
            self.name,
            "GET",
            self.URL,
            headers={
                "X-Subscription-Token": self._token.get_secret_value(),
                "Accept": "application/json",
            },
            params={"q": query[:400], "count": max(1, min(limit, 20))},
        )
        web = data.get("web") if isinstance(data, dict) else None
        results = web.get("results") if isinstance(web, dict) else None
        results = results if isinstance(results, list) else []
        return [
            SearchHit(r["url"], _s(r.get("title"), 200), _s(r.get("description"), 400), self.name)
            for r in results
            if isinstance(r, dict) and isinstance(r.get("url"), str)
        ][:limit]


class GitHubRepoSearch:
    """Repository search via the GitHub REST API. The token is optional (raises rate limits)."""

    name = "github"
    URL = "https://api.github.com/search/repositories"

    def __init__(self, client: httpx.AsyncClient, token: SecretStr | None = None) -> None:
        self._client, self._token = client, token

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token and self._token.get_secret_value():
            headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        data = await _request_json(
            self._client,
            self.name,
            "GET",
            self.URL,
            headers=headers,
            params={
                "q": query[:256],
                "sort": "stars",
                "order": "desc",
                "per_page": max(1, min(limit, 20)),
            },
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        hits: list[SearchHit] = []
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get("html_url"), str):
                continue
            lic = it.get("license")
            lic_id = lic.get("spdx_id") if isinstance(lic, dict) else None
            snippet = f"{_s(it.get('description'), 300)} [stars={it.get('stargazers_count')}, license={lic_id}]"
            hits.append(SearchHit(it["html_url"], _s(it.get("full_name"), 200), snippet, self.name))
        return hits[:limit]


class PackageRegistry(Protocol):
    ecosystem: str

    async def lookup(self, name: str) -> PackageFact | None: ...


class PyPIRegistry:
    ecosystem = "pypi"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def lookup(self, name: str) -> PackageFact | None:
        if not _PYPI_NAME.fullmatch(name):
            raise InvalidPackageNameError("invalid PyPI package name")
        url = f"https://pypi.org/pypi/{quote(name, safe='')}/json"
        data = await _request_json(self._client, "pypi", "GET", url, allow_404=True)
        if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
            return None
        info = data["info"]
        return PackageFact(
            ecosystem="pypi",
            name=name,
            latest_version=_s(info.get("version"), 64) or None,
            license=(
                _s(info.get("license_expression"), 120) or _s(info.get("license"), 120) or None
            ),
            summary=_s(info.get("summary"), 300) or None,
            registry_url=f"https://pypi.org/project/{quote(name, safe='')}/",
        )


class NpmRegistry:
    ecosystem = "npm"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def lookup(self, name: str) -> PackageFact | None:
        if not _NPM_NAME.fullmatch(name) or len(name) > 214:
            raise InvalidPackageNameError("invalid npm package name")
        if name.startswith("@"):
            scope, pkg = name.split("/", 1)
            path = f"{quote(scope, safe='@')}%2F{quote(pkg, safe='')}"
        else:
            path = quote(name, safe="")
        url = f"https://registry.npmjs.org/{path}"
        data = await _request_json(self._client, "npm", "GET", url, allow_404=True)
        if not isinstance(data, dict):
            return None
        latest = (
            (data.get("dist-tags") or {}).get("latest")
            if isinstance(data.get("dist-tags"), dict)
            else None
        )
        lic = data.get("license")
        return PackageFact(
            ecosystem="npm",
            name=name,
            latest_version=_s(latest, 64) or None,
            license=_s(lic, 120) or None,
            summary=_s(data.get("description"), 300) or None,
            registry_url=f"https://www.npmjs.com/package/{name}",
        )


class OSVAdvisories:
    """Known-vulnerability lookup via OSV.dev (no credentials)."""

    URL = "https://api.osv.dev/v1/query"
    _ECOSYSTEM: ClassVar[dict[str, str]] = {"pypi": "PyPI", "npm": "npm"}

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def query(self, ref: PackageRef, version: str | None) -> list[AdvisoryRef]:
        if version is not None and not _VERSION.fullmatch(version):
            raise ResearchProviderError("osv: invalid version string")
        body: dict[str, Any] = {
            "package": {"name": ref.name, "ecosystem": self._ECOSYSTEM[ref.ecosystem]}
        }
        if version:
            body["version"] = version
        data = await _request_json(self._client, "osv", "POST", self.URL, json_body=body)
        vulns = data.get("vulns", []) if isinstance(data, dict) else []
        return [
            AdvisoryRef(advisory_id=_s(v.get("id"), 80), summary=_s(v.get("summary"), 300))
            for v in vulns
            if isinstance(v, dict) and isinstance(v.get("id"), str)
        ][:25]

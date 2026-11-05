"""SSRF-safe, size/time-bounded fetcher for untrusted web content."""

from __future__ import annotations

import asyncio
import hashlib
import http.cookiejar
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
import structlog
from pydantic import BaseModel

from requirements_architect.research.url_safety import (
    Resolver,
    UnsafeUrlError,
    UrlPolicy,
    ValidatedUrl,
    default_resolver,
    validate_url,
)

log = structlog.get_logger()

ALLOWED_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "text/markdown",
        "application/json",
        "application/xml",
        "text/xml",
    }
)
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


class FetchError(Exception):
    """Base class. Messages never include response bodies."""


class FetchTimeoutError(FetchError): ...


class FetchHttpError(FetchError):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class ResponseTooLargeError(FetchError): ...


class DisallowedContentTypeError(FetchError): ...


class TooManyRedirectsError(FetchError): ...


class FetchLimits(BaseModel):
    max_bytes: int = 2_000_000  # measured on DECODED bytes, so compression bombs are capped too
    timeout_seconds: float = 15.0  # wall-clock for the whole fetch incl. redirects
    max_redirects: int = 3
    min_host_interval_seconds: float = 1.0
    user_agent: str = "RequirementsArchitect-Research/0.1"


@dataclass(frozen=True)
class FetchedDocument:
    final_url: str
    status: int
    content_type: str
    body: bytes
    text: str
    sha256: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class HostRateLimiter:
    """Minimum spacing between requests to the same host."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._min = min_interval
        self._clock = clock
        self._sleep = sleep
        self._next_ok: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, host: str) -> None:
        async with self._lock:
            now = self._clock()
            ready = self._next_ok.get(host, now)
            delay = max(0.0, ready - now)
            self._next_ok[host] = max(now, ready) + self._min
        if delay:
            await self._sleep(delay)


def make_fetch_client() -> httpx.AsyncClient:
    """Client with no env proxies, no auto-redirects, and a cookie jar that stores nothing."""
    client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
    client.cookies.jar.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
    return client


class SafeFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        policy: UrlPolicy | None = None,
        limits: FetchLimits | None = None,
        resolver: Resolver = default_resolver,
        limiter: HostRateLimiter | None = None,
    ) -> None:
        self._client = client
        self._policy = policy or UrlPolicy()
        self._limits = limits or FetchLimits()
        self._resolver = resolver
        self._limiter = limiter or HostRateLimiter(self._limits.min_host_interval_seconds)

    async def fetch(self, url: str) -> FetchedDocument:
        try:
            async with asyncio.timeout(self._limits.timeout_seconds):
                return await self._fetch(url)
        except TimeoutError as exc:
            raise FetchTimeoutError("fetch exceeded its deadline") from exc

    async def _fetch(self, url: str) -> FetchedDocument:
        current = url
        for _ in range(self._limits.max_redirects + 1):
            # Re-validate EVERY hop: a public URL may redirect to http://169.254.169.254/.
            target = await validate_url(current, self._policy, self._resolver)
            await self._limiter.wait(target.host)
            resp_or_doc = await self._request(target)
            if isinstance(resp_or_doc, FetchedDocument):
                return resp_or_doc
            current = urljoin(target.url, resp_or_doc)
        raise TooManyRedirectsError(f"more than {self._limits.max_redirects} redirects")

    async def _request(self, target: ValidatedUrl) -> FetchedDocument | str:
        """Returns a document, or the Location string when the response is a redirect."""
        last_exc: Exception | None = None
        for ip in target.ips:  # connect only to addresses that passed validation
            ip_host = f"[{ip}]" if ":" in ip else ip
            default = 443 if target.scheme == "https" else 80
            host_header = target.host if target.port == default else f"{target.host}:{target.port}"
            request = self._client.build_request(
                "GET",
                f"{target.scheme}://{ip_host}:{target.port}{target.path_qs}",
                headers={
                    "Host": host_header,
                    "User-Agent": self._limits.user_agent,
                    "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.1",
                },
                extensions={"sni_hostname": target.host} if target.scheme == "https" else {},
            )
            try:
                response = await self._client.send(request, stream=True)
            except httpx.TransportError as exc:
                last_exc = exc
                continue
            try:
                return await self._consume(target, response)
            finally:
                await response.aclose()
        raise FetchError(f"connection failed ({type(last_exc).__name__})")

    async def _consume(
        self, target: ValidatedUrl, response: httpx.Response
    ) -> FetchedDocument | str:
        status = response.status_code
        if status in _REDIRECTS:
            location = response.headers.get("location")
            if not location:
                raise FetchHttpError(status)
            return str(location)
        if status >= 400:
            raise FetchHttpError(status)
        ctype = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if ctype not in ALLOWED_CONTENT_TYPES:
            raise DisallowedContentTypeError(f"content type not allowed: {ctype or '(missing)'}")
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._limits.max_bytes:
            raise ResponseTooLargeError("declared size exceeds limit")
        buf = bytearray()
        async for chunk in response.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > self._limits.max_bytes:
                raise ResponseTooLargeError("response exceeded size limit")
        body = bytes(buf)
        text = body.decode(response.encoding or "utf-8", errors="replace")
        return FetchedDocument(
            final_url=target.url,
            status=status,
            content_type=ctype,
            body=body,
            text=text,
            sha256=hashlib.sha256(body).hexdigest(),
        )


__all__ = [
    "FetchError",
    "FetchLimits",
    "FetchedDocument",
    "SafeFetcher",
    "UnsafeUrlError",
    "make_fetch_client",
]

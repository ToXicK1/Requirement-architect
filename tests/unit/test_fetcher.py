import asyncio
import gzip

import httpx
import pytest

from requirements_architect.research.fetcher import (
    DisallowedContentTypeError,
    FetchHttpError,
    FetchLimits,
    FetchTimeoutError,
    HostRateLimiter,
    ResponseTooLargeError,
    SafeFetcher,
    TooManyRedirectsError,
    make_fetch_client,
)
from requirements_architect.research.url_safety import UnsafeUrlError, UrlPolicy

PUBLIC = "93.184.216.34"
HTML = {"content-type": "text/html; charset=utf-8"}


class Recorder:
    def __init__(self, handler):
        self.handler, self.requests = handler, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def fetcher(handler, resolver=None, limits=None, policy=None):
    rec = Recorder(handler)
    calls = []

    async def default_resolver(host, port):
        calls.append(host)
        return [PUBLIC]

    async def nosleep(_):
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(rec), trust_env=False)
    f = SafeFetcher(
        client,
        policy or UrlPolicy(),
        limits or FetchLimits(),
        resolver or default_resolver,
        HostRateLimiter(0, sleep=nosleep),
    )
    return f, rec, calls


async def test_connects_to_vetted_ip_with_original_host_and_sni():
    f, rec, _ = fetcher(lambda r: httpx.Response(200, headers=HTML, text="<p>hi</p>"))
    doc = await f.fetch("https://docs.example.com/a?x=1")
    req = rec.requests[0]
    assert req.url.host == PUBLIC and req.headers["host"] == "docs.example.com"
    assert req.extensions["sni_hostname"] == "docs.example.com"
    assert req.url.path == "/a" and req.url.query == b"x=1"
    assert doc.text == "<p>hi</p>" and doc.status == 200 and len(doc.sha256) == 64
    assert "cookie" not in req.headers and "authorization" not in req.headers


async def test_dns_is_resolved_once_per_hop_so_rebinding_cannot_swap_the_ip():
    answers = iter([[PUBLIC], ["127.0.0.1"], ["127.0.0.1"]])

    async def rebinding(host, port):
        return next(answers)

    f, rec, _ = fetcher(lambda r: httpx.Response(200, headers=HTML, text="ok"), resolver=rebinding)
    await f.fetch("https://evil.example.com/")
    assert [r.url.host for r in rec.requests] == [PUBLIC]  # connected to the vetted answer only


async def test_redirect_to_private_ip_literal_is_blocked():
    def h(r):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    f, rec, _ = fetcher(h, policy=UrlPolicy(allowed_schemes=("https", "http")))
    with pytest.raises(UnsafeUrlError):
        await f.fetch("https://example.com/")
    assert len(rec.requests) == 1  # the forbidden target was never requested


async def test_redirect_to_hostname_resolving_privately_is_blocked():
    async def resolver(host, port):
        return [PUBLIC] if host == "example.com" else ["10.0.0.7"]

    f, rec, _ = fetcher(
        lambda r: httpx.Response(301, headers={"location": "https://sneaky.example.net/x"}),
        resolver,
    )
    with pytest.raises(UnsafeUrlError, match="non-public"):
        await f.fetch("https://example.com/")
    assert len(rec.requests) == 1


@pytest.mark.parametrize(
    "loc", ["file:///etc/passwd", "ftp://example.org/x", "https://u:p@example.org/"]
)
async def test_redirect_to_disallowed_scheme_or_credentials_blocked(loc):
    f, _, _ = fetcher(lambda r: httpx.Response(302, headers={"location": loc}))
    with pytest.raises(UnsafeUrlError):
        await f.fetch("https://example.com/")


async def test_relative_redirect_followed_and_final_url_reported():
    def h(r):
        if r.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, headers=HTML, text="new")

    f, rec, _ = fetcher(h)
    doc = await f.fetch("https://example.com/old")
    assert (
        doc.final_url == "https://example.com/new" and doc.text == "new" and len(rec.requests) == 2
    )


async def test_redirect_loop_is_bounded():
    f, rec, _ = fetcher(
        lambda r: httpx.Response(302, headers={"location": "/again"}),
        limits=FetchLimits(max_redirects=3),
    )
    with pytest.raises(TooManyRedirectsError):
        await f.fetch("https://example.com/")
    assert len(rec.requests) == 4


async def test_redirect_without_location_is_error():
    f, _, _ = fetcher(lambda r: httpx.Response(302))
    with pytest.raises(FetchHttpError):
        await f.fetch("https://example.com/")


async def test_oversize_body_aborted_while_streaming():
    f, _, _ = fetcher(
        lambda r: httpx.Response(200, headers=HTML, content=b"a" * 5000),
        limits=FetchLimits(max_bytes=1000),
    )
    with pytest.raises(ResponseTooLargeError):
        await f.fetch("https://example.com/")


async def test_declared_content_length_rejected_early():
    f, _, _ = fetcher(
        lambda r: httpx.Response(200, headers={**HTML, "content-length": "999999"}, content=b"x"),
        limits=FetchLimits(max_bytes=1000),
    )
    with pytest.raises(ResponseTooLargeError, match="declared"):
        await f.fetch("https://example.com/")


async def test_compression_bomb_capped_on_decoded_size():
    bomb = gzip.compress(b"0" * 5_000_000)  # a few KB on the wire, 5 MB decoded
    assert len(bomb) < 20_000
    f, _, _ = fetcher(
        lambda r: httpx.Response(200, headers={**HTML, "content-encoding": "gzip"}, content=bomb),
        limits=FetchLimits(max_bytes=100_000),
    )
    with pytest.raises(ResponseTooLargeError):
        await f.fetch("https://example.com/")


@pytest.mark.parametrize(
    "ctype",
    [
        "image/png",
        "application/octet-stream",
        "application/pdf",
        "application/x-sh",
        "video/mp4",
        "",
    ],
)
async def test_disallowed_or_missing_content_type(ctype):
    headers = {"content-type": ctype} if ctype else {}
    f, _, _ = fetcher(lambda r: httpx.Response(200, headers=headers, content=b"data"))
    with pytest.raises(DisallowedContentTypeError):
        await f.fetch("https://example.com/")


@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
async def test_http_errors_surface_status_without_body(status):
    f, _, _ = fetcher(lambda r: httpx.Response(status, text="SECRET-BODY"))
    with pytest.raises(FetchHttpError) as ei:
        await f.fetch("https://example.com/")
    assert ei.value.status == status and "SECRET-BODY" not in str(ei.value)


async def test_wall_clock_timeout_enforced():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, headers=HTML, text="late")

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow), trust_env=False)

    async def resolver(h, p):
        return [PUBLIC]

    f = SafeFetcher(
        client,
        limits=FetchLimits(timeout_seconds=0.05),
        resolver=resolver,
        limiter=HostRateLimiter(0),
    )
    with pytest.raises(FetchTimeoutError):
        await f.fetch("https://example.com/")


async def test_falls_back_to_next_vetted_ip_on_connect_error():
    seen = []

    def h(r: httpx.Request):
        seen.append(r.url.host)
        if r.url.host == "93.184.216.34":
            raise httpx.ConnectError("down")
        return httpx.Response(200, headers=HTML, text="ok")

    async def two(host, port):
        return ["93.184.216.34", "8.8.8.8"]

    f, _, _ = fetcher(h, resolver=two)
    assert (await f.fetch("https://example.com/")).text == "ok"
    assert seen == ["93.184.216.34", "8.8.8.8"]


async def test_rate_limiter_spaces_requests_per_host_only():
    now = [0.0]
    slept = []

    async def sleep(d):
        slept.append(d)
        now[0] += d

    lim = HostRateLimiter(2.0, clock=lambda: now[0], sleep=sleep)
    await lim.wait("a.com")
    await lim.wait("a.com")
    await lim.wait("b.com")
    assert slept == [2.0]


async def test_client_never_stores_cookies():
    def h(r):
        return httpx.Response(200, headers={**HTML, "set-cookie": "sid=abc; Path=/"}, text="x")

    async def resolver(host, port):
        return [PUBLIC]

    client = make_fetch_client()
    client._transport = httpx.MockTransport(h)  # swap transport only; keep real cookie policy
    f = SafeFetcher(client, resolver=resolver, limiter=HostRateLimiter(0))
    await f.fetch("https://example.com/")
    await f.fetch("https://example.com/")
    assert len(client.cookies.jar) == 0

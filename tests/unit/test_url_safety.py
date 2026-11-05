import pytest

from requirements_architect.research.url_safety import (
    UnsafeUrlError,
    UrlPolicy,
    is_blocked_ip,
    validate_url,
)

PUBLIC = "93.184.216.34"


def resolves(*ips: str):
    async def r(host: str, port: int) -> list[str]:
        return list(ips)

    return r


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.1.2.3",
        "10.0.0.1",
        "172.16.0.5",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "255.255.255.255",
        "192.0.2.1",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
        "2001:0:4136:e378::1",
        "not-an-ip",
        "",
    ],
)
def test_blocked_ips(ip):
    assert is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", [PUBLIC, "8.8.8.8", "1.1.1.1", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_ips_allowed(ip):
    assert is_blocked_ip(ip) is False


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "javascript:alert(1)",
        "data:text/html,hi",
        "http://example.com/",
        "//example.com/x",
        "example.com/x",
        "",
        "https://user:pw@example.com/",
        "https://example.com@evil.com/",
        "https://@example.com/",
        "https://example.com:8080/",
        "https://example.com:22/",
        "https://example.com:notaport/",
        "https:///nohost",
        "https://exa mple.com/",
        "https://example.com/a\nb",
        "https://example.com\\@evil.com",
        "https://localhost/",
        "https://LOCALHOST./",
        "https://foo.localhost/",
        "https://printer.local/",
        "https://db.internal/",
        "https://intranet/",
        "https://corp/",
        "https://x.home.arpa/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://169.254.169.254/latest/meta-data/",
        "https://2130706433/",
        "https://0x7f.0.0.1/",
        "https://0177.0.0.1/",
        "https://127.1/",
        "https://0/",
        "https://" + "a" * 3000 + ".com/",
    ],
)
async def test_rejected_before_any_dns(url):
    async def must_not_resolve(host, port):  # a rejection must not depend on / trigger DNS
        raise AssertionError("resolver called")

    with pytest.raises(UnsafeUrlError):
        await validate_url(url, UrlPolicy(allowed_schemes=("https",)), must_not_resolve)


async def test_accepts_public_https_and_normalizes():
    v = await validate_url("HTTPS://Docs.Example.COM./a/b?q=1#frag", resolver=resolves(PUBLIC))
    assert v.url == "https://docs.example.com/a/b?q=1" and v.ips == (PUBLIC,) and v.port == 443


async def test_http_only_when_policy_allows():
    pol = UrlPolicy(allowed_schemes=("https", "http"))
    assert (await validate_url("http://example.com/", pol, resolves(PUBLIC))).port == 80


@pytest.mark.parametrize(
    "ips",
    [
        ["127.0.0.1"],
        ["10.1.1.1"],
        ["169.254.169.254"],
        ["::1"],
        [PUBLIC, "10.0.0.1"],
        ["10.0.0.1", PUBLIC],
    ],
)
async def test_public_looking_name_resolving_to_private_is_blocked(ips):
    with pytest.raises(UnsafeUrlError, match="non-public"):
        await validate_url("https://innocent.example.com/", resolver=resolves(*ips))


async def test_empty_resolution_blocked():
    with pytest.raises(UnsafeUrlError):
        await validate_url("https://innocent.example.com/", resolver=resolves())


async def test_domain_allowlist():
    pol = UrlPolicy(allowed_domains=("python.org",))
    assert await validate_url("https://docs.python.org/3/", pol, resolves(PUBLIC))
    assert await validate_url("https://python.org/", pol, resolves(PUBLIC))
    for bad in ("https://evilpython.org/", "https://python.org.evil.com/", "https://8.8.8.8/"):
        with pytest.raises(UnsafeUrlError):
            await validate_url(bad, pol, resolves(PUBLIC))


@pytest.mark.parametrize("host", ["2130706433", "0x7f000001", "0177.0.0.1", "127.1", "localhost"])
async def test_real_resolver_never_lets_loopback_encodings_through(host):
    """No mocks: go through getaddrinfo and make sure the result is still rejected."""
    with pytest.raises(UnsafeUrlError):
        await validate_url(f"https://{host}/")

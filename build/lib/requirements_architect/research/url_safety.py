"""URL validation and SSRF defence.

Every URL that originates outside our own code (search hits, LLM output, redirects) must pass
`validate_url` before any socket is opened. Validation resolves DNS itself and returns the
addresses it approved, so the fetcher can connect to exactly those IPs (defeating DNS rebinding).
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel

Resolver = Callable[[str, int], Awaitable[list[str]]]

MAX_URL_LENGTH = 2048
_BAD_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")
# every label numeric or 0x-hex: forms like 2130706433, 0x7f.1, 0177.0.0.1 that inet_aton accepts
_NUMERICISH = re.compile(r"^(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*$", re.IGNORECASE)

_EXTRA_BLOCKED_V6 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "64:ff9b::/96",  # NAT64: embeds arbitrary IPv4, including private
        "64:ff9b:1::/48",
        "2002::/16",  # 6to4
        "2001::/32",  # Teredo
        "fec0::/10",  # deprecated site-local
    )
)


class UnsafeUrlError(Exception):
    """The URL (or where it resolves/redirects to) is not allowed. Message is safe to log."""


class UrlPolicy(BaseModel):
    allowed_schemes: tuple[str, ...] = ("https",)
    allowed_ports: tuple[int, ...] = (80, 443)
    allowed_domains: tuple[str, ...] | None = None  # suffix match; None = any public host
    blocked_suffixes: tuple[str, ...] = (
        ".localhost",
        ".local",
        ".internal",
        ".lan",
        ".home.arpa",
        ".intranet",
        ".corp",
    )


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    scheme: str
    host: str
    port: int
    path_qs: str
    ips: tuple[str, ...]  # already vetted; connect to these, not to a fresh DNS answer


def is_blocked_ip(ip: str) -> bool:
    """True unless the address is a normal, globally routable unicast address."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address):
        # Defence in depth: some Python versions mis-classify mapped addresses, so unwrap explicitly.
        if addr.ipv4_mapped is not None:
            return is_blocked_ip(str(addr.ipv4_mapped))
        if any(addr in net for net in _EXTRA_BLOCKED_V6):
            return True
    return not addr.is_global or addr.is_multicast


async def default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("hostname could not be resolved") from exc
    seen: dict[str, None] = {}
    for info in infos:
        seen[str(info[4][0]).split("%", 1)[0]] = None
    return list(seen)


def _parse(url: str) -> SplitResult:
    if len(url) > MAX_URL_LENGTH or _BAD_CHARS.search(url):
        raise UnsafeUrlError("malformed URL")
    try:
        return urlsplit(url)
    except ValueError as exc:
        raise UnsafeUrlError("malformed URL") from exc


async def validate_url(
    url: str, policy: UrlPolicy | None = None, resolver: Resolver = default_resolver
) -> ValidatedUrl:
    policy = policy or UrlPolicy()
    parts = _parse(url)
    scheme = parts.scheme.lower()
    if scheme not in policy.allowed_schemes:
        raise UnsafeUrlError(f"scheme not allowed: {scheme or '(none)'}")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("credentials in URL are not allowed")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("invalid port") from exc
    if port not in policy.allowed_ports:
        raise UnsafeUrlError(f"port not allowed: {port}")
    raw_host = (parts.hostname or "").rstrip(".").lower()
    if not raw_host:
        raise UnsafeUrlError("missing host")
    try:
        host = raw_host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeUrlError("invalid hostname") from exc

    literal: str | None = None
    try:
        literal = str(ipaddress.ip_address(host))
    except ValueError:
        pass

    if literal is None:
        if _NUMERICISH.match(host):
            raise UnsafeUrlError("numeric host forms are not allowed")
        if host == "localhost" or any(host.endswith(s) for s in policy.blocked_suffixes):
            raise UnsafeUrlError("internal hostname")
        if "." not in host:
            raise UnsafeUrlError("single-label hostname")
        if policy.allowed_domains is not None and not any(
            host == d or host.endswith("." + d) for d in policy.allowed_domains
        ):
            raise UnsafeUrlError("domain not in allowlist")
        ips = await resolver(host, port)
    else:
        if policy.allowed_domains is not None:
            raise UnsafeUrlError("IP literals not allowed with a domain allowlist")
        ips = [literal]

    if not ips:
        raise UnsafeUrlError("hostname did not resolve")
    # ANY blocked address fails the whole host: an attacker-controlled name may mix public+private.
    if any(is_blocked_ip(ip) for ip in ips):
        raise UnsafeUrlError("host resolves to a non-public address")

    path_qs = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    netloc_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    shown = netloc_host if port == default_port else f"{netloc_host}:{port}"
    return ValidatedUrl(f"{scheme}://{shown}{path_qs}", scheme, host, port, path_qs, tuple(ips))

"""Password hashing, session tokens and a small in-process rate limiter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable

_N, _R, _P = 2**14, 8, 1
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,39}$")
MIN_PASSWORD = 12
MAX_PASSWORD = 200


class PasswordPolicyError(ValueError):
    pass


def normalize_username(raw: str) -> str:
    name = raw.strip().lower()
    if not _USERNAME.match(name):
        raise ValueError("username must be 3-40 characters: letters, digits, '_', '.', '-'")
    return name


def check_password_policy(password: str) -> None:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise PasswordPolicyError(f"password must be {MIN_PASSWORD}-{MAX_PASSWORD} characters long")
    if len(set(password)) < 5:
        raise PasswordPolicyError("password is too repetitive")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=128 * n * r * 2
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _N, _R, _P)
    enc = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${enc(salt).decode()}${enc(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when a username does not exist, so timing does not reveal valid usernames.
DUMMY_HASH = hash_password("dummy-password-for-timing")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RateLimiter:
    """Sliding window per key. In-process only: with several workers the limit is per worker."""

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._clock()
        q = self._hits[key]
        while q and now - q[0] >= self._window:
            q.popleft()
        if len(q) >= self._limit:
            return False
        q.append(now)
        if len(self._hits) > 10_000:  # bound memory
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self._window]:
                del self._hits[k]
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

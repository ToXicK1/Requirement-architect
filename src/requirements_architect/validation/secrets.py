"""Detect and redact secret-looking text in generated documents (spec: no secrets in output)."""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*[^\s,;]{6,}"),
    re.compile(r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]{3,}@"),  # credentials inside a URL
]
REDACTED = "[REDACTED]"


def scrub(text: str) -> tuple[str, bool]:
    """Return (text with secret-looking spans replaced, whether anything was found)."""
    found = False
    for pat in _PATTERNS:
        text, n = pat.subn(REDACTED, text)
        found = found or n > 0
    return text, found

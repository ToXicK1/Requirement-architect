"""Deterministic evidence handling: reliability assessment and claim verification.

The LLM proposes findings; this module decides what may be called "verified". A model can
neither mark its own claims verified nor attach a source that was never retrieved.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from requirements_architect.schemas.research import (
    Finding,
    FindingKind,
    RawFinding,
    Reliability,
    SourceType,
    VerificationStatus,
)

# Curated, deliberately small. Heuristic: hostname-based, NOT a judgement of any page's content.
_HOST_RULES: tuple[tuple[str, SourceType, Reliability], ...] = (
    ("pypi.org", SourceType.PACKAGE_REGISTRY, Reliability.HIGH),
    ("registry.npmjs.org", SourceType.PACKAGE_REGISTRY, Reliability.HIGH),
    ("npmjs.com", SourceType.PACKAGE_REGISTRY, Reliability.HIGH),
    ("osv.dev", SourceType.ADVISORY, Reliability.HIGH),
    ("nvd.nist.gov", SourceType.ADVISORY, Reliability.HIGH),
    ("cve.org", SourceType.ADVISORY, Reliability.HIGH),
    ("owasp.org", SourceType.STANDARD, Reliability.HIGH),
    ("nist.gov", SourceType.STANDARD, Reliability.HIGH),
    ("ietf.org", SourceType.STANDARD, Reliability.HIGH),
    ("rfc-editor.org", SourceType.STANDARD, Reliability.HIGH),
    ("w3.org", SourceType.STANDARD, Reliability.HIGH),
    ("docs.python.org", SourceType.OFFICIAL_DOCS, Reliability.HIGH),
    ("fastapi.tiangolo.com", SourceType.OFFICIAL_DOCS, Reliability.HIGH),
    ("docs.pydantic.dev", SourceType.OFFICIAL_DOCS, Reliability.HIGH),
    ("docs.sqlalchemy.org", SourceType.OFFICIAL_DOCS, Reliability.HIGH),
    ("postgresql.org", SourceType.OFFICIAL_DOCS, Reliability.HIGH),
    ("docs.docker.com", SourceType.OFFICIAL_DOCS, Reliability.HIGH),
    ("docs.anthropic.com", SourceType.OFFICIAL_DOCS, Reliability.HIGH),
    ("api.github.com", SourceType.REPOSITORY, Reliability.MEDIUM),
    ("github.com", SourceType.REPOSITORY, Reliability.MEDIUM),
    ("gitlab.com", SourceType.REPOSITORY, Reliability.MEDIUM),
)


def classify_source(url: str) -> tuple[SourceType, Reliability, str]:
    host = (urlsplit(url).hostname or "").lower()
    for suffix, stype, rel in _HOST_RULES:
        if host == suffix or host.endswith("." + suffix):
            return stype, rel, f"host matches curated list ({suffix})"
    return SourceType.WEB, Reliability.LOW, "unlisted host; treat as unverified secondary source"


_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Case-, whitespace- and quote-style-insensitive form used ONLY for quote matching."""
    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return _WS.sub(" ", text).strip().lower()


MIN_QUOTE_CHARS = 25  # heuristic floor (~4-5 words): short phrases match almost any document


def verify_findings(raw: Sequence[RawFinding], source_texts: Mapping[str, str]) -> list[Finding]:
    """Assign ids and verification. `source_texts` maps source_id -> full sanitized text that
    was actually retrieved. Unknown source ids are dropped from the finding (and noted)."""
    normalized = {sid: normalize(t) for sid, t in source_texts.items()}
    out: list[Finding] = []
    for i, f in enumerate(raw, start=1):
        known = [s for s in dict.fromkeys(f.source_ids) if s in normalized]
        dropped = [s for s in f.source_ids if s not in normalized]
        note_bits: list[str] = []
        if dropped:
            note_bits.append(f"cited unknown source(s) {dropped}; ignored")

        if f.kind is not FindingKind.FACT:
            status = VerificationStatus.UNVERIFIED
            note_bits.append(f"{f.kind.value}: engineering judgement, not independently verified")
        elif not known:
            status = VerificationStatus.UNSUPPORTED
            note_bits.append("fact without any retrieved source")
        elif not f.quote or len(normalize(f.quote)) < MIN_QUOTE_CHARS:
            status = VerificationStatus.UNVERIFIED
            note_bits.append("no sufficiently long supporting quote provided")
        else:
            q = normalize(f.quote)
            hit = next((s for s in known if q in normalized[s]), None)
            if hit:
                status = VerificationStatus.VERIFIED
                note_bits.append(f"quote found in {hit}")
            else:
                status = VerificationStatus.UNVERIFIED
                note_bits.append("quote not found in any cited source")
        out.append(
            Finding(
                finding_id=f"F-{i:03d}",
                kind=f.kind,
                claim=f.claim,
                source_ids=known,
                quote=f.quote,
                verification=status,
                verification_note="; ".join(note_bits),
            )
        )
    return out

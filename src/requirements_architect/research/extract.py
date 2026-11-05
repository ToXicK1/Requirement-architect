"""Safe text extraction from untrusted documents. Nothing here executes or evaluates content."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

import structlog

log = structlog.get_logger()

MAX_TEXT_CHARS = 200_000

_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "iframe",
        "object",
        "embed",
        "svg",
        "template",
        "canvas",
    }
)
_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
_BLOCK = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "pre",
        "blockquote",
        "header",
        "footer",
        "main",
        "nav",
        "dt",
        "dd",
    }
)
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem)?\s*(?:;|$)|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)",
    re.IGNORECASE,
)

# Heuristic only: flags text that talks TO an AI. It is evidence for review, not a security boundary
# (the boundary is: retrieved text is data, delimited, and model output is schema- and quote-checked).
_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your)\b"
        r"[^.\n]{0,30}\b(instructions?|prompts?|rules|guidelines|directions)\b",
        re.IGNORECASE,
    ),
    "role_reassignment": re.compile(
        r"\byou are (now|no longer)\b|\bact as (an?|the)\b[^.\n]{0,30}\b(assistant|ai|model|agent)\b|\bnew instructions?\s*:",
        re.IGNORECASE,
    ),
    "prompt_exfiltration": re.compile(
        r"\b(reveal|print|show|repeat|output|leak)\b[^.\n]{0,30}\b(system prompt|your (instructions|prompt)|hidden instructions)\b",
        re.IGNORECASE,
    ),
    "fake_delimiters": re.compile(
        r"<\s*/?\s*(system|assistant|developer|instructions?|source|brief|problem_statement|answers)\b[^>]*>"
        r"|\[/?(INST|SYS)\]|<\|(im_start|im_end|endoftext)\|>",
        re.IGNORECASE,
    ),
    "tool_or_action_request": re.compile(
        r"\b(send|email|post|upload|exfiltrate|transmit)\b[^.\n]{0,40}\b(api[_ -]?key|password|secret|credentials?|token)s?\b",
        re.IGNORECASE,
    ),
}


@dataclass
class ExtractedDocument:
    title: str
    text: str
    injection_flags: list[str] = field(default_factory=list)
    truncated: bool = False


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._skip_tag: str | None = None
        self._skip_depth = 0

    @staticmethod
    def _hidden(attrs: list[tuple[str, str | None]]) -> bool:
        d = {k.lower(): (v or "") for k, v in attrs}
        return (
            "hidden" in d
            or d.get("aria-hidden", "").lower() == "true"
            or bool(_HIDDEN_STYLE.search(d.get("style", "")))
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag not in _VOID and (tag in _SKIP_TAGS or self._hidden(attrs)):
            self._skip_tag, self._skip_depth = tag, 1
            return
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_tag is None and tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_tag is not None:
            return
        (self.title_parts if self._in_title else self.parts).append(data)


def sanitize_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    """Strip control/format/invisible characters (zero-width, bidi overrides) and normalise spacing."""
    text = unicodedata.normalize("NFKC", text)
    cleaned = "".join(
        ch
        for ch in text
        if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    )
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r" ?\n ?", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) > max_chars:
        return cleaned[:max_chars].rsplit(" ", 1)[0], True
    return cleaned, False


def detect_injection(text: str) -> list[str]:
    return [name for name, pat in _INJECTION_PATTERNS.items() if pat.search(text)]


def extract_document(
    raw: str, content_type: str, max_chars: int = MAX_TEXT_CHARS
) -> ExtractedDocument:
    title = ""
    body = raw
    if content_type in ("text/html", "application/xhtml+xml"):
        parser = _Extractor()
        try:
            parser.feed(raw)
            parser.close()
        except (ValueError, AssertionError):  # html.parser can choke on pathological input
            log.warning("html_parse_degraded", content_type=content_type)
        body = "".join(parser.parts)
        title = " ".join("".join(parser.title_parts).split())
    text, truncated = sanitize_text(body, max_chars)
    title, _ = sanitize_text(title, 300)
    return ExtractedDocument(title.replace("\n", " "), text, detect_injection(text), truncated)

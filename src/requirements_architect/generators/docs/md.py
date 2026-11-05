"""Markdown building blocks. All model/user text goes through these so it cannot change the
structure of the document (headings, tables, fences, HTML)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

_BLOCK_START = re.compile(r"^(?:[#>\-*+|`~=]|\d+[.)]\s|\[.*\]:)")


def text(value: object) -> str:
    """One-line inline text: whitespace collapsed, angle brackets and block starts neutralized."""
    s = " ".join(str(value).split())
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    if _BLOCK_START.match(s):
        s = "\\" + s
    return s


def inline(value: object) -> str:
    """Heading text: one line, no HTML. Block-start escaping is unnecessary after a '#' prefix."""
    return " ".join(str(value).split()).replace("<", "&lt;").replace(">", "&gt;")


def cell(value: object) -> str:
    s = " ".join(str(value).split()).replace("<", "&lt;").replace(">", "&gt;")
    return s.replace("\\", "\\\\").replace("|", "\\|") or "-"


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    body = [f"| {' | '.join(cell(c) for c in r)} |" for r in rows]
    if not body:
        return ""
    head = f"| {' | '.join(headers)} |\n| {' | '.join('---' for _ in headers)} |"
    return "\n".join([head, *body])


def bullets(items: Iterable[object]) -> str:
    return "\n".join(f"- {text(i)}" for i in items)


def numbered(items: Iterable[object]) -> str:
    return "\n".join(f"{n}. {text(i)}" for n, i in enumerate(items, 1))


def fence(code: str, lang: str = "") -> str:
    """Code block that the content cannot terminate early."""
    ticks = "```"
    while ticks in code:
        ticks += "`"
    return f"{ticks}{lang}\n{code}\n{ticks}"


def mermaid(code: str) -> str:
    return fence(code, "mermaid") if code.strip() else ""


def join(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p and p.strip()) + "\n"


def section(title: str, *body: str, level: int = 2) -> str:
    return join(f"{'#' * level} {inline(title)}", *body)

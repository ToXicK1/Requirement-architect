"""Deterministic Mermaid rendering. Model text only ever appears as sanitized, quoted labels."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

_LABEL_BAD = re.compile(r"[^A-Za-z0-9 .,:/_+()&#'-]")
_ID_BAD = re.compile(r"[^A-Za-z0-9_]")


def label(text: str, limit: int = 60) -> str:
    """Strip everything that could break out of a quoted label or start a directive."""
    cleaned = _LABEL_BAD.sub(" ", text.replace("%%", " "))
    cleaned = " ".join(cleaned.split())
    return (cleaned[: limit - 1] + "…") if len(cleaned) > limit else cleaned or "unnamed"


def node_id(raw_id: str) -> str:
    out = _ID_BAD.sub("", raw_id)
    return out if out and not out[0].isdigit() else f"n{out}"


def flowchart(
    nodes: Iterable[tuple[str, str]],
    edges: Iterable[tuple[str, str, str | None]],
    direction: str = "LR",
) -> str:
    """nodes: (id, text); edges: (source id, target id, optional text). Unknown endpoints are dropped."""
    node_list = list(nodes)
    known = {node_id(i) for i, _ in node_list}
    lines = [f"flowchart {direction}"]
    lines += [f'    {node_id(i)}["{label(t)}"]' for i, t in node_list]
    for s, t, text in edges:
        if node_id(s) in known and node_id(t) in known:
            arrow = f'-->|"{label(text, 40)}"|' if text else "-->"
            lines.append(f"    {node_id(s)} {arrow} {node_id(t)}")
    return "\n".join(lines)


def sequence(participants: Sequence[tuple[str, str]], steps: Iterable[tuple[str, str, str]]) -> str:
    known = {node_id(i) for i, _ in participants}
    lines = ["sequenceDiagram"]
    lines += [f"    participant {node_id(i)} as {label(t, 40)}" for i, t in participants]
    for s, t, msg in steps:
        if node_id(s) in known and node_id(t) in known:
            lines.append(f"    {node_id(s)}->>{node_id(t)}: {label(msg, 70)}")
    return "\n".join(lines)


def er_diagram(
    entities: Iterable[tuple[str, Sequence[tuple[str, str]]]],
    relations: Iterable[tuple[str, str, str]],
) -> str:
    """entities: (name, [(type, field)]); relations: (child, parent, label) rendered many-to-one."""
    ent = list(entities)
    names = {node_id(n) for n, _ in ent}
    lines = ["erDiagram"]
    for name, fields in ent:
        lines.append(f"    {node_id(name)} {{")
        lines += [f"        {node_id(t) or 'string'} {node_id(f)}" for t, f in fields]
        lines.append("    }")
    for child, parent, text in relations:
        if node_id(child) in names and node_id(parent) in names:
            lines.append(f'    {node_id(child)} }}o--|| {node_id(parent)} : "{label(text, 30)}"')
    return "\n".join(lines)

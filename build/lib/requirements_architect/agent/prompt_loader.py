"""Loads version-controlled prompt files and renders them safely."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from string import Template

_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTIONS = re.compile(r"^## (SYSTEM|USER)\n", re.MULTILINE)


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    system: str
    user: str

    def render(self, **values: str) -> tuple[str, str]:
        """Strict substitution: a missing placeholder raises instead of leaking '$name'."""
        try:
            return Template(self.system).substitute(values), Template(self.user).substitute(values)
        except KeyError as exc:
            raise PromptError(f"{self.id} v{self.version}: missing value {exc}") from exc


def _parse(text: str, source: str) -> Prompt:
    m = _FRONT.match(text)
    if not m:
        raise PromptError(f"{source}: missing front matter")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    parts = _SECTIONS.split(m.group(2))
    # parts = ['', 'SYSTEM', body, 'USER', body]
    sections = dict(zip(parts[1::2], parts[2::2], strict=False))
    if "id" not in meta or "version" not in meta or set(sections) != {"SYSTEM", "USER"}:
        raise PromptError(f"{source}: needs id, version, SYSTEM and USER sections")
    return Prompt(meta["id"], meta["version"], sections["SYSTEM"].strip(), sections["USER"].strip())


@cache
def load_prompt(prompt_id: str, version: int | None = None) -> Prompt:
    """Load a prompt by id; the highest version is used unless one is pinned."""
    root = resources.files("requirements_architect.agent") / "prompts" / prompt_id
    if not root.is_dir():
        raise PromptError(f"unknown prompt: {prompt_id}")
    versions = sorted(
        int(p.name[1:-3]) for p in root.iterdir() if re.fullmatch(r"v\d+\.md", p.name)
    )
    if not versions:
        raise PromptError(f"no versions for prompt: {prompt_id}")
    chosen = version if version is not None else versions[-1]
    if chosen not in versions:
        raise PromptError(f"{prompt_id}: version {chosen} not found")
    path = root / f"v{chosen}.md"
    return _parse(path.read_text(encoding="utf-8"), f"{prompt_id}/v{chosen}")


def wrap_untrusted(text: str, tag: str) -> str:
    """Neutralize attempts to close/open our delimiter tag from inside user-controlled text."""
    return re.sub(rf"<\s*/?\s*{re.escape(tag)}\b[^>]*>", "[removed-tag]", text, flags=re.IGNORECASE)

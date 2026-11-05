"""Independent LLM review. It sees only the persisted specifications (never the generator's
prompts, reasoning or retries), may not set fixability, and its citations are checked by code."""

from __future__ import annotations

import re

from requirements_architect.agent.prompt_loader import load_prompt, wrap_untrusted
from requirements_architect.agent.stages.common import (
    render_architecture,
    render_data_api,
    render_requirements,
    render_technology,
)
from requirements_architect.audit.specset import SpecSet
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.llm.types import LLMRequest, Message
from requirements_architect.schemas.audit import (
    AuditCategory,
    AuditFinding,
    AuditSeverity,
    RawAuditReview,
)
from requirements_architect.schemas.state import StageId
from requirements_architect.validation.secrets import scrub

_ID = re.compile(r"\b(?:FR|NFR|C|TECH|E|EP|SC|TH|SCR|FL|TC|US|OBJ)-\d{3,}\b")
_STAGE_BY_PREFIX = {
    "FR": StageId.REQUIREMENTS,
    "NFR": StageId.REQUIREMENTS,
    "US": StageId.REQUIREMENTS,
    "OBJ": StageId.REQUIREMENTS,
    "C": StageId.ARCHITECTURE,
    "TECH": StageId.TECHNOLOGY,
    "E": StageId.DATA_API,
    "EP": StageId.DATA_API,
    "SC": StageId.SECURITY,
    "TH": StageId.SECURITY,
    "SCR": StageId.UX,
    "FL": StageId.UX,
    "TC": StageId.QA_DEPLOY,
}


def known_ids(s: SpecSet) -> set[str]:
    return (
        {f.id for f in s.requirements.functional}
        | {n.id for n in s.requirements.nonfunctional}
        | {u.id for u in s.requirements.user_stories}
        | {o.id for o in s.requirements.objectives}
        | {c.id for c in s.architecture.components}
        | {t.id for t in s.technology.technologies}
        | {e.id for e in s.data_api.entities}
        | {e.id for e in s.data_api.endpoints}
        | {c.id for c in s.security.controls}
        | {t.id for t in s.security.threats}
        | {x.id for x in s.ux.screens}
        | {x.id for x in s.ux.flows}
        | {t.id for t in s.qa.test_cases}
    )


def _render(s: SpecSet) -> dict[str, str]:
    sec = [f"{c.id} {c.name} ({c.area.value}): {c.description[:160]}" for c in s.security.controls]
    sec += [
        f"{t.id} {t.title} [{t.risk_level}] controls: {', '.join(t.control_ids) or 'none'}"
        for t in s.security.threats
    ]
    ux = [f"{x.id} {x.name}: {x.purpose[:140]}" for x in s.ux.screens]
    ux += [f"{x.id} {x.name} ({x.actor})" for x in s.ux.flows]
    tests = [
        f"{t.id} ({t.test_type.value}) verifies {', '.join(t.requirement_ids)}: {t.scenario[:120]}"
        for t in s.qa.test_cases
    ]
    return {
        "requirements": render_requirements(s.requirements),
        "architecture": render_architecture(s.architecture),
        "technology": render_technology(s.technology),
        "dataapi": render_data_api(s.data_api),
        "security": "\n".join(sec) or "(none)",
        "ux": "\n".join(ux) or "(none)",
        "tests": "\n".join(tests) or "(none)",
    }


def to_findings(raw: RawAuditReview, valid: set[str]) -> tuple[list[AuditFinding], int]:
    """Validate citations and cap severity. Returns (findings, number discarded)."""
    out: list[AuditFinding] = []
    discarded = 0
    for r in raw.findings:
        cited = list(dict.fromkeys([*r.refs, *_ID.findall(r.message)]))
        refs = [x for x in cited if x in valid]
        if cited and not refs:
            discarded += 1  # it points only at things that do not exist
            continue
        sev = AuditSeverity(r.severity)
        if not refs and sev is AuditSeverity.MAJOR:
            sev = AuditSeverity.MINOR  # no checkable evidence: cannot be a major defect
        message, _ = scrub(" ".join(r.message.split()))
        prefix = re.match(r"([A-Z]+)-", refs[0]) if refs else None
        out.append(
            AuditFinding(
                source="llm",
                category=AuditCategory.REVIEW,
                severity=sev,
                code=f"LLM_{r.kind.upper()}",
                message=message,
                refs=sorted(refs),
                stage=_STAGE_BY_PREFIX.get(prefix.group(1)) if prefix else None,
                auto_fixable=False,  # a model's judgment is never grounds for rewriting specs
                needs_human=True,
            )
        )
    return out, discarded


async def review(
    gateway: LLMGateway, specs: SpecSet, project_id: str
) -> tuple[list[AuditFinding], int]:
    prompt = load_prompt("audit_review")
    values = {k: wrap_untrusted(v, k) for k, v in _render(specs).items()}
    system, user = prompt.render(**values)
    request = LLMRequest(
        system=system,
        messages=[Message(role="user", content=user)],
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        project_id=project_id,
        max_tokens=8000,
    )
    raw, _ = await gateway.complete_structured(request, RawAuditReview)
    return to_findings(raw, known_ids(specs))

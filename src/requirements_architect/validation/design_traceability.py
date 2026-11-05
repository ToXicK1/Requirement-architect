"""Full-chain traceability: requirement -> component / entity / endpoint / control / test.

Extends the Phase 5 objective/story links with the links the design stages emit, so
`analyze()` can report requirements without design or test coverage and orphan
components, entities, endpoints, controls and tests.
"""

from __future__ import annotations

from collections.abc import Sequence

from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.requirements import RequirementsSpec
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.technology import TechnologySpec
from requirements_architect.schemas.ux import UxSpec
from requirements_architect.validation.traceability import (
    TraceKind,
    TraceLink,
    TraceReport,
    analyze,
    links_from_spec,
)

DEFAULT_REQUIRED = (TraceKind.OBJECTIVE, TraceKind.STORY, TraceKind.COMPONENT, TraceKind.TEST)


def design_links(
    arch: ArchitectureSpec | None,
    api: DataApiSpec | None,
    sec: SecuritySpec | None,
    qa: QaSpec | None,
) -> list[TraceLink]:
    links: list[TraceLink] = []
    for comp in arch.components if arch else []:
        links += [
            TraceLink(requirement_id=r, kind=TraceKind.COMPONENT, target_id=comp.id)
            for r in comp.requirement_ids
        ]
    for ent in api.entities if api else []:
        links += [
            TraceLink(requirement_id=r, kind=TraceKind.ENTITY, target_id=ent.id)
            for r in ent.requirement_ids
        ]
    for ep in api.endpoints if api else []:
        links += [
            TraceLink(requirement_id=r, kind=TraceKind.ENDPOINT, target_id=ep.id)
            for r in ep.requirement_ids
        ]
    for ctl in sec.controls if sec else []:
        links += [
            TraceLink(requirement_id=r, kind=TraceKind.CONTROL, target_id=ctl.id)
            for r in ctl.requirement_ids
        ]
    for case in qa.test_cases if qa else []:
        links += [
            TraceLink(requirement_id=r, kind=TraceKind.TEST, target_id=case.id)
            for r in case.requirement_ids
        ]
    return links


def design_targets(
    arch: ArchitectureSpec | None,
    api: DataApiSpec | None,
    sec: SecuritySpec | None,
    qa: QaSpec | None,
) -> dict[TraceKind, set[str]]:
    return {
        TraceKind.COMPONENT: {c.id for c in arch.components} if arch else set(),
        TraceKind.ENTITY: {e.id for e in api.entities} if api else set(),
        TraceKind.ENDPOINT: {e.id for e in api.endpoints} if api else set(),
        TraceKind.CONTROL: {c.id for c in sec.controls} if sec else set(),
        TraceKind.TEST: {t.id for t in qa.test_cases} if qa else set(),
    }


def full_report(
    reqs: RequirementsSpec,
    arch: ArchitectureSpec | None,
    api: DataApiSpec | None,
    sec: SecuritySpec | None,
    qa: QaSpec | None,
    required: Sequence[TraceKind] = DEFAULT_REQUIRED,
) -> tuple[list[TraceLink], TraceReport]:
    links = [*links_from_spec(reqs), *design_links(arch, api, sec, qa)]
    return links, analyze(reqs, links, required, design_targets(arch, api, sec, qa))


def collect_approval_candidates(
    arch: ArchitectureSpec | None,
    tech: TechnologySpec | None,
    sec: SecuritySpec | None,
    ux: UxSpec | None,
    api: DataApiSpec | None,
    qa: QaSpec | None,
) -> list[ApprovalCandidate]:
    out: list[ApprovalCandidate] = []
    for spec in (arch, tech, api, sec, ux, qa):
        if spec is not None:
            out += spec.approval_candidates
    return out

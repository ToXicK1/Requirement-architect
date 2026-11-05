"""Requirements traceability: links, coverage analysis, orphan detection, CSV export.

Pure and deterministic. Phase 5 supplies objective and story links; later stages add
component/entity/endpoint/control/test/task links and extend `required`.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from enum import StrEnum

from pydantic import BaseModel, Field

from requirements_architect.schemas.requirements import RequirementsSpec


class TraceKind(StrEnum):
    OBJECTIVE = "objective"
    STORY = "story"
    COMPONENT = "component"
    ENTITY = "entity"
    ENDPOINT = "endpoint"
    CONTROL = "control"
    TEST = "test"
    TASK = "task"


class TraceLink(BaseModel):
    requirement_id: str
    kind: TraceKind
    target_id: str


class TargetRef(BaseModel):
    kind: TraceKind
    target_id: str


class TraceReport(BaseModel):
    uncovered: dict[str, list[TraceKind]] = Field(default_factory=dict)
    orphan_targets: list[TargetRef] = Field(default_factory=list)
    dangling_links: list[TraceLink] = Field(default_factory=list)
    coverage: dict[TraceKind, float] = Field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not (self.uncovered or self.orphan_targets or self.dangling_links)


def links_from_spec(spec: RequirementsSpec) -> list[TraceLink]:
    links: list[TraceLink] = []
    for fr in spec.functional:
        if fr.objective_id:
            links.append(
                TraceLink(requirement_id=fr.id, kind=TraceKind.OBJECTIVE, target_id=fr.objective_id)
            )
    for story in spec.user_stories:
        for rid in story.requirement_ids:
            links.append(TraceLink(requirement_id=rid, kind=TraceKind.STORY, target_id=story.id))
    return links


def known_targets_from_spec(spec: RequirementsSpec) -> dict[TraceKind, set[str]]:
    return {
        TraceKind.OBJECTIVE: {o.id for o in spec.objectives},
        TraceKind.STORY: {s.id for s in spec.user_stories},
    }


def analyze(
    spec: RequirementsSpec,
    links: Sequence[TraceLink],
    required: Sequence[TraceKind] = (TraceKind.OBJECTIVE, TraceKind.STORY),
    known_targets: Mapping[TraceKind, AbstractSet[str]] | None = None,
) -> TraceReport:
    """Find requirements lacking required links, targets nobody traces to, and links to nothing."""
    targets: dict[TraceKind, set[str]] = {
        k: set(v) for k, v in known_targets_from_spec(spec).items()
    }
    for kind, ids in (known_targets or {}).items():
        targets.setdefault(kind, set()).update(ids)

    fr_ids = [fr.id for fr in spec.functional]
    valid_requirements = set(fr_ids) | {n.id for n in spec.nonfunctional}

    dangling: list[TraceLink] = []
    linked: dict[tuple[TraceKind, str], bool] = {}
    by_req: dict[str, set[TraceKind]] = {}
    for link in links:
        target_known = link.target_id in targets.get(link.kind, set())
        if link.requirement_id not in valid_requirements or (
            link.kind in targets and not target_known
        ):
            dangling.append(link)
            continue
        linked[(link.kind, link.target_id)] = True
        by_req.setdefault(link.requirement_id, set()).add(link.kind)

    uncovered = {
        rid: [k for k in required if k not in by_req.get(rid, set())]
        for rid in fr_ids
        if any(k not in by_req.get(rid, set()) for k in required)
    }
    orphans = [
        TargetRef(kind=kind, target_id=tid)
        for kind, ids in sorted(targets.items(), key=lambda kv: kv[0].value)
        for tid in sorted(ids)
        if (kind, tid) not in linked
    ]
    total = len(fr_ids)
    coverage = {
        k: (sum(1 for rid in fr_ids if k in by_req.get(rid, set())) / total if total else 1.0)
        for k in required
    }
    return TraceReport(
        uncovered=uncovered, orphan_targets=orphans, dangling_links=dangling, coverage=coverage
    )


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection: requirement text is model/user controlled."""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def to_csv(spec: RequirementsSpec, links: Sequence[TraceLink]) -> str:
    kinds = list(TraceKind)
    index: dict[tuple[str, TraceKind], list[str]] = {}
    for link in links:
        index.setdefault((link.requirement_id, link.kind), []).append(link.target_id)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["requirement_id", "name", "priority", *[k.value for k in kinds]])
    for fr in spec.functional:
        writer.writerow(
            [
                fr.id,
                _csv_safe(fr.name),
                fr.priority.value,
                *[_csv_safe(";".join(sorted(index.get((fr.id, k), [])))) for k in kinds],
            ]
        )
    return buf.getvalue()

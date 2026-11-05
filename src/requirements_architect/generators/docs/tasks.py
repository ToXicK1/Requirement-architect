"""Deterministic implementation plan: tasks are derived from the specifications by code, so
every task points at real ids and the order respects declared dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field

from requirements_architect.generators.docs.model import DocInputs
from requirements_architect.validation.traceability import TraceKind, TraceLink

PHASES = (
    "Foundation",
    "Data model",
    "Components",
    "API",
    "Security controls",
    "User interface",
    "Tests",
    "Deployment",
)


@dataclass
class Task:
    id: str = ""
    title: str = ""
    phase: int = 0
    refs: list[str] = field(default_factory=list)  # ids of the spec items this task implements
    requirement_ids: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # task ids
    done_when: str = ""
    key: str = ""  # internal handle for the item implemented


@dataclass
class Plan:
    tasks: list[Task]
    notes: list[str]


def _order(tasks: list[Task], notes: list[str]) -> list[Task]:
    """Phase first, then dependency order inside a phase; a dependency cycle is broken by
    ignoring the back edge (and reported) rather than failing."""
    by_key = {t.key: t for t in tasks}
    visiting: set[str] = set()
    done: set[str] = set()
    out: list[Task] = []

    def visit(t: Task) -> None:
        if t.key in done:
            return
        visiting.add(t.key)
        for dep in list(t.depends_on):
            d = by_key.get(dep)
            if d is None:
                continue
            if d.key in visiting:
                notes.append(f"dependency cycle: {t.title} <-> {d.title}; edge ignored in ordering")
                t.depends_on.remove(dep)
                continue
            visit(d)
        visiting.discard(t.key)
        done.add(t.key)
        out.append(t)

    for phase in range(len(PHASES)):
        for t in tasks:
            if t.phase == phase:
                visit(t)
    return out


def build_plan(i: DocInputs) -> Plan:
    a, api, sec, ux, qa = i.architecture, i.data_api, i.security, i.ux, i.qa
    tasks: list[Task] = []
    notes: list[str] = []

    def add(
        key: str,
        title: str,
        phase: int,
        refs: list[str],
        reqs: list[str],
        deps: list[str],
        done: str,
    ) -> None:
        tasks.append(
            Task(
                key=key,
                title=title,
                phase=phase,
                refs=refs,
                requirement_ids=sorted(set(reqs)),
                depends_on=deps,
                done_when=done,
            )
        )

    add(
        "setup",
        "Set up repository, tooling and CI",
        0,
        [t.id for t in i.technology.technologies],
        [],
        [],
        "Project builds, lints and runs an empty test suite in CI.",
    )
    ent_key = {e.id: f"ent:{e.id}" for e in api.entities}
    for e in api.entities:
        deps = ["setup"] + [
            f"ent:{k.references_entity}"
            for k in e.foreign_keys
            if f"ent:{k.references_entity}" in ent_key.values()
        ]
        add(
            f"ent:{e.id}",
            f"Implement data model {e.id} ({e.name}) and its migration",
            1,
            [e.id],
            e.requirement_ids,
            deps,
            "Migration applies and rolls back; constraints and indexes match the specification.",
        )
    for c in a.components:
        add(
            f"comp:{c.id}",
            f"Implement component {c.id} ({c.name})",
            2,
            [c.id],
            c.requirement_ids,
            ["setup"] + [f"comp:{d}" for d in c.depends_on],
            "Responsibility is implemented and covered by its linked test cases.",
        )
    for ep in api.endpoints:
        add(
            f"ep:{ep.id}",
            f"Implement endpoint {ep.id} {ep.method.value} {ep.path}",
            3,
            [ep.id],
            ep.requirement_ids,
            ["setup"] + [ent_key[x] for x in ep.entity_ids if x in ent_key],
            "Endpoint matches the specified method, path, authentication, validation and error responses.",
        )
    for ctl in sec.controls:
        add(
            f"ctl:{ctl.id}",
            f"Implement security control {ctl.id} ({ctl.name})",
            4,
            [ctl.id],
            ctl.requirement_ids,
            ["setup"],
            "Control is enforced and its security test passes.",
        )
    for s in ux.screens if ux.has_ui else []:
        add(
            f"scr:{s.id}",
            f"Implement screen {s.id} ({s.name})",
            5,
            [s.id],
            s.requirement_ids,
            ["setup"] + [f"ep:{x}" for x in s.endpoint_ids],
            "All specified states render and accessibility requirements are met.",
        )
    impl = [t for t in tasks if t.phase < 6]
    for case in qa.test_cases:
        deps = [t.key for t in impl if set(t.requirement_ids) & set(case.requirement_ids)] or [
            "setup"
        ]
        add(
            f"tc:{case.id}",
            f"Implement and pass test case {case.id}",
            6,
            [case.id],
            case.requirement_ids,
            deps,
            case.expected_result,
        )
    add(
        "deploy",
        "Prepare deployment, monitoring and rollback",
        7,
        [],
        [],
        [t.key for t in tasks if t.phase == 6] or ["setup"],
        "Deployment plan steps are executed in a staging environment and rollback is rehearsed.",
    )

    ordered = _order(tasks, notes)
    ids = {t.key: f"T-{n:03d}" for n, t in enumerate(ordered, 1)}
    for t in ordered:
        t.id = ids[t.key]
        t.depends_on = [ids[d] for d in t.depends_on if d in ids]
    return Plan(ordered, notes)


def task_links(plan: Plan) -> list[TraceLink]:
    return [
        TraceLink(requirement_id=r, kind=TraceKind.TASK, target_id=t.id)
        for t in plan.tasks
        for r in t.requirement_ids
    ]

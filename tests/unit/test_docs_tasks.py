from requirements_architect.agent.stages.architecture import build_architecture
from requirements_architect.generators.docs.package import build_package
from requirements_architect.generators.docs.tasks import (
    PHASES,
    Task,
    _order,
    build_plan,
    task_links,
)
from requirements_architect.generators.docs.validation import all_links, report
from requirements_architect.schemas.architecture import RawArchitecture
from requirements_architect.validation.traceability import TraceKind
from tests.design_helpers import make_reqs, raw_arch, raw_comp
from tests.doc_helpers import make_inputs


def test_task_ids_are_dense_and_dependencies_point_backwards():
    plan = build_plan(make_inputs())
    ids = [t.id for t in plan.tasks]
    assert ids == [f"T-{n:03d}" for n in range(1, len(ids) + 1)]
    pos = {t.id: n for n, t in enumerate(plan.tasks)}
    for t in plan.tasks:
        assert all(pos[d] < pos[t.id] for d in t.depends_on), t.id


def test_phases_are_in_order_and_cover_each_spec_kind():
    plan = build_plan(make_inputs())
    phases = [t.phase for t in plan.tasks]
    assert phases == sorted(phases)
    titles = " ".join(t.title for t in plan.tasks)
    for word in (
        "component C-001",
        "endpoint EP-001",
        "data model E-001",
        "control SC-001",
        "screen SCR-001",
        "test case TC-001",
        "deployment",
    ):
        assert word in titles, word
    assert plan.tasks[0].title.startswith("Set up") and plan.tasks[-1].phase == len(PHASES) - 1


def test_component_dependency_is_implemented_first():
    plan = build_plan(make_inputs())
    by_ref = {t.refs[0]: t for t in plan.tasks if t.refs}
    assert by_ref["C-001"].id in by_ref["C-002"].depends_on  # C2 depends_on C1


def test_test_tasks_depend_on_the_work_they_verify():
    plan = build_plan(make_inputs())
    tc = next(t for t in plan.tasks if t.refs == ["TC-001"])
    impl = {
        t.id for t in plan.tasks if t.phase < 6 and set(t.requirement_ids) & set(tc.requirement_ids)
    }
    assert impl and impl <= set(tc.depends_on)


def test_cycles_are_broken_reported_and_do_not_hang():
    a = Task(key="a", title="A", phase=2, depends_on=["b"])
    b = Task(key="b", title="B", phase=2, depends_on=["a"])
    notes: list[str] = []
    out = _order([a, b], notes)
    assert {t.key for t in out} == {"a", "b"} and len(out) == 2
    assert any("cycle" in n for n in notes)


def test_cyclic_architecture_still_plans():
    reqs = make_reqs(2)
    arch = build_architecture(
        RawArchitecture.model_validate(
            raw_arch(
                components=[raw_comp("C1", depends_on=["C2"]), raw_comp("C2", depends_on=["C1"])]
            )
        ),
        reqs,
    )
    inp = make_inputs(reqs)
    inp = inp.__class__(**{**inp.__dict__, "architecture": arch})
    plan = build_plan(inp)
    assert len(plan.tasks) >= 2
    build_package(inp)


def test_no_ui_means_no_screen_tasks():
    plan = build_plan(make_inputs(ux={"has_ui": False, "interface_note": "API only"}))
    assert not any("screen" in t.title for t in plan.tasks)


def test_task_links_feed_traceability_and_all_requirements_are_covered():
    inp = make_inputs()
    plan = build_plan(inp)
    links = all_links(inp, plan)
    assert {link.kind for link in links} >= {TraceKind.TASK, TraceKind.TEST, TraceKind.COMPONENT}
    assert all(link.kind is TraceKind.TASK for link in task_links(plan))
    rep = report(inp, plan, links)
    assert rep.dangling_links == []
    design = {TraceKind.COMPONENT, TraceKind.TEST, TraceKind.TASK}
    for fr in ("FR-001", "FR-002"):
        assert not design & set(rep.uncovered.get(fr, [])), fr


def test_traceability_matrix_document_reports_gaps():
    reqs = make_reqs(2)
    inp = make_inputs(reqs)
    # drop component coverage of FR-002
    arch = inp.architecture.model_copy(deep=True)
    arch.components[1].requirement_ids = []
    inp = inp.__class__(**{**inp.__dict__, "architecture": arch})
    doc = next(d for d in build_package(inp).docs if d.path.endswith("TRACEABILITY_MATRIX.md"))
    assert "FR-002" in doc.body and "component" in doc.body.split("## Gaps")[1]


def test_risk_register_sorts_highest_risk_first():
    inp = make_inputs(
        security={
            "threats": [
                {
                    "key": "TH1",
                    "title": "low one",
                    "category": "spoofing",
                    "asset": "a",
                    "description": "d",
                    "likelihood": "low",
                    "impact": "low",
                    "control_keys": ["SC1"],
                },
                {
                    "key": "TH2",
                    "title": "high one",
                    "category": "tampering",
                    "asset": "a",
                    "description": "d",
                    "likelihood": "high",
                    "impact": "high",
                    "control_keys": ["SC1"],
                },
            ]
        }
    )
    body = next(d for d in build_package(inp).docs if d.path.endswith("RISK_REGISTER.md")).body
    assert body.index("high one") < body.index("low one")

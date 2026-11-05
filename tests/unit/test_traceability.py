from requirements_architect.agent.stages.requirements import build_spec
from requirements_architect.schemas.requirements import RawRequirementsOutput
from requirements_architect.schemas.state import ProjectBrief
from requirements_architect.validation.traceability import (
    TraceKind,
    TraceLink,
    analyze,
    links_from_spec,
    to_csv,
)
from tests.conftest import raw_fr

BRIEF = ProjectBrief(
    actual_problem="p", proposed_solution="s", business_objectives=["Obj A", "Obj B"]
)


def make(frs, stories):
    raw = RawRequirementsOutput.model_validate({"functional": frs, "user_stories": stories})
    return build_spec(raw, BRIEF, None)


def story(*keys):
    return {"actor": "a", "want": "w", "benefit": "b", "requirement_keys": list(keys)}


def test_links_and_clean_report():
    spec = make(
        [raw_fr("R1", objective="Obj A"), raw_fr("R2", objective="Obj B")],
        [story("R1"), story("R2")],
    )
    links = links_from_spec(spec)
    assert {(l.requirement_id, l.kind.value, l.target_id) for l in links} == {
        ("FR-001", "objective", "OBJ-001"),
        ("FR-002", "objective", "OBJ-002"),
        ("FR-001", "story", "US-001"),
        ("FR-002", "story", "US-002"),
    }
    rep = analyze(spec, links)
    assert rep.clean and rep.coverage == {TraceKind.OBJECTIVE: 1.0, TraceKind.STORY: 1.0}


def test_uncovered_requirements_and_orphan_objective_detected():
    spec = make([raw_fr("R1", objective="Obj A"), raw_fr("R2")], [story("R1")])
    rep = analyze(spec, links_from_spec(spec))
    assert rep.uncovered == {"FR-002": [TraceKind.OBJECTIVE, TraceKind.STORY]}
    assert [(o.kind, o.target_id) for o in rep.orphan_targets] == [(TraceKind.OBJECTIVE, "OBJ-002")]
    assert rep.coverage[TraceKind.OBJECTIVE] == 0.5 and not rep.clean


def test_dangling_links_detected_unknown_requirement_and_unknown_target():
    spec = make([raw_fr("R1", objective="Obj A")], [story("R1")])
    links = [
        *links_from_spec(spec),
        TraceLink(requirement_id="FR-099", kind=TraceKind.STORY, target_id="US-001"),
        TraceLink(requirement_id="FR-001", kind=TraceKind.STORY, target_id="US-099"),
    ]
    rep = analyze(spec, links)
    assert {(l.requirement_id, l.target_id) for l in rep.dangling_links} == {
        ("FR-099", "US-001"),
        ("FR-001", "US-099"),
    }


def test_later_stage_targets_orphans_and_required_extension():
    spec = make(
        [raw_fr("R1", objective="Obj A"), raw_fr("R2", objective="Obj B")], [story("R1", "R2")]
    )
    links = [
        *links_from_spec(spec),
        TraceLink(requirement_id="FR-001", kind=TraceKind.TEST, target_id="T-1"),
    ]
    known = {TraceKind.TEST: {"T-1", "T-2"}}
    rep = analyze(spec, links, required=(TraceKind.TEST,), known_targets=known)
    assert rep.uncovered == {"FR-002": [TraceKind.TEST]}
    assert [(o.kind, o.target_id) for o in rep.orphan_targets if o.kind is TraceKind.TEST] == [
        (TraceKind.TEST, "T-2")
    ]
    unknown_test = analyze(
        spec,
        [*links, TraceLink(requirement_id="FR-001", kind=TraceKind.TEST, target_id="T-9")],
        required=(TraceKind.TEST,),
        known_targets=known,
    )
    assert [l.target_id for l in unknown_test.dangling_links] == ["T-9"]


def test_csv_export_columns_and_formula_injection_guard():
    spec = make(
        [
            raw_fr("R1", name='=HYPERLINK("http://evil")', objective="Obj A"),
            raw_fr("R2", name="@SUM(A1)"),
            raw_fr("R3", name="+1"),
            raw_fr("R4", name="Normal, name"),
        ],
        [story("R1", "R2")],
    )
    out = to_csv(spec, links_from_spec(spec))
    import csv
    import io

    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0][:3] == ["requirement_id", "name", "priority"] and "test" in rows[0]
    names = [r[1] for r in rows[1:]]
    assert names == ['\'=HYPERLINK("http://evil")', "'@SUM(A1)", "'+1", "Normal, name"]
    assert rows[1][rows[0].index("objective")] == "OBJ-001"
    assert rows[1][rows[0].index("story")] == "US-001"

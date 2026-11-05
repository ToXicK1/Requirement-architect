import pytest
from pydantic import ValidationError

from requirements_architect.agent.stages.architecture import build_architecture
from requirements_architect.schemas.architecture import RawArchitecture
from tests.design_helpers import make_reqs, raw_arch, raw_comp

REQS = make_reqs(2)


def build(**kw):
    return build_architecture(RawArchitecture.model_validate(raw_arch(**kw)), REQS)


def codes(spec):
    return [i.code for i in spec.issues]


def test_ids_assigned_and_diagrams_rendered_from_structure():
    spec = build(
        components=[
            raw_comp("C1", requirement_ids=["FR-001"], depends_on=["C2"]),
            raw_comp("C2", requirement_ids=["FR-002"]),
            raw_comp("C3", kind="external", requirement_ids=[]),
        ],
        data_flows=[{"source": "C1", "target": "C2", "data": "orders"}],
        sequences=[
            {"name": "Create order", "steps": [{"source": "C1", "target": "C2", "message": "save"}]}
        ],
    )
    assert [c.id for c in spec.components] == ["C-001", "C-002", "C-003"]
    assert spec.components[0].depends_on == ["C-002"]
    assert 'C001 -->|"uses"| C002' in spec.component_diagram
    assert 'C001 -->|"orders"| C002' in spec.dataflow_diagram
    assert "ACTOR1" in spec.context_diagram and "SYSTEM --> C003" in spec.context_diagram
    assert spec.sequences[0].mermaid.startswith("sequenceDiagram")
    assert codes(spec) == []  # external components need no requirement; all FRs served


def test_unknown_references_are_dropped_and_reported():
    spec = build(
        components=[raw_comp("C1", requirement_ids=["FR-001", "FR-999"], depends_on=["C1", "C9"])],
        data_flows=[{"source": "C1", "target": "C9", "data": "x"}],
    )
    assert spec.components[0].requirement_ids == ["FR-001"] and spec.components[0].depends_on == []
    assert spec.data_flows == []
    assert {
        "UNKNOWN_REQUIREMENT",
        "SELF_DEPENDENCY",
        "UNKNOWN_DEPENDENCY",
        "UNKNOWN_FLOW_ENDPOINT",
    } <= set(codes(spec))


def test_coverage_gaps_reported():
    spec = build(
        components=[raw_comp("C1", requirement_ids=["NFR-001"]), raw_comp("C2", requirement_ids=[])]
    )
    assert [i.ref for i in spec.issues if i.code == "FR_NO_COMPONENT"] == ["FR-001", "FR-002"]
    assert [i.ref for i in spec.issues if i.code == "ORPHAN_COMPONENT"] == ["C-002"]


def test_component_cycle_detected():
    spec = build(components=[raw_comp("C1", depends_on=["C2"]), raw_comp("C2", depends_on=["C1"])])
    assert codes(spec).count("COMPONENT_CYCLE") == 1


def test_pattern_must_be_justified_and_compared():
    spec = build(selected_pattern="microservices")  # evaluated as unsuitable in the default fixture
    err = [i for i in spec.issues if i.code == "PATTERN_NOT_JUSTIFIED"]
    assert err and err[0].severity.value == "error"
    one = build(
        pattern_evaluations=[{"pattern": "modular_monolith", "suitable": True, "rationale": "r"}]
    )
    assert "PATTERN_NOT_COMPARED" in codes(one) and "PATTERN_NOT_JUSTIFIED" not in codes(one)
    absent = build(selected_pattern="serverless")
    assert "PATTERN_NOT_JUSTIFIED" in codes(absent)


def test_sequences_partially_or_fully_invalid():
    spec = build(
        components=[raw_comp("C1"), raw_comp("C2", requirement_ids=["FR-002"])],
        sequences=[
            {
                "name": "ok",
                "steps": [
                    {"source": "C1", "target": "C2", "message": "m"},
                    {"source": "C1", "target": "C9", "message": "bad"},
                ],
            },
            {"name": "dead", "steps": [{"source": "C8", "target": "C9", "message": "bad"}]},
        ],
    )
    assert [s.name for s in spec.sequences] == ["ok"] and len(spec.sequences[0].steps) == 1
    assert {"UNKNOWN_SEQUENCE_PARTICIPANT", "SEQUENCE_DROPPED"} <= set(codes(spec))


def test_decisions_quality_checks_and_approval_candidates():
    spec = build(
        decisions=[
            {
                "key": "D1",
                "title": "Use one DB",
                "decision": "d",
                "rationale": "r",
                "alternatives": [{"name": "two DBs", "why_rejected": "cost"}],
                "tradeoffs": ["t"],
                "component_keys": ["C1", "C9"],
            },
            {
                "key": "D2",
                "title": "Adopt vendor X",
                "decision": "d",
                "rationale": "r",
                "needs_human_approval": True,
                "approval_reason": "vendor lock-in",
            },
        ]
    )
    assert [d.id for d in spec.decisions] == ["AD-001", "AD-002"]
    assert spec.decisions[0].component_ids == ["C-001"]
    assert [i.ref for i in spec.issues if i.code == "DECISION_NO_ALTERNATIVES"] == ["AD-002"]
    assert [i.ref for i in spec.issues if i.code == "DECISION_NO_TRADEOFFS"] == ["AD-002"]
    assert [(c.ref, c.reason) for c in spec.approval_candidates] == [("AD-002", "vendor lock-in")]


def test_diagram_text_cannot_inject_mermaid_syntax():
    import re

    evil = 'A"]\n%%{init: {}}%%\nclick X call alert()\nC1["pwned'
    spec = build(components=[raw_comp("C1", name=evil)])
    label = r'"[A-Za-z0-9 .,:/_+()&#\'\u2026-]*"'
    node = rf"    \w+\[{label}\]"
    edge = rf"    \w+ -->(\|{label}\|)? \w+"
    for diagram in (spec.component_diagram, spec.context_diagram, spec.dataflow_diagram):
        header, *body = diagram.splitlines()
        assert header == "flowchart LR"
        # every line is a plain node or edge: no directives, no stray brackets, no extra statements
        assert all(re.fullmatch(node, ln) or re.fullmatch(edge, ln) for ln in body), body


def test_raw_schema_rejects_bad_structure():
    with pytest.raises(ValidationError):
        RawArchitecture.model_validate(raw_arch(components=[raw_comp("C1"), raw_comp("C1")]))
    with pytest.raises(ValidationError):
        RawArchitecture.model_validate(raw_arch(components=[]))
    with pytest.raises(ValidationError):
        RawArchitecture.model_validate(raw_arch(components=[raw_comp("component-1")]))
    with pytest.raises(ValidationError):
        RawArchitecture.model_validate(raw_arch(selected_pattern="big_ball_of_mud"))

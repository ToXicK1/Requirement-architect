import pytest
from pydantic import ValidationError

from requirements_architect.agent.prompt_loader import load_prompt
from requirements_architect.agent.stages.requirements import (
    _find_cycles,
    approve_nfr_targets,
    build_spec,
)
from requirements_architect.schemas.requirements import (
    NfrCategory,
    RawRequirementsOutput,
    TargetStatus,
)
from requirements_architect.schemas.research import (
    Finding,
    FindingKind,
    ResearchReport,
    VerificationStatus,
)
from requirements_architect.schemas.state import ProjectBrief
from tests.conftest import raw_fr

BRIEF = ProjectBrief(
    actual_problem="p",
    proposed_solution="s",
    business_objectives=["Reduce onboarding time", "Improve audit trail"],
)
REPORT = ResearchReport(
    findings=[
        Finding(
            finding_id="F-001",
            kind=FindingKind.FACT,
            claim="c",
            verification=VerificationStatus.VERIFIED,
            verification_note="n",
        )
    ]
)


def raw(*frs, nfrs=(), stories=()):
    return RawRequirementsOutput.model_validate(
        {"functional": list(frs), "nonfunctional": list(nfrs), "user_stories": list(stories)}
    )


def codes(spec):
    return [i.code for i in spec.issues]


def test_ids_are_assigned_by_code_in_order():
    spec = build_spec(raw(raw_fr("R7"), raw_fr("R2")), BRIEF, REPORT)
    assert [f.id for f in spec.functional] == ["FR-001", "FR-002"]
    assert [o.id for o in spec.objectives] == ["OBJ-001", "OBJ-002"]


def test_objective_must_match_brief_case_and_space_insensitively():
    spec = build_spec(
        raw(
            raw_fr("R1", objective="  reduce   ONBOARDING time "),
            raw_fr("R2", objective="Invented objective"),
            raw_fr("R3"),
        ),
        BRIEF,
        REPORT,
    )
    assert [f.objective_id for f in spec.functional] == ["OBJ-001", None, None]
    assert codes(spec).count("UNKNOWN_OBJECTIVE") == 1 and codes(spec).count("NO_OBJECTIVE") == 1


def test_brief_without_objectives_is_reported_once_not_per_requirement():
    spec = build_spec(
        raw(raw_fr("R1"), raw_fr("R2")),
        ProjectBrief(actual_problem="p", proposed_solution="s"),
        None,
    )
    assert codes(spec).count("BRIEF_HAS_NO_OBJECTIVES") == 1 and "NO_OBJECTIVE" not in codes(spec)


def test_unknown_finding_ids_are_dropped_and_reported():
    spec = build_spec(raw(raw_fr("R1", finding_ids=["F-001", "F-999", "F-001"])), BRIEF, REPORT)
    assert spec.functional[0].finding_ids == ["F-001"]
    assert codes(spec).count("UNKNOWN_FINDING") == 1


def test_external_dependency_without_valid_citation_is_an_error_needing_confirmation():
    spec = build_spec(
        raw(
            raw_fr("R1", depends_on_external_facts=True, finding_ids=["F-999"]),
            raw_fr("R2", depends_on_external_facts=True, finding_ids=["F-001"]),
        ),
        BRIEF,
        REPORT,
    )
    assert [f.needs_confirmation for f in spec.functional] == [True, False]
    bad = [i for i in spec.issues if i.code == "UNCITED_EXTERNAL_DEPENDENCY"]
    assert len(bad) == 1 and bad[0].ref == "FR-001" and bad[0].severity.value == "error"


def test_external_dependency_with_no_research_at_all():
    spec = build_spec(raw(raw_fr("R1", depends_on_external_facts=True)), BRIEF, None)
    assert "UNCITED_EXTERNAL_DEPENDENCY" in codes(spec)


def test_assumed_rules_become_assumptions_and_flag_the_requirement():
    rules = [
        {"statement": "Orders over $500 need approval", "basis": "assumption"},
        {"statement": "Users must log in", "basis": "stated"},
    ]
    spec = build_spec(
        raw(
            raw_fr("R1", business_rules=rules),
            raw_fr(
                "R2", business_rules=[rules[0] | {"statement": "orders over $500 need  approval"}]
            ),
        ),
        BRIEF,
        REPORT,
    )
    assert [f.needs_confirmation for f in spec.functional] == [True, True]
    assert len(spec.assumptions) == 1  # de-duplicated across requirements
    assert "needs confirmation" in spec.assumptions[0].basis
    assert [r.basis.value for r in spec.functional[0].business_rules] == ["assumption", "stated"]


def test_dependency_validation_self_unknown_and_mapping():
    spec = build_spec(
        raw(raw_fr("R1", depends_on=["R1", "R9", "R2", "R2"]), raw_fr("R2")), BRIEF, REPORT
    )
    assert spec.functional[0].dependencies == ["FR-002"]
    assert {"SELF_DEPENDENCY", "UNKNOWN_DEPENDENCY"} <= set(codes(spec))


def test_dependency_cycle_detected_as_error():
    spec = build_spec(
        raw(
            raw_fr("R1", depends_on=["R2"]),
            raw_fr("R2", depends_on=["R3"]),
            raw_fr("R3", depends_on=["R1"]),
        ),
        BRIEF,
        REPORT,
    )
    cyc = [i for i in spec.issues if i.code == "DEPENDENCY_CYCLE"]
    assert len(cyc) == 1 and cyc[0].severity.value == "error"
    assert "FR-001" in cyc[0].message and "FR-003" in cyc[0].message


def test_find_cycles_ignores_acyclic_diamond():
    assert _find_cycles({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}) == []


def test_stories_unknown_keys_dropped_orphans_removed_and_uncovered_reported():
    spec = build_spec(
        raw(
            raw_fr("R1"),
            raw_fr("R2"),
            stories=[
                {"actor": "a", "want": "w1", "benefit": "b", "requirement_keys": ["R1", "R9"]},
                {"actor": "a", "want": "w2", "benefit": "b", "requirement_keys": ["R9"]},
            ],
        ),
        BRIEF,
        REPORT,
    )
    assert [(s.id, s.requirement_ids) for s in spec.user_stories] == [("US-001", ["FR-001"])]
    c = codes(spec)
    assert "UNKNOWN_STORY_REQUIREMENT" in c and "ORPHAN_STORY_DROPPED" in c
    assert [i.ref for i in spec.issues if i.code == "FR_NO_STORY"] == ["FR-002"]


def test_nfr_targets_are_proposed_never_approved_and_measurability_checked():
    nfrs = [
        {"category": "performance", "statement": "s", "target": "p95 < 300ms", "rationale": "r"},
        {
            "category": "security",
            "statement": "s",
            "target": "  ",
            "rationale": "r",
            "measurement_method": "pen test",
        },
        {
            "category": "privacy",
            "statement": "s",
            "target": "x",
            "rationale": "r",
            "measurement_method": "audit",
        },
    ]
    spec = build_spec(raw(raw_fr("R1"), nfrs=nfrs), BRIEF, REPORT)
    assert [n.target_status for n in spec.nonfunctional] == [
        TargetStatus.PROPOSED,
        TargetStatus.NONE,
        TargetStatus.PROPOSED,
    ]
    assert spec.nonfunctional[1].target is None
    assert [i.ref for i in spec.issues if i.code == "UNMEASURABLE_TARGET"] == ["NFR-001"]


def test_missing_nfr_categories_reported_exactly():
    nfrs = [
        {"category": c.value, "statement": "s", "rationale": "r"}
        for c in NfrCategory
        if c not in (NfrCategory.ACCESSIBILITY, NfrCategory.DISASTER_RECOVERY)
    ]
    spec = build_spec(raw(raw_fr("R1"), nfrs=nfrs), BRIEF, REPORT)
    missing = [i.message for i in spec.issues if i.code == "MISSING_NFR_CATEGORY"]
    assert len(missing) == 2 and any("accessibility" in m for m in missing)
    assert any("disaster_recovery" in m for m in missing)


def test_model_cannot_smuggle_approval_or_ids_through_raw_schema():
    nfr = {
        "category": "performance",
        "statement": "s",
        "rationale": "r",
        "target": "1s",
        "target_status": "user_approved",
        "id": "NFR-777",
    }
    spec = build_spec(
        raw(raw_fr("R1", id="FR-777", needs_confirmation=False), nfrs=[nfr]), BRIEF, REPORT
    )
    assert spec.nonfunctional[0].id == "NFR-001"
    assert spec.nonfunctional[0].target_status is TargetStatus.PROPOSED
    assert spec.functional[0].id == "FR-001"


def test_raw_schema_rejects_bad_output():
    with pytest.raises(ValidationError):
        raw()  # no functional requirements
    with pytest.raises(ValidationError):
        raw(raw_fr("R1"), raw_fr("R1"))  # duplicate keys
    with pytest.raises(ValidationError):
        raw(raw_fr("R1", acceptance_criteria=[]))  # every FR needs acceptance criteria
    with pytest.raises(ValidationError):
        raw(raw_fr("one"))  # malformed key


def test_approve_nfr_targets_flow():
    nfrs = [
        {
            "category": "performance",
            "statement": "s",
            "target": "300ms",
            "rationale": "r",
            "measurement_method": "load test",
        },
        {"category": "security", "statement": "s", "rationale": "r"},
    ]
    spec = build_spec(raw(raw_fr("R1"), nfrs=nfrs), BRIEF, REPORT)
    approved = approve_nfr_targets(spec, ["NFR-001"])
    assert approved.nonfunctional[0].target_status is TargetStatus.USER_APPROVED
    assert spec.nonfunctional[0].target_status is TargetStatus.PROPOSED  # original untouched
    with pytest.raises(ValueError, match="unknown"):
        approve_nfr_targets(spec, ["NFR-009"])
    with pytest.raises(ValueError, match="no target"):
        approve_nfr_targets(spec, ["NFR-002"])


def test_prompt_loads_and_does_not_collide_with_clarification_routing():
    p = load_prompt("requirements")
    assert "UNTRUSTED" in p.system and "$findings" in p.user
    marker = "writing a software requirements specification"
    assert marker in p.system
    for other in ("clarification", "problem_understanding", "research_plan", "research_synthesis"):
        assert marker not in load_prompt(other).system

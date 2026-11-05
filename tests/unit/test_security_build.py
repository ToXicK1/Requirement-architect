import pytest
from pydantic import ValidationError

from requirements_architect.agent.stages.security import build_security, risk_level
from requirements_architect.schemas.security import (
    AI_THREATS,
    COMPLIANCE_STATEMENT,
    STRIDE,
    ControlArea,
    RawSecurityOutput,
    ThreatCategory,
)
from tests.design_helpers import make_reqs, raw_control, raw_security, raw_threat

REQS = make_reqs(2)


def build(**kw):
    return build_security(RawSecurityOutput.model_validate(raw_security(**kw)), REQS)


def codes(spec):
    return [i.code for i in spec.issues]


def test_threat_partition_is_exact():
    assert len(STRIDE) == 6 and len(AI_THREATS) == 8 and not (STRIDE & AI_THREATS)
    assert ThreatCategory.SPOOFING in STRIDE and ThreatCategory.PROMPT_INJECTION in AI_THREATS


@pytest.mark.parametrize(
    ("score", "level"),
    [(1, "low"), (2, "low"), (3, "medium"), (4, "medium"), (6, "high"), (9, "critical")],
)
def test_risk_level_bands(score, level):
    assert risk_level(score) == level


def test_scores_are_computed_by_code_from_likelihood_and_impact():
    spec = build(
        threats=[
            raw_threat("TH1", likelihood="high", impact="high"),
            raw_threat("TH2", likelihood="low", impact="high", control_keys=["SC1"]),
            raw_threat("TH3", likelihood="medium", impact="medium"),
        ]
    )
    assert [(t.id, t.risk_score, t.risk_level) for t in spec.threats] == [
        ("TH-001", 9, "critical"),
        ("TH-002", 3, "medium"),
        ("TH-003", 4, "medium"),
    ]


def test_model_cannot_supply_score_or_approval():
    spec = build(
        threats=[
            raw_threat("TH1", likelihood="low", impact="low", risk_score=9, requires_approval=True)
        ]
    )
    assert spec.threats[0].risk_score == 1 and spec.threats[0].requires_approval is False


def test_accepting_high_risk_needs_approval_and_critical_is_an_error():
    spec = build(
        threats=[
            raw_threat(
                "TH1", treatment="accept", likelihood="high", impact="medium", control_keys=[]
            ),
            raw_threat(
                "TH2", treatment="accept", likelihood="high", impact="high", control_keys=[]
            ),
            raw_threat("TH3", treatment="accept", likelihood="low", impact="low", control_keys=[]),
        ]
    )
    assert [t.requires_approval for t in spec.threats] == [True, True, False]
    assert [c.ref for c in spec.approval_candidates] == ["TH-001", "TH-002"]
    crit = [i for i in spec.issues if i.code == "ACCEPTED_CRITICAL_RISK"]
    assert [i.ref for i in crit] == ["TH-002"] and crit[0].severity.value == "error"
    assert "THREAT_NO_CONTROL" not in codes(spec)  # accepted threats need no control


def test_mitigated_threat_needs_a_valid_control():
    spec = build(
        threats=[raw_threat("TH1", control_keys=["SC9"]), raw_threat("TH2", control_keys=[])]
    )
    assert codes(spec).count("THREAT_NO_CONTROL") == 2 and "UNKNOWN_CONTROL" in codes(spec)
    transferred = build(threats=[raw_threat("TH1", treatment="transfer", control_keys=[])])
    assert "THREAT_NO_CONTROL" not in codes(transferred)


def test_orphan_controls_and_unknown_requirements():
    spec = build(
        controls=[raw_control("SC1", requirement_ids=["FR-001", "FR-999"]), raw_control("SC2")]
    )
    assert [i.ref for i in spec.issues if i.code == "ORPHAN_CONTROL"] == ["SC-002"]
    assert spec.controls[0].requirement_ids == ["FR-001"] and "UNKNOWN_REQUIREMENT" in codes(spec)


def test_control_area_coverage_depends_on_project_kind():
    plain = build()
    missing_plain = {
        i.message.split()[-1] for i in plain.issues if i.code == "MISSING_CONTROL_AREA"
    }
    assert "authorization" in missing_plain and "authentication" not in missing_plain
    assert not {"privacy", "retention", "backup", "ai_safety"} & missing_plain
    both = build(is_ai_project=True, handles_sensitive_data=True)
    missing_both = {i.message.split()[-1] for i in both.issues if i.code == "MISSING_CONTROL_AREA"}
    assert {"privacy", "retention", "backup", "ai_safety"} <= missing_both
    assert "PRIVACY_REQUIREMENTS_MISSING" in codes(both)
    assert "PRIVACY_REQUIREMENTS_MISSING" not in codes(
        build(handles_sensitive_data=True, privacy_requirements=["x"])
    )


def test_ai_threat_categories_required_only_for_ai_projects():
    plain = build()
    assert (
        "MISSING_AI_THREAT" not in codes(plain)
        and codes(plain).count("MISSING_STRIDE_CATEGORY") == 5
    )
    ai = build(
        is_ai_project=True,
        controls=[raw_control("SC1", area=a.value) for a in ControlArea][:1]
        + [raw_control(f"SC{i}", area=a.value) for i, a in enumerate(ControlArea, 2)],
        threats=[raw_threat("TH1", category="prompt_injection")],
    )
    assert codes(ai).count("MISSING_AI_THREAT") == 7
    assert "MISSING_CONTROL_AREA" not in codes(ai)


def test_test_plan_mapping_and_coverage():
    spec = build(
        controls=[raw_control("SC1"), raw_control("SC2", area="audit")],
        threats=[raw_threat("TH1", control_keys=["SC1", "SC2"])],
        test_plan=[
            {"name": "pen test", "method": "m", "control_keys": ["SC1", "SC9"]},
            {"name": "ghost", "method": "m", "control_keys": ["SC8"]},
        ],
    )
    assert [(t.name, t.control_ids) for t in spec.test_plan] == [("pen test", ["SC-001"])]
    assert "TEST_PLAN_ITEM_DROPPED" in codes(spec)
    assert [i.ref for i in spec.issues if i.code == "CONTROL_NO_TEST"] == ["SC-002"]


@pytest.mark.parametrize(
    "text",
    [
        "This makes us fully compliant with GDPR",
        "Guarantees compliance with HIPAA",
        "The platform is certified for SOC2",
        "will comply with PCI-DSS",
    ],
)
def test_compliance_claims_are_flagged_in_controls_and_threats(text):
    assert "COMPLIANCE_CLAIM" in codes(build(controls=[raw_control("SC1", description=text)]))
    assert "COMPLIANCE_CLAIM" in codes(build(threats=[raw_threat("TH1", residual_note=text)]))


def test_honest_framework_mapping_is_not_flagged_and_disclaimer_is_fixed():
    spec = build(
        controls=[
            raw_control(
                "SC1",
                description="Maps to OWASP ASVS V2 for password handling",
                framework_refs=["OWASP ASVS V2"],
            )
        ]
    )
    assert "COMPLIANCE_CLAIM" not in codes(spec)
    assert (
        spec.compliance_statement == COMPLIANCE_STATEMENT
        and "not a statement of compliance" in COMPLIANCE_STATEMENT
    )
    forged = RawSecurityOutput.model_validate(
        raw_security(compliance_statement="We are fully compliant")
    )
    assert build_security(forged, REQS).compliance_statement == COMPLIANCE_STATEMENT


def test_raw_schema_rejects_bad_input():
    for bad in (
        raw_security(threats=[]),
        raw_security(controls=[]),
        raw_security(threats=[raw_threat("TH1"), raw_threat("TH1")]),
        raw_security(controls=[raw_control("SC1"), raw_control("SC1")]),
        raw_security(threats=[raw_threat("TH1", likelihood="extreme")]),
        raw_security(threats=[raw_threat("TH1", category="gremlins")]),
    ):
        with pytest.raises(ValidationError):
            RawSecurityOutput.model_validate(bad)

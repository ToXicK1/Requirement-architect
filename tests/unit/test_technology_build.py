from requirements_architect.agent.stages.architecture import build_architecture
from requirements_architect.agent.stages.technology import build_technology
from requirements_architect.schemas.architecture import RawArchitecture
from requirements_architect.schemas.research import (
    AdvisoryRef,
    Finding,
    FindingKind,
    PackageFact,
    ResearchReport,
    VerificationStatus,
)
from requirements_architect.schemas.technology import ClaimStatus, RawTechnologyOutput
from tests.design_helpers import make_reqs, raw_arch, raw_comp, raw_tech

ARCH = build_architecture(
    RawArchitecture.model_validate(
        raw_arch(
            components=[
                raw_comp("C1"),
                raw_comp("C2", requirement_ids=["FR-002"]),
                raw_comp("C3", kind="external", requirement_ids=[]),
            ]
        )
    ),
    make_reqs(2),
)
REPORT = ResearchReport(
    findings=[
        Finding(
            finding_id="F-001",
            kind=FindingKind.FACT,
            claim="c",
            verification=VerificationStatus.VERIFIED,
            verification_note="n",
        ),
        Finding(
            finding_id="F-002",
            kind=FindingKind.ASSUMPTION,
            claim="c",
            verification=VerificationStatus.UNVERIFIED,
            verification_note="n",
        ),
    ],
    packages=[
        PackageFact(
            ecosystem="pypi",
            name="FastAPI",
            latest_version="0.115.0",
            license="MIT",
            registry_url="https://pypi.org/project/fastapi/",
            advisories=[AdvisoryRef(advisory_id="GHSA-x")],
            advisories_checked=True,
        ),
        PackageFact(
            ecosystem="pypi",
            name="httpx",
            latest_version=None,
            registry_url="https://pypi.org/project/httpx/",
        ),
    ],
)


def build(*techs, arch=ARCH, report=REPORT):
    return build_technology(
        RawTechnologyOutput.model_validate({"technologies": list(techs)}), arch, report
    )


def codes(spec):
    return [i.code for i in spec.issues]


def test_versions_and_licenses_are_compared_with_registry_never_trusted():
    pkg = {"ecosystem": "pypi", "name": "fastapi"}
    spec = build(
        raw_tech("T1", package=pkg, recommended_version="v0.115.0", license=" mit "),
        raw_tech("T2", name="B", package=pkg, recommended_version="0.99.0", license="Apache-2.0"),
        raw_tech("T3", name="C", package=pkg),
        raw_tech(
            "T4",
            name="D",
            package={"ecosystem": "pypi", "name": "httpx"},
            recommended_version="1.0",
        ),
        raw_tech("T5", name="E", recommended_version="3.12"),
    )
    got = [(t.version_status, t.license_status) for t in spec.technologies]
    assert got[0] == (ClaimStatus.CONFIRMED, ClaimStatus.CONFIRMED)  # v-prefix and case ignored
    assert got[1] == (ClaimStatus.DIFFERS, ClaimStatus.DIFFERS)
    assert got[2][0] is ClaimStatus.NOT_SPECIFIED
    assert got[3][0] is ClaimStatus.UNVERIFIED  # registry had no latest version
    assert got[4][0] is ClaimStatus.UNVERIFIED  # no package given: nothing to confirm against
    assert spec.technologies[1].registry_version == "0.115.0"
    assert {"VERSION_DIFFERS_FROM_REGISTRY", "LICENSE_DIFFERS_FROM_REGISTRY"} <= set(codes(spec))


def test_unresearched_package_flagged_and_advisories_carried_over():
    spec = build(
        raw_tech("T1", package={"ecosystem": "npm", "name": "left-pad"}),
        raw_tech("T2", name="B", package={"ecosystem": "pypi", "name": "fastapi"}),
    )
    assert "PACKAGE_NOT_RESEARCHED" in codes(spec)
    t = spec.technologies[1]
    assert [a.advisory_id for a in t.advisories] == ["GHSA-x"] and t.advisories_checked
    assert [i.ref for i in spec.issues if i.code == "KNOWN_ADVISORIES"] == ["TECH-002"]


def test_evidence_status_only_from_verified_findings():
    spec = build(
        raw_tech("T1", finding_ids=["F-001", "F-999"]),
        raw_tech("T2", name="B", finding_ids=["F-002"]),
        raw_tech("T3", name="C"),
    )
    assert [t.evidence for t in spec.technologies] == [
        "verified_finding",
        "unverified",
        "unverified",
    ]
    assert spec.technologies[0].finding_ids == ["F-001"] and "UNKNOWN_FINDING" in codes(spec)


def test_component_references_and_coverage():
    spec = build(raw_tech("T1", component_ids=["C-001", "C-099"]))
    assert spec.technologies[0].component_ids == ["C-001"]
    assert "UNKNOWN_COMPONENT" in codes(spec)
    # C-002 is internal and has no technology; C-003 is external and is exempt
    assert [i.ref for i in spec.issues if i.code == "COMPONENT_NO_TECHNOLOGY"] == ["C-002"]


def test_quality_checks_and_duplicates():
    spec = build(
        raw_tech("T1", alternatives=[], license=None), raw_tech("T2", name="tech t1", advantages=[])
    )
    c = codes(spec)
    assert {
        "TECH_NO_ALTERNATIVES",
        "LICENSE_UNKNOWN",
        "DUPLICATE_TECHNOLOGY",
        "TECH_NO_TRADEOFFS",
    } <= set(c)


def test_approval_candidates_for_lock_in_and_cost():
    spec = build(
        raw_tech("T1", vendor_lock_in="high"),
        raw_tech("T2", name="B", significant_cost=True),
        raw_tech("T3", name="C", vendor_lock_in="low"),
    )
    got = {c.ref: c.reason for c in spec.approval_candidates}
    assert got == {"TECH-001": "substantial vendor lock-in", "TECH-002": "significant cost"}


def test_works_without_architecture_or_research():
    spec = build(
        raw_tech("T1", component_ids=["C-001"], finding_ids=["F-001"]), arch=None, report=None
    )
    assert spec.technologies[0].component_ids == [] and spec.technologies[0].finding_ids == []

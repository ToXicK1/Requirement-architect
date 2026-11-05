from requirements_architect.audit.checks import run_checks
from requirements_architect.audit.engine import audit_deterministic
from requirements_architect.schemas.audit import AuditSeverity as Sev
from requirements_architect.schemas.audit import AuditThresholds, AuditVerdict
from requirements_architect.schemas.requirements import Severity, SpecIssue
from requirements_architect.schemas.state import StageId
from requirements_architect.schemas.technology import ClaimStatus
from tests.doc_helpers import make_specset


def codes(findings):
    return [f.code for f in findings]


def get(findings, code):
    return [f for f in findings if f.code == code]


def test_baseline_fixture_has_no_blockers_and_ids_are_dense_and_sorted():
    f = run_checks(make_specset())
    assert [x.id for x in f] == [f"AUD-{n:03d}" for n in range(1, len(f) + 1)]
    order = [list(Sev).index(x.severity) for x in f]
    assert order == sorted(order)
    assert not [x for x in f if x.severity is Sev.BLOCKER]


def test_audit_is_deterministic():
    assert run_checks(make_specset()) == run_checks(make_specset())


def test_stage_issues_are_passed_through_with_stage_and_fixability():
    s = make_specset()
    f = run_checks(s)
    miss = get(f, "STAGE_MISSING_NFR_CATEGORY")
    assert miss and all(
        x.stage is StageId.REQUIREMENTS and x.needs_human and not x.auto_fixable for x in miss
    )
    s.qa.issues.append(
        SpecIssue(code="DEPLOY_SECTION_EMPTY", severity=Severity.WARNING, message="m", ref="x")
    )
    d = get(run_checks(s), "STAGE_DEPLOY_SECTION_EMPTY")
    assert d and d[0].auto_fixable and d[0].stage is StageId.QA_DEPLOY


def test_builder_duplicate_of_independent_check_is_suppressed():
    s = make_specset()
    s.qa.test_cases = []
    s.qa.issues = []
    f = run_checks(s)
    assert get(f, "NO_TEST_CASES")[0].severity is Sev.BLOCKER
    assert not get(f, "STAGE_FR_NO_TEST")


def test_broken_references_are_found_in_every_spec():
    s = make_specset()
    s.architecture.components[0].requirement_ids.append("FR-099")
    s.architecture.components[0].depends_on.append("C-099")
    s.technology.technologies[0].component_ids.append("C-099")
    s.data_api.endpoints[0].entity_ids.append("E-099")
    s.security.threats[0].control_ids.append("SC-099")
    s.ux.screens[0].endpoint_ids.append("EP-099")
    s.qa.test_cases[0].requirement_ids.append("FR-099")
    s.requirements.functional[0].dependencies.append("FR-099")
    refs = {r for x in get(run_checks(s), "BROKEN_REFERENCE") for r in x.refs}
    assert {"FR-099", "C-099", "E-099", "SC-099", "EP-099"} <= refs
    stages = {x.stage for x in get(run_checks(s), "BROKEN_REFERENCE")}
    assert {
        StageId.ARCHITECTURE,
        StageId.TECHNOLOGY,
        StageId.DATA_API,
        StageId.SECURITY,
        StageId.UX,
        StageId.QA_DEPLOY,
        StageId.REQUIREMENTS,
    } <= stages


def test_requirement_without_component_or_test_is_major_and_auto_fixable():
    s = make_specset()
    s.architecture.components[1].requirement_ids = []
    s.qa.test_cases[0].requirement_ids = ["NFR-001"]
    f = run_checks(s)
    assert any(x.refs == ["FR-002"] and x.auto_fixable for x in get(f, "FR_NO_COMPONENT"))
    assert {r for x in get(f, "FR_NO_TEST") for r in x.refs} == {"FR-001", "FR-002"}
    assert get(f, "ORPHAN_ITEM")  # C-002 now serves nothing


def test_missing_acceptance_criteria_needs_a_human_not_regeneration():
    s = make_specset()
    s.requirements.functional[0].acceptance_criteria = []
    x = get(run_checks(s), "FR_NO_ACCEPTANCE_CRITERIA")[0]
    assert x.needs_human and not x.auto_fixable and x.stage is StageId.REQUIREMENTS


def test_duplicates_and_cycles():
    s = make_specset()
    s.architecture.components[1].name = s.architecture.components[0].name.upper()
    s.architecture.components[0].depends_on = ["C-002"]
    s.architecture.components[1].depends_on = ["C-001"]
    f = run_checks(s)
    assert get(f, "DUPLICATE_COMPONENT") and get(f, "COMPONENT_CYCLE")
    s2 = make_specset()
    s2.requirements.functional[0].dependencies = ["FR-002"]
    s2.requirements.functional[1].dependencies = ["FR-001"]
    assert get(run_checks(s2), "REQUIREMENT_CYCLE")


def test_diagram_inconsistency_is_detected():
    s = make_specset()
    s.architecture.component_diagram = 'flowchart LR\n    X["x"]'
    s.data_api.er_diagram = "erDiagram"
    f = run_checks(s)
    assert get(f, "DIAGRAM_MISSING_COMPONENT") and get(f, "DIAGRAM_MISSING_ENTITY")
    s.architecture.component_diagram = ""
    assert get(run_checks(s), "DIAGRAM_MISSING")


def test_security_gaps():
    s = make_specset()
    s.security.threats[0].risk_level = "high"
    s.security.threats[0].control_ids = []
    s.security.controls = []
    s.security.handles_sensitive_data = True
    s.security.is_ai_project = True
    s.data_api.endpoints[0].authentication = type(s.data_api.endpoints[0].authentication)("none")
    f = run_checks(s)
    for c in (
        "HIGH_RISK_NO_CONTROL",
        "NO_SECURITY_CONTROLS",
        "SENSITIVE_NO_PRIVACY",
        "AI_THREATS_MISSING",
        "NO_AUTH_CONTROL",
        "UNAUTHENTICATED_ENDPOINT",
    ):
        assert get(f, c), c
    assert get(f, "UNAUTHENTICATED_ENDPOINT")[0].severity is Sev.MAJOR
    s.security.handles_sensitive_data = False
    assert get(run_checks(s), "UNAUTHENTICATED_ENDPOINT")[0].severity is Sev.MINOR


def test_accepted_high_risk_requires_a_human():
    s = make_specset()
    t = s.security.threats[0]
    t.risk_level, t.treatment = "critical", type(t.treatment)("accept")
    x = get(run_checks(s), "HIGH_RISK_ACCEPTED")[0]
    assert x.needs_human and not x.auto_fixable


def test_compliance_claim_and_secret_detection():
    s = make_specset()
    s.security.controls[
        0
    ].description = "This control ensures compliance with GDPR and is certified"
    s.qa.deployment.secrets_management = "api_key = abcdef123456"
    f = run_checks(s)
    assert get(f, "UNSUPPORTED_COMPLIANCE_CLAIM")
    sec = get(f, "SECRET_IN_SPEC")[0]
    assert sec.severity is Sev.BLOCKER and sec.stage is StageId.QA_DEPLOY


def test_evidence_findings():
    s = make_specset()
    t = s.technology.technologies[0]
    t.recommended_version, t.version_status = "1.0", ClaimStatus.DIFFERS
    t.license_status = ClaimStatus.UNVERIFIED
    t.component_ids = []
    t.dependencies = ["Missing Lib"]
    f = run_checks(s)
    for c in (
        "TECH_VERSION_DIFFERS",
        "TECH_LICENSE_UNVERIFIED",
        "TECH_NOT_USED",
        "TECH_DEPENDENCY_NOT_IN_STACK",
        "NO_EXTERNAL_RESEARCH",
        "TECH_CHOICE_UNSUPPORTED",
    ):
        assert get(f, c), c
    assert get(f, "TECH_VERSION_DIFFERS")[0].needs_human


def test_assumptions_ambiguity_and_unapproved_targets():
    s = make_specset()
    s.requirements.functional[0].needs_confirmation = True
    s.requirements.functional[1].description = "The system must be fast and user-friendly, etc."
    s.requirements.nonfunctional[0].target = "p95 < 200ms"
    s.requirements.nonfunctional[0].target_status = type(
        s.requirements.nonfunctional[0].target_status
    )("proposed")
    s.brief.missing_information = ["budget"]
    f = run_checks(s)
    assert (
        get(f, "REQUIREMENTS_NEED_CONFIRMATION")
        and get(f, "MISSING_INFORMATION")
        and get(f, "NFR_TARGETS_UNAPPROVED")
    )
    vague = get(f, "VAGUE_WORDING")[0]
    assert vague.refs == ["FR-002"] and "fast" in vague.message and "etc" in vague.message


def test_unmeasured_nfr_and_uncovered_role():
    s = make_specset()
    s.brief.user_roles = ["Auditor"]
    f = run_checks(s)
    assert get(f, "NFR_NO_TARGET") and get(f, "ROLE_NOT_COVERED")


def test_objective_without_requirement_is_flagged():
    from requirements_architect.schemas.requirements import Objective

    s = make_specset()
    s.requirements.objectives.append(Objective(id="OBJ-001", text="Grow"))
    assert get(run_checks(s), "OBJECTIVE_NO_REQUIREMENT")


# ---- gates, verdict, tasks -------------------------------------------------------------


def test_clean_structure_is_ready_for_review_but_never_approved():
    s = make_specset()
    rep = audit_deterministic(s)
    assert rep.verdict is AuditVerdict.READY_FOR_REVIEW, [g for g in rep.gates if not g.passed]
    assert all(g.passed for g in rep.gates)
    assert any("human must still review" in x for x in rep.limitations)
    assert any("No independent LLM review" in x for x in rep.limitations)


def test_each_gate_can_fail_independently():
    base = make_specset()
    base.qa.test_cases = []  # blocker + traceability
    rep = audit_deterministic(base)
    failed = {g.name for g in rep.gates if not g.passed}
    assert {"no_blockers", "every_requirement_has_component_and_test"} <= failed
    assert rep.verdict is AuditVerdict.NOT_READY

    s = make_specset()
    s.qa.deployment.secrets_management = "token = abcdef123456"
    assert "no_secrets_in_specifications" in {
        g.name for g in audit_deterministic(s).gates if not g.passed
    }

    s = make_specset()
    s.security.threats[0].risk_level, s.security.threats[0].control_ids = "high", []
    assert "security_risks_addressed" in {
        g.name for g in audit_deterministic(s).gates if not g.passed
    }


def test_major_threshold_is_configurable():
    s = make_specset()
    s.requirements.functional[0].acceptance_criteria = []
    assert audit_deterministic(s).verdict is AuditVerdict.NOT_READY
    lenient = audit_deterministic(s, AuditThresholds(max_major=5))
    assert next(g for g in lenient.gates if g.name == "major_findings_within_limit").passed
    off = audit_deterministic(make_specset(), AuditThresholds(require_fr_component_and_test=False))
    assert next(g for g in off.gates if g.name.startswith("every_requirement")).passed


def test_remediation_tasks_split_auto_and_human_and_skip_info():
    s = make_specset()
    s.qa.test_cases[0].requirement_ids = ["NFR-001"]
    s.requirements.functional[0].acceptance_criteria = []
    rep = audit_deterministic(s)
    by_finding = {f.id: f for f in rep.findings}
    assert all(by_finding[t.finding_id].severity is not Sev.INFO for t in rep.tasks)
    owners = {by_finding[t.finding_id].code: t.owner for t in rep.tasks}
    assert owners["FR_NO_TEST"] == "auto" and owners["FR_NO_ACCEPTANCE_CRITERIA"] == "human"
    assert [t.id for t in rep.tasks] == [f"RT-{n:03d}" for n in range(1, len(rep.tasks) + 1)]


def test_stage_issue_duplicating_an_independent_check_is_not_reported_twice():
    s = make_specset()
    s.qa.test_cases = []
    s.qa.issues = [
        SpecIssue(code="FR_NO_TEST", severity=Severity.WARNING, message="m", ref="FR-001")
    ]
    f = run_checks(s)
    assert not get(f, "STAGE_FR_NO_TEST") and get(f, "FR_NO_TEST")


def test_only_design_stages_can_be_auto_fixable_even_if_asked():
    from requirements_architect.audit.checks import _f
    from requirements_architect.schemas.audit import AuditCategory

    f = _f(AuditCategory.COMPLETENESS, Sev.MAJOR, "X", "m", [], StageId.REQUIREMENTS, fix=True)
    assert not f.auto_fixable
    assert _f(
        AuditCategory.COMPLETENESS, Sev.MAJOR, "X", "m", [], StageId.QA_DEPLOY, fix=True
    ).auto_fixable


def test_a_finding_needing_a_human_is_never_assigned_to_auto_even_if_fixable():
    from requirements_architect.audit.engine import make_tasks
    from requirements_architect.schemas.audit import AuditCategory, AuditFinding

    f = AuditFinding(
        id="AUD-001",
        category=AuditCategory.COMPLETENESS,
        severity=Sev.MAJOR,
        code="X",
        message="m",
        stage=StageId.QA_DEPLOY,
        auto_fixable=True,
        needs_human=True,
    )
    assert make_tasks([f])[0].owner == "human"


def test_limits_come_from_settings():
    from requirements_architect.audit.service import AuditLimits
    from requirements_architect.core.config import Settings

    lim = AuditLimits.from_settings(
        Settings(
            audit_max_rounds=1, audit_max_stage_runs=4, audit_max_major=2, audit_llm_review=False
        )
    )
    assert (lim.max_rounds, lim.max_stage_runs, lim.llm_review, lim.thresholds.max_major) == (
        1,
        4,
        False,
        2,
    )

from requirements_architect.agent.stages.qa_deploy import build_qa
from requirements_architect.schemas.qa import RawQaOutput
from tests.design_helpers import make_reqs

REQS = make_reqs(2)  # FR-001, FR-002, NFR-001

FULL_DEPLOY = {
    "environments": [{"name": n, "purpose": "p"} for n in ("dev", "staging", "production")],
    **{
        k: "text"
        for k in (
            "containerization",
            "secrets_management",
            "migrations",
            "monitoring",
            "logging",
            "backups",
            "rollback",
            "recovery",
            "scaling",
        )
    },
}
STRATEGY = [{"test_type": t, "approach": "a"} for t in ("unit", "integration", "security", "api")]


def case(key="TC1", reqs=("FR-001",), **kw):
    base = {
        "key": key,
        "requirement_ids": list(reqs),
        "scenario": "scenario",
        "steps": ["s"],
        "expected_result": "ok",
        "priority": "must",
        "test_type": "unit",
    }
    return base | kw


def build(cases=None, deployment=None, strategy=STRATEGY, **kw):
    cases = cases or [case("TC1", ("FR-001",)), case("TC2", ("FR-002", "NFR-001"))]
    raw = RawQaOutput.model_validate(
        {
            "strategy": strategy,
            "test_cases": cases,
            "deployment": FULL_DEPLOY if deployment is None else deployment,
            **{k: v for k, v in kw.items() if k == "ai_evaluation"},
        }
    )
    flags = {k: v for k, v in kw.items() if k != "ai_evaluation"}
    return build_qa(raw, REQS, **flags)


def codes(spec):
    return [i.code for i in spec.issues]


def test_complete_plan_is_clean_and_gets_sequential_ids():
    spec = build(has_endpoints=True)
    assert spec.issues == []
    assert [c.id for c in spec.test_cases] == ["TC-001", "TC-002"]


def test_case_with_no_valid_requirement_is_dropped_and_ids_stay_dense():
    spec = build(
        [case("TC1", ("FR-099",)), case("TC2", ("FR-001", "FR-002", "NFR-001"))],
        has_endpoints=True,
    )
    assert [c.id for c in spec.test_cases] == ["TC-001"]
    assert "TEST_CASE_DROPPED" in codes(spec) and "UNKNOWN_REQUIREMENT" in codes(spec)


def test_unknown_requirement_ids_are_removed_from_kept_case():
    spec = build([case("TC1", ("FR-001", "FR-099")), case("TC2", ("FR-002", "NFR-001"))])
    assert spec.test_cases[0].requirement_ids == ["FR-001"]


def test_untested_requirements_are_reported_by_kind():
    spec = build([case("TC1", ("FR-001",))])
    by = {i.ref: i.code for i in spec.issues if i.code.endswith("_NO_TEST")}
    assert by == {"FR-002": "FR_NO_TEST", "NFR-001": "NFR_NO_TEST"}


def test_missing_strategy_types_depend_on_project_shape():
    base = [{"test_type": "unit", "approach": "a"}]
    spec = build(strategy=base, has_endpoints=True, has_ui=True, is_ai=True)
    missing = {i.message.split()[-1] for i in spec.issues if i.code == "MISSING_STRATEGY_TYPE"}
    assert {"integration", "security", "api", "accessibility", "ai_eval"} <= missing
    spec2 = build(strategy=base)
    missing2 = {i.message.split()[-1] for i in spec2.issues if i.code == "MISSING_STRATEGY_TYPE"}
    assert "api" not in missing2 and "accessibility" not in missing2


def test_ai_project_without_evaluation_plan_is_flagged_and_with_one_is_not():
    assert "AI_EVALUATION_MISSING" in codes(build(is_ai=True))
    assert "AI_EVALUATION_MISSING" not in codes(build(is_ai=True, ai_evaluation="golden set"))
    assert "AI_EVALUATION_MISSING" not in codes(build(is_ai=False))


def test_empty_deployment_reports_environments_and_sections():
    spec = build(deployment={})
    assert codes(spec).count("MISSING_ENVIRONMENT") == 3
    assert codes(spec).count("DEPLOY_SECTION_EMPTY") == 9


def test_secret_in_test_data_is_redacted_and_is_an_error():
    spec = build([case("TC1", ("FR-001", "FR-002", "NFR-001"), test_data=["token = abcdef123456"])])
    assert "abcdef123456" not in spec.model_dump_json()
    issue = next(i for i in spec.issues if i.code == "SECRET_IN_TEST_DATA")
    assert issue.severity.value == "error" and issue.ref == "TC-001"


def test_secret_in_deployment_text_ci_step_and_env_purpose_is_redacted():
    dep = FULL_DEPLOY | {
        "secrets_management": "api_key = zzzzzz999999",
        "ci_cd": ["deploy with Bearer abcdefghijklmnopqrstuvwx"],
        "environment_variables": [
            {"name": "DB_URL", "purpose": "password: topsecret1", "secret": True}
        ],
    }
    spec = build(deployment=dep)
    dumped = spec.model_dump_json()
    for leaked in ("zzzzzz999999", "abcdefghijklmnopqrstuvwx", "topsecret1"):
        assert leaked not in dumped
    assert codes(spec).count("SECRET_IN_DEPLOYMENT") == 3


def test_duplicate_env_var_is_flagged():
    dep = FULL_DEPLOY | {
        "environment_variables": [
            {"name": "A", "purpose": "p"},
            {"name": "A", "purpose": "q"},
        ]
    }
    assert "DUPLICATE_ENV_VAR" in codes(build(deployment=dep))


def test_env_var_cannot_carry_a_value():
    from pydantic import ValidationError

    from requirements_architect.schemas.qa import EnvVar

    assert "value" not in EnvVar.model_fields
    try:
        EnvVar.model_validate({"name": "A", "purpose": "p", "value": "x"})
    except ValidationError:
        return
    assert not hasattr(EnvVar.model_validate({"name": "A", "purpose": "p", "value": "x"}), "value")

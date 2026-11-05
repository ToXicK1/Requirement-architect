from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable
from requirements_architect.schemas.qa import QaCase, QaType


def _case(c: QaCase) -> str:
    return md.join(
        md.section(f"{c.id} - {c.scenario}", level=3),
        f"**Type:** {c.test_type.value}; **priority:** {c.priority.value}; **requirements:** {', '.join(c.requirement_ids)}",
        "**Preconditions:**\n\n" + (md.bullets(c.preconditions) or "none"),
        "**Test data:**\n\n" + (md.bullets(c.test_data) or "none"),
        "**Steps:**\n\n" + md.numbered(c.steps),
        f"**Expected result:** {md.text(c.expected_result)}",
        f"**Pass criteria:** {md.text(c.execution_criteria or 'all steps produce the expected result')}",
    )


def render(i: DocInputs) -> list[Doc]:
    q = i.qa
    strategy = md.join(
        md.table(
            ["Test type", "Approach", "Tools"],
            [(s.test_type.value, s.approach, ", ".join(s.tools) or "-") for s in q.strategy],
        )
        or "No strategy was produced.",
        md.section(
            "Cases by type",
            md.table(
                ["Type", "Cases"],
                [
                    (t.value, sum(1 for c in q.test_cases if c.test_type is t))
                    for t in QaType
                    if any(c.test_type is t for c in q.test_cases)
                ],
            ),
        ),
    )
    cases = (
        md.join(*[_case(c) for c in q.test_cases])
        if q.test_cases
        else "No test cases were produced.\n"
    )
    perf = [c for c in q.test_cases if c.test_type in (QaType.PERFORMANCE, QaType.STRESS)]
    perf_nfrs = [n for n in i.requirements.nonfunctional if n.category.value == "performance"]
    docs = [
        Doc("07_QUALITY_ASSURANCE/TEST_STRATEGY.md", "Test Strategy", strategy),
        Doc("07_QUALITY_ASSURANCE/TEST_CASES.md", "Test Cases", cases),
    ]
    if perf or perf_nfrs:
        docs.append(
            Doc(
                "07_QUALITY_ASSURANCE/PERFORMANCE_TESTING.md",
                "Performance Testing",
                md.join(
                    md.section(
                        "Performance requirements",
                        md.table(
                            ["ID", "Requirement", "Target", "Target status"],
                            [
                                (
                                    n.id,
                                    n.statement,
                                    n.target or "not defined",
                                    n.target_status.value,
                                )
                                for n in perf_nfrs
                            ],
                        )
                        or "None.",
                    ),
                    md.section(
                        "Performance and stress test cases",
                        md.join(*[_case(c) for c in perf])
                        if perf
                        else "No performance test cases were produced; this is a gap.",
                    ),
                ),
            )
        )
    else:
        docs.append(
            not_applicable(
                "07_QUALITY_ASSURANCE/PERFORMANCE_TESTING.md",
                "Performance Testing",
                "No performance requirements or performance test cases exist.",
            )
        )
    docs.append(
        Doc(
            "07_QUALITY_ASSURANCE/AI_EVALUATION.md",
            "AI Evaluation",
            md.text(q.ai_evaluation or "No AI evaluation plan was produced; this is a gap."),
        )
        if i.security.is_ai_project
        else not_applicable(
            "07_QUALITY_ASSURANCE/AI_EVALUATION.md",
            "AI Evaluation",
            "The project is not classified as an AI project.",
        )
    )
    return docs


def render_infra(i: DocInputs) -> list[Doc]:
    d = i.qa.deployment

    def para(title: str, value: str) -> str:
        return md.section(title, md.text(value) if value.strip() else "Not specified.")

    deploy = md.join(
        md.section(
            "Environments",
            md.table(
                ["Environment", "Purpose", "Notes"],
                [(e.name, e.purpose, e.notes or "-") for e in d.environments],
            )
            or "None specified.",
        ),
        para("Containerization", d.containerization),
        para("Database migrations", d.migrations),
        para("Rollback", d.rollback),
        para("Recovery", d.recovery),
        para("Backups", d.backups),
        para("Scaling", d.scaling),
    )
    devops = md.join(
        md.section("CI/CD", md.numbered(d.ci_cd) or "Not specified."),
        para("Secrets management", d.secrets_management),
        md.section(
            "Environment variables",
            md.table(
                ["Name", "Purpose", "Secret", "Required"],
                [
                    (v.name, v.purpose, "yes" if v.secret else "no", "yes" if v.required else "no")
                    for v in d.environment_variables
                ],
            )
            or "None specified.",
            "This list contains names and purposes only. No values are recorded in this documentation.",
        ),
    )
    mon = md.join(para("Monitoring", d.monitoring), para("Logging", d.logging))
    return [
        Doc("08_INFRASTRUCTURE/DEPLOYMENT_PLAN.md", "Deployment Plan", deploy),
        Doc("08_INFRASTRUCTURE/DEVOPS_REQUIREMENTS.md", "DevOps Requirements", devops),
        Doc("08_INFRASTRUCTURE/MONITORING.md", "Monitoring and Logging", mon),
    ]

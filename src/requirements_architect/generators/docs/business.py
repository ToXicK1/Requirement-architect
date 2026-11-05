from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable


def render(i: DocInputs) -> list[Doc]:
    r, b = i.requirements, i.brief
    brd = md.join(
        md.section(
            "Business objectives",
            md.table(["ID", "Objective"], [(o.id, o.text) for o in r.objectives])
            or "No objectives were recorded.",
        ),
        md.section("Expected outcomes", md.bullets(b.expected_outcomes) or "Not stated."),
        md.section(
            "Objective coverage",
            md.table(
                ["Objective", "Functional requirements"],
                [
                    (
                        o.id,
                        ", ".join(f.id for f in r.functional if f.objective_id == o.id) or "none",
                    )
                    for o in r.objectives
                ],
            )
            or "No objectives to cover.",
        ),
    )
    people = [*b.stakeholders]
    stake = (
        md.join(
            md.section("Stakeholders", md.bullets(people)),
            md.section("Target users", md.bullets(b.target_users) or "Not stated."),
            md.section("User roles", md.bullets(b.user_roles) or "Not stated."),
        )
        if people
        else None
    )
    rules = [
        (f.id, rule.statement, rule.basis.value) for f in r.functional for rule in f.business_rules
    ]
    docs = [Doc("01_BUSINESS_REQUIREMENTS/BRD.md", "Business Requirements", brd)]
    docs.append(
        Doc("01_BUSINESS_REQUIREMENTS/STAKEHOLDERS.md", "Stakeholders", stake)
        if stake
        else not_applicable(
            "01_BUSINESS_REQUIREMENTS/STAKEHOLDERS.md",
            "Stakeholders",
            "No stakeholders were stated or established during clarification. "
            "This should be confirmed with the project owner.",
        )
    )
    docs.append(
        Doc(
            "01_BUSINESS_REQUIREMENTS/BUSINESS_RULES.md",
            "Business Rules",
            md.join(
                md.table(["Requirement", "Rule", "Basis"], rules),
                "Rules with basis `assumption` were inferred and must be confirmed.",
            ),
        )
        if rules
        else not_applicable(
            "01_BUSINESS_REQUIREMENTS/BUSINESS_RULES.md",
            "Business Rules",
            "No business rules were stated or inferred for any requirement.",
        )
    )
    return docs

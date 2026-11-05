from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs


def render(i: DocInputs) -> list[Doc]:
    b = i.brief
    brief = md.join(
        md.section("Problem", md.text(b.actual_problem)),
        md.section("Proposed solution", md.text(b.proposed_solution)),
        md.section("Business objectives", md.bullets(b.business_objectives) or "None stated."),
        md.section("Target users", md.bullets(b.target_users) or "None stated."),
        md.section("User roles", md.bullets(b.user_roles) or "None stated."),
        md.section("Main workflows", md.bullets(b.main_workflows) or "None stated."),
        md.section("Constraints", md.bullets(b.constraints) or "None stated."),
        md.section("Expected outcomes", md.bullets(b.expected_outcomes) or "None stated."),
    )
    problem = md.join(
        md.section(
            "Original problem statement (as submitted by the user)",
            "\n".join(f"> {line}" if line.strip() else ">" for line in _lines(i.problem_statement)),
        ),
        md.section("Understood problem", md.text(b.actual_problem)),
    )
    scope = md.join(
        md.section("In scope", md.bullets(b.in_scope) or "Not stated."),
        md.section("Out of scope", md.bullets(b.out_of_scope) or "Not stated."),
    )
    assumptions = [*b.assumptions, *i.requirements.assumptions]
    seen: set[str] = set()
    rows = []
    for a in assumptions:
        if a.statement not in seen:
            seen.add(a.statement)
            rows.append((a.statement, a.basis))
    assume = md.join(
        md.section(
            "Assumptions",
            md.table(["Assumption", "Basis"], rows) or "No assumptions were recorded.",
        ),
        md.section(
            "Information still missing", md.bullets(b.missing_information) or "None recorded."
        ),
    )
    glossary = md.join(
        md.section(
            "Identifier conventions",
            md.table(
                ["Prefix", "Meaning"],
                [
                    ("OBJ-", "Business objective"),
                    ("FR- / NFR-", "Functional / non-functional requirement"),
                    ("US-", "User story"),
                    ("C-", "Architecture component"),
                    ("AD-", "Architecture decision"),
                    ("TECH-", "Technology choice"),
                    ("E- / EP-", "Data entity / API endpoint"),
                    ("SC- / TH-", "Security control / threat"),
                    ("SCR- / FL-", "Screen / user flow"),
                    ("TC-", "Test case"),
                    ("T-", "Implementation task"),
                    ("F- / S-", "Research finding / source"),
                ],
            ),
        ),
        md.section(
            "Statuses",
            md.table(
                ["Term", "Meaning"],
                [
                    ("proposed", "Suggested by the system; no human has approved it."),
                    ("user_approved", "Explicitly approved by a person."),
                    ("assumption", "Not stated by the user; inferred and needs confirmation."),
                    ("verified", "A quoted passage was found in the retrieved source text."),
                    ("unverified", "No evidence was found; the claim may still be true."),
                ],
            ),
        ),
    )
    return [
        Doc("00_PROJECT_OVERVIEW/PROJECT_BRIEF.md", "Project Brief", brief),
        Doc("00_PROJECT_OVERVIEW/PROBLEM_STATEMENT.md", "Problem Statement", problem),
        Doc("00_PROJECT_OVERVIEW/PROJECT_SCOPE.md", "Project Scope", scope),
        Doc("00_PROJECT_OVERVIEW/ASSUMPTIONS.md", "Assumptions", assume),
        Doc("00_PROJECT_OVERVIEW/GLOSSARY.md", "Glossary and Conventions", glossary),
    ]


def _lines(s: str) -> list[str]:
    return [" ".join(x.split()).replace("<", "&lt;").replace(">", "&gt;") for x in s.splitlines()]

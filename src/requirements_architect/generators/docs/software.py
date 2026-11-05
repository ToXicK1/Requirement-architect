from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs
from requirements_architect.schemas.requirements import FunctionalRequirement, Severity


def _fr(f: FunctionalRequirement) -> str:
    rows = [
        ("Priority", f.priority.value),
        ("Actor", f.actor),
        ("Objective", f.objective_id or "none"),
        ("Trigger", f.trigger),
        ("Validation method", f.validation_method.value),
        ("Depends on", ", ".join(f.dependencies) or "none"),
        ("Research findings", ", ".join(f.finding_ids) or "none"),
        ("Needs confirmation", "yes" if f.needs_confirmation else "no"),
    ]
    return md.join(
        md.section(f"{f.id} - {f.name}", md.text(f.description), level=2),
        md.table(["Field", "Value"], rows),
        f"**Justification:** {md.text(f.justification)}",
        f"**Expected behavior:** {md.text(f.expected_behavior)}",
        _list("Preconditions", f.preconditions),
        _list("Inputs", f.inputs),
        _list("Outputs", f.outputs),
        _list("Failure scenarios", f.failure_scenarios),
    )


def _list(title: str, items: list[str]) -> str:
    return f"**{title}:**\n\n{md.bullets(items)}" if items else ""


def render(i: DocInputs) -> list[Doc]:
    r = i.requirements
    errors = [x for x in r.issues if x.severity is Severity.ERROR]
    warns = [x for x in r.issues if x.severity is Severity.WARNING]
    srs = md.join(
        md.section(
            "Overview",
            f"This specification contains {len(r.functional)} functional and "
            f"{len(r.nonfunctional)} non-functional requirements, {len(r.user_stories)} user "
            f"stories and {len(r.objectives)} business objectives.",
        ),
        md.section(
            "Open issues in this specification",
            md.table(
                ["Severity", "Code", "Reference", "Message"],
                [(x.severity.value, x.code, x.ref or "-", x.message) for x in [*errors, *warns]],
            )
            or "None recorded.",
        ),
        md.section(
            "Requirements needing confirmation",
            md.bullets(f"{f.id} - {f.name}" for f in r.functional if f.needs_confirmation)
            or "None.",
        ),
        md.section(
            "Document map",
            md.bullets(
                [
                    "FUNCTIONAL_REQUIREMENTS.md - detailed functional requirements",
                    "NON_FUNCTIONAL_REQUIREMENTS.md - quality attributes and targets",
                    "USER_STORIES.md - stories linked to requirements",
                    "ACCEPTANCE_CRITERIA.md - Given/When/Then criteria",
                ]
            ),
        ),
    )
    fr_doc = (
        md.join(*[_fr(f) for f in r.functional])
        if r.functional
        else "No functional requirements were produced.\n"
    )
    nfr = md.join(
        md.table(
            [
                "ID",
                "Category",
                "Requirement",
                "Target",
                "Target status",
                "Measurement",
                "Rationale",
            ],
            [
                (
                    n.id,
                    n.category.value,
                    n.statement,
                    n.target or "not defined",
                    n.target_status.value,
                    n.measurement_method or "-",
                    n.rationale,
                )
                for n in r.nonfunctional
            ],
        )
        or "No non-functional requirements were produced.",
        "Targets with status `proposed` were suggested by the system and are **not** approved.",
    )
    stories = md.join(
        md.table(
            ["ID", "As a", "I want", "So that", "Requirements"],
            [
                (s.id, s.actor, s.want, s.benefit, ", ".join(s.requirement_ids))
                for s in r.user_stories
            ],
        )
        or "No user stories were produced."
    )
    ac = (
        md.join(
            *[
                md.join(
                    md.section(f"{f.id} - {f.name}", level=3),
                    md.table(
                        ["Given", "When", "Then"],
                        [(c.given, c.when, c.then) for c in f.acceptance_criteria],
                    ),
                )
                for f in r.functional
                if f.acceptance_criteria
            ]
        )
        or "No acceptance criteria were produced.\n"
    )
    return [
        Doc("02_SOFTWARE_REQUIREMENTS/SRS.md", "Software Requirements Specification", srs),
        Doc(
            "02_SOFTWARE_REQUIREMENTS/FUNCTIONAL_REQUIREMENTS.md", "Functional Requirements", fr_doc
        ),
        Doc(
            "02_SOFTWARE_REQUIREMENTS/NON_FUNCTIONAL_REQUIREMENTS.md",
            "Non-Functional Requirements",
            nfr,
        ),
        Doc("02_SOFTWARE_REQUIREMENTS/USER_STORIES.md", "User Stories", stories),
        Doc("02_SOFTWARE_REQUIREMENTS/ACCEPTANCE_CRITERIA.md", "Acceptance Criteria", ac),
    ]

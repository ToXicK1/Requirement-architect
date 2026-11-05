from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable


def render(i: DocInputs) -> list[Doc]:
    u = i.ux
    if not u.has_ui:
        why = u.interface_note or "The project has no user interface."
        return [
            not_applicable("06_UI_UX/USER_FLOWS.md", "User Flows", why),
            not_applicable("06_UI_UX/SCREEN_SPECIFICATIONS.md", "Screen Specifications", why),
            not_applicable("06_UI_UX/DESIGN_SYSTEM.md", "Design System", why),
        ]
    flows = md.join(
        md.section(
            "Personas",
            md.table(
                ["Persona", "Description", "Goals"],
                [(p.name, p.description, "; ".join(p.goals)) for p in u.personas],
            )
            or "None recorded.",
        ),
        *[
            md.join(
                md.section(f"{f.id} - {f.name}", f"**Actor:** {md.text(f.actor)}", level=2),
                md.numbered(f.steps),
                f"**Requirements:** {', '.join(f.requirement_ids) or 'none'}",
            )
            for f in u.flows
        ],
        md.section("Navigation", md.bullets(u.navigation) or "Not specified."),
    )
    screens = (
        md.join(
            *[
                md.join(
                    md.section(f"{s.id} - {s.name}", md.text(s.purpose), level=2),
                    md.table(
                        ["State", "Description"], [(x.state.value, x.description) for x in s.states]
                    ),
                    "**Inputs:**\n\n" + (md.bullets(s.inputs) or "none"),
                    "**Outputs:**\n\n" + (md.bullets(s.outputs) or "none"),
                    f"**Responsive behavior:** {md.text(s.responsive or 'not specified')}",
                    "**Accessibility:**\n\n" + (md.bullets(s.accessibility) or "none recorded"),
                    f"**Requirements:** {', '.join(s.requirement_ids) or 'none'}; **endpoints:** {', '.join(s.endpoint_ids) or 'none'}",
                )
                for s in u.screens
            ]
        )
        or "No screens were produced.\n"
    )
    ds = md.join(
        md.section("Design system", md.bullets(u.design_system) or "Not specified."),
        md.section(
            "Accessibility requirements",
            md.bullets(u.accessibility_requirements) or "Not specified.",
        ),
    )
    return [
        Doc("06_UI_UX/USER_FLOWS.md", "User Flows", flows),
        Doc("06_UI_UX/SCREEN_SPECIFICATIONS.md", "Screen Specifications", screens),
        Doc("06_UI_UX/DESIGN_SYSTEM.md", "Design System", ds),
    ]

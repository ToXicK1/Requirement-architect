from __future__ import annotations

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.model import Doc, DocInputs, not_applicable


def render(i: DocInputs) -> list[Doc]:
    s = i.security
    disclaimer = md.text(s.compliance_statement)
    reqs = md.join(
        md.section("Attack surface", md.bullets(s.attack_surface) or "Not recorded."),
        md.section(
            "Security controls",
            md.table(
                ["ID", "Name", "Area", "Description", "Requirements", "Framework references"],
                [
                    (
                        c.id,
                        c.name,
                        c.area.value,
                        c.description,
                        ", ".join(c.requirement_ids) or "-",
                        ", ".join(c.framework_refs) or "-",
                    )
                    for c in s.controls
                ],
            )
            or "No controls were produced.",
        ),
        md.section("Compliance note", disclaimer),
    )
    ctl_names = {c.id: c.name for c in s.controls}
    threats = md.join(
        md.table(
            [
                "ID",
                "Threat",
                "STRIDE / AI category",
                "Asset",
                "Likelihood",
                "Impact",
                "Score",
                "Risk",
                "Treatment",
                "Controls",
                "Needs approval",
            ],
            [
                (
                    t.id,
                    t.title,
                    t.category.value,
                    t.asset,
                    t.likelihood.value,
                    t.impact.value,
                    t.risk_score,
                    t.risk_level,
                    t.treatment.value,
                    ", ".join(f"{c} ({ctl_names.get(c, '?')})" for c in t.control_ids) or "none",
                    "yes" if t.requires_approval else "no",
                )
                for t in s.threats
            ],
        )
        or "No threats were produced.",
        "Risk score and level are computed from likelihood and impact by fixed rules, not by the model.",
        *[
            md.join(
                md.section(f"{t.id} - {t.title}", md.text(t.description), level=3),
                f"**Residual risk:** {md.text(t.residual_note or 'not recorded')}",
            )
            for t in s.threats
        ],
        md.section("Compliance note", disclaimer),
    )
    docs = [
        Doc("05_SECURITY/SECURITY_REQUIREMENTS.md", "Security Requirements", reqs),
        Doc("05_SECURITY/THREAT_MODEL.md", "Threat Model", threats),
    ]
    docs.append(
        Doc(
            "05_SECURITY/PRIVACY_REQUIREMENTS.md",
            "Privacy Requirements",
            md.join(md.bullets(s.privacy_requirements), md.section("Compliance note", disclaimer)),
        )
        if s.privacy_requirements
        else not_applicable(
            "05_SECURITY/PRIVACY_REQUIREMENTS.md",
            "Privacy Requirements",
            "The analysis recorded no privacy requirements"
            + (
                ""
                if s.handles_sensitive_data
                else " and the project is not marked as handling sensitive data"
            )
            + ". This should be confirmed.",
        )
    )
    docs.append(
        Doc(
            "05_SECURITY/SECURITY_TEST_PLAN.md",
            "Security Test Plan",
            md.table(
                ["Test", "Method", "Controls"],
                [(t.name, t.method, ", ".join(t.control_ids) or "-") for t in s.test_plan],
            ),
        )
        if s.test_plan
        else not_applicable(
            "05_SECURITY/SECURITY_TEST_PLAN.md",
            "Security Test Plan",
            "No security tests were planned.",
        )
    )
    return docs

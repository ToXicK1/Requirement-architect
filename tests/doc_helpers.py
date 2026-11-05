"""Builds a realistic DocInputs from the stage builders. Test-only."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from requirements_architect.agent.stages.architecture import build_architecture
from requirements_architect.agent.stages.dataapi import build_data_api
from requirements_architect.agent.stages.qa_deploy import build_qa
from requirements_architect.agent.stages.security import build_security
from requirements_architect.agent.stages.technology import build_technology
from requirements_architect.agent.stages.ux import build_ux
from requirements_architect.generators.docs.model import DocInputs
from requirements_architect.schemas.architecture import RawArchitecture
from requirements_architect.schemas.dataapi import RawDataApi
from requirements_architect.schemas.qa import RawQaOutput
from requirements_architect.schemas.requirements import RequirementsSpec
from requirements_architect.schemas.security import RawSecurityOutput
from requirements_architect.schemas.state import ProjectBrief
from requirements_architect.schemas.technology import RawTechnologyOutput
from requirements_architect.schemas.ux import RawUx
from tests.design_helpers import (
    make_reqs,
    raw_arch,
    raw_comp,
    raw_endpoint,
    raw_entity,
    raw_security,
    raw_tech,
)

FULL_DEPLOY: dict[str, Any] = {
    "environments": [{"name": n, "purpose": "p"} for n in ("dev", "staging", "production")],
    **{
        k: f"{k} text"
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
    "ci_cd": ["lint", "test"],
    "environment_variables": [{"name": "DATABASE_URL", "purpose": "db", "secret": True}],
}


def make_inputs(
    reqs: RequirementsSpec | None = None,
    *,
    ux: dict[str, Any] | None = None,
    security: dict[str, Any] | None = None,
    entities: bool = True,
    endpoints: bool = True,
    name: str = "Demo project",
    statement: str = "We need a thing.",
    brief: ProjectBrief | None = None,
) -> DocInputs:
    reqs = reqs or make_reqs(2)
    arch = build_architecture(
        RawArchitecture.model_validate(
            raw_arch(
                components=[
                    raw_comp("C1"),
                    raw_comp("C2", requirement_ids=["FR-002"], depends_on=["C1"]),
                ]
            )
        ),
        reqs,
    )
    tech = build_technology(
        RawTechnologyOutput.model_validate({"technologies": [raw_tech("T1")]}), arch, None
    )
    api = build_data_api(
        RawDataApi.model_validate(
            {
                "entities": [raw_entity()] if entities else [],
                "endpoints": [raw_endpoint()] if endpoints else [],
                "interface_note": "" if entities and endpoints else "No database or API.",
            }
        ),
        reqs,
    )
    sec = build_security(RawSecurityOutput.model_validate(raw_security(**(security or {}))), reqs)
    uxs = build_ux(
        RawUx.model_validate(
            ux
            or {
                "has_ui": True,
                "personas": [{"name": "Ann", "description": "d"}],
                "screens": [
                    {
                        "key": "S1",
                        "name": "Home",
                        "purpose": "p",
                        "states": [
                            {"state": s, "description": "d"}
                            for s in ("loading", "error", "empty", "populated")
                        ],
                        "accessibility": ["keyboard"],
                        "requirement_ids": ["FR-001"],
                        "endpoint_ids": ["EP-001"],
                    }
                ],
            }
        ),
        reqs,
        api,
    )
    qa = build_qa(
        RawQaOutput.model_validate(
            {
                "strategy": [
                    {"test_type": t, "approach": "a"} for t in ("unit", "integration", "security")
                ],
                "test_cases": [
                    {
                        "key": "TC1",
                        "requirement_ids": ["FR-001", "FR-002", "NFR-001"],
                        "scenario": "works",
                        "steps": ["do"],
                        "expected_result": "ok",
                        "priority": "must",
                        "test_type": "unit",
                    }
                ],
                "deployment": FULL_DEPLOY,
            }
        ),
        reqs,
    )
    return DocInputs(
        project_id="11111111-2222-3333-4444-555555555555",
        project_name=name,
        problem_statement=statement,
        brief=brief or ProjectBrief(actual_problem="p", proposed_solution="s"),
        requirements=reqs,
        architecture=arch,
        technology=tech,
        data_api=api,
        security=sec,
        ux=uxs,
        qa=qa,
        research=None,
        package_version=1,
        generated_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
    )

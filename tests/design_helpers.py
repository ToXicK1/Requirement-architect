"""Builders for design-stage tests. Test-only."""

from __future__ import annotations

from typing import Any

from requirements_architect.agent.stages.requirements import build_spec
from requirements_architect.schemas.requirements import RawRequirementsOutput, RequirementsSpec
from requirements_architect.schemas.state import ProjectBrief
from tests.conftest import raw_fr


def make_reqs(n: int = 2, actor: str = "user") -> RequirementsSpec:
    frs = [raw_fr(f"R{i}", actor=actor) for i in range(1, n + 1)]
    nfr = [{"category": "security", "statement": "s", "rationale": "r"}]
    raw = RawRequirementsOutput.model_validate(
        {
            "functional": frs,
            "nonfunctional": nfr,
            "user_stories": [
                {
                    "actor": "a",
                    "want": "w",
                    "benefit": "b",
                    "requirement_keys": [f"R{i}" for i in range(1, n + 1)],
                }
            ],
        }
    )
    return build_spec(raw, ProjectBrief(actual_problem="p", proposed_solution="s"), None)


def raw_comp(key: str = "C1", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "name": f"Comp {key}",
        "kind": "module",
        "responsibility": "does a thing",
        "requirement_ids": ["FR-001"],
    }
    return base | kw


def raw_arch(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "selected_pattern": "modular_monolith",
        "pattern_evaluations": [
            {"pattern": "modular_monolith", "suitable": True, "rationale": "simple"},
            {"pattern": "microservices", "suitable": False, "rationale": "overkill"},
        ],
        "components": [raw_comp("C1")],
    }
    return base | kw


def raw_tech(key: str = "T1", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "name": f"Tech {key}",
        "category": "backend",
        "purpose": "p",
        "reason": "r",
        "alternatives": ["alt"],
        "advantages": ["a"],
        "disadvantages": ["d"],
        "license": "MIT",
        "component_ids": ["C-001"],
    }
    return base | kw


def raw_entity(key: str = "E1", name: str = "users", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "name": name,
        "description": "d",
        "fields": [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "email", "type": "text"},
        ],
        "requirement_ids": ["FR-001"],
    }
    return base | kw


def raw_endpoint(key: str = "EP1", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "method": "GET",
        "path": "/users",
        "purpose": "list users",
        "authentication": "bearer",
        "authorization": "admin only",
        "error_responses": [{"status": 401, "meaning": "no token"}],
        "requirement_ids": ["FR-001"],
        "entity_keys": ["E1"],
    }
    return base | kw

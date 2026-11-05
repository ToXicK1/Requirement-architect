from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from requirements_architect.agent.service import WorkflowService
from requirements_architect.agent.workflow import build_workflow
from requirements_architect.llm.gateway import LLMGateway, RetryPolicy, Target
from requirements_architect.llm.types import LLMRequest
from requirements_architect.llm.usage import UsageTracker
from requirements_architect.research.service import ResearchService
from requirements_architect.storage.database import Base, make_engine, make_session_factory
from requirements_architect.storage.repository import Repository
from tests.fakes import FakeProvider

BRIEF = {"actual_problem": "slow onboarding", "proposed_solution": "an onboarding app"}


def raw_fr(key: str = "R1", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "name": f"Requirement {key}",
        "description": "d",
        "justification": "j",
        "objective": None,
        "actor": "user",
        "trigger": "t",
        "expected_behavior": "b",
        "priority": "must",
        "acceptance_criteria": [{"given": "g", "when": "w", "then": "t"}],
        "validation_method": "test",
    }
    return base | overrides


MINIMAL_REQUIREMENTS: dict[str, Any] = {
    "functional": [raw_fr("R1")],
    "nonfunctional": [],
    "user_stories": [{"actor": "user", "want": "w", "benefit": "b", "requirement_keys": ["R1"]}],
}


MINIMAL_ARCH: dict[str, Any] = {
    "selected_pattern": "modular_monolith",
    "pattern_evaluations": [
        {"pattern": "modular_monolith", "suitable": True, "rationale": "simple"},
        {"pattern": "microservices", "suitable": False, "rationale": "overkill"},
    ],
    "components": [
        {
            "key": "C1",
            "name": "Core",
            "kind": "module",
            "responsibility": "does it",
            "requirement_ids": ["FR-001"],
        }
    ],
}
MINIMAL_TECH: dict[str, Any] = {
    "technologies": [
        {
            "key": "T1",
            "name": "Python",
            "category": "backend",
            "purpose": "p",
            "reason": "r",
            "alternatives": ["Go"],
            "advantages": ["a"],
            "disadvantages": ["d"],
            "license": "PSF",
            "component_ids": ["C-001"],
        }
    ]
}
MINIMAL_DATA_API: dict[str, Any] = {
    "entities": [
        {
            "key": "E1",
            "name": "users",
            "description": "d",
            "fields": [{"name": "id", "type": "uuid", "primary_key": True}],
            "requirement_ids": ["FR-001"],
        }
    ],
    "endpoints": [
        {
            "key": "EP1",
            "method": "GET",
            "path": "/users",
            "purpose": "list",
            "authentication": "bearer",
            "authorization": "admin",
            "error_responses": [{"status": 401, "meaning": "no token"}],
            "requirement_ids": ["FR-001"],
            "entity_keys": ["E1"],
        }
    ],
}
MINIMAL_SECURITY: dict[str, Any] = {
    "is_ai_project": False,
    "handles_sensitive_data": False,
    "threats": [
        {
            "key": "TH1",
            "title": "t",
            "category": "spoofing",
            "asset": "accounts",
            "description": "d",
            "likelihood": "medium",
            "impact": "medium",
            "control_keys": ["SC1"],
        }
    ],
    "controls": [
        {
            "key": "SC1",
            "name": "Auth",
            "description": "d",
            "area": "authentication",
            "requirement_ids": ["FR-001"],
        }
    ],
}
MINIMAL_UX: dict[str, Any] = {"has_ui": False, "interface_note": "API only"}
MINIMAL_QA: dict[str, Any] = {
    "strategy": [{"test_type": "unit", "approach": "pytest"}],
    "test_cases": [
        {
            "key": "TC1",
            "requirement_ids": ["FR-001"],
            "scenario": "s",
            "steps": ["do"],
            "expected_result": "ok",
            "priority": "must",
            "test_type": "unit",
        }
    ],
    "deployment": {},
}


def q(qid: str, text: str, blocking: bool = True) -> dict[str, Any]:
    return {"id": qid, "question": text, "reason": "r", "impact": "i", "blocking": blocking}


def plan(*questions: dict[str, Any]) -> dict[str, Any]:
    blocking = any(x["blocking"] for x in questions)
    return {"sufficient": not blocking, "rationale": "because", "questions": list(questions)}


@dataclass
class Script:
    """Scripted LLM: separate response queues for each stage; the last item repeats."""

    understand: list[Any] = field(default_factory=lambda: [BRIEF])
    clarify: list[Any] = field(default_factory=lambda: [plan()])
    research_plan: list[Any] = field(default_factory=lambda: [{}])
    research_synthesis: list[Any] = field(
        default_factory=lambda: [{"feasibility_summary": "feasible", "findings": []}]
    )
    requirements: list[Any] = field(default_factory=lambda: [MINIMAL_REQUIREMENTS])
    architecture: list[Any] = field(default_factory=lambda: [MINIMAL_ARCH])
    technology: list[Any] = field(default_factory=lambda: [MINIMAL_TECH])
    data_api: list[Any] = field(default_factory=lambda: [MINIMAL_DATA_API])
    security: list[Any] = field(default_factory=lambda: [MINIMAL_SECURITY])
    ux: list[Any] = field(default_factory=lambda: [MINIMAL_UX])
    qa_deploy: list[Any] = field(default_factory=lambda: [MINIMAL_QA])
    audit_review: list[Any] = field(default_factory=lambda: [{"findings": []}])
    calls: dict[str, int] = field(
        default_factory=lambda: {
            "understand": 0,
            "clarify": 0,
            "research_plan": 0,
            "research_synthesis": 0,
            "requirements": 0,
            "architecture": 0,
            "technology": 0,
            "data_api": 0,
            "security": 0,
            "ux": 0,
            "qa_deploy": 0,
            "audit_review": 0,
        }
    )
    requests: list[LLMRequest] = field(default_factory=list)

    def __call__(self, request: LLMRequest) -> str:
        self.requests.append(request)
        sysmsg = request.system or ""
        if "business analyst" in sysmsg:
            stage = "understand"
        elif "planning technical research" in sysmsg:
            stage = "research_plan"
        elif "evidence-based feasibility" in sysmsg:
            stage = "research_synthesis"
        elif "writing a software requirements specification" in sysmsg:
            stage = "requirements"
        elif "independent reviewer" in sysmsg:
            stage = "audit_review"
        elif "designing the system architecture" in sysmsg:
            stage = "architecture"
        elif "selecting technologies" in sysmsg:
            stage = "technology"
        elif "designing the database and API" in sysmsg:
            stage = "data_api"
        elif "security and privacy analysis" in sysmsg:
            stage = "security"
        elif "designing the user experience" in sysmsg:
            stage = "ux"
        elif "defining the test and deployment strategy" in sysmsg:
            stage = "qa_deploy"
        else:
            stage = "clarify"
        queue = getattr(self, stage)
        item = queue[min(self.calls[stage], len(queue) - 1)]
        self.calls[stage] += 1
        if isinstance(item, Exception):
            raise item
        return json.dumps(item)


@dataclass
class Stack:
    repo: Repository
    service: WorkflowService
    script: Script
    gateway: LLMGateway
    engine: Any = None


def db_url_for(tmp_path: Path, name: str) -> str:
    """SQLite by default; set TEST_DATABASE_URL to run the same tests on PostgreSQL."""
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / name}"


async def reset_schema(engine: Any) -> None:
    async with engine.begin() as conn:
        if os.environ.get("TEST_DATABASE_URL"):
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def make_stack(
    tmp_path: Path,
    script: Script,
    max_rounds: int = 2,
    init_db: bool = True,
    research_factory: Callable[[Repository, LLMGateway], ResearchService] | None = None,
) -> AsyncIterator[Stack]:
    """Fresh gateway/graph/checkpointer connection over the SAME sqlite files in tmp_path."""
    engine = make_engine(db_url_for(tmp_path, "app.db"))
    if init_db:
        await reset_schema(engine)
    repo = Repository(make_session_factory(engine))
    provider = FakeProvider([script])

    async def nosleep(_: float) -> None:
        return None

    gateway = LLMGateway(
        Target(provider, "m"),
        policy=RetryPolicy(max_attempts=1, structured_attempts=1),
        tracker=UsageTracker(sink=repo.record_usage),
        sleep=nosleep,
    )
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "ckpt.db")) as saver:
        research = research_factory(repo, gateway) if research_factory else None
        graph = build_workflow(gateway, repo, saver, max_rounds=max_rounds, research=research)
        yield Stack(repo, WorkflowService(graph, repo), script, gateway, engine)
    await engine.dispose()

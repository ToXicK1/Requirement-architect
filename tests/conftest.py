from __future__ import annotations

import json
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
    calls: dict[str, int] = field(
        default_factory=lambda: {
            "understand": 0,
            "clarify": 0,
            "research_plan": 0,
            "research_synthesis": 0,
            "requirements": 0,
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


@asynccontextmanager
async def make_stack(
    tmp_path: Path,
    script: Script,
    max_rounds: int = 2,
    init_db: bool = True,
    research_factory: Callable[[Repository, LLMGateway], ResearchService] | None = None,
) -> AsyncIterator[Stack]:
    """Fresh gateway/graph/checkpointer connection over the SAME sqlite files in tmp_path."""
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    if init_db:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
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
        yield Stack(repo, WorkflowService(graph, repo), script, gateway)
    await engine.dispose()

from __future__ import annotations

import json
from collections.abc import AsyncIterator
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
from requirements_architect.storage.database import Base, make_engine, make_session_factory
from requirements_architect.storage.repository import Repository
from tests.fakes import FakeProvider

BRIEF = {"actual_problem": "slow onboarding", "proposed_solution": "an onboarding app"}


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
    calls: dict[str, int] = field(default_factory=lambda: {"understand": 0, "clarify": 0})
    requests: list[LLMRequest] = field(default_factory=list)

    def __call__(self, request: LLMRequest) -> str:
        self.requests.append(request)
        stage = "understand" if "business analyst" in (request.system or "") else "clarify"
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
    tmp_path: Path, script: Script, max_rounds: int = 2, init_db: bool = True
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
        graph = build_workflow(gateway, repo, saver, max_rounds=max_rounds)
        yield Stack(repo, WorkflowService(graph, repo), script, gateway)
    await engine.dispose()

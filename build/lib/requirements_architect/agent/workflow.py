"""LangGraph workflow for stages 1-2 (understanding + clarification).

Graph:  understand -> clarify -> (gate <-> gate | clarify | finish)

* `gate` is the only node that calls interrupt(); it has no LLM side effects, because LangGraph
  re-executes an interrupted node from its start when resumed.
* LLM re-evaluation (`clarify`) is bounded by `max_rounds`. Human input is never bounded.
* A retry after failure resumes from the last checkpoint, so completed nodes are not re-run.
"""

from __future__ import annotations

from typing import Any, TypedDict

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from requirements_architect.agent.stages.clarification import run_clarification
from requirements_architect.agent.stages.understanding import run_problem_understanding
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.state import (
    ClarificationAnswer,
    ClarificationPlan,
    Dependency,
    ProjectBrief,
    StageId,
    WorkflowStatus,
)
from requirements_architect.storage.repository import Repository

log = structlog.get_logger()


class WorkflowState(TypedDict, total=False):
    project_id: str
    problem_statement: str
    brief: dict[str, Any]
    brief_version: int
    plan: dict[str, Any]
    asked: dict[str, str]  # every question id ever asked -> text
    open_questions: list[dict[str, Any]]  # blocking and unanswered
    round: int
    status: str


def build_workflow(
    gateway: LLMGateway,
    repo: Repository,
    checkpointer: BaseCheckpointSaver[Any],
    max_rounds: int = 2,
) -> CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState]:
    async def understand(state: WorkflowState) -> dict[str, Any]:
        pid = state["project_id"]
        await repo.set_status(pid, WorkflowStatus.RUNNING.value)
        brief = await run_problem_understanding(gateway, pid, state["problem_statement"])
        meta = await repo.save_stage_output(pid, StageId.PROBLEM_UNDERSTANDING, brief)
        return {
            "brief": brief.model_dump(mode="json"),
            "brief_version": meta.version,
            "round": 0,
            "asked": {},
            "open_questions": [],
            "status": WorkflowStatus.RUNNING.value,
        }

    async def clarify(state: WorkflowState) -> dict[str, Any]:
        pid = state["project_id"]
        answers = await repo.get_answers(pid)
        asked = dict(state.get("asked", {}))
        plan = await run_clarification(
            gateway,
            pid,
            state["problem_statement"],
            ProjectBrief.model_validate(state["brief"]),
            asked,
            answers,
        )
        await repo.save_stage_output(
            pid,
            StageId.CLARIFICATION,
            plan,
            [Dependency(stage_id=StageId.PROBLEM_UNDERSTANDING, version=state["brief_version"])],
        )
        for q in plan.questions:
            asked[q.id] = q.question
        open_qs = [q.model_dump(mode="json") for q in plan.questions if q.blocking]
        return {
            "plan": plan.model_dump(mode="json"),
            "asked": asked,
            "open_questions": open_qs,
            "round": state.get("round", 0) + 1,
        }

    async def gate(state: WorkflowState) -> dict[str, Any]:
        pid = state["project_id"]
        await repo.set_status(pid, WorkflowStatus.AWAITING_CLARIFICATION.value)
        resume = interrupt(
            {
                "project_id": pid,
                "round": state.get("round", 0),
                "questions": state["open_questions"],
            }
        )
        answers = [ClarificationAnswer.model_validate(a) for a in resume["answers"]]
        await repo.save_answers(pid, answers)
        answered = {a.question_id for a in answers}
        remaining = [q for q in state["open_questions"] if q["id"] not in answered]
        await repo.set_status(pid, WorkflowStatus.RUNNING.value)
        return {"open_questions": remaining}

    async def finish(state: WorkflowState) -> dict[str, Any]:
        await repo.set_status(state["project_id"], WorkflowStatus.READY_FOR_RESEARCH.value)
        return {"status": WorkflowStatus.READY_FOR_RESEARCH.value}

    def after_clarify(state: WorkflowState) -> str:
        return "gate" if state.get("open_questions") else "finish"

    def after_gate(state: WorkflowState) -> str:
        if state.get("open_questions"):
            return "gate"  # human gave partial answers; keep waiting (human-driven, not LLM-driven)
        return "clarify" if state.get("round", 0) < max_rounds else "finish"

    g: StateGraph[WorkflowState, None, WorkflowState, WorkflowState] = StateGraph(WorkflowState)
    g.add_node("understand", understand)
    g.add_node("clarify", clarify)
    g.add_node("gate", gate)
    g.add_node("finish", finish)
    g.add_edge(START, "understand")
    g.add_edge("understand", "clarify")
    g.add_conditional_edges("clarify", after_clarify, {"gate": "gate", "finish": "finish"})
    g.add_conditional_edges(
        "gate", after_gate, {"gate": "gate", "clarify": "clarify", "finish": "finish"}
    )
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["ClarificationPlan", "WorkflowState", "build_workflow"]

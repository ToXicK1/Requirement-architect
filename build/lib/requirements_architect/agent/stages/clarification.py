"""Stage 2: clarification planning."""

from __future__ import annotations

import re
from collections.abc import Mapping

from requirements_architect.agent.prompt_loader import load_prompt, wrap_untrusted
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.llm.types import LLMRequest, Message
from requirements_architect.schemas.state import (
    ClarificationAnswer,
    ClarificationPlan,
    ClarificationQuestion,
    ProjectBrief,
)

MAX_QUESTIONS = 8


def next_question_id(asked: Mapping[str, str]) -> str:
    nums = [int(m.group(1)) for k in asked if (m := re.fullmatch(r"Q-(\d+)", k))]
    return f"Q-{(max(nums) if nums else 0) + 1:03d}"


async def run_clarification(
    gateway: LLMGateway,
    project_id: str,
    problem_statement: str,
    brief: ProjectBrief,
    asked: Mapping[str, str],
    answers: Mapping[str, ClarificationAnswer],
) -> ClarificationPlan:
    """Return a plan containing only NEW questions (answered/duplicate ones are removed)."""
    prompt = load_prompt("clarification")
    asked_txt = "\n".join(f"{qid}: {text}" for qid, text in asked.items()) or "(none)"
    answers_txt = "\n".join(f"{a.question_id}: {a.answer}" for a in answers.values()) or "(none)"
    system, user = prompt.render(
        problem_statement=wrap_untrusted(problem_statement, "problem_statement"),
        brief_json=wrap_untrusted(brief.model_dump_json(indent=2), "brief"),
        previously_asked=wrap_untrusted(asked_txt, "previously_asked"),
        answers=wrap_untrusted(answers_txt, "answers"),
        next_question_id=next_question_id(asked),
        max_questions=str(MAX_QUESTIONS),
    )
    request = LLMRequest(
        system=system,
        messages=[Message(role="user", content=user)],
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        project_id=project_id,
    )
    plan, _ = await gateway.complete_structured(request, ClarificationPlan)
    return reconcile_plan(plan, asked)


def reconcile_plan(plan: ClarificationPlan, asked: Mapping[str, str]) -> ClarificationPlan:
    """Deterministic guard against the model re-using ids.

    - same id + same text as an earlier question -> duplicate, drop it
    - same id + different text -> genuinely new question; give it a fresh id (never lose one)
    Then recompute sufficiency from what remains.
    """
    used = dict(asked)
    kept: list[ClarificationQuestion] = []
    for q in plan.questions[:MAX_QUESTIONS]:
        if q.id in used:
            if used[q.id].strip().lower() == q.question.strip().lower():
                continue
            q = q.model_copy(update={"id": next_question_id(used)})
        used[q.id] = q.question
        kept.append(q)
    blocking = any(qq.blocking for qq in kept)
    return ClarificationPlan(sufficient=not blocking, rationale=plan.rationale, questions=kept)

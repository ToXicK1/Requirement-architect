"""Stage 1: problem understanding."""

from __future__ import annotations

from requirements_architect.agent.prompt_loader import load_prompt, wrap_untrusted
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.llm.types import LLMRequest, Message
from requirements_architect.schemas.state import ProjectBrief


async def run_problem_understanding(
    gateway: LLMGateway, project_id: str, problem_statement: str
) -> ProjectBrief:
    prompt = load_prompt("problem_understanding")
    system, user = prompt.render(
        problem_statement=wrap_untrusted(problem_statement, "problem_statement")
    )
    request = LLMRequest(
        system=system,
        messages=[Message(role="user", content=user)],
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        project_id=project_id,
    )
    brief, _ = await gateway.complete_structured(request, ProjectBrief)
    return brief

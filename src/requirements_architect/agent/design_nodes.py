"""Graph nodes for stages 5-10, built from one table so every stage persists, records
dependencies and loads context the same way."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from requirements_architect.agent.stages.architecture import generate_architecture
from requirements_architect.agent.stages.common import StageContext
from requirements_architect.agent.stages.dataapi import generate_data_api
from requirements_architect.agent.stages.qa_deploy import generate_qa
from requirements_architect.agent.stages.security import generate_security
from requirements_architect.agent.stages.technology import generate_technology
from requirements_architect.agent.stages.ux import generate_ux
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.requirements import RequirementsSpec
from requirements_architect.schemas.research import ResearchReport
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.state import (
    Dependency,
    ProjectBrief,
    StageId,
    WorkflowStatus,
)
from requirements_architect.schemas.technology import TechnologySpec
from requirements_architect.schemas.ux import UxSpec
from requirements_architect.storage.repository import Repository

Generator = Callable[[LLMGateway, StageContext], Awaitable[BaseModel]]


@dataclass(frozen=True)
class DesignStage:
    name: str  # graph node name and key in StageContext.extras
    stage_id: StageId
    model: type[BaseModel]
    generate: Generator
    depends_on: tuple[StageId, ...]


DESIGN_STAGES: tuple[DesignStage, ...] = (
    DesignStage(
        "architecture",
        StageId.ARCHITECTURE,
        ArchitectureSpec,
        generate_architecture,
        (StageId.REQUIREMENTS, StageId.RESEARCH),
    ),
    DesignStage(
        "technology",
        StageId.TECHNOLOGY,
        TechnologySpec,
        generate_technology,
        (StageId.REQUIREMENTS, StageId.ARCHITECTURE, StageId.RESEARCH),
    ),
    DesignStage(
        "data_api",
        StageId.DATA_API,
        DataApiSpec,
        generate_data_api,
        (StageId.REQUIREMENTS, StageId.ARCHITECTURE, StageId.TECHNOLOGY),
    ),
    DesignStage(
        "security",
        StageId.SECURITY,
        SecuritySpec,
        generate_security,
        (StageId.REQUIREMENTS, StageId.ARCHITECTURE, StageId.TECHNOLOGY, StageId.DATA_API),
    ),
    DesignStage(
        "ux",
        StageId.UX,
        UxSpec,
        generate_ux,
        (StageId.REQUIREMENTS, StageId.ARCHITECTURE, StageId.DATA_API),
    ),
    DesignStage(
        "qa_deploy",
        StageId.QA_DEPLOY,
        QaSpec,
        generate_qa,
        (
            StageId.REQUIREMENTS,
            StageId.ARCHITECTURE,
            StageId.TECHNOLOGY,
            StageId.DATA_API,
            StageId.SECURITY,
            StageId.UX,
        ),
    ),
)

# StageContext.extras keys come from DesignStage.name; "architecture" is also a typed field.
_EXTRA_KEY = {
    StageId.TECHNOLOGY: "technology",
    StageId.DATA_API: "dataapi",
    StageId.SECURITY: "security",
    StageId.UX: "ux",
}


async def load_context(
    repo: Repository, project_id: str, brief: ProjectBrief, feedback: str | None = None
) -> StageContext:
    pid = project_id
    project = await repo.get_project(pid)
    latest_req = await repo.get_latest_output(pid, StageId.REQUIREMENTS, RequirementsSpec)
    if latest_req is None:
        raise RuntimeError("requirements output is missing; cannot run design stages")
    research = await repo.get_latest_output(pid, StageId.RESEARCH, ResearchReport)
    arch = await repo.get_latest_output(pid, StageId.ARCHITECTURE, ArchitectureSpec)
    extras: dict[str, object] = {}
    for stage in DESIGN_STAGES:
        key = _EXTRA_KEY.get(stage.stage_id)
        if key is None:
            continue
        found = await repo.get_latest_output(pid, stage.stage_id, stage.model)
        if found is not None:
            extras[key] = found[1]
    if feedback:
        extras["audit_feedback"] = feedback
    return StageContext(
        project_id=pid,
        problem_statement=project.problem_statement,
        brief=brief,
        answers=await repo.get_answers(pid),
        requirements=latest_req[1],
        research=research[1] if research else None,
        architecture=arch[1] if arch else None,
        extras=extras,
    )


async def run_design_stage(
    gateway: LLMGateway,
    repo: Repository,
    stage: DesignStage,
    project_id: str,
    brief: ProjectBrief,
    feedback: str | None = None,
) -> int:
    """Generate one design stage from the latest persisted inputs and save it as a new version."""
    ctx = await load_context(repo, project_id, brief, feedback)
    spec = await stage.generate(gateway, ctx)
    deps: list[Dependency] = []
    for dep in stage.depends_on:
        versions = await repo.list_versions(project_id, dep)
        if versions:
            deps.append(Dependency(stage_id=dep, version=versions[-1]))
    meta = await repo.save_stage_output(project_id, stage.stage_id, spec, deps)
    return meta.version


def make_design_node(
    gateway: LLMGateway, repo: Repository, stage: DesignStage, *, last: bool
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        pid: str = state["project_id"]
        brief = ProjectBrief.model_validate(state["brief"])
        version = await run_design_stage(gateway, repo, stage, pid, brief)
        versions_map = {**state.get("design_versions", {}), stage.name: version}
        update: dict[str, Any] = {"design_versions": versions_map}
        if last:
            await repo.set_status(pid, WorkflowStatus.SPECS_COMPLETE.value)
            update["status"] = WorkflowStatus.SPECS_COMPLETE.value
        return update

    return node

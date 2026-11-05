from __future__ import annotations

from dataclasses import dataclass

from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.requirements import RequirementsSpec
from requirements_architect.schemas.research import ResearchReport
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.state import ProjectBrief
from requirements_architect.schemas.technology import TechnologySpec
from requirements_architect.schemas.ux import UxSpec


@dataclass(frozen=True)
class SpecSet:
    """Everything the auditor looks at: only persisted outputs, never generator reasoning."""

    brief: ProjectBrief
    requirements: RequirementsSpec
    architecture: ArchitectureSpec
    technology: TechnologySpec
    data_api: DataApiSpec
    security: SecuritySpec
    ux: UxSpec
    qa: QaSpec
    research: ResearchReport | None = None

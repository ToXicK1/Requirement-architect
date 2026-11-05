from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.requirements import RequirementsSpec
from requirements_architect.schemas.research import ResearchReport
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.state import ProjectBrief
from requirements_architect.schemas.technology import TechnologySpec
from requirements_architect.schemas.ux import UxSpec

ROOT = "PROJECT_DOCUMENTATION"


@dataclass(frozen=True)
class DocInputs:
    project_id: str
    project_name: str
    problem_statement: str
    brief: ProjectBrief
    requirements: RequirementsSpec
    architecture: ArchitectureSpec
    technology: TechnologySpec
    data_api: DataApiSpec
    security: SecuritySpec
    ux: UxSpec
    qa: QaSpec
    research: ResearchReport | None
    package_version: int
    generated_at: datetime
    # stage versions the package was built from: {stage name: version}
    source_versions: dict[str, int] = field(default_factory=dict)

    @property
    def pending_approvals(self) -> int:
        return sum(
            len(s.approval_candidates)
            for s in (self.architecture, self.technology, self.data_api, self.security, self.ux)
        ) + len(self.qa.approval_candidates)

    @property
    def approval_status(self) -> str:
        n = self.pending_approvals
        return (
            f"DRAFT - {n} item(s) await human approval; nothing has been approved"
            if n
            else "DRAFT - not yet reviewed by a human"
        )


@dataclass(frozen=True)
class Doc:
    path: str  # e.g. "03_ARCHITECTURE/SYSTEM_ARCHITECTURE.md" (relative to ROOT)
    title: str
    body: str  # without the metadata header
    applicable: bool = True  # False -> the body explains why the topic does not apply

    @property
    def folder(self) -> str:
        return self.path.split("/", 1)[0]


def not_applicable(path: str, title: str, reason: str) -> Doc:
    return Doc(path, title, f"**Not applicable.** {reason}\n", applicable=False)

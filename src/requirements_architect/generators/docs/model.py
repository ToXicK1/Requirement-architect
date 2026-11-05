from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.audit import AuditReport
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.requirements import RequirementsSpec, TargetStatus
from requirements_architect.schemas.research import ResearchReport
from requirements_architect.schemas.security import SecuritySpec
from requirements_architect.schemas.state import ProjectBrief, StageId
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
    audit: AuditReport | None = None  # only a current (non-stale) audit is passed in
    audit_note: str = ""  # why there is no audit document (not run / stale)
    # human decisions that still match the current request: {"stage/ref": state}
    approval_states: dict[str, str] = field(default_factory=dict)

    def approval_state(self, stage: str, ref: str) -> str:
        return self.approval_states.get(f"{stage}/{ref}", "pending")

    def _candidates(self) -> list[tuple[str, str]]:
        specs = (self.architecture, self.technology, self.data_api, self.security, self.ux, self.qa)
        out = [(c.source_stage, c.ref) for sp in specs for c in sp.approval_candidates]
        out += [
            (StageId.REQUIREMENTS.value, n.id)
            for n in self.requirements.nonfunctional
            if n.target_status is TargetStatus.PROPOSED and n.target
        ]
        return out

    @property
    def pending_approvals(self) -> int:
        return sum(1 for st, ref in self._candidates() if self.approval_state(st, ref) == "pending")

    @property
    def approval_status(self) -> str:
        n = self.pending_approvals
        decided = [self.approval_state(st, ref) for st, ref in self._candidates()]
        if n:
            return f"DRAFT - {n} item(s) await human approval; the package itself is not approved"
        if decided:
            return (
                f"DRAFT - {decided.count('approved')} item(s) approved, "
                f"{decided.count('rejected')} rejected, "
                f"{decided.count('revision_requested')} sent back for revision; "
                "the package itself has not been approved as a whole"
            )
        return "DRAFT - not yet reviewed by a human"


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

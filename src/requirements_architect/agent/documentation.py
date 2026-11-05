"""Generate, verify and persist the documentation package for a project."""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from requirements_architect.generators.docs.bundle import (
    PDF_NAME,
    Manifest,
    assemble,
    build_zip,
    verify_directory,
    verify_zip,
    write_files,
)
from requirements_architect.generators.docs.model import ROOT, DocInputs
from requirements_architect.generators.docs.package import build_package
from requirements_architect.generators.docs.pdf import render_pdf
from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.audit import AuditReport
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

_PROJECT_ID = re.compile(r"^[0-9a-fA-F\-]{36}$")
_ALLOWED_STATUS = {
    WorkflowStatus.SPECS_COMPLETE.value,
    WorkflowStatus.AUDIT_COMPLETE.value,
    WorkflowStatus.DOCUMENTS_COMPLETE.value,
}


class DocumentationError(RuntimeError):
    """The package could not be generated or failed verification."""


@dataclass
class GeneratedPackage:
    project_id: str
    version: int
    directory: Path
    zip_path: Path
    manifest: Manifest
    warnings: list[str] = field(default_factory=list)


class DocumentationService:
    def __init__(self, repo: Repository, output_dir: Path) -> None:
        self._repo = repo
        self._out = output_dir

    async def _load(self, project_id: str) -> tuple[DocInputs, list[Dependency]]:
        project = await self._repo.get_project(project_id)
        if project.status not in _ALLOWED_STATUS:
            raise DocumentationError(
                f"project status is '{project.status}'; the specifications must be complete first"
            )
        deps: list[Dependency] = []

        async def need[T: BaseModel](stage: StageId, model: type[T]) -> T:
            got = await self._repo.get_latest_output(project_id, stage, model)
            if got is None:
                raise DocumentationError(f"missing stage output: {stage.value}")
            deps.append(Dependency(stage_id=stage, version=got[0].version))
            return got[1]

        brief = await need(StageId.PROBLEM_UNDERSTANDING, ProjectBrief)
        reqs = await need(StageId.REQUIREMENTS, RequirementsSpec)
        arch = await need(StageId.ARCHITECTURE, ArchitectureSpec)
        tech = await need(StageId.TECHNOLOGY, TechnologySpec)
        api = await need(StageId.DATA_API, DataApiSpec)
        sec = await need(StageId.SECURITY, SecuritySpec)
        ux = await need(StageId.UX, UxSpec)
        qa = await need(StageId.QA_DEPLOY, QaSpec)
        research = await self._repo.get_latest_output(project_id, StageId.RESEARCH, ResearchReport)
        if research is not None:
            deps.append(Dependency(stage_id=StageId.RESEARCH, version=research[0].version))
        audit, audit_note = await self._current_audit(
            project_id, {d.stage_id.value: d.version for d in deps}
        )
        previous = await self._repo.list_versions(project_id, StageId.DOCUMENTATION)
        inputs = DocInputs(
            project_id=project_id,
            project_name=project.name,
            problem_statement=project.problem_statement,
            brief=brief,
            requirements=reqs,
            architecture=arch,
            technology=tech,
            data_api=api,
            security=sec,
            ux=ux,
            qa=qa,
            research=research[1] if research else None,
            package_version=(previous[-1] if previous else 0) + 1,
            generated_at=datetime.now(UTC).replace(second=0, microsecond=0),
            source_versions={d.stage_id.value: d.version for d in deps},
            audit=audit,
            audit_note=audit_note,
        )
        return inputs, deps

    async def _current_audit(
        self, project_id: str, current: dict[str, int]
    ) -> tuple[AuditReport | None, str]:
        """The latest audit, unless it is missing or was run on older specifications."""
        got = await self._repo.get_latest_output(project_id, StageId.AUDIT, AuditReport)
        if got is None:
            return None, "the audit has not been run"
        stale = sorted(k for k, v in got[1].source_versions.items() if current.get(k, v) != v)
        if stale:
            return None, "the audit is stale: these stages changed after it ran: " + ", ".join(
                stale
            )
        return got[1], ""

    async def generate(self, project_id: str) -> GeneratedPackage:
        if not _PROJECT_ID.match(project_id):
            raise DocumentationError("invalid project id")
        inputs, deps = await self._load(project_id)
        pkg = build_package(inputs)
        pdf = await asyncio.to_thread(render_pdf, pkg.docs, inputs, pkg.pending)
        files = assemble(pkg, inputs, pdf=pdf.data)
        if PDF_NAME not in files:
            raise DocumentationError("PDF was not produced")

        target = self._out / project_id / f"v{inputs.package_version}"
        if target.exists():
            raise DocumentationError(f"output already exists: v{inputs.package_version}")
        staging = self._out / project_id / f".staging-v{inputs.package_version}"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            root = await asyncio.to_thread(write_files, files, staging)
            problems = await asyncio.to_thread(verify_directory, root)
            zip_bytes = build_zip(files)
            problems += verify_zip(zip_bytes)
            if problems:
                raise DocumentationError("package verification failed: " + "; ".join(problems[:10]))
            (staging / f"{ROOT}.zip").write_bytes(zip_bytes)
            staging.replace(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        root = target / ROOT
        zip_path = target / f"{ROOT}.zip"

        manifest = Manifest.model_validate_json(files["manifest.json"])
        await self._repo.save_stage_output(project_id, StageId.DOCUMENTATION, manifest, deps)
        await self._repo.set_status(project_id, WorkflowStatus.DOCUMENTS_COMPLETE.value)
        return GeneratedPackage(
            project_id, inputs.package_version, root, zip_path, manifest, pdf.warnings
        )

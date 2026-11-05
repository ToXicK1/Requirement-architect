"""HTTP routes. Every project route authenticates the caller and checks ownership; a project the
caller does not own is reported as 404, so ids cannot be probed."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from requirements_architect.agent.approvals import ApprovalError, Decision
from requirements_architect.agent.service import (
    AnswerValidationError,
    WorkflowService,
    WorkflowStateError,
)
from requirements_architect.api.auth import AuthError, RateLimitedError
from requirements_architect.api.container import Container
from requirements_architect.api.jobs import JobBusyError
from requirements_architect.api.schemas import Answers, Credentials, DecisionIn, NewProject
from requirements_architect.audit.service import AuditService
from requirements_architect.generators.docs.bundle import MANIFEST, Manifest, safe_relative
from requirements_architect.generators.docs.model import ROOT
from requirements_architect.schemas.audit import AuditReport
from requirements_architect.schemas.state import ClarificationAnswer, StageId, WorkflowStatus
from requirements_architect.storage.accounts import UsernameTakenError
from requirements_architect.storage.models import Project, User
from requirements_architect.storage.repository import NotFoundError

router = APIRouter(prefix="/api/v1")
_DOC_STATES = {
    WorkflowStatus.SPECS_COMPLETE.value,
    WorkflowStatus.AUDIT_COMPLETE.value,
    WorkflowStatus.DOCUMENTS_COMPLETE.value,
}


def client_ip(request: Request, trust_forwarded: bool) -> str:
    """The proxy appends the real peer to X-Forwarded-For, so only the LAST entry is trustworthy;
    earlier entries are client-supplied and can be forged."""
    if trust_forwarded:
        last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if last:
            return last[:64]
    return request.client.host if request.client else "unknown"


def container(request: Request) -> Container:
    c: Container = request.app.state.container
    return c


C = Annotated[Container, Depends(container)]


def _token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})
    return value.strip()


async def current_user(request: Request, c: C) -> User:
    try:
        return await c.auth.authenticate(_token(request))
    except AuthError:
        raise HTTPException(
            401, "authentication required", headers={"WWW-Authenticate": "Bearer"}
        ) from None


U = Annotated[User, Depends(current_user)]


async def owned_project(project_id: str, user: U, c: C) -> Project:
    try:
        project = await c.repo.get_project(project_id)
    except NotFoundError:
        raise HTTPException(404, "project not found") from None
    if project.owner_id != user.id:
        raise HTTPException(404, "project not found")
    return project


P = Annotated[Project, Depends(owned_project)]


def _need_llm(c: Container) -> tuple[WorkflowService, AuditService]:
    if c.workflow is None or c.audit is None:
        raise HTTPException(503, "the LLM is not configured on this server")
    return c.workflow, c.audit


def _spend(c: Container, user: User) -> None:
    if not c.expensive.allow(user.id):
        raise HTTPException(429, "too many generation requests; try again later")


def _project_out(p: Project, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": p.id,
        "name": p.name,
        "status": p.status,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }
    if detail:
        out["problem_statement"] = p.problem_statement
    return out


def _job_out(c: Container, project_id: str) -> dict[str, Any] | None:
    j = c.jobs.get(project_id)
    return (
        None
        if j is None
        else {k: getattr(j, k) for k in ("kind", "state", "started_at", "finished_at", "error")}
    )


def _start_job(c: Container, project_id: str, kind: str, work: Any) -> dict[str, Any]:
    try:
        c.jobs.start(project_id, kind, work)
    except JobBusyError as exc:
        raise HTTPException(409, str(exc)) from None
    return _job_out(c, project_id) or {}


# ---------------------------------------------------------------- auth
@router.post("/auth/register", status_code=201)
async def register(body: Credentials, c: C) -> dict[str, str]:
    if not c.settings.allow_registration:
        raise HTTPException(403, "registration is disabled; ask an administrator for an account")
    try:
        user = await c.auth.register(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except UsernameTakenError:
        raise HTTPException(409, "username is not available") from None
    return {"id": user.id, "username": user.username}


@router.post("/auth/login")
async def login(body: Credentials, request: Request, c: C) -> dict[str, str]:
    client = client_ip(request, c.settings.trust_forwarded_for)
    try:
        token, user = await c.auth.login(body.username, body.password, client)
    except RateLimitedError:
        raise HTTPException(429, "too many attempts; try again later") from None
    except AuthError:
        raise HTTPException(401, "invalid username or password") from None
    return {"token": token, "username": user.username}


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, user: U, c: C) -> Response:
    await c.auth.logout(_token(request), user)
    return Response(status_code=204)


@router.get("/auth/me")
async def me(user: U) -> dict[str, str]:
    return {"id": user.id, "username": user.username}


# ---------------------------------------------------------------- projects
@router.post("/projects", status_code=201)
async def create_project(body: NewProject, user: U, c: C) -> dict[str, Any]:
    p = await c.repo.create_project(body.name.strip(), body.problem_statement, owner_id=user.id)
    await c.accounts.log("project.create", user_id=user.id, project_id=p.id)
    return _project_out(p, detail=True)


@router.get("/projects")
async def list_projects(user: U, c: C) -> list[dict[str, Any]]:
    return [_project_out(p) for p in await c.repo.list_projects(user.id)]


@router.get("/projects/{project_id}")
async def get_project(p: P, c: C) -> dict[str, Any]:
    return _project_out(p, detail=True) | {"job": _job_out(c, p.id)}


@router.get("/projects/{project_id}/status")
async def status(p: P, c: C) -> dict[str, Any]:
    snap = None
    if c.workflow is not None:
        snap = (await c.workflow.snapshot(p.id)).model_dump(mode="json")
    fresh = await c.repo.get_project(p.id)
    return {"status": fresh.status, "workflow": snap, "job": _job_out(c, p.id)}


@router.post("/projects/{project_id}/start", status_code=202)
async def start(p: P, user: U, c: C) -> dict[str, Any]:
    wf, _ = _need_llm(c)
    if p.status != WorkflowStatus.CREATED.value:
        raise HTTPException(409, f"project already started (status={p.status})")
    _spend(c, user)
    await c.accounts.log("workflow.start", user_id=user.id, project_id=p.id)
    return _start_job(c, p.id, "workflow", lambda: wf.start(p.id))


@router.post("/projects/{project_id}/answers", status_code=202)
async def answer(body: Answers, p: P, user: U, c: C) -> dict[str, Any]:
    wf, _ = _need_llm(c)
    answers = [ClarificationAnswer(**a.model_dump()) for a in body.answers]
    try:
        await wf.validate_answers(p.id, answers)
    except WorkflowStateError as exc:
        raise HTTPException(409, str(exc)) from None
    except AnswerValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    _spend(c, user)
    await c.accounts.log(
        "workflow.answers", user_id=user.id, project_id=p.id, detail={"count": len(answers)}
    )
    return _start_job(c, p.id, "workflow", lambda: wf.resume(p.id, answers))


@router.post("/projects/{project_id}/retry", status_code=202)
async def retry(p: P, user: U, c: C) -> dict[str, Any]:
    wf, _ = _need_llm(c)
    snap = await wf.snapshot(p.id)
    if snap.status != WorkflowStatus.FAILED.value:
        raise HTTPException(409, f"nothing to retry (status={snap.status})")
    _spend(c, user)
    await c.accounts.log("workflow.retry", user_id=user.id, project_id=p.id)
    return _start_job(c, p.id, "workflow", lambda: wf.retry(p.id))


# ---------------------------------------------------------------- outputs
@router.get("/projects/{project_id}/outputs")
async def outputs(p: P, c: C) -> dict[str, list[int]]:
    out = {}
    for stage in StageId:
        versions = await c.repo.list_versions(p.id, stage)
        if versions:
            out[stage.value] = versions
    return out


@router.get("/projects/{project_id}/outputs/{stage}")
async def output(stage: StageId, p: P, c: C, version: int | None = None) -> dict[str, Any]:
    got = await c.repo.get_output_payload(p.id, stage, version)
    if got is None:
        raise HTTPException(404, "no such output")
    meta, payload = got
    return {
        "stage": stage.value,
        "version": meta.version,
        "status": meta.status.value,
        "created_at": meta.created_at,
        "depends_on": [d.model_dump(mode="json") for d in meta.depends_on],
        "payload": payload,
    }


# ---------------------------------------------------------------- audit
@router.post("/projects/{project_id}/audit", status_code=202)
async def run_audit(p: P, user: U, c: C) -> dict[str, Any]:
    _, audit = _need_llm(c)
    if p.status not in _DOC_STATES:
        raise HTTPException(409, f"specifications are not complete (status={p.status})")
    _spend(c, user)
    await c.accounts.log("audit.run", user_id=user.id, project_id=p.id)
    return _start_job(c, p.id, "audit", lambda: audit.run(p.id))


@router.get("/projects/{project_id}/audit")
async def get_audit(p: P, c: C) -> dict[str, Any]:
    got = await c.repo.get_latest_output(p.id, StageId.AUDIT, AuditReport)
    if got is None:
        raise HTTPException(404, "the audit has not been run")
    return {"version": got[0].version, "report": got[1].model_dump(mode="json")}


# ---------------------------------------------------------------- approvals
@router.get("/projects/{project_id}/approvals")
async def approvals(p: P, c: C) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in await c.approvals.list(p.id)]


@router.post("/projects/{project_id}/approvals")
async def decide(body: DecisionIn, p: P, user: U, c: C, response: Response) -> dict[str, Any]:
    async def work() -> object:
        return await c.approvals.decide(
            p.id, body.stage_id, body.ref, body.fingerprint, body.decision, body.note, user.id
        )

    await c.accounts.log(
        "approval.decide",
        user_id=user.id,
        project_id=p.id,
        detail={"stage": body.stage_id.value, "ref": body.ref, "decision": body.decision.value},
    )
    if body.decision is Decision.REQUEST_REVISION:
        _need_llm(c)
        _spend(c, user)
        response.status_code = 202
        return {"job": _start_job(c, p.id, "revision", work)}
    try:
        result = await work()
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from None
    return result.model_dump(mode="json")  # type: ignore[attr-defined,no-any-return]


# ---------------------------------------------------------------- documents
@router.post("/projects/{project_id}/documents", status_code=202)
async def generate_documents(p: P, user: U, c: C) -> dict[str, Any]:
    if p.status not in _DOC_STATES:
        raise HTTPException(409, f"specifications are not complete (status={p.status})")
    _spend(c, user)
    await c.accounts.log("documents.generate", user_id=user.id, project_id=p.id)
    return _start_job(c, p.id, "documents", lambda: c.docs.generate(p.id))


async def _package(c: Container, project_id: str, version: int | None) -> tuple[Manifest, Any]:
    got = await c.repo.get_output_payload(project_id, StageId.DOCUMENTATION, version)
    if got is None:
        raise HTTPException(404, "no documents have been generated")
    manifest = Manifest.model_validate(got[1])
    base = (c.output_dir / project_id / f"v{manifest.package_version}").resolve()
    if not base.is_relative_to(c.output_dir.resolve()) or not base.is_dir():
        raise HTTPException(404, "the package is no longer on disk")
    return manifest, base


@router.get("/projects/{project_id}/documents")
async def documents(p: P, c: C, version: int | None = None) -> dict[str, Any]:
    manifest, _ = await _package(c, p.id, version)
    return manifest.model_dump(mode="json")


@router.get("/projects/{project_id}/documents/download.zip")
async def download_zip(p: P, c: C, user: U, version: int | None = None) -> FileResponse:
    manifest, base = await _package(c, p.id, version)
    zpath = base / f"{ROOT}.zip"
    if not zpath.is_file():
        raise HTTPException(404, "the archive is missing")
    await c.accounts.log(
        "documents.download", user_id=user.id, project_id=p.id, detail={"file": "zip"}
    )
    return FileResponse(
        zpath, media_type="application/zip", filename=f"{ROOT}-v{manifest.package_version}.zip"
    )


@router.get("/projects/{project_id}/documents/files/{path:path}")
async def document_file(path: str, p: P, c: C, version: int | None = None) -> FileResponse:
    manifest, base = await _package(c, p.id, version)
    try:
        rel = safe_relative(path)
    except ValueError:
        raise HTTPException(404, "no such file") from None
    # Only files the manifest lists (plus the manifest itself) can be served.
    if rel != MANIFEST and rel not in {e.path for e in manifest.files}:
        raise HTTPException(404, "no such file")
    root = (base / ROOT).resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "no such file")
    if rel.endswith(".pdf"):
        return FileResponse(target, media_type="application/pdf", filename=target.name)
    # Never rendered as HTML by the browser: plain text with nosniff.
    return FileResponse(target, media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------- activity
@router.get("/projects/{project_id}/activity")
async def activity(p: P, c: C) -> list[dict[str, Any]]:
    rows = await c.accounts.activity(p.id)
    return [
        {"timestamp": r.timestamp, "user_id": r.user_id, "action": r.action, "detail": r.detail}
        for r in rows
    ]

"""Composition root: builds every service once and hands them to the routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from requirements_architect.agent.approvals import ApprovalError, ApprovalService
from requirements_architect.agent.documentation import DocumentationError, DocumentationService
from requirements_architect.agent.service import (
    AnswerValidationError,
    WorkflowService,
    WorkflowStateError,
)
from requirements_architect.agent.workflow import build_workflow
from requirements_architect.api.auth import AuthService
from requirements_architect.api.jobs import JobRunner
from requirements_architect.audit.service import AuditError, AuditLimits, AuditService
from requirements_architect.core.config import Settings
from requirements_architect.core.security import RateLimiter
from requirements_architect.llm.factory import build_gateway
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.llm.types import LLMError
from requirements_architect.research.factory import build_research_service
from requirements_architect.storage.accounts import AccountRepository
from requirements_architect.storage.approvals import ApprovalRepository
from requirements_architect.storage.database import make_engine, make_session_factory
from requirements_architect.storage.repository import Repository

DOMAIN_ERRORS: tuple[type[Exception], ...] = (
    LLMError,  # messages are documented to never hold credentials or provider bodies
    ApprovalError,
    AnswerValidationError,
    AuditError,
    DocumentationError,
    WorkflowStateError,
)


@dataclass
class Container:
    settings: Settings
    repo: Repository
    accounts: AccountRepository
    auth: AuthService
    approvals: ApprovalService
    docs: DocumentationService
    jobs: JobRunner
    expensive: RateLimiter  # per user: operations that call the LLM
    output_dir: Path
    engine: AsyncEngine
    workflow: WorkflowService | None = None  # None when no LLM is configured
    audit: AuditService | None = None


def assemble(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    *,
    workflow: WorkflowService | None,
    audit: AuditService | None,
    approvals_gateway: LLMGateway | None = None,
) -> Container:
    repo = Repository(factory)
    accounts = AccountRepository(factory)
    approvals = ApprovalService(repo, ApprovalRepository(factory), approvals_gateway)
    out = Path(settings.output_dir)
    return Container(
        settings=settings,
        repo=repo,
        accounts=accounts,
        auth=AuthService(accounts, timedelta(hours=settings.session_ttl_hours)),
        approvals=approvals,
        docs=DocumentationService(repo, out, approvals),
        jobs=JobRunner(DOMAIN_ERRORS),
        expensive=RateLimiter(limit=20, window_seconds=3600),
        output_dir=out,
        engine=engine,
        workflow=workflow,
        audit=audit,
    )


@asynccontextmanager
async def open_container(settings: Settings) -> AsyncIterator[Container]:
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    repo = Repository(factory)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    async with (
        httpx.AsyncClient() as llm_client,
        httpx.AsyncClient() as api_client,
        httpx.AsyncClient(follow_redirects=False) as fetch_client,
    ):
        if not settings.llm_configured:
            yield assemble(settings, factory, engine, workflow=None, audit=None)
        else:
            gateway = build_gateway(settings, llm_client)
            research = build_research_service(settings, repo, gateway, api_client, fetch_client)
            ckpt = Path(settings.checkpoint_path)
            ckpt.parent.mkdir(parents=True, exist_ok=True)
            async with AsyncSqliteSaver.from_conn_string(str(ckpt)) as saver:
                graph = build_workflow(gateway, repo, saver, research=research)
                c = assemble(
                    settings,
                    factory,
                    engine,
                    workflow=WorkflowService(graph, repo),
                    audit=AuditService(repo, gateway, AuditLimits.from_settings(settings)),
                    approvals_gateway=gateway,
                )
                yield c
    await engine.dispose()

"""One background job per project (long LLM runs must not block a request).

State is in-process: a restart loses the job record, but every result is persisted by the
services themselves, so the project status remains the source of truth."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

log = structlog.get_logger()


class JobBusyError(Exception):
    pass


@dataclass
class Job:
    kind: str
    state: str  # running | succeeded | failed
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None


class JobRunner:
    def __init__(self, safe_errors: tuple[type[Exception], ...] = ()) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._safe = safe_errors

    def get(self, project_id: str) -> Job | None:
        return self._jobs.get(project_id)

    def start(self, project_id: str, kind: str, work: Callable[[], Awaitable[object]]) -> Job:
        current = self._jobs.get(project_id)
        if current and current.state == "running":
            raise JobBusyError(f"a {current.kind} job is already running for this project")
        job = Job(kind, "running", datetime.now(UTC))
        self._jobs[project_id] = job

        async def run() -> None:
            try:
                await work()
                job.state = "succeeded"
            except Exception as exc:  # noqa: BLE001 - task boundary: record, never crash the loop
                job.state = "failed"
                # Only our own domain errors carry safe, user-oriented messages.
                job.error = str(exc)[:500] if isinstance(exc, self._safe) else "internal error"
                log.error(
                    "job_failed", project_id=project_id, kind=kind, error_type=type(exc).__name__
                )
            finally:
                job.finished_at = datetime.now(UTC)

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

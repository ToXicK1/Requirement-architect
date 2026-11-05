"""In-process usage ledger. Durable persistence is added with the ORM models in Phase 3."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger()


class UsageRecord(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provider: str
    model: str
    prompt_id: str
    prompt_version: str
    project_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal | None = None
    latency_seconds: float = 0.0
    success: bool = True
    error_type: str | None = None
    attempt: int = 1


UsageSink = Callable[[UsageRecord], Awaitable[None]]


class UsageTracker:
    """In-memory ledger with an optional durable sink. A failing sink never breaks an LLM call."""

    def __init__(self, sink: UsageSink | None = None) -> None:
        self._records: list[UsageRecord] = []
        self._lock = asyncio.Lock()
        self._sink = sink

    async def record(self, rec: UsageRecord) -> None:
        async with self._lock:
            self._records.append(rec)
        if self._sink is not None:
            try:
                await self._sink(rec)
            except Exception:  # noqa: BLE001 - accounting must not take down the workflow
                log.error("usage_sink_failed", provider=rec.provider, model=rec.model)

    @property
    def records(self) -> list[UsageRecord]:
        return list(self._records)

    def total_tokens(self) -> tuple[int, int]:
        return (
            sum(r.input_tokens for r in self._records),
            sum(r.output_tokens for r in self._records),
        )

    def total_cost_usd(self) -> Decimal:
        """Sum of *known* costs only; calls with unknown pricing are excluded."""
        return sum((r.estimated_cost_usd or Decimal(0) for r in self._records), Decimal(0))

    def unpriced_calls(self) -> int:
        return sum(1 for r in self._records if r.success and r.estimated_cost_usd is None)

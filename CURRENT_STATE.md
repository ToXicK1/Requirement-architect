# Current State
- **Phase:** 3 (core agent, stages 1-2) implemented and tested; next Phase 4 (research).
- **Completed:** P1-01..05, P2-01..06, P3-01..07 (TESTED).
- **Known issues / unverified:**
  - Docker/compose never built (no Docker). PostgreSQL unavailable: DB layer, migrations and LangGraph checkpointing verified on SQLite only; Postgres checkpointer (langgraph-checkpoint-postgres) not yet added.
  - Prompts and LLM adapters never exercised against a real model.
  - WorkflowService lock is in-process; multi-worker deployments need a DB-level lock/lease (Phase 10).
  - No HTTP endpoints for projects/workflow yet (Phase 9). No auth yet; `owner_id` column exists but is unused.
  - Workflow currently ends at `ready_for_research`; stages 3-11 are not built.
- **Resume:**
  ```
  cd requirements-architect && python3 -m venv .venv && . .venv/bin/activate
  pip install -e ".[dev]" && pytest -q && ruff check . && mypy src
  ```
- **Last verified results:** pytest 75 passed; ruff clean; mypy strict clean (33 files); alembic up/down/check OK on SQLite.
- **External deps needed:** LLM key (live runs); PostgreSQL/Docker host (production verification); optional search API key (Phase 4).
- **Next actions:** Phase 4: URL validator + SSRF-safe fetcher (scheme/domain allowlist, private-IP + DNS-rebinding checks, size/time limits, redirect re-validation), safe content extraction/sanitization, evidence registry (source id/url/title/type/date/claim/verification/reliability), research provider interface with adapters (web search, GitHub, package registries), prompt-injection handling for retrieved content.

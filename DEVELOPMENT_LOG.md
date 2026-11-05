# Development Log
## Session 1 - Phase 1 foundation
- Environment: Python 3.12.3, git 2.43. NO Docker, NO PostgreSQL in sandbox.
- Built: config (startup validation), structlog + redaction, async DB layer, health endpoints, Alembic async wiring, Dockerfile, compose.
- Failures hit & fixed: sh vs bash brace expansion (files not created, recreated); missing greenlet (sqlalchemy[asyncio]); mypy type on log processor; alembic.ini script_location; ruff SIM117.
- Tests: 9 passed (5 config, 1 logging, 3 health). ruff clean, mypy strict clean.
- Remaining: Docker build and PostgreSQL run unverified; no ORM models/migrations yet (Phase 3).

## Session 2 - Phase 2 LLM infrastructure
- Built llm package (types, provider protocol, 2 adapters, gateway, pricing, usage, factory) + config validation.
- Tests: 48 passed total (39 new). ruff + mypy strict clean.
- Failure: one test expected specific timeout type after exhaustion; gateway intentionally raises aggregate error; test corrected (behavior unchanged).
- Not verified: live API calls; prompt version *files* (loader comes with agent stages in P3); usage persistence.

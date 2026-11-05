# Architecture Decision Records
## ADR-001: Modular monolith, FastAPI + SQLAlchemy 2 async
Per master spec. Alternatives (microservices) rejected: unnecessary for v1.
## ADR-002: SQLite (aiosqlite) for tests, PostgreSQL (asyncpg) for production
Sandbox has no PostgreSQL. Production config validator rejects SQLite. PG behavior must be verified separately.
## ADR-003: structlog JSON logging with key-based secret redaction
Redaction is key-name based; free-text secrets in messages are not caught. Residual risk noted.

## ADR-004: Own thin gateway over raw HTTP (httpx) instead of vendor SDKs
Keeps provider-independence, one error taxonomy and full control of retries/timeouts; avoids pulling a vendor SDK into agent logic. Trade-off: we maintain two small adapters and must track API changes. Alternatives: LiteLLM, vendor SDKs.
## ADR-005: Separate `llm` package
Master spec lists package folders as examples of modularity; the gateway is a distinct cross-cutting concern, so it gets its own package rather than living in `core`.
## ADR-006: No built-in model names or prices
Models and prices change; the operator supplies LLM_MODEL and LLM_PRICE_TABLE_JSON. Unpriced calls are reported as unknown, not estimated.
## ADR-007: Fallback only on transient/rate-limit/timeout failures
Permanent errors (auth, bad request) fail fast so misconfiguration is not hidden by silently switching vendors.

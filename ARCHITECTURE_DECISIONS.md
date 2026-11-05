# Architecture Decision Records
## ADR-001: Modular monolith, FastAPI + SQLAlchemy 2 async
Per master spec. Alternatives (microservices) rejected: unnecessary for v1.
## ADR-002: SQLite (aiosqlite) for tests, PostgreSQL (asyncpg) for production
Sandbox has no PostgreSQL. Production config validator rejects SQLite. PG behavior must be verified separately.
## ADR-003: structlog JSON logging with key-based secret redaction
Redaction is key-name based; free-text secrets in messages are not caught. Residual risk noted.

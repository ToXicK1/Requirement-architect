# Task Tracker
Statuses: NOT_STARTED, IN_PROGRESS, BLOCKED, IMPLEMENTED, TESTED, VERIFIED

| ID | Task | Pri | Status | Deps | Notes / Test status |
|---|---|---|---|---|---|
| P1-01 | Repo structure + pyproject | H | TESTED | - | see CURRENT_STATE |
| P1-02 | Settings w/ startup validation | H | TESTED | P1-01 | 5 unit tests |
| P1-03 | Structured logging + redaction | H | TESTED | P1-01 | 1 unit test |
| P1-04 | Async DB layer | H | TESTED | P1-01 | via health tests (SQLite only) |
| P1-05 | Health endpoints | H | TESTED | P1-04 | 3 integration tests |
| P1-06 | Alembic async config | H | IN_PROGRESS | P1-04 | no migrations yet (no models) |
| P1-07 | Dockerfile + compose | M | IMPLEMENTED | P1-01 | NOT built: Docker unavailable in sandbox |
| P1-08 | PostgreSQL verification | H | BLOCKED | P1-04 | no PostgreSQL/Docker in sandbox |
| P2-01 | Provider interface + types/error taxonomy | H | TESTED | P1 | |
| P2-02 | Anthropic + OpenAI-compatible adapters | H | TESTED | P2-01 | httpx.MockTransport only; NOT run against live APIs (no key) |
| P2-03 | Gateway: timeout, bounded retry/backoff, rate limits, fallback, concurrency cap | H | TESTED | P2-01 | 12 unit tests incl. bounded-attempt checks |
| P2-04 | Structured output (JSON schema, fence strip, bounded re-ask) | H | TESTED | P2-03 | |
| P2-05 | Usage + cost tracking (operator price table, unknown = None) | H | TESTED | P2-03 | in-memory only; DB persistence in P3 |
| P2-06 | Config validation + factory | H | TESTED | P2-01 | prod requires LLM config |
| P2-07 | Live provider smoke test | H | BLOCKED | P2-02 | needs real LLM_API_KEY |
| P3-* | Project state, workflow, checkpoints | H | NOT_STARTED | P2 | |

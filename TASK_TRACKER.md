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
| P2-* | LLM gateway | H | NOT_STARTED | P1 | |

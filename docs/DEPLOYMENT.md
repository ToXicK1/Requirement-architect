# Deployment

Supported shape: **one instance** of the API process behind a TLS-terminating reverse proxy, PostgreSQL, one persistent volume. Do not run several API replicas: background jobs, rate limits and workflow/approval locks are in-process (ADR-042/044), and the LangGraph checkpointer is a SQLite file (ADR-048).

## Requirements
- Python 3.12+ (or the Docker image), PostgreSQL 16 for production (SQLite is refused when `APP_ENV=production`).
- An LLM provider key. Production refuses to start without `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` and a `SECRET_KEY` of 32+ characters.
- Persistent storage for `OUTPUT_DIR` (generated packages) and `CHECKPOINT_PATH` (workflow state).

## Docker Compose
```
cp .env.example .env        # fill LLM_*, SECRET_KEY, set APP_ENV is forced to production by compose
export POSTGRES_PASSWORD=...  # long random value, not committed
docker compose up -d --build
docker compose exec api python -m requirements_architect create-user NAME   # prompts for the password
```
The API listens on 127.0.0.1:8000 only. Put a reverse proxy (TLS, HTTP/2, request logging) in front. Migrations run at every container start.

## Reverse proxy and client addresses
Rate limits are per client address. Behind a proxy every request appears to come from the proxy, so one user's failed logins could lock everybody out. If, and only if, exactly one trusted proxy sits in front and appends the real client address to `X-Forwarded-For`, set `TRUST_FORWARDED_FOR=true`: the **last** entry is used (earlier entries are client-controlled). Never enable it when the API is directly reachable.

## Settings that matter
| Setting | Meaning |
|---|---|
| `ALLOW_REGISTRATION` | false by default; create users with the CLI |
| `SESSION_TTL_HOURS` | session lifetime (default 12) |
| `AUDIT_MAX_ROUNDS`, `AUDIT_MAX_STAGE_RUNS` | cap LLM spend during audit remediation |
| `LLM_MAX_CONCURRENCY`, `LLM_MAX_ATTEMPTS`, `LLM_TIMEOUT_SECONDS` | provider load and retries |
| `RESEARCH_*`, `BRAVE_API_KEY`, `GITHUB_TOKEN` | optional research providers |

## Network egress
The research fetcher blocks private/loopback/metadata addresses in application code (SSRF guard), but that is one layer. In production also restrict egress at the network level to the LLM provider and the research hosts you use.

## What was and was not verified
Verified on this project's build host: migrations up/down/check and the whole test suite on PostgreSQL 16; the server started in `APP_ENV=production` on PostgreSQL (docs/openapi disabled, readiness OK, an invalid key produced a readable 401 and no key in logs); compose file syntax. **Not verified:** `docker build`/`docker compose up` (no Docker daemon was available), TLS/proxy setup, behavior under real load.

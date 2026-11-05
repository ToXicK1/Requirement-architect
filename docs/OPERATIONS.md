# Operations

## What to back up
1. **PostgreSQL** (all projects, specs, approvals, users, activity).
2. **`/data/output`** (generated packages; reproducible from the database, but versioned deliverables people may have downloaded).
3. **`/data/checkpoints.db`** (LangGraph workflow state; needed to resume a paused/failed workflow, not to read results).
4. `.env` / secrets in your secret manager (never in the backup bundle).

## Backup (verified procedure)
```
pg_dump -Fc "$DB_NAME" -f ra-$(date +%F).dump
tar czf data-$(date +%F).tar.gz /data           # stop writes or accept a crash-consistent copy
```
Take the database dump before the volume copy.

## Restore (verified for the database part)
```
createdb ra_restore
pg_restore -d ra_restore --no-owner ra-YYYY-MM-DD.dump
# compare: select count(*) from users, projects; select version_num from alembic_version;
```
On the build host a dump of a production-mode database restored with identical row counts and the same migration revision. Restoring the volume tarball and a full disaster-recovery drill (new host, new containers) were **not** exercised. Run one before relying on this.

After restoring: point `DATABASE_URL` at the restored database, restore `/data`, start the API (migrations run), log in. A workflow that was running at backup time shows as failed; use **Retry**.

## Upgrades
Take a backup, deploy the new image (migrations run at start), check `/health/ready`. Downgrade migrations exist but data written by newer code may not fit older schemas: restore from backup rather than downgrading in production.

## Users and sessions
- Create: `python -m requirements_architect create-user NAME` (password from a prompt or `--password-stdin`).
- There is no password-reset or user-disable command yet. To lock out an account: `update users set is_active=false where username='x'` (and `update sessions set revoked=true where user_id=...`).
- Sessions are server-side; revoking rows ends them immediately.

## Health and logs
`/health/live` (process), `/health/ready` (database). Logs are JSON (structlog). Job failures log `job_failed` / `workflow_failed` with a scrubbed, truncated reason; the API shows the same reason only for our own error types and LLM gateway errors, otherwise "internal error".

## Cost control
Every LLM call is recorded in `llm_usage` (tokens, estimated cost when `LLM_PRICE_TABLE_JSON` has the model). Per-user limit: 20 generation operations per hour. Audit remediation is bounded by `AUDIT_MAX_ROUNDS` and `AUDIT_MAX_STAGE_RUNS`.

## Restart behavior
A restart loses job records and any in-flight run. The project status stays `running` or `failed`; use **Retry** (resumes from the last checkpoint). Documents and audits are idempotent and can be re-run.

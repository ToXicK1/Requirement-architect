#!/bin/sh
# Apply migrations, then start the server. Migrations run on every start (idempotent).
set -eu
alembic upgrade head
exec uvicorn requirements_architect.main:app --host 0.0.0.0 --port 8000 --no-server-header

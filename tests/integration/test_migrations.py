import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _alembic(db: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "APP_ENV": "test"}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, check=True, capture_output=True
    )


def _tables(db: Path) -> set[str]:
    return {
        r[0]
        for r in sqlite3.connect(db).execute("select name from sqlite_master where type='table'")
    }


def test_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "head")
    assert {"projects", "stage_outputs", "clarification_answers", "llm_usage"} <= _tables(db)
    _alembic(db, "downgrade", "base")
    assert _tables(db) == {"alembic_version"}


def test_models_match_migration(tmp_path):
    """`alembic check` fails if the ORM models drift from the migration history."""
    db = tmp_path / "c.db"
    _alembic(db, "upgrade", "head")
    _alembic(db, "check")

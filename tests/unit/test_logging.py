import json

import structlog

from requirements_architect.core.logging import configure_logging


def test_secrets_are_redacted(capsys):
    configure_logging("INFO")
    structlog.get_logger().info("evt", api_key="sk-123", password="pw", note="ok")
    out = capsys.readouterr().out
    assert "sk-123" not in out and "pw" not in out.replace("password", "")
    data = json.loads(out.strip().splitlines()[-1])
    assert data["api_key"] == "***REDACTED***" and data["note"] == "ok"

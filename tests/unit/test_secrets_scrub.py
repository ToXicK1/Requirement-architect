import pytest

from requirements_architect.validation.secrets import scrub


@pytest.mark.parametrize(
    "text",
    [
        "key sk-abcdefghijklmnop1234",
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_" + "a" * 36,
        "-----BEGIN RSA PRIVATE KEY-----",
        "Authorization: Bearer abcdefghijklmnopqrstuvwx",
        "password = hunter2hunter2",
        "API_KEY: abc123def456",
        "postgres://admin:s3cretpw@db.internal/app",
    ],
)
def test_secret_shapes_are_redacted(text):
    out, found = scrub(text)
    assert found and "[REDACTED]" in out
    for fragment in ("abcdefghijklmnop1234", "hunter2hunter2", "s3cretpw", "abc123def456"):
        assert fragment not in out


@pytest.mark.parametrize(
    "text",
    [
        "Store the password in a secrets manager",
        "Use DATABASE_URL for the connection string",
        "postgres://db.internal/app",
        "token refresh happens hourly",
        "",
    ],
)
def test_ordinary_prose_is_untouched(text):
    assert scrub(text) == (text, False)

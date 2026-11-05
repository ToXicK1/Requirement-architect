import pytest

from requirements_architect.core.security import (
    PasswordPolicyError,
    RateLimiter,
    check_password_policy,
    hash_password,
    new_token,
    normalize_username,
    token_hash,
    verify_password,
)


def test_hash_verifies_and_is_salted():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password("correct horse battery", h1)
    assert not verify_password("correct horse batterz", h1)
    assert "correct" not in h1


@pytest.mark.parametrize("bad", ["", "plain", "scrypt$1$2", "scrypt$x$y$z$!!$!!", "md5$a$b$c$d$e"])
def test_malformed_stored_hashes_never_verify_or_raise(bad):
    assert verify_password("anything", bad) is False


@pytest.mark.parametrize("pw", ["short", "a" * 11, "x" * 201, "aaaaaaaaaaaaaaaa"])
def test_weak_passwords_are_rejected(pw):
    with pytest.raises(PasswordPolicyError):
        check_password_policy(pw)


def test_acceptable_password_passes():
    check_password_policy("a reasonable passphrase 42")


@pytest.mark.parametrize("raw,expect", [("  Alice ", "alice"), ("bob.smith-1", "bob.smith-1")])
def test_usernames_are_normalized(raw, expect):
    assert normalize_username(raw) == expect


@pytest.mark.parametrize("bad", ["ab", "-bad", "has space", "a" * 41, "ünï", "a/b", ""])
def test_bad_usernames_rejected(bad):
    with pytest.raises(ValueError):
        normalize_username(bad)


def test_tokens_are_random_and_hash_is_stable_and_not_the_token():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 40
    assert token_hash(a) == token_hash(a) and token_hash(a) != a and len(token_hash(a)) == 64


def test_rate_limiter_window_and_independent_keys():
    now = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: now[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    assert rl.allow("b")
    now[0] = 10.0
    assert rl.allow("a")
    rl.reset("a")
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")

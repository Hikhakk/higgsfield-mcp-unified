from __future__ import annotations

from higgsfield_mcp.backends.base import BackendError
from higgsfield_mcp.errors import (
    AuthError,
    BotChallengeError,
    RateLimitError,
    classify_http,
    parse_retry_after,
)


def test_parse_retry_after_seconds() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("not-a-number") is None


def test_classify_401_is_auth_error() -> None:
    err = classify_http(401, body="bad key")
    assert isinstance(err, AuthError)
    assert err.status_code == 401


def test_classify_403_cloudflare_is_bot_challenge() -> None:
    err = classify_http(403, body="Just a moment...", headers={"cf-mitigated": "challenge"})
    assert isinstance(err, BotChallengeError)


def test_classify_403_plain_is_auth_error() -> None:
    err = classify_http(403, body="forbidden")
    assert isinstance(err, AuthError)


def test_classify_429_carries_retry_after() -> None:
    err = classify_http(429, headers={"retry-after": "5"})
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 5.0


def test_classify_500_is_plain_backend_error() -> None:
    err = classify_http(500, body="boom")
    assert isinstance(err, BackendError)
    assert not isinstance(err, (AuthError, RateLimitError, BotChallengeError))
    assert err.status_code == 500

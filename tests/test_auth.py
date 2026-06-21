from __future__ import annotations

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.auth.clerk import JWTAuth


def test_v2_header_unchanged() -> None:
    auth = ApiKeyAuth(api_key="k", secret="s")
    assert auth.header == "Key k:s"


def test_v1_headers_use_split_scheme() -> None:
    auth = ApiKeyAuth(api_key="k", secret="s")
    assert auth.v1_headers == {"hf-api-key": "k", "hf-secret": "s"}


def test_clerk_default_slack_is_10s() -> None:
    # exp 5s in the future: with 10s slack it is considered expired
    import time

    auth = JWTAuth(jwt="a.b.c", expires_at=time.time() + 5)
    assert auth.is_expired() is True
    # exp 20s in the future: not expired under 10s slack
    auth2 = JWTAuth(jwt="a.b.c", expires_at=time.time() + 20)
    assert auth2.is_expired() is False

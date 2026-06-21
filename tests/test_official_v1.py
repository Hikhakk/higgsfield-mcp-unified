from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.errors import AuthError


@pytest.fixture
def auth() -> ApiKeyAuth:
    return ApiKeyAuth(api_key="kid", secret="sec")


@pytest.mark.asyncio
async def test_v1_request_uses_split_headers(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.get("/v1/motions").mock(
                return_value=httpx.Response(200, json={"motions": []})
            )
            await backend._v1_request("GET", "/v1/motions")
        req = route.calls.last.request
        assert req.headers["hf-api-key"] == "kid"
        assert req.headers["hf-secret"] == "sec"
        assert req.headers.get("Authorization") is None  # v1 must NOT send the Key scheme
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_v1_request_classifies_401(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.post("/v1/billing/credits").mock(return_value=httpx.Response(401, text="bad"))
            with pytest.raises(AuthError):
                await backend._v1_request("POST", "/v1/billing/credits", json={})
    finally:
        await backend.aclose()

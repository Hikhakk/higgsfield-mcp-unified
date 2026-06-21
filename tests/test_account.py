from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import BackendPool, get_balance, list_soul_styles


@pytest.fixture
def pool():
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="kid", secret="sec"))
    return p


@pytest.mark.asyncio
async def test_get_balance_defensive(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/billing/credits").mock(
            return_value=httpx.Response(200, json={"credits": 1234, "plan": "pro"})
        )
        out = await get_balance(pool)
    assert out["credits"] == 1234
    assert out["plan"] == "pro"
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_soul_styles_handles_list_or_dict(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/v1/text2image/soul-styles").mock(
            return_value=httpx.Response(200, json=["cinematic", "anime", "noir"])
        )
        out = await list_soul_styles(pool)
    assert out["count"] == 3
    assert "cinematic" in out["names"]
    await pool.aclose()

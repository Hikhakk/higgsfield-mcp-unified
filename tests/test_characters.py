from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import (
    create_character,
    delete_character,
    list_characters,
)


@pytest.fixture
def auth() -> ApiKeyAuth:
    return ApiKeyAuth(api_key="kid", secret="sec")


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch, auth: ApiKeyAuth):
    from higgsfield_mcp.tools import BackendPool

    p = BackendPool()
    p._official = OfficialBackend(auth=auth)
    return p


@pytest.mark.asyncio
async def test_create_character(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/v1/custom-references").mock(
            return_value=httpx.Response(200, json={"id": "soul-1", "status": "queued"})
        )
        out = await create_character(pool, name="Ada", image_urls=["https://x/1.png"])
    assert out["id"] == "soul-1"
    body = route.calls.last.request
    assert body.headers["hf-api-key"] == "kid"
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_characters_defensive(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/v1/custom-references/list").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": "soul-1", "name": "Ada", "status": "ready"}]}
            )
        )
        out = await list_characters(pool)
    assert out["count"] == 1
    assert out["characters"][0]["id"] == "soul-1"
    await pool.aclose()


@pytest.mark.asyncio
async def test_delete_character(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.delete("/v1/custom-references/soul-1").mock(return_value=httpx.Response(200, json={}))
        out = await delete_character(pool, character_id="soul-1")
    assert out == {"deleted": True, "character_id": "soul-1"}
    await pool.aclose()

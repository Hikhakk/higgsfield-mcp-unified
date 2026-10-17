from __future__ import annotations

import json

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import BackendPool, generate_batch, generate_image, generate_video


@pytest.fixture
def pool() -> BackendPool:
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="k", secret="s"))
    return p


@pytest.mark.asyncio
async def test_extra_params_pass_through_filtered(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/alibaba/qwen-image-3/edit").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        await generate_image(
            pool,
            model_id="alibaba/qwen-image-3/edit",
            prompt="p",
            extra_params={"image_urls": ["https://x/1.png"], "bogus": 1},
        )
    assert json.loads(route.calls.last.request.content) == {
        "prompt": "p",
        "image_urls": ["https://x/1.png"],
    }
    await pool.aclose()


@pytest.mark.asyncio
async def test_official_sound_bool_becomes_enum(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/kling-video/v3.0/pro/text-to-video").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        await generate_video(
            pool, model_id="kling-video/v3.0/pro/text-to-video", prompt="p", sound=False
        )
    assert json.loads(route.calls.last.request.content)["sound"] == "off"
    await pool.aclose()


@pytest.mark.asyncio
async def test_video_without_prompt(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/higgsfield/genjutsu/motion-transfer/v1.0").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        out = await generate_batch(
            pool,
            [
                {
                    "kind": "video",
                    "model_id": "higgsfield/genjutsu/motion-transfer/v1.0",
                    "extra_params": {
                        "video_url": "https://x/v.mp4",
                        "image_urls": ["https://x/1.png"],
                    },
                }
            ],
        )
    assert out["results"][0]["ok"] is True
    assert json.loads(route.calls.last.request.content) == {
        "video_url": "https://x/v.mp4",
        "image_urls": ["https://x/1.png"],
    }
    await pool.aclose()

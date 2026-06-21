from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import BackendPool, generate_speech_video


@pytest.fixture
def pool():
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="kid", secret="sec"))
    return p


@pytest.mark.asyncio
async def test_generate_speech_video(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/speak/higgsfield").mock(
            return_value=httpx.Response(200, json={"request_id": "spk-1"})
        )
        out = await generate_speech_video(
            pool, image_url="https://x/face.png", audio_url="https://x/a.wav"
        )
    assert out["job_handle"] == "official:spk-1"
    assert out["backend"] == "official"
    await pool.aclose()

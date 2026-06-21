from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import BackendPool, generate_batch


@pytest.fixture
def pool() -> BackendPool:
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="k", secret="s"))
    return p


@pytest.mark.asyncio
async def test_generate_batch_mixed_ok_and_error(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/higgsfield-ai/soul/standard").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        out = await generate_batch(
            pool,
            [
                {"kind": "image", "model_id": "higgsfield-ai/soul/standard", "prompt": "a"},
                {"kind": "image", "model_id": "higgsfield-ai/soul/standard", "prompt": "b"},
                {"kind": "image", "model_id": "higgsfield-ai/soul/standard"},  # missing prompt
            ],
        )
    assert out["count"] == 3
    oks = [r for r in out["results"] if r["ok"]]
    bad = [r for r in out["results"] if not r["ok"]]
    assert len(oks) == 2
    assert all(r["job_handle"] == "official:r" for r in oks)
    assert len(bad) == 1
    assert "model_id" in bad[0]["error"]
    await pool.aclose()

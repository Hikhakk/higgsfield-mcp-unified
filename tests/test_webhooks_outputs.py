"""Webhooks, extra outputs, polling backoff and upload checks (docs.higgsfield.ai)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.base import JobHandle, JobStatus
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.errors import RateLimitError
from higgsfield_mcp.models import REGISTRY
from higgsfield_mcp.tools import (
    BackendPool,
    generate_batch,
    generate_image,
    generate_video,
    subscribe,
    upload_image,
)


@pytest.fixture
def pool() -> BackendPool:
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="k", secret="s"))
    return p


@pytest.mark.asyncio
async def test_webhook_sent_as_hf_webhook_query(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/higgsfield-ai/soul/v2/standard").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        await generate_image(
            pool,
            model_id="higgsfield-ai/soul/v2/standard",
            prompt="p",
            webhook_url="https://example.com/hooks/hf?x=1",
        )
    url = route.calls.last.request.url
    assert url.path == "/higgsfield-ai/soul/v2/standard"
    assert url.params["hf_webhook"] == "https://example.com/hooks/hf?x=1"
    await pool.aclose()


@pytest.mark.asyncio
async def test_no_webhook_means_no_query(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/higgsfield-ai/soul/v2/standard").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        await generate_image(pool, model_id="higgsfield-ai/soul/v2/standard", prompt="p")
    assert "hf_webhook" not in route.calls.last.request.url.params
    await pool.aclose()


@pytest.mark.asyncio
async def test_webhook_must_be_https(pool: BackendPool) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        await generate_video(
            pool,
            model_id="kling-video/v3.0/pro/text-to-video",
            prompt="p",
            webhook_url="http://example.com/hook",
        )


@pytest.mark.asyncio
async def test_webhook_rejected_for_web_models(pool: BackendPool) -> None:
    with pytest.raises(ValueError, match="official"):
        await generate_video(
            pool, model_id="sora2-video", prompt="p", webhook_url="https://example.com/hook"
        )


@pytest.mark.asyncio
async def test_batch_forwards_webhook(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/bytedance/seedance-2.5/text-to-video").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        out = await generate_batch(
            pool,
            [
                {
                    "kind": "video",
                    "model_id": "bytedance/seedance-2.5/text-to-video",
                    "prompt": "p",
                    "webhook_url": "https://example.com/hook",
                }
            ],
        )
    assert out["results"][0]["ok"] is True
    assert route.calls.last.request.url.params["hf_webhook"] == "https://example.com/hook"
    await pool.aclose()


@pytest.mark.asyncio
async def test_status_surfaces_audio_and_artifacts(pool: BackendPool) -> None:
    body = {
        "status": "completed",
        "request_id": "r",
        "video": {"url": "https://cdn/v.mp4"},
        "audio": {"url": "https://cdn/a.mp3"},
        "audios": [{"url": "https://cdn/a.mp3"}, {"url": "https://cdn/b.mp3"}],
        "zip": {"url": "https://cdn/out.zip"},
        "mov": "https://cdn/out.mov",
        "fbx": [{"url": "https://cdn/1.fbx"}, {"url": "https://cdn/2.fbx"}],
    }
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/requests/r/status").mock(return_value=httpx.Response(200, json=body))
        out = await subscribe(pool, "official:r")
    assert out["state"] == "completed"
    assert out["video_url"] == "https://cdn/v.mp4"
    assert out["audio_urls"] == ["https://cdn/a.mp3", "https://cdn/b.mp3"]
    assert out["artifacts"] == {
        "zip": ["https://cdn/out.zip"],
        "mov": ["https://cdn/out.mov"],
        "fbx": ["https://cdn/1.fbx", "https://cdn/2.fbx"],
    }
    await pool.aclose()


@pytest.mark.asyncio
async def test_canceled_spelling_is_terminal(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/requests/r/status").mock(
            return_value=httpx.Response(200, json={"status": "canceled", "request_id": "r"})
        )
        out = await subscribe(pool, "official:r")
    assert out["state"] == "cancelled"
    await pool.aclose()


@pytest.mark.asyncio
async def test_subscribe_backs_off_to_ten_seconds(
    pool: BackendPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []
    states = iter(["queued"] * 7 + ["completed"])

    async def fake_status(handle: JobHandle) -> JobStatus:
        return JobStatus(state=next(states))  # type: ignore[arg-type]

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(pool.get("official"), "status", fake_status)
    monkeypatch.setattr("higgsfield_mcp.tools.asyncio.sleep", fake_sleep)
    await subscribe(pool, "official:r")
    assert sleeps[0] == 2.0
    assert sleeps == sorted(sleeps)
    assert max(sleeps) == 10.0
    await pool.aclose()


@pytest.mark.asyncio
async def test_submit_retries_500_with_same_idempotency_key() -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/v2/standard")
    backend = OfficialBackend(auth=ApiKeyAuth(api_key="k", secret="s"))
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(f"/{spec.endpoint}").mock(
                side_effect=[
                    httpx.Response(500, headers={"retry-after": "0"}),
                    httpx.Response(200, json={"request_id": "ok"}),
                ]
            )
            handle = await backend.submit(spec, {"prompt": "p"})
        assert handle.request_id == "ok"
        assert len({c.request.headers["idempotency-key"] for c in route.calls}) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_concurrency_400_is_rate_limit() -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/v2/standard")
    backend = OfficialBackend(auth=ApiKeyAuth(api_key="k", secret="s"))
    detail: dict[str, Any] = {
        "detail": "Maximum number of concurrent requests (4) has been reached"
    }
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(f"/{spec.endpoint}").mock(
                return_value=httpx.Response(400, json=detail)
            )
            with pytest.raises(RateLimitError, match="Concurrency"):
                await backend.submit(spec, {"prompt": "p"})
        assert route.call_count == 1  # 400 is not auto-retried
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_upload_defaults_to_official_and_accepts_video(pool: BackendPool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        presign = mock.post("/files/generate-upload-url").mock(
            return_value=httpx.Response(
                200,
                json={
                    "upload_url": "https://s3.example/put",
                    "public_url": "https://cdn/v.mp4",
                    "upload_headers": {"Content-Type": "video/mp4"},
                },
            )
        )
        mock.put("https://s3.example/put").mock(return_value=httpx.Response(200))
        out = await upload_image(pool, data_base64="AAAA", mime="video/mp4")
    assert out == {"url": "https://cdn/v.mp4", "backend": "official"}
    assert presign.calls.last.request.content == b'{"content_type":"video/mp4"}'
    await pool.aclose()


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_type(pool: BackendPool) -> None:
    with pytest.raises(ValueError, match="Unsupported content type"):
        await upload_image(pool, data_base64="AAAA", mime="application/pdf")


@pytest.mark.asyncio
async def test_estimate_cost(pool: BackendPool) -> None:
    from higgsfield_mcp.tools import estimate_cost

    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/estimate/higgsfield-ai/soul/v2/standard").mock(
            return_value=httpx.Response(200, json={"credits": "1.500", "usd": "0.094"})
        )
        out = await estimate_cost(
            pool, "higgsfield-ai/soul/v2/standard", {"prompt": "p", "bogus": 1}
        )
    assert out["credits"] == "1.500"
    assert out["usd"] == "0.094"
    assert route.calls.last.request.content == b'{"prompt":"p"}'
    assert "idempotency-key" not in route.calls.last.request.headers
    await pool.aclose()


@pytest.mark.asyncio
async def test_estimate_rejects_web_models(pool: BackendPool) -> None:
    from higgsfield_mcp.tools import estimate_cost

    with pytest.raises(ValueError, match="official"):
        await estimate_cost(pool, "sora2-video", {"prompt": "p"})


@pytest.mark.asyncio
async def test_list_presets_restyle(pool: BackendPool) -> None:
    from higgsfield_mcp.tools import list_model_presets

    body = {
        "model": "higgsfield/genjutsu/restyle/v1.0",
        "items": [{"id": "c214", "name": "Cel-Shaded CG Anime", "preview_url": "https://cdn/p"}],
    }
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/models/higgsfield/genjutsu/restyle/v1.0/presets").mock(
            return_value=httpx.Response(200, json=body)
        )
        out = await list_model_presets(pool, "higgsfield/genjutsu/restyle/v1.0")
    assert out["items"][0]["id"] == "c214"
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_presets_marketing_paginates(pool: BackendPool) -> None:
    from higgsfield_mcp.tools import list_model_presets

    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/marketing-studio/image/presets").mock(
            return_value=httpx.Response(
                200, json={"total": 120, "cursor": 50, "items": [{"id": "p1"}]}
            )
        )
        out = await list_model_presets(
            pool, "marketing-studio/image/flare", search="editorial", size=50
        )
    params = route.calls.last.request.url.params
    assert params["search"] == "editorial"
    assert params["size"] == "50"
    assert "cursor" not in params
    assert out["total"] == 120
    assert out["next_cursor"] == 50
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_presets_ai_influencer_categories(pool: BackendPool) -> None:
    from higgsfield_mcp.tools import list_model_presets

    body = {"config_revision": "abc", "categories": [{"key": "gender", "options": []}]}
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/models/higgsfield/ai-influencer/options").mock(
            return_value=httpx.Response(200, json=body)
        )
        out = await list_model_presets(pool, "higgsfield/ai-influencer")
    assert out["items"] == [{"key": "gender", "options": []}]
    assert out["raw"]["config_revision"] == "abc"
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_presets_unknown_model(pool: BackendPool) -> None:
    from higgsfield_mcp.tools import list_model_presets

    with pytest.raises(ValueError, match="No preset catalog"):
        await list_model_presets(pool, "higgsfield-ai/soul/v2/standard")


@pytest.mark.asyncio
async def test_ai_influencer_without_prompt(pool: BackendPool) -> None:
    import json

    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/higgsfield/ai-influencer").mock(
            return_value=httpx.Response(200, json={"request_id": "r"})
        )
        await generate_image(
            pool,
            model_id="higgsfield/ai-influencer",
            extra_params={"tier": "cats", "seed": 42817, "variation_index": 1},
        )
    assert json.loads(route.calls.last.request.content) == {
        "tier": "cats",
        "seed": 42817,
        "variation_index": 1,
    }
    await pool.aclose()

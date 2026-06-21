"""Mocked HTTP tests for the official backend."""

from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.base import BackendError, JobHandle
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.errors import AuthError
from higgsfield_mcp.models import REGISTRY


@pytest.fixture
def auth() -> ApiKeyAuth:
    return ApiKeyAuth(api_key="key", secret="secret")


@pytest.mark.asyncio
async def test_submit_returns_handle(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL, assert_all_called=True) as mock:
            mock.post(f"/{spec.endpoint}").mock(
                return_value=httpx.Response(200, json={"request_id": "abc-123"})
            )
            handle = await backend.submit(spec, {"prompt": "a cat"})
        assert handle.backend == "official"
        assert handle.request_id == "abc-123"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_submit_authorization_header(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(f"/{spec.endpoint}").mock(
                return_value=httpx.Response(200, json={"request_id": "x"})
            )
            await backend.submit(spec, {"prompt": "p"})
        assert route.calls.last.request.headers["Authorization"] == "Key key:secret"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_status_completed_with_image(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.get("/requests/r1/status").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "images": [{"url": "https://cdn/x.png"}],
                    },
                )
            )
            status = await backend.status(JobHandle(backend="official", request_id="r1"))
        assert status.state == "completed"
        assert status.images == ("https://cdn/x.png",)
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_status_completed_with_video(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.get("/requests/r2/status").mock(
                return_value=httpx.Response(
                    200,
                    json={"status": "completed", "video": {"url": "https://cdn/v.mp4"}},
                )
            )
            status = await backend.status(JobHandle(backend="official", request_id="r2"))
        assert status.video_url == "https://cdn/v.mp4"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_cancel(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.post("/requests/r3/cancel").mock(return_value=httpx.Response(204))
            await backend.cancel(JobHandle(backend="official", request_id="r3"))
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_http_error_wrapped(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.post(f"/{spec.endpoint}").mock(return_value=httpx.Response(401, text="bad key"))
            with pytest.raises(BackendError) as excinfo:
                await backend.submit(spec, {"prompt": "p"})
            assert excinfo.value.status_code == 401
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_refuses_web_model(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("sora2-video")
    backend = OfficialBackend(auth=auth)
    try:
        with pytest.raises(BackendError, match="cannot submit web model"):
            await backend.submit(spec, {})
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_401_raises_auth_error(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.post(f"/{spec.endpoint}").mock(return_value=httpx.Response(401, text="bad"))
            with pytest.raises(AuthError):
                await backend.submit(spec, {"prompt": "p"})
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_429_retries_with_constant_idempotency_key(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(f"/{spec.endpoint}").mock(
                side_effect=[
                    httpx.Response(429, headers={"retry-after": "0"}),
                    httpx.Response(200, json={"request_id": "ok-1"}),
                ]
            )
            handle = await backend.submit(spec, {"prompt": "p"})
        assert handle.request_id == "ok-1"
        assert route.call_count == 2
        # the idempotency key is generated once and reused across retries
        keys = {c.request.headers["x-idempotency-key"] for c in route.calls}
        assert len(keys) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_transport_error_retries_then_succeeds(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(f"/{spec.endpoint}").mock(
                side_effect=[
                    httpx.ConnectError("boom"),
                    httpx.Response(200, json={"request_id": "ok-2"}),
                ]
            )
            handle = await backend.submit(spec, {"prompt": "p"})
        assert handle.request_id == "ok-2"
        assert route.call_count == 2
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_upload_two_step(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(f"{BASE_URL}/files/generate-upload-url").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "upload_url": "https://s3.example/put?sig=1",
                        "public_url": "https://cdn.higgsfield/abc.png",
                    },
                )
            )
            put = mock.put("https://s3.example/put").mock(return_value=httpx.Response(200))
            url = await backend.upload(b"\x89PNG...", "image/png")
        assert url == "https://cdn.higgsfield/abc.png"
        assert put.calls.last.request.headers["Content-Type"] == "image/png"
        assert "Authorization" not in put.calls.last.request.headers
    finally:
        await backend.aclose()

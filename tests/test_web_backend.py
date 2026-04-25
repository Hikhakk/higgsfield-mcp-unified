"""Mocked HTTP tests for the web backend."""

from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.clerk import JWTAuth
from higgsfield_mcp.backends.base import BackendError, JobHandle
from higgsfield_mcp.backends.web import (
    BASE_URL,
    ENABLE_FLAG,
    WebBackend,
    WebBackendDisabledError,
)
from higgsfield_mcp.models import REGISTRY


@pytest.fixture(autouse=True)
def enable_web(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLE_FLAG, "1")


@pytest.fixture
def jwt_auth() -> JWTAuth:
    return JWTAuth(jwt="abc.def.ghi", expires_at=None)


@pytest.mark.asyncio
async def test_disabled_without_flag(monkeypatch: pytest.MonkeyPatch, jwt_auth: JWTAuth) -> None:
    monkeypatch.delenv(ENABLE_FLAG)
    with pytest.raises(WebBackendDisabledError):
        WebBackend(auth=jwt_auth)


@pytest.mark.asyncio
async def test_submit_uses_bearer(jwt_auth: JWTAuth) -> None:
    spec = REGISTRY.get("sora2-video")
    backend = WebBackend(auth=jwt_auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(spec.endpoint).mock(
                return_value=httpx.Response(200, json={"job_id": "job_42"})
            )
            handle = await backend.submit(spec, {"prompt": "spaceship"})
        assert handle.backend == "web"
        assert handle.request_id == "job_42"
        sent = route.calls.last.request
        assert sent.headers["Authorization"] == "Bearer abc.def.ghi"
        body = sent.read()
        assert b"sora2-video" in body  # model_id injected into payload
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_status_extracts_video_url(jwt_auth: JWTAuth) -> None:
    backend = WebBackend(auth=jwt_auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.get("/jobs/abc").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "outputs": [{"url": "https://cdn/movie.mp4"}],
                    },
                )
            )
            status = await backend.status(JobHandle(backend="web", request_id="abc"))
        assert status.state == "completed"
        assert status.video_url == "https://cdn/movie.mp4"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_refuses_official_model(jwt_auth: JWTAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = WebBackend(auth=jwt_auth)
    try:
        with pytest.raises(BackendError, match="cannot submit official model"):
            await backend.submit(spec, {})
    finally:
        await backend.aclose()

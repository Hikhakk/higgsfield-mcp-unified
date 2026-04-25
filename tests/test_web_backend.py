"""Pure-function unit tests for the web backend.

The live HTTP layer uses ``curl_cffi`` (Chrome TLS impersonation) to bypass
Datadome on ``fnf.higgsfield.ai``. ``respx`` only intercepts ``httpx``, so the
HTTP path is exercised by the live smoke scripts instead. These tests cover
the deterministic helpers that compose request bodies and parse responses.
"""

from __future__ import annotations

import pytest

from higgsfield_mcp.auth.clerk import JWTAuth
from higgsfield_mcp.backends.base import BackendError
from higgsfield_mcp.backends.web import (
    ENABLE_FLAG,
    V2_MODELS,
    WebBackend,
    WebBackendDisabledError,
    _build_body,
    _extract_job_id,
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
async def test_refuses_official_model(jwt_auth: JWTAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = WebBackend(auth=jwt_auth)
    try:
        with pytest.raises(BackendError, match="cannot submit official model"):
            await backend.submit(spec, {})
    finally:
        await backend.aclose()


def test_v2_body_shape() -> None:
    spec = REGISTRY.get("seedance2")
    body = _build_body(spec, {"prompt": "p"})
    assert body == {"params": {"prompt": "p"}, "use_unlim": False, "use_free_gens": False}


def test_v1_body_shape() -> None:
    spec = REGISTRY.get("sora2-video")
    body = _build_body(spec, {"prompt": "p"})
    assert body == {"params": {"prompt": "p"}, "use_unlim": False}
    assert "use_free_gens" not in body


def test_v1_kling_turbo_uses_unlim() -> None:
    spec = REGISTRY.get("kling2-5-turbo")
    body = _build_body(spec, {"prompt": "p"})
    assert body == {"params": {"prompt": "p"}, "use_unlim": True}


def test_v2_models_set_matches_registry() -> None:
    """Every slug in V2_MODELS must exist in the registry."""
    for slug in V2_MODELS:
        REGISTRY.get(slug)


def test_extract_job_id_from_job_sets() -> None:
    body = {"job_sets": [{"jobs": [{"id": "abc-123"}]}]}
    assert _extract_job_id(body) == "abc-123"


def test_extract_job_id_fallback_to_flat_id() -> None:
    assert _extract_job_id({"job_id": "fallback"}) == "fallback"
    assert _extract_job_id({"id": "fallback"}) == "fallback"


def test_extract_job_id_returns_none_when_missing() -> None:
    assert _extract_job_id({"unrelated": True}) is None


def test_extract_image_urls() -> None:
    job = {"results": [{"url": "https://cdn/x.png"}, {"public_url": "https://cdn/y.jpg"}]}
    urls = WebBackend._extract_image_urls(job)
    assert urls == ["https://cdn/x.png", "https://cdn/y.jpg"]


def test_extract_image_urls_skips_video() -> None:
    job = {"results": [{"url": "https://cdn/movie.mp4"}, {"url": "https://cdn/x.png"}]}
    urls = WebBackend._extract_image_urls(job)
    assert urls == ["https://cdn/x.png"]


def test_extract_video_url_from_results() -> None:
    job = {"results": [{"url": "https://cdn/movie.mp4"}]}
    assert WebBackend._extract_video_url(job) == "https://cdn/movie.mp4"


def test_extract_video_url_from_video_dict() -> None:
    job = {"video": {"url": "https://cdn/v.webm"}}
    assert WebBackend._extract_video_url(job) == "https://cdn/v.webm"

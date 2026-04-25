"""MCP tool implementations.

Each tool is a small async function that the FastMCP server exposes by name.
Routing logic (model_id -> backend) lives here, so the server file stays a
thin wiring layer.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict
from pathlib import Path
from typing import Any

from higgsfield_mcp.backends.base import BackendDriver, JobHandle, JobStatus
from higgsfield_mcp.backends.official import OfficialBackend
from higgsfield_mcp.backends.web import WebBackend, assert_enabled
from higgsfield_mcp.models import REGISTRY, Backend, Kind, ModelSpec


class BackendPool:
    """Lazily instantiates backends and reuses them across tool calls."""

    def __init__(self) -> None:
        self._official: OfficialBackend | None = None
        self._web: WebBackend | None = None

    def get(self, name: Backend) -> BackendDriver:
        if name == "official":
            if self._official is None:
                self._official = OfficialBackend()
            return self._official
        if name == "web":
            assert_enabled()
            if self._web is None:
                self._web = WebBackend()
            return self._web
        raise ValueError(f"Unknown backend: {name!r}")

    async def aclose(self) -> None:
        if self._official is not None:
            await self._official.aclose()
        if self._web is not None:
            await self._web.aclose()


def _spec_for(model_id: str, expected_kind: Kind | None = None) -> ModelSpec:
    spec = REGISTRY.get(model_id)
    # Allow image-edit endpoints (kind=image) to be invoked from generate_image
    # even if they accept image_url; reject only mismatches like calling
    # generate_video on an image-only model.
    if expected_kind == "video" and spec.kind != "video":
        raise ValueError(f"Model {model_id!r} is a {spec.kind} model; use the matching tool.")
    return spec


def _filter_params(spec: ModelSpec, params: dict[str, Any]) -> dict[str, Any]:
    """Drop unknown params and warn via a synthetic key."""
    accepted = {k: v for k, v in params.items() if k in spec.supports and v is not None}
    return accepted


# ---------------------------------------------------------------------------
# Tool functions. Each returns a plain dict so FastMCP can serialise it.
# ---------------------------------------------------------------------------


async def list_models(
    kind: Kind | None = None,
    backend: Backend | None = None,
    include_unverified: bool = False,
) -> dict[str, Any]:
    """Return the model registry. Always call this before guessing model_id."""
    specs = REGISTRY.list(kind=kind, backend=backend, include_unverified=include_unverified)
    return {
        "count": len(specs),
        "models": [asdict(s) for s in specs],
    }


async def generate_image(
    pool: BackendPool,
    model_id: str,
    prompt: str,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    quality: str | None = None,
    image_url: str | None = None,
    input_image_urls: list[str] | None = None,
    seed: int | None = None,
    batch_size: int | None = None,
    enhance_prompt: bool | None = None,
) -> dict[str, Any]:
    """Submit an image-generation job. Returns a serialisable JobHandle string."""
    spec = _spec_for(model_id, expected_kind="image")
    params = _filter_params(
        spec,
        {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "quality": quality,
            "image_url": image_url,
            "input_image_urls": input_image_urls,
            "seed": seed,
            "batch_size": batch_size,
            "enhance_prompt": enhance_prompt,
        },
    )
    backend = pool.get(spec.backend)
    handle = await backend.submit(spec, params)
    return {"job_handle": handle.serialise(), "model_id": model_id, "backend": spec.backend}


async def generate_video(
    pool: BackendPool,
    model_id: str,
    prompt: str,
    image_url: str | None = None,
    end_image_url: str | None = None,
    duration: int | None = None,
    resolution: str | None = None,
    sound: bool | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Submit a video-generation job (text-to-video or image-to-video)."""
    spec = _spec_for(model_id, expected_kind="video")
    params = _filter_params(
        spec,
        {
            "prompt": prompt,
            "image_url": image_url,
            "end_image_url": end_image_url,
            "duration": duration,
            "resolution": resolution,
            "sound": sound,
            "seed": seed,
        },
    )
    backend = pool.get(spec.backend)
    handle = await backend.submit(spec, params)
    return {"job_handle": handle.serialise(), "model_id": model_id, "backend": spec.backend}


async def get_status(pool: BackendPool, job_handle: str) -> dict[str, Any]:
    """Poll a previously-submitted job. Returns state + output URLs when ready."""
    handle = JobHandle.parse(job_handle)
    backend = pool.get(handle.backend)
    status = await backend.status(handle)
    return _status_dict(handle, status)


async def cancel_job(pool: BackendPool, job_handle: str) -> dict[str, Any]:
    handle = JobHandle.parse(job_handle)
    backend = pool.get(handle.backend)
    await backend.cancel(handle)
    return {"cancelled": True, "job_handle": job_handle}


async def upload_image(
    pool: BackendPool,
    path: str | None = None,
    data_base64: str | None = None,
    mime: str = "image/png",
    backend: Backend = "web",
) -> dict[str, Any]:
    """Upload a local file (path) or base64-encoded bytes to Higgsfield storage."""
    if path and data_base64:
        raise ValueError("Pass either path or data_base64, not both.")
    if path:
        data = Path(path).read_bytes()
    elif data_base64:
        data = base64.b64decode(data_base64)
    else:
        raise ValueError("path or data_base64 is required")
    driver = pool.get(backend)
    url = await driver.upload(data, mime)
    return {"url": url, "backend": backend}


async def subscribe(
    pool: BackendPool,
    job_handle: str,
    poll_interval: float = 2.0,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    """Block until the job reaches a terminal state. Convenience over get_status."""
    handle = JobHandle.parse(job_handle)
    backend = pool.get(handle.backend)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        status = await backend.status(handle)
        if status.state in ("completed", "failed", "nsfw", "cancelled"):
            return _status_dict(handle, status)
        if asyncio.get_running_loop().time() >= deadline:
            return _status_dict(handle, status) | {"timeout": True}
        await asyncio.sleep(poll_interval)


def _status_dict(handle: JobHandle, status: JobStatus) -> dict[str, Any]:
    return {
        "job_handle": handle.serialise(),
        "state": status.state,
        "progress": status.progress,
        "images": list(status.images),
        "video_url": status.video_url,
        "error": status.error,
    }

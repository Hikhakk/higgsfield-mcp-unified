"""MCP tool implementations.

Each tool is a small async function that the FastMCP server exposes by name.
Routing logic (model_id -> backend) lives here, so the server file stays a
thin wiring layer.
"""

from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from higgsfield_mcp.backends.base import BackendDriver, JobHandle, JobStatus
from higgsfield_mcp.backends.official import OfficialBackend
from higgsfield_mcp.backends.web import WebBackend, assert_enabled
from higgsfield_mcp.models import REGISTRY, Backend, Kind, ModelSpec, UnknownModelError


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
    soul_id: str | None = None,
    soul_strength: float | None = None,
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
            "custom_reference_id": soul_id,
            "custom_reference_strength": soul_strength,
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


async def preflight_check(pool: BackendPool) -> dict[str, Any]:
    """Validate credentials/reachability for both backends without spending a generation."""
    from higgsfield_mcp.auth.api_key import MissingCredentialsError, load_from_env
    from higgsfield_mcp.auth.clerk import MissingJWTError, load_jwt
    from higgsfield_mcp.backends.web import WebBackendDisabledError, assert_enabled

    official: dict[str, Any] = {"configured": False, "ok": False, "error": None}
    try:
        load_from_env()
        official.update(configured=True, ok=True)
    except MissingCredentialsError as exc:
        official["error"] = str(exc)

    web: dict[str, Any] = {"enabled": False, "ok": False, "error": None}
    try:
        assert_enabled()
        web["enabled"] = True
        try:
            await load_jwt()
            web["ok"] = True
        except MissingJWTError as exc:
            web["error"] = str(exc)
    except WebBackendDisabledError as exc:
        web["error"] = str(exc)

    return {"official": official, "web": web}


async def recommend_model(
    intent: str,
    kind: Kind | None = None,
    top: int = 5,
    include_unverified: bool = False,
) -> dict[str, Any]:
    """Rank registry models by keyword overlap with a natural-language intent."""
    tokens = {t for t in re.findall(r"[a-z0-9]+", intent.lower()) if len(t) > 1}
    scored: list[dict[str, Any]] = []
    for spec in REGISTRY.list(kind=kind, include_unverified=include_unverified):
        haystack = " ".join(
            [spec.id, spec.label, " ".join(spec.constraints), spec.notes, spec.kind]
        ).lower()
        hits = sorted(t for t in tokens if t in haystack)
        scored.append(
            {
                "model_id": spec.id,
                "label": spec.label,
                "kind": spec.kind,
                "backend": spec.backend,
                "score": len(hits),
                "why": "matched: " + ", ".join(hits) if hits else "no keyword match",
            }
        )
    scored.sort(key=lambda r: (-r["score"], r["model_id"]))
    return {"intent": intent, "recommendations": scored[: max(0, top)]}


async def validate_params(model_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Check params against a model's supported set locally (no backend call)."""
    try:
        spec = REGISTRY.get(model_id)
    except UnknownModelError:
        return {
            "model_id": model_id,
            "known_model": False,
            "valid": False,
            "unsupported": sorted(params),
            "supported": [],
            "constraints": [],
        }
    unsupported = sorted(k for k in params if k not in spec.supports)
    return {
        "model_id": model_id,
        "known_model": True,
        "valid": not unsupported,
        "unsupported": unsupported,
        "supported": list(spec.supports),
        "constraints": list(spec.constraints),
    }


async def create_character(pool: BackendPool, name: str, image_urls: list[str]) -> dict[str, Any]:
    """Train a reusable Soul character from reference image URLs (official backend)."""
    backend = pool.get("official")
    return await backend.create_character(name, image_urls)  # type: ignore[attr-defined,no-any-return]


async def get_character(pool: BackendPool, character_id: str) -> dict[str, Any]:
    """Poll a Soul character's training status."""
    backend = pool.get("official")
    return await backend.get_character(character_id)  # type: ignore[attr-defined,no-any-return]


async def list_characters(pool: BackendPool, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """List trained Soul characters."""
    backend = pool.get("official")
    return await backend.list_characters(page, page_size)  # type: ignore[attr-defined,no-any-return]


async def delete_character(pool: BackendPool, character_id: str) -> dict[str, Any]:
    """Delete a trained Soul character."""
    backend = pool.get("official")
    return await backend.delete_character(character_id)  # type: ignore[attr-defined,no-any-return]


async def get_balance(pool: BackendPool) -> dict[str, Any]:
    """Credit balance + plan (official backend). Raises EndpointUnavailableError
    on the known 404 (no working balance route currently exists upstream) and
    re-raises any other failure — this never returns a fabricated/guessed
    response."""
    backend = pool.get("official")
    return await backend.get_balance()  # type: ignore[attr-defined,no-any-return]


async def list_jobs(pool: BackendPool, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """List recent generations from the official backend (history)."""
    backend = pool.get("official")
    return await backend.list_jobs_official(page, page_size)  # type: ignore[attr-defined,no-any-return]


async def list_soul_styles(pool: BackendPool) -> dict[str, Any]:
    """List Soul image style presets by name."""
    backend = pool.get("official")
    return await backend.list_soul_styles()  # type: ignore[attr-defined,no-any-return]


async def list_motions(pool: BackendPool) -> dict[str, Any]:
    """List DOP motion presets by name."""
    backend = pool.get("official")
    return await backend.list_motions()  # type: ignore[attr-defined,no-any-return]


async def generate_speech_video(
    pool: BackendPool,
    image_url: str,
    audio_url: str,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Talking-head video from a face image + WAV audio (official backend). Audio must be WAV."""
    backend = pool.get("official")
    handle = await backend.speak(image_url, audio_url, prompt)  # type: ignore[attr-defined]
    return {"job_handle": handle.serialise(), "model_id": "higgsfield/speak", "backend": "official"}


async def generate_batch(pool: BackendPool, requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Submit multiple generations concurrently.

    Each request is a dict: ``{"kind": "image"|"video", "model_id", "prompt", ...params}``.
    Returns a per-item result with ``ok`` and either ``job_handle`` or ``error`` (one bad
    item never fails the others).
    """

    async def _one(req: dict[str, Any]) -> dict[str, Any]:
        model_id = req.get("model_id")
        prompt = req.get("prompt")
        if not model_id or not prompt:
            return {
                "ok": False,
                "model_id": model_id or "",
                "error": "each request needs 'model_id' and 'prompt'",
            }
        try:
            if req.get("kind") == "video":
                res = await generate_video(
                    pool,
                    model_id=model_id,
                    prompt=prompt,
                    image_url=req.get("image_url"),
                    end_image_url=req.get("end_image_url"),
                    duration=req.get("duration"),
                    resolution=req.get("resolution"),
                    sound=req.get("sound"),
                    seed=req.get("seed"),
                )
            else:
                res = await generate_image(
                    pool,
                    model_id=model_id,
                    prompt=prompt,
                    aspect_ratio=req.get("aspect_ratio"),
                    resolution=req.get("resolution"),
                    quality=req.get("quality"),
                    image_url=req.get("image_url"),
                    input_image_urls=req.get("input_image_urls"),
                    seed=req.get("seed"),
                    batch_size=req.get("batch_size"),
                    enhance_prompt=req.get("enhance_prompt"),
                    soul_id=req.get("soul_id"),
                    soul_strength=req.get("soul_strength"),
                )
            return {
                "ok": True,
                "model_id": model_id,
                "backend": res.get("backend"),
                "job_handle": res.get("job_handle"),
            }
        except Exception as exc:
            return {"ok": False, "model_id": model_id, "error": str(exc)}

    results = await asyncio.gather(*[_one(r) for r in requests])
    return {"count": len(results), "results": list(results)}

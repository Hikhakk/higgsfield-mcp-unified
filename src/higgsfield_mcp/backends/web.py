"""Web backend driver: ``cloud.higgsfield.ai``.

This backend is opt-in and inherently fragile. It posts to undocumented
endpoints with a Clerk JWT in the ``Authorization`` header. The shapes below
mirror what ``jfikrat/higgsfield-mcp`` sends today and may need updates as
the cloud frontend evolves.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from higgsfield_mcp.auth.clerk import JWTAuth, load_jwt
from higgsfield_mcp.models import Backend as BackendName
from higgsfield_mcp.models import ModelSpec

from .base import BackendDriver, BackendError, JobHandle, JobState, JobStatus

BASE_URL = "https://cloud.higgsfield.ai"
ENABLE_FLAG = "HIGGSFIELD_ENABLE_WEB_BACKEND"

_STATE_MAP: dict[str, JobState] = {
    "queued": "queued",
    "pending": "queued",
    "in_progress": "in_progress",
    "running": "in_progress",
    "processing": "in_progress",
    "completed": "completed",
    "succeeded": "completed",
    "done": "completed",
    "failed": "failed",
    "error": "failed",
    "nsfw": "nsfw",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


class WebBackendDisabledError(BackendError):
    """Raised when the web backend is requested without the opt-in env flag."""


def assert_enabled() -> None:
    if os.getenv(ENABLE_FLAG) not in ("1", "true", "True", "yes"):
        raise WebBackendDisabledError(
            f"The cloud.higgsfield.ai web backend is opt-in. "
            f"Set {ENABLE_FLAG}=1 if you understand the risks (web auth may break, "
            f"may not be covered by Higgsfield's terms of use)."
        )


class WebBackend(BackendDriver):
    name: BackendName = "web"

    def __init__(self, *, auth: JWTAuth | None = None, base_url: str = BASE_URL) -> None:
        assert_enabled()
        self._auth = auth
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._auth is None:
            self._auth = await load_jwt()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": self._auth.header,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def submit(self, model: ModelSpec, params: dict[str, Any]) -> JobHandle:
        if model.backend != "web":
            raise BackendError(f"WebBackend cannot submit official model {model.id!r}")
        client = await self._ensure_client()
        payload = {"model_id": model.id, **params}
        resp = await client.post(model.endpoint, json=payload)
        body = self._json_or_raise(resp)
        request_id = body.get("job_id") or body.get("id") or body.get("request_id")
        if not request_id:
            raise BackendError(
                f"Submit response missing job_id: {body!r}",
                status_code=resp.status_code,
            )
        return JobHandle(backend="web", request_id=str(request_id))

    async def status(self, handle: JobHandle) -> JobStatus:
        client = await self._ensure_client()
        resp = await client.get(f"/jobs/{handle.request_id}")
        body = self._json_or_raise(resp)
        raw_state = str(body.get("status") or body.get("state") or "").lower()
        state = _STATE_MAP.get(raw_state, "in_progress")
        images = tuple(self._extract_image_urls(body))
        video_url = self._extract_video_url(body)
        return JobStatus(
            state=state,
            progress=body.get("progress"),
            images=images,
            video_url=video_url,
            error=body.get("error") or body.get("error_message"),
            raw=body,
        )

    async def cancel(self, handle: JobHandle) -> None:
        client = await self._ensure_client()
        resp = await client.post(f"/jobs/{handle.request_id}/cancel")
        if resp.status_code >= 400:
            raise BackendError(
                f"Cancel failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )

    async def upload(self, data: bytes, mime: str) -> str:
        client = await self._ensure_client()
        files = {"file": ("upload.bin", data, mime)}
        # The web app uses a presigned-upload flow at /uploads; this is the
        # documented path used by jfikrat's TS port. If Higgsfield rotates the
        # path, this is the first thing that will need updating.
        resp = await client.post("/uploads", files=files, headers={"Content-Type": ""})
        body = self._json_or_raise(resp)
        url = body.get("url") or body.get("public_url")
        if not url:
            raise BackendError(f"Upload response missing url: {body!r}")
        return str(url)

    @staticmethod
    def _extract_image_urls(body: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("images", "outputs", "results"):
            entries = body.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, str):
                    urls.append(entry)
                elif isinstance(entry, dict):
                    url = entry.get("url") or entry.get("image_url") or entry.get("public_url")
                    if url and not str(url).endswith((".mp4", ".webm", ".mov")):
                        urls.append(str(url))
        return urls

    @staticmethod
    def _extract_video_url(body: dict[str, Any]) -> str | None:
        video = body.get("video")
        if isinstance(video, str):
            return video
        if isinstance(video, dict):
            return str(video.get("url") or video.get("public_url") or "") or None
        # Some endpoints return a flat URL under "outputs"
        outputs = body.get("outputs")
        if isinstance(outputs, list):
            for entry in outputs:
                if isinstance(entry, dict):
                    url = entry.get("url") or entry.get("public_url")
                    if url and str(url).endswith((".mp4", ".webm", ".mov")):
                        return str(url)
        return None

    @staticmethod
    def _json_or_raise(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise BackendError(
                f"HTTP {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
                body=resp.text,
            )
        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise BackendError(f"Invalid JSON response: {resp.text[:200]}") from exc
        return data

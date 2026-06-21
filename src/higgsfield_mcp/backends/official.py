"""Official backend driver: ``platform.higgsfield.ai``.

API shape (https://docs.higgsfield.ai/how-to/introduction.md):

* ``POST /{model_id}`` -> ``{ request_id, status_url, cancel_url, ... }``
* ``GET  /requests/{request_id}/status`` -> status payload
* ``POST /requests/{request_id}/cancel``

Auth is a single header: ``Authorization: Key {api_key}:{secret}``.
"""

from __future__ import annotations

from typing import Any, cast

import httpx

from higgsfield_mcp.auth.api_key import ApiKeyAuth, load_from_env
from higgsfield_mcp.errors import NetworkError, SchemaError, classify_http
from higgsfield_mcp.models import Backend as BackendName
from higgsfield_mcp.models import ModelSpec
from higgsfield_mcp.reliability import CircuitBreaker, new_idempotency_key, retrying_request

from .base import BackendDriver, BackendError, JobHandle, JobState, JobStatus

BASE_URL = "https://platform.higgsfield.ai"

_STATE_MAP: dict[str, JobState] = {
    "queued": "queued",
    "in_progress": "in_progress",
    "running": "in_progress",
    "processing": "in_progress",
    "completed": "completed",
    "succeeded": "completed",
    "failed": "failed",
    "error": "failed",
    "nsfw": "nsfw",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


class OfficialBackend(BackendDriver):
    name: BackendName = "official"

    def __init__(self, *, auth: ApiKeyAuth | None = None, base_url: str = BASE_URL) -> None:
        self._auth = auth or load_from_env()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": self._auth.header,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._breaker = CircuitBreaker()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def submit(self, model: ModelSpec, params: dict[str, Any]) -> JobHandle:
        if model.backend != "official":
            raise BackendError(f"OfficialBackend cannot submit web model {model.id!r}")
        self._breaker.check()
        idem = new_idempotency_key()

        async def _send() -> httpx.Response:
            try:
                return await self._client.post(
                    f"/{model.endpoint}", json=params, headers={"X-Idempotency-Key": idem}
                )
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc

        try:
            resp = cast(httpx.Response, await retrying_request(_send))
        except Exception:
            self._breaker.record_failure()
            raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        body = self._json_or_raise(resp)
        request_id = body.get("request_id") or body.get("id")
        if not request_id:
            raise SchemaError(
                f"Submit response missing request_id: {body!r}",
                status_code=resp.status_code,
            )
        return JobHandle(backend="official", request_id=request_id)

    async def status(self, handle: JobHandle) -> JobStatus:
        self._breaker.check()

        async def _send() -> httpx.Response:
            try:
                return await self._client.get(f"/requests/{handle.request_id}/status")
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc

        try:
            resp = cast(httpx.Response, await retrying_request(_send, max_attempts=3))
        except Exception:
            self._breaker.record_failure()
            raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        body = self._json_or_raise(resp)
        raw_state = str(body.get("status", "")).lower()
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
        resp = await self._client.post(f"/requests/{handle.request_id}/cancel")
        if resp.status_code >= 400:
            raise BackendError(
                f"Cancel failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )

    async def upload(self, data: bytes, mime: str) -> str:
        resp = await self._client.post("/files/generate-upload-url", json={"content_type": mime})
        body = self._json_or_raise(resp)
        upload_url = body.get("upload_url")
        public_url = body.get("public_url") or body.get("url")
        if not upload_url or not public_url:
            raise BackendError(
                f"generate-upload-url response missing upload_url/public_url: {body!r}",
                status_code=resp.status_code,
            )
        # The signed PUT must NOT carry the platform Authorization header.
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as raw:
            put = await raw.put(upload_url, content=data, headers={"Content-Type": mime})
            if put.status_code >= 400:
                raise BackendError(
                    f"Signed upload PUT failed: HTTP {put.status_code}",
                    status_code=put.status_code,
                    body=put.text,
                )
        return str(public_url)

    @staticmethod
    def _extract_image_urls(body: dict[str, Any]) -> list[str]:
        images = body.get("images") or []
        out: list[str] = []
        for entry in images:
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict):
                url = entry.get("url") or entry.get("image_url")
                if url:
                    out.append(url)
        return out

    @staticmethod
    def _extract_video_url(body: dict[str, Any]) -> str | None:
        video = body.get("video")
        if isinstance(video, str):
            return video
        if isinstance(video, dict):
            return video.get("url")
        return None

    @staticmethod
    def _json_or_raise(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise classify_http(resp.status_code, resp.text, dict(resp.headers))
        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise BackendError(f"Invalid JSON response: {resp.text[:200]}") from exc
        return data

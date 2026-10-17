"""Official backend driver: ``api.higgsfield.ai``.

API shape (https://docs.higgsfield.ai/docs/how-to/introduction.md):

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
from higgsfield_mcp.reliability import (
    RETRYABLE_STATUS,
    CircuitBreaker,
    new_idempotency_key,
    retrying_request,
)

from .base import BackendDriver, BackendError, JobHandle, JobState, JobStatus

BASE_URL = "https://api.higgsfield.ai"

# Extra files some video/3D operations return next to ``video`` (docs: concepts/requests).
ARTIFACT_KEYS: tuple[str, ...] = ("zip", "mov", "jsx", "fbx", "ply")

# A 500 on submit is safe to retry: the Idempotency-Key makes the replay return the
# original request instead of creating a second generation (docs: concepts/errors).
_SUBMIT_RETRY_STATUS = RETRYABLE_STATUS | {500}

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
        self._base_url = base_url
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

    async def submit(
        self, model: ModelSpec, params: dict[str, Any], *, webhook_url: str | None = None
    ) -> JobHandle:
        if model.backend != "official":
            raise BackendError(f"OfficialBackend cannot submit web model {model.id!r}")
        self._breaker.check()
        idem = new_idempotency_key()
        query = {"hf_webhook": webhook_url} if webhook_url else None

        async def _send() -> httpx.Response:
            try:
                return await self._client.post(
                    f"/{model.endpoint}",
                    json=params,
                    params=query,
                    headers={"Idempotency-Key": idem},
                )
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc

        try:
            resp = cast(
                httpx.Response,
                await retrying_request(_send, retry_status=_SUBMIT_RETRY_STATUS),
            )
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
        audio_urls = tuple(
            dict.fromkeys(
                [*self._media_urls(body.get("audio")), *self._media_urls(body.get("audios"))]
            )
        )
        artifacts = {k: urls for k in ARTIFACT_KEYS if (urls := self._media_urls(body.get(k)))}
        return JobStatus(
            state=state,
            progress=body.get("progress"),
            images=images,
            video_url=video_url,
            audio_urls=audio_urls,
            artifacts=artifacts,
            error=body.get("error") or body.get("error_message"),
            raw=body,
        )

    async def estimate(self, model: ModelSpec, params: dict[str, Any]) -> dict[str, Any]:
        """Price a request without submitting it (docs: concepts/billing-and-retention)."""
        if model.backend != "official":
            raise BackendError(f"OfficialBackend cannot estimate web model {model.id!r}")
        self._breaker.check()

        async def _send() -> httpx.Response:
            try:
                return await self._client.post(f"/estimate/{model.endpoint}", json=params)
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
        credits, usd = body.get("credits"), body.get("usd")
        return {
            "credits": None if credits is None else str(credits),
            "usd": None if usd is None else str(usd),
            "raw": body,
        }

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Authenticated GET for catalog lookups (presets, options)."""
        self._breaker.check()

        async def _send() -> httpx.Response:
            try:
                return await self._client.get(path, params=params)
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
        return self._json_or_raise(resp)

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
        upload_headers = {str(k): str(v) for k, v in (body.get("upload_headers") or {}).items()}
        if not upload_url or not public_url:
            raise BackendError(
                f"generate-upload-url response missing upload_url/public_url: {body!r}",
                status_code=resp.status_code,
            )
        # The signed PUT must NOT carry the API Authorization header, but must carry
        # every header the presign response lists (e.g. x-amz-tagging).
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as raw:
            put = await raw.put(
                upload_url, content=data, headers={"Content-Type": mime, **upload_headers}
            )
            if put.status_code >= 400:
                raise BackendError(
                    f"Signed upload PUT failed: HTTP {put.status_code}",
                    status_code=put.status_code,
                    body=put.text,
                )
        return str(public_url)

    async def _v1_request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        """Call a legacy /v1/ (or /agents/) endpoint with hf-api-key/hf-secret auth.

        A dedicated client is used so the v2 ``Key`` Authorization default is not sent.
        Response shapes are undocumented; callers parse defensively.
        """
        headers = {
            **self._auth.v1_headers,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._breaker.check()
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=httpx.Timeout(60.0, connect=10.0)
        ) as client:

            async def _send() -> httpx.Response:
                try:
                    return await client.request(method, path, json=json, headers=headers)
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
        if resp.status_code >= 400:
            raise classify_http(resp.status_code, resp.text, dict(resp.headers))
        try:
            return resp.json()
        except ValueError as exc:
            raise BackendError(f"Invalid JSON response: {resp.text[:200]}") from exc

    @staticmethod
    def _character_view(raw: dict[str, Any]) -> dict[str, Any]:
        images = (
            raw.get("input_images")
            or raw.get("image_urls")
            or raw.get("images")
            or raw.get("medias")
            or []
        )
        return {
            "id": raw.get("id") or raw.get("custom_reference_id") or raw.get("soul_id") or "",
            "name": raw.get("name") or raw.get("title") or "",
            "status": str(raw.get("status") or raw.get("state") or "unknown"),
            "image_count": len(images) if isinstance(images, list) else 0,
            "raw": raw,
        }

    async def create_character(
        self, name: str, image_urls: list[str], model_version: str = "v1"
    ) -> dict[str, Any]:
        body = self._v1_payload_create(name, image_urls, model_version)
        raw = await self._v1_request("POST", "/v1/custom-references", json=body)
        return self._character_view(raw if isinstance(raw, dict) else {"raw": raw})

    @staticmethod
    def _v1_payload_create(name: str, image_urls: list[str], model_version: str) -> dict[str, Any]:
        # https://docs.higgsfield.ai/docs/models/soul-id/create-character
        return {
            "name": name,
            "model_version": model_version,
            "input_images": [{"type": "image_url", "image_url": u} for u in image_urls],
        }

    async def get_character(self, character_id: str) -> dict[str, Any]:
        raw = await self._v1_request("GET", f"/v1/custom-references/{character_id}")
        return self._character_view(raw if isinstance(raw, dict) else {"raw": raw})

    async def list_characters(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        raw = await self._v1_request(
            "GET", f"/v1/custom-references/list?page={page}&page_size={page_size}"
        )
        items: list[Any] = []
        if isinstance(raw, dict):
            for key in ("items", "results", "custom_references", "data"):
                v = raw.get(key)
                if isinstance(v, list):
                    items = v
                    break
        elif isinstance(raw, list):
            items = raw
        chars = [self._character_view(i) for i in items if isinstance(i, dict)]
        return {"count": len(chars), "characters": chars}

    async def delete_character(self, character_id: str) -> dict[str, Any]:
        await self._v1_request("DELETE", f"/v1/custom-references/{character_id}")
        return {"deleted": True, "character_id": character_id}

    @staticmethod
    def _names_view(raw: Any) -> dict[str, Any]:
        names: list[str] = []
        seq: list[Any] = []
        if isinstance(raw, list):
            seq = raw
        elif isinstance(raw, dict):
            for key in ("styles", "motions", "items", "results", "data"):
                v = raw.get(key)
                if isinstance(v, list):
                    seq = v
                    break
        for entry in seq:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                n = entry.get("name") or entry.get("id") or entry.get("slug")
                if n:
                    names.append(str(n))
        return {"count": len(names), "names": names, "raw": raw if isinstance(raw, dict) else {}}

    async def get_balance(self) -> dict[str, Any]:
        raw = await self._v1_request("POST", "/v1/billing/credits", json={})
        d = raw if isinstance(raw, dict) else {}
        credits = d.get("credits")
        if credits is None:
            credits = d.get("balance") or d.get("available_credits")
        return {"credits": credits, "plan": d.get("plan") or d.get("tier"), "raw": d}

    async def list_jobs_official(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        raw = await self._v1_request(
            "POST", "/agents/jobs", json={"page": page, "page_size": page_size}
        )
        jobs: list[Any] = []
        if isinstance(raw, dict):
            for key in ("jobs", "items", "results", "job_sets", "data"):
                v = raw.get(key)
                if isinstance(v, list):
                    jobs = v
                    break
        elif isinstance(raw, list):
            jobs = raw
        return {"count": len(jobs), "jobs": [j for j in jobs if isinstance(j, dict)]}

    async def list_soul_styles(self) -> dict[str, Any]:
        return self._names_view(await self._v1_request("GET", "/v1/text2image/soul-styles"))

    async def list_motions(self) -> dict[str, Any]:
        return self._names_view(await self._v1_request("GET", "/v1/motions"))

    async def speak(self, image_url: str, audio_url: str, prompt: str | None = None) -> JobHandle:
        body: dict[str, Any] = {"input_image_url": image_url, "audio_url": audio_url}
        if prompt:
            body["prompt"] = prompt
        raw = await self._v1_request("POST", "/v1/speak/higgsfield", json=body)
        d = raw if isinstance(raw, dict) else {}
        request_id = d.get("request_id") or d.get("id") or d.get("job_id")
        if not request_id:
            raise SchemaError(f"speak response missing request_id: {d!r}")
        return JobHandle(backend="official", request_id=str(request_id))

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
    def _media_urls(value: Any) -> list[str]:
        """Normalise a MediaOutput (``{"url": ...}``), bare URL, or list of either."""
        items = value if isinstance(value, list) else [value]
        out: list[str] = []
        for item in items:
            if isinstance(item, str) and item:
                out.append(item)
            elif isinstance(item, dict) and isinstance(item.get("url"), str):
                out.append(item["url"])
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

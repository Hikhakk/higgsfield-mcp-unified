"""Web backend driver: ``fnf.higgsfield.ai``.

This backend is opt-in and inherently fragile. It posts to undocumented
endpoints with a Clerk JWT in the ``Authorization`` header. The shapes mirror
``jfikrat/higgsfield-mcp`` and may need updates as the cloud frontend evolves.

Implementation notes:

* Uses ``curl_cffi`` with Chrome TLS impersonation. ``fnf.higgsfield.ai`` is
  protected by a Cloudflare TLS-fingerprint challenge which fingerprints
  Python's TLS stack and blocks it with a 403 captcha challenge;
  ``curl_cffi`` carries Chrome's exact JA3/JA4 signature and slips through.
* Submit body is ``{"params": {...}, "use_unlim": false, "use_free_gens": false}``
  for V2 models, ``{"params": {...}, "use_unlim": ...}`` for V1.
* Submit response shape: ``{"job_sets": [{"jobs": [{"id": "..."}]}]}``.
* Status is fetched via ``GET /jobs?size=100`` and the caller filters by id.
* ``HIGGSFIELD_DATADOME_COOKIE`` is a legacy Cloudflare cookie hint; optional
  but may improve first-request hit rate.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from curl_cffi.requests import AsyncSession

from higgsfield_mcp.auth.clerk import JWTAuth, load_jwt
from higgsfield_mcp.errors import NetworkError, SchemaError, classify_http
from higgsfield_mcp.models import Backend as BackendName
from higgsfield_mcp.models import ModelSpec
from higgsfield_mcp.reliability import CircuitBreaker, new_idempotency_key, retrying_request

from .base import BackendDriver, BackendError, JobHandle, JobState, JobStatus

try:
    from curl_cffi.requests.exceptions import RequestException as _CurlError
except ImportError:  # pragma: no cover - unexpected curl_cffi layout
    _CurlError = Exception  # type: ignore[assignment,misc]

_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (_CurlError, OSError)

BASE_URL = "https://fnf.higgsfield.ai"
ENABLE_FLAG = "HIGGSFIELD_ENABLE_WEB_BACKEND"

V2_MODELS: frozenset[str] = frozenset(
    {
        "nano-banana-2",
        "soul-v2",
        "kling3",
        "kling-o3-flf",
        "grok",
        "wan2-6",
        "seedance1-5",
        "seedance2",
        "seedance2-fast",
    }
)

_STATE_MAP: dict[str, JobState] = {
    "queued": "queued",
    "pending": "queued",
    "in_progress": "in_progress",
    "in_progress_v2": "in_progress",
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
    pass


def assert_enabled() -> None:
    if os.getenv(ENABLE_FLAG) not in ("1", "true", "True", "yes"):
        raise WebBackendDisabledError(
            "The web backend is opt-in. Set HIGGSFIELD_ENABLE_WEB_BACKEND=1 if you "
            "understand the risks (auth may break, may not be covered by ToS)."
        )


def _build_body(model: ModelSpec, params: dict[str, Any]) -> dict[str, Any]:
    if model.id in V2_MODELS:
        return {"params": params, "use_unlim": False, "use_free_gens": False}
    return {"params": params, "use_unlim": model.id == "kling2-5-turbo"}


def _extract_job_id(body: dict[str, Any]) -> str | None:
    job_sets = body.get("job_sets")
    if isinstance(job_sets, list) and job_sets:
        first = job_sets[0]
        if isinstance(first, dict):
            jobs = first.get("jobs")
            if isinstance(jobs, list) and jobs:
                first_job = jobs[0]
                if isinstance(first_job, dict):
                    job_id = first_job.get("id")
                    if isinstance(job_id, str):
                        return job_id
    for key in ("job_id", "id", "request_id"):
        v = body.get(key)
        if isinstance(v, str):
            return v
    return None


_BROWSER_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://cloud.higgsfield.ai",
    "Referer": "https://cloud.higgsfield.ai/",
    "sec-ch-ua": '"Chromium";v="120", "Google Chrome";v="120", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


class WebBackend(BackendDriver):
    name: BackendName = "web"

    def __init__(
        self,
        *,
        auth: JWTAuth | None = None,
        base_url: str = BASE_URL,
        session: Any | None = None,
    ) -> None:
        assert_enabled()
        self._auth = auth
        self._base_url = base_url
        self._session: Any | None = session
        self._datadome = os.getenv("HIGGSFIELD_DATADOME_COOKIE")
        self._auth_lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(3)
        self._breaker = CircuitBreaker()

    async def _ensure_session(self) -> Any:
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome120", timeout=60)
        return self._session

    async def _auth_header(self) -> dict[str, str]:
        async with self._auth_lock:
            if self._auth is None or self._auth.is_expired():
                self._auth = await load_jwt()
            return {"Authorization": self._auth.header}

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _cookies(self) -> dict[str, str] | None:
        return {"datadome": self._datadome} if self._datadome else None

    async def submit(self, model: ModelSpec, params: dict[str, Any]) -> JobHandle:
        if model.backend != "web":
            raise BackendError(f"WebBackend cannot submit official model {model.id!r}")
        session = await self._ensure_session()
        headers = {**_BROWSER_HEADERS, **(await self._auth_header())}
        body = _build_body(model, params)
        self._breaker.check()
        idem = new_idempotency_key()

        async def _send() -> Any:
            try:
                return await session.post(
                    f"{self._base_url}{model.endpoint}",
                    json=body,
                    headers={**headers, "X-Idempotency-Key": idem},
                    cookies=self._cookies(),
                )
            except _TRANSPORT_ERRORS as exc:
                raise NetworkError(str(exc)) from exc

        async with self._sem:
            try:
                resp = await retrying_request(_send)
            except Exception:
                self._breaker.record_failure()
                raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        data = self._json_or_raise(resp)
        job_id = _extract_job_id(data)
        if not job_id:
            raise SchemaError(
                f"Submit response missing job_id: {data!r}",
                status_code=resp.status_code,
            )
        return JobHandle(backend="web", request_id=job_id)

    async def status(self, handle: JobHandle) -> JobStatus:
        session = await self._ensure_session()
        headers = {**_BROWSER_HEADERS, **(await self._auth_header())}
        self._breaker.check()

        async def _send() -> Any:
            try:
                return await session.get(
                    f"{self._base_url}/jobs",
                    params={"size": 100},
                    headers=headers,
                    cookies=self._cookies(),
                )
            except _TRANSPORT_ERRORS as exc:
                raise NetworkError(str(exc)) from exc

        async with self._sem:
            try:
                resp = await retrying_request(_send, max_attempts=3)
            except Exception:
                self._breaker.record_failure()
                raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        data = self._json_or_raise(resp)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        job: dict[str, Any] | None = None
        if isinstance(jobs, list):
            for entry in jobs:
                if isinstance(entry, dict) and entry.get("id") == handle.request_id:
                    job = entry
                    break
        if job is None:
            return JobStatus(state="in_progress", raw={"missing": True})

        raw_state = str(job.get("status") or job.get("state") or "").lower()
        state = _STATE_MAP.get(raw_state, "in_progress")
        return JobStatus(
            state=state,
            progress=job.get("progress"),
            images=tuple(self._extract_image_urls(job)),
            video_url=self._extract_video_url(job),
            error=job.get("error") or job.get("error_message"),
            raw=job,
        )

    async def cancel(self, handle: JobHandle) -> None:
        session = await self._ensure_session()
        headers = {**_BROWSER_HEADERS, **(await self._auth_header())}
        resp = await session.post(
            f"{self._base_url}/jobs/{handle.request_id}/cancel",
            headers=headers,
            cookies=self._cookies(),
        )
        if resp.status_code >= 400:
            raise BackendError(
                f"Cancel failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )

    async def upload(self, data: bytes, mime: str) -> str:
        session = await self._ensure_session()
        headers = {**_BROWSER_HEADERS, **(await self._auth_header())}
        create = await session.post(
            f"{self._base_url}/media/batch",
            json={"mimetypes": [mime], "source": "user_upload"},
            headers=headers,
            cookies=self._cookies(),
        )
        batch = self._json_or_raise(create)
        items = batch.get("items") or batch.get("media") or []
        if not items or not isinstance(items, list):
            raise BackendError(f"Unexpected /media/batch response: {batch!r}")
        item = items[0]
        upload_url = item.get("upload_url")
        media_id = item.get("id")
        public_url = item.get("url") or item.get("public_url")
        if not upload_url or not media_id:
            raise BackendError(f"/media/batch missing upload_url or id: {item!r}")
        async with AsyncSession(impersonate="chrome120", timeout=120) as raw:
            put = await raw.put(upload_url, data=data, headers={"Content-Type": mime})
            if put.status_code >= 400:
                raise BackendError(f"S3 upload failed: HTTP {put.status_code}")
        await session.post(
            f"{self._base_url}/media/{media_id}/upload",
            json={},
            headers=headers,
            cookies=self._cookies(),
        )
        return str(public_url) if public_url else ""

    @staticmethod
    def _extract_image_urls(job: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("results", "images", "outputs"):
            entries = job.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, str) and not entry.endswith((".mp4", ".webm", ".mov")):
                    urls.append(entry)
                elif isinstance(entry, dict):
                    url = (
                        entry.get("url")
                        or entry.get("image_url")
                        or entry.get("public_url")
                        or entry.get("preview_url")
                    )
                    if url and not str(url).endswith((".mp4", ".webm", ".mov")):
                        urls.append(str(url))
        return urls

    @staticmethod
    def _extract_video_url(job: dict[str, Any]) -> str | None:
        video = job.get("video")
        if isinstance(video, str):
            return video
        if isinstance(video, dict):
            url = video.get("url") or video.get("public_url")
            if url:
                return str(url)
        for key in ("results", "outputs", "media"):
            entries = job.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                url = None
                if isinstance(entry, dict):
                    url = entry.get("url") or entry.get("public_url")
                elif isinstance(entry, str):
                    url = entry
                if url and str(url).endswith((".mp4", ".webm", ".mov")):
                    return str(url)
        return None

    @staticmethod
    def _json_or_raise(resp: Any) -> dict[str, Any]:
        if resp.status_code >= 400:
            headers = dict(getattr(resp, "headers", {}) or {})
            raise classify_http(resp.status_code, getattr(resp, "text", ""), headers)
        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise BackendError(f"Invalid JSON response: {resp.text[:200]}") from exc
        return data

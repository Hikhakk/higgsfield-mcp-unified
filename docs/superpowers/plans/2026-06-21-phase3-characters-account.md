# Phase 3 — Soul Characters + Account/History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the official-API v1 feature surface the hosted MCP has and we lack — Soul character training, account credits, generation history, style/motion lookups, and talking-head speech video — using the v1 two-header auth, with defensive response parsing (endpoints are confirmed to exist; response shapes are best-guess and parsed leniently until verified with live credentials).

**Architecture:** `OfficialBackend` gains a `_v1_request` helper that issues requests to `/v1/...` (and `/agents/jobs`) with the `hf-api-key`/`hf-secret` headers (via a dedicated client so the v2 `Key` auth path is untouched). New backend methods wrap each v1 endpoint with lenient parsing. New `tools.py` functions surface them; `server.py` exposes typed tools; `schemas.py` adds output models. All tests use `respx` (httpx) — no live calls.

**Tech Stack:** Python 3.10+, httpx, FastMCP 3.2.4, pydantic v2, pytest + respx, ruff, mypy --strict.

## Global Constraints

- All shell commands run inside the repo: prefix with `cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified &&`.
- On branch `feat/phase3-characters-account`. Commit there. NEVER push, open a PR, or switch branches.
- Tooling uses the dev extra; all four gates must be clean: `uv run --extra dev pytest -q`, `uv run --extra dev ruff check .`, `uv run --extra dev ruff format --check .`, `uv run --extra dev mypy src`.
- Do NOT change the existing v2 code paths in `official.py` (`submit`/`status`/`cancel`/`upload`) or their behavior — only ADD v1 methods. Do NOT modify `web.py`/`auth/`/`models.py`/the registry.
- Do NOT add runtime dependencies. Every new module starts with `from __future__ import annotations`.
- Response shapes are UNVERIFIED: parse defensively (`.get(...)` with fallbacks, tolerate missing keys), mirroring the existing `_extract_image_urls` style. Each new tool's docstring notes results are best-effort until verified.
- The full pre-existing suite (84 tests) must stay green.

---

### Task 1: v1 request plumbing on OfficialBackend

**Files:**
- Modify: `src/higgsfield_mcp/backends/official.py` (`__init__` to store `self._base_url`; add `_v1_request`)
- Test: `tests/test_official_v1.py`

**Interfaces:**
- Consumes: `self._auth.v1_headers` (`{"hf-api-key", "hf-secret"}`, from Phase 1a), `retrying_request`, `classify_http`, `NetworkError`.
- Produces: `async OfficialBackend._v1_request(method: str, path: str, *, json: dict[str, Any] | None = None) -> Any` — issues a request to `{base_url}{path}` with v1 headers (NOT the `Key` Authorization), retries (max 3), classifies errors, returns parsed JSON (dict or list).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_official_v1.py
from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.errors import AuthError


@pytest.fixture
def auth() -> ApiKeyAuth:
    return ApiKeyAuth(api_key="kid", secret="sec")


@pytest.mark.asyncio
async def test_v1_request_uses_split_headers(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.get("/v1/motions").mock(
                return_value=httpx.Response(200, json={"motions": []})
            )
            await backend._v1_request("GET", "/v1/motions")
        req = route.calls.last.request
        assert req.headers["hf-api-key"] == "kid"
        assert req.headers["hf-secret"] == "sec"
        assert req.headers.get("Authorization") is None  # v1 must NOT send the Key scheme
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_v1_request_classifies_401(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.post("/v1/billing/credits").mock(return_value=httpx.Response(401, text="bad"))
            with pytest.raises(AuthError):
                await backend._v1_request("POST", "/v1/billing/credits", json={})
    finally:
        await backend.aclose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_official_v1.py -q`
Expected: FAIL — `AttributeError: 'OfficialBackend' object has no attribute '_v1_request'`.

- [ ] **Step 3: Implement**

In `src/higgsfield_mcp/backends/official.py`, in `__init__`, add right after `self._auth = auth or load_from_env()`:

```python
        self._base_url = base_url
```

Add this method to the class (after `upload`):

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_official_v1.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/backends/official.py tests/test_official_v1.py
git commit -m "feat: add v1 (hf-api-key) request plumbing to official backend"
```

---

### Task 2: Soul characters (create / get / list / delete)

**Files:**
- Modify: `src/higgsfield_mcp/backends/official.py` (character methods)
- Modify: `src/higgsfield_mcp/schemas.py` (`Character`, `CharacterList`, `CharacterDeleted`)
- Modify: `src/higgsfield_mcp/tools.py` (`create_character`, `get_character`, `list_characters`, `delete_character`)
- Modify: `src/higgsfield_mcp/server.py` (4 tools)
- Test: `tests/test_characters.py`

**Interfaces:**
- Produces backend methods: `create_character(name, image_urls) -> dict`, `get_character(character_id) -> dict`, `list_characters(page, page_size) -> dict`, `delete_character(character_id) -> dict`. Endpoints (verified to exist): `POST /v1/custom-references`, `GET /v1/custom-references/{id}`, `GET /v1/custom-references/list`, `DELETE /v1/custom-references/{id}`. Schemas: `Character {id, name, status, image_count, raw}`, `CharacterList {count, characters}`, `CharacterDeleted {deleted, character_id}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_characters.py
from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import (
    create_character,
    delete_character,
    list_characters,
)


@pytest.fixture
def auth() -> ApiKeyAuth:
    return ApiKeyAuth(api_key="kid", secret="sec")


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch, auth: ApiKeyAuth):
    from higgsfield_mcp.tools import BackendPool

    p = BackendPool()
    p._official = OfficialBackend(auth=auth)
    return p


@pytest.mark.asyncio
async def test_create_character(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/v1/custom-references").mock(
            return_value=httpx.Response(200, json={"id": "soul-1", "status": "queued"})
        )
        out = await create_character(pool, name="Ada", image_urls=["https://x/1.png"])
    assert out["id"] == "soul-1"
    body = route.calls.last.request
    assert body.headers["hf-api-key"] == "kid"
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_characters_defensive(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/v1/custom-references/list").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": "soul-1", "name": "Ada", "status": "ready"}]}
            )
        )
        out = await list_characters(pool)
    assert out["count"] == 1
    assert out["characters"][0]["id"] == "soul-1"
    await pool.aclose()


@pytest.mark.asyncio
async def test_delete_character(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.delete("/v1/custom-references/soul-1").mock(return_value=httpx.Response(200, json={}))
        out = await delete_character(pool, character_id="soul-1")
    assert out == {"deleted": True, "character_id": "soul-1"}
    await pool.aclose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_characters.py -q`
Expected: FAIL — `ImportError: cannot import name 'create_character'`.

- [ ] **Step 3: Implement**

In `src/higgsfield_mcp/backends/official.py`, add these methods (after `_v1_request`). Parsing is defensive:

```python
    @staticmethod
    def _character_view(raw: dict[str, Any]) -> dict[str, Any]:
        images = raw.get("image_urls") or raw.get("images") or raw.get("medias") or []
        return {
            "id": raw.get("id") or raw.get("custom_reference_id") or raw.get("soul_id") or "",
            "name": raw.get("name") or raw.get("title") or "",
            "status": str(raw.get("status") or raw.get("state") or "unknown"),
            "image_count": len(images) if isinstance(images, list) else 0,
            "raw": raw,
        }

    async def create_character(self, name: str, image_urls: list[str]) -> dict[str, Any]:
        body = self._v1_payload_create(name, image_urls)
        raw = await self._v1_request("POST", "/v1/custom-references", json=body)
        return self._character_view(raw if isinstance(raw, dict) else {"raw": raw})

    @staticmethod
    def _v1_payload_create(name: str, image_urls: list[str]) -> dict[str, Any]:
        # Request shape is a best guess (CLI says 5-20 training images).
        return {"name": name, "image_urls": list(image_urls)}

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
```

In `src/higgsfield_mcp/schemas.py`, append:

```python
class Character(BaseModel):
    id: str
    name: str
    status: str
    image_count: int
    raw: dict[str, Any] = {}


class CharacterList(BaseModel):
    count: int
    characters: list[Character]


class CharacterDeleted(BaseModel):
    deleted: bool
    character_id: str
```

Add `from typing import Any` to `schemas.py`'s imports (top of file, before `from pydantic import BaseModel`).

In `src/higgsfield_mcp/tools.py`, append:

```python
async def create_character(
    pool: BackendPool, name: str, image_urls: list[str]
) -> dict[str, Any]:
    """Train a reusable Soul character from reference image URLs (official backend)."""
    backend = pool.get("official")
    return await backend.create_character(name, image_urls)  # type: ignore[attr-defined]


async def get_character(pool: BackendPool, character_id: str) -> dict[str, Any]:
    """Poll a Soul character's training status."""
    backend = pool.get("official")
    return await backend.get_character(character_id)  # type: ignore[attr-defined]


async def list_characters(
    pool: BackendPool, page: int = 1, page_size: int = 50
) -> dict[str, Any]:
    """List trained Soul characters."""
    backend = pool.get("official")
    return await backend.list_characters(page, page_size)  # type: ignore[attr-defined]


async def delete_character(pool: BackendPool, character_id: str) -> dict[str, Any]:
    """Delete a trained Soul character."""
    backend = pool.get("official")
    return await backend.delete_character(character_id)  # type: ignore[attr-defined]
```

In `src/higgsfield_mcp/server.py`, import the four tools (from tools) and `Character, CharacterList, CharacterDeleted` (from schemas), then register:

```python
    @mcp.tool
    async def create_character_tool(name: str, image_urls: list[str]) -> Character:
        """Train a reusable Soul character from reference images. Results best-effort until verified."""
        return Character.model_validate(await create_character(pool, name=name, image_urls=image_urls))

    @mcp.tool
    async def get_character_tool(character_id: str) -> Character:
        """Check a Soul character's training status."""
        return Character.model_validate(await get_character(pool, character_id=character_id))

    @mcp.tool
    async def list_characters_tool(page: int = 1, page_size: int = 50) -> CharacterList:
        """List trained Soul characters."""
        return CharacterList.model_validate(await list_characters(pool, page=page, page_size=page_size))

    @mcp.tool
    async def delete_character_tool(character_id: str) -> CharacterDeleted:
        """Delete a trained Soul character."""
        return CharacterDeleted.model_validate(await delete_character(pool, character_id=character_id))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_characters.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/backends/official.py src/higgsfield_mcp/schemas.py src/higgsfield_mcp/tools.py src/higgsfield_mcp/server.py tests/test_characters.py
git commit -m "feat: add Soul character train/list/get/delete tools"
```

---

### Task 3: Account credits, history, and lookups

**Files:**
- Modify: `src/higgsfield_mcp/backends/official.py` (`get_balance`, `list_jobs_official`, `list_soul_styles`, `list_motions`)
- Modify: `src/higgsfield_mcp/schemas.py` (`Balance`, `JobList`, `NameList`)
- Modify: `src/higgsfield_mcp/tools.py` (`get_balance`, `list_jobs`, `list_soul_styles`, `list_motions`)
- Modify: `src/higgsfield_mcp/server.py` (4 tools)
- Test: `tests/test_account.py`

**Interfaces:**
- Endpoints (verified to exist): `POST /v1/billing/credits` (balance), `POST /agents/jobs` (history), `GET /v1/text2image/soul-styles`, `GET /v1/motions`. Schemas: `Balance {credits, plan, raw}`, `JobList {count, jobs}`, `NameList {count, names, raw}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_account.py
from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import BackendPool, get_balance, list_soul_styles


@pytest.fixture
def pool():
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="kid", secret="sec"))
    return p


@pytest.mark.asyncio
async def test_get_balance_defensive(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/billing/credits").mock(
            return_value=httpx.Response(200, json={"credits": 1234, "plan": "pro"})
        )
        out = await get_balance(pool)
    assert out["credits"] == 1234
    assert out["plan"] == "pro"
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_soul_styles_handles_list_or_dict(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/v1/text2image/soul-styles").mock(
            return_value=httpx.Response(200, json=["cinematic", "anime", "noir"])
        )
        out = await list_soul_styles(pool)
    assert out["count"] == 3
    assert "cinematic" in out["names"]
    await pool.aclose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_account.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_balance'`.

- [ ] **Step 3: Implement**

In `src/higgsfield_mcp/backends/official.py`, add (defensive parsing):

```python
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
```

In `src/higgsfield_mcp/schemas.py`, append:

```python
class Balance(BaseModel):
    credits: int | None = None
    plan: str | None = None
    raw: dict[str, Any] = {}


class JobList(BaseModel):
    count: int
    jobs: list[dict[str, Any]]


class NameList(BaseModel):
    count: int
    names: list[str]
    raw: dict[str, Any] = {}
```

In `src/higgsfield_mcp/tools.py`, append:

```python
async def get_balance(pool: BackendPool) -> dict[str, Any]:
    """Best-effort credit balance + plan (official backend; response shape unverified)."""
    backend = pool.get("official")
    return await backend.get_balance()  # type: ignore[attr-defined]


async def list_jobs(pool: BackendPool, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """List recent generations from the official backend (history)."""
    backend = pool.get("official")
    return await backend.list_jobs_official(page, page_size)  # type: ignore[attr-defined]


async def list_soul_styles(pool: BackendPool) -> dict[str, Any]:
    """List Soul image style presets by name."""
    backend = pool.get("official")
    return await backend.list_soul_styles()  # type: ignore[attr-defined]


async def list_motions(pool: BackendPool) -> dict[str, Any]:
    """List DOP motion presets by name."""
    backend = pool.get("official")
    return await backend.list_motions()  # type: ignore[attr-defined]
```

In `src/higgsfield_mcp/server.py`, import these four tools and `Balance, JobList, NameList`, then register:

```python
    @mcp.tool
    async def get_balance_tool() -> Balance:
        """Get available credits + plan (best-effort; official API key required)."""
        return Balance.model_validate(await get_balance(pool))

    @mcp.tool
    async def list_jobs_tool(page: int = 1, page_size: int = 20) -> JobList:
        """List recent generations (history) from the official backend."""
        return JobList.model_validate(await list_jobs(pool, page=page, page_size=page_size))

    @mcp.tool
    async def list_soul_styles_tool() -> NameList:
        """List Soul image style presets to pick by name."""
        return NameList.model_validate(await list_soul_styles(pool))

    @mcp.tool
    async def list_motions_tool() -> NameList:
        """List DOP motion presets for image-to-video."""
        return NameList.model_validate(await list_motions(pool))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_account.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/backends/official.py src/higgsfield_mcp/schemas.py src/higgsfield_mcp/tools.py src/higgsfield_mcp/server.py tests/test_account.py
git commit -m "feat: add balance, history, and style/motion lookup tools"
```

---

### Task 4: Talking-head speech video + Soul params on generate_image

**Files:**
- Modify: `src/higgsfield_mcp/backends/official.py` (`speak`)
- Modify: `src/higgsfield_mcp/schemas.py` (reuse `SubmitResult`)
- Modify: `src/higgsfield_mcp/tools.py` (`generate_speech_video`; add `soul_id`/`soul_strength` to `generate_image`)
- Modify: `src/higgsfield_mcp/server.py` (`generate_speech_video_tool`; add the two params to `generate_image_tool`)
- Test: `tests/test_speech.py`, and extend `tests/test_official_backend.py` is NOT needed.

**Interfaces:**
- `OfficialBackend.speak(image_url, audio_url, prompt) -> dict` → `POST /v1/speak/higgsfield`, returns `{request_id}`-style; tool returns a `SubmitResult`-shaped dict `{job_handle, model_id, backend}`. `generate_image` gains optional `soul_id`/`soul_strength` mapped into params as `custom_reference_id`/`custom_reference_strength` (only added to the registry `supports` for Soul models is NOT required — pass-through filtered by `_filter_params`; add both keys to the Soul model's supports).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_speech.py
from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.tools import BackendPool, generate_speech_video


@pytest.fixture
def pool():
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="kid", secret="sec"))
    return p


@pytest.mark.asyncio
async def test_generate_speech_video(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/speak/higgsfield").mock(
            return_value=httpx.Response(200, json={"request_id": "spk-1"})
        )
        out = await generate_speech_video(
            pool, image_url="https://x/face.png", audio_url="https://x/a.wav"
        )
    assert out["job_handle"] == "official:spk-1"
    assert out["backend"] == "official"
    await pool.aclose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_speech.py -q`
Expected: FAIL — `ImportError: cannot import name 'generate_speech_video'`.

- [ ] **Step 3: Implement**

In `src/higgsfield_mcp/backends/official.py`, add:

```python
    async def speak(
        self, image_url: str, audio_url: str, prompt: str | None = None
    ) -> JobHandle:
        body: dict[str, Any] = {"input_image_url": image_url, "audio_url": audio_url}
        if prompt:
            body["prompt"] = prompt
        raw = await self._v1_request("POST", "/v1/speak/higgsfield", json=body)
        d = raw if isinstance(raw, dict) else {}
        request_id = d.get("request_id") or d.get("id") or d.get("job_id")
        if not request_id:
            raise SchemaError(f"speak response missing request_id: {d!r}")
        return JobHandle(backend="official", request_id=str(request_id))
```

In `src/higgsfield_mcp/tools.py`, append:

```python
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
```

Add Soul params to `generate_image` — change its signature to add `soul_id: str | None = None, soul_strength: float | None = None`, and in the `_filter_params` dict add the mapped keys:

```python
            "custom_reference_id": soul_id,
            "custom_reference_strength": soul_strength,
```

Add `"custom_reference_id"` and `"custom_reference_strength"` to the `supports` tuple of the `higgsfield-ai/soul/standard` and `soul-v2` entries in `models.py` so `_filter_params` keeps them. (This is the one allowed `models.py` edit for Task 4.)

In `src/higgsfield_mcp/server.py`, add `soul_id`/`soul_strength` params to `generate_image_tool` and pass them through, and register:

```python
    @mcp.tool
    async def generate_speech_video_tool(
        image_url: str, audio_url: str, prompt: str | None = None
    ) -> SubmitResult:
        """Talking-head video from a face image + WAV audio (official backend)."""
        return SubmitResult.model_validate(
            await generate_speech_video(pool, image_url=image_url, audio_url=audio_url, prompt=prompt)
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_speech.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add -A
git commit -m "feat: add talking-head speech video and Soul-id params"
```

Note: adding `custom_reference_*` to two `models.py` entries changes no registry counts (still 43); if `tests/test_models.py` asserts specific `supports` tuples it does not — counts only — so it stays green.

---

## Final verification

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv sync --all-extras --frozen
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q
```

Expected: all green; new tests in `test_official_v1.py` (2), `test_characters.py` (3), `test_account.py` (2), `test_speech.py` (1).

## Self-review against the spec

- Spec §5 new tools: Soul characters (Task 2), `list_jobs`/`get_balance` (Task 3), `generate_speech_video` + `soul_id`/`soul_strength` (Task 4), `list_soul_styles`/`list_motions` (Task 3). Covered.
- Spec "Auth design" v1 two-header routes: Task 1 plumbing. Covered.
- All response parsing is defensive (best-guess shapes), per the user's "build now" decision; correctness to be confirmed when live credentials are available.

## Out of scope (later)

- Live verification of request/response shapes (needs credentials) — will correct any parsing that does not match reality.
- Phase 4: cloud creative suite (audio/3d/upscale/edit), MCP prompts, `generate_batch`, README/docs, PyPI release.

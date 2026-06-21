# Phase 1b — Structured Output + FastMCP Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every MCP tool a precise machine-readable `outputSchema` (MCP 2025-06-18 structured output) by returning Pydantic models from the FastMCP tool wrappers, and tighten the `fastmcp` version floor to match reality.

**Architecture:** Add a `schemas.py` of Pydantic output models. Keep `tools.py` returning plain dicts (no backend-logic churn, existing tests stay green); the thin `server.py` wrappers validate each dict into its model via `Model.model_validate(...)` and declare the model as their return type, which is what FastMCP turns into `outputSchema` + `structuredContent`.

**Tech Stack:** Python 3.10+, FastMCP 3.2.4 (already installed/locked), pydantic v2, pytest + pytest-asyncio, ruff, mypy --strict.

## Global Constraints

- All shell commands run inside the repo: prefix with `cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified &&`.
- On branch `feat/phase1b-structured-output`. Commit there. NEVER push, open a PR, or switch branches.
- Use the dev extra for ALL tooling: `uv run --extra dev pytest -q`, `uv run --extra dev ruff check .`, `uv run --extra dev ruff format --check .`, `uv run --extra dev mypy src`. (CI enforces `ruff format --check` — keep it clean. Plain `uv run pytest` will not find pytest.)
- Do NOT modify `src/higgsfield_mcp/models.py`, the registry, or any backend logic in `backends/`. Do NOT change `tools.py` function bodies or their dict return shapes (the wrappers adapt dict→model).
- Do NOT add new runtime dependencies (`pydantic` is already a dependency).
- Preserve existing tool names exactly as registered (`list_models_tool`, `generate_image_tool`, `generate_video_tool`, `get_status_tool`, `cancel_job_tool`, `upload_image_tool`, `subscribe_tool`, `preflight_check_tool`) — renaming is out of scope.
- Every new module starts with `from __future__ import annotations`.
- The full pre-existing suite (67 tests) must stay green.
- Code passes `ruff check .`, `ruff format --check .`, and `mypy --strict src`.

---

### Task 1: Output schema models (`schemas.py`)

**Files:**
- Create: `src/higgsfield_mcp/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces these pydantic v2 `BaseModel`s, each validatable from the exact dict the matching `tools.py` function returns:
  - `ModelInfo` (mirrors `ModelSpec` via `asdict`): `id,label,kind,backend,endpoint: str`; `supports: list[str]`; `constraints: list[str] = []`; `pending_verification: bool = False`; `notes: str = ""`.
  - `ModelList`: `count: int`; `models: list[ModelInfo]`.
  - `SubmitResult`: `job_handle: str`; `model_id: str`; `backend: str`.
  - `JobStatusResult`: `job_handle: str`; `state: str`; `progress: float | None = None`; `images: list[str] = []`; `video_url: str | None = None`; `error: str | None = None`; `timeout: bool = False`.
  - `CancelResult`: `cancelled: bool`; `job_handle: str`.
  - `UploadResult`: `url: str`; `backend: str`.
  - `OfficialHealth`: `configured: bool`; `ok: bool`; `error: str | None = None`.
  - `WebHealth`: `enabled: bool`; `ok: bool`; `error: str | None = None`.
  - `PreflightResult`: `official: OfficialHealth`; `web: WebHealth`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas.py
from __future__ import annotations

from higgsfield_mcp.schemas import (
    JobStatusResult,
    ModelList,
    PreflightResult,
    SubmitResult,
)


def test_modellist_validates_registry_dict() -> None:
    raw = {
        "count": 1,
        "models": [
            {
                "id": "higgsfield-ai/soul/standard",
                "label": "Soul",
                "kind": "image",
                "backend": "official",
                "endpoint": "higgsfield-ai/soul/standard",
                "supports": ("prompt", "aspect_ratio"),  # tuple coerces to list
                "constraints": (),
                "pending_verification": False,
                "notes": "",
            }
        ],
    }
    parsed = ModelList.model_validate(raw)
    assert parsed.count == 1
    assert parsed.models[0].supports == ["prompt", "aspect_ratio"]


def test_submit_result() -> None:
    s = SubmitResult.model_validate(
        {"job_handle": "official:abc", "model_id": "m", "backend": "official"}
    )
    assert s.job_handle == "official:abc"


def test_job_status_defaults_timeout_false() -> None:
    s = JobStatusResult.model_validate(
        {"job_handle": "web:1", "state": "queued", "progress": None,
         "images": [], "video_url": None, "error": None}
    )
    assert s.timeout is False


def test_job_status_timeout_true() -> None:
    s = JobStatusResult.model_validate(
        {"job_handle": "web:1", "state": "in_progress", "progress": None,
         "images": [], "video_url": None, "error": None, "timeout": True}
    )
    assert s.timeout is True


def test_preflight_result_nested() -> None:
    p = PreflightResult.model_validate(
        {"official": {"configured": True, "ok": True, "error": None},
         "web": {"enabled": False, "ok": False, "error": "disabled"}}
    )
    assert p.official.configured is True
    assert p.web.enabled is False
    assert p.web.error == "disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'higgsfield_mcp.schemas'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/higgsfield_mcp/schemas.py
"""Pydantic output models for the MCP tools.

FastMCP turns a tool's Pydantic return annotation into the MCP ``outputSchema``
and emits ``structuredContent``. The ``tools.py`` functions still return plain
dicts; the ``server.py`` wrappers validate those dicts into these models.
"""

from __future__ import annotations

from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    label: str
    kind: str
    backend: str
    endpoint: str
    supports: list[str]
    constraints: list[str] = []
    pending_verification: bool = False
    notes: str = ""


class ModelList(BaseModel):
    count: int
    models: list[ModelInfo]


class SubmitResult(BaseModel):
    job_handle: str
    model_id: str
    backend: str


class JobStatusResult(BaseModel):
    job_handle: str
    state: str
    progress: float | None = None
    images: list[str] = []
    video_url: str | None = None
    error: str | None = None
    timeout: bool = False


class CancelResult(BaseModel):
    cancelled: bool
    job_handle: str


class UploadResult(BaseModel):
    url: str
    backend: str


class OfficialHealth(BaseModel):
    configured: bool
    ok: bool
    error: str | None = None


class WebHealth(BaseModel):
    enabled: bool
    ok: bool
    error: str | None = None


class PreflightResult(BaseModel):
    official: OfficialHealth
    web: WebHealth
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_schemas.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Lint, format, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev ruff check src/higgsfield_mcp/schemas.py tests/test_schemas.py
uv run --extra dev ruff format --check src/higgsfield_mcp/schemas.py tests/test_schemas.py
uv run --extra dev mypy src/higgsfield_mcp/schemas.py
git add src/higgsfield_mcp/schemas.py tests/test_schemas.py
git commit -m "feat: add pydantic output schemas for MCP tools"
```

---

### Task 2: Return typed models from the server wrappers

**Files:**
- Modify: `src/higgsfield_mcp/server.py` (all 8 `@mcp.tool` wrappers)
- Test: `tests/test_server_schemas.py` (create)

**Interfaces:**
- Consumes: the models from Task 1; the existing `tools.py` functions (unchanged, still return dicts).
- Produces: each `@mcp.tool` wrapper declares its model as the return type and returns `Model.model_validate(await <tool>(...))`. FastMCP then exposes a specific `outputSchema` per tool (verified by the test). Tool names are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_schemas.py
from __future__ import annotations

import pytest

from higgsfield_mcp.server import build_server

GENERIC = {"additionalProperties": True, "type": "object"}

TOOLS = [
    "list_models_tool",
    "generate_image_tool",
    "generate_video_tool",
    "get_status_tool",
    "cancel_job_tool",
    "upload_image_tool",
    "subscribe_tool",
    "preflight_check_tool",
]


@pytest.mark.asyncio
async def test_every_tool_has_specific_output_schema() -> None:
    mcp = build_server()
    for name in TOOLS:
        tool = await mcp.get_tool(name)
        schema = tool.to_mcp_tool().outputSchema
        assert schema is not None, f"{name} has no outputSchema"
        assert schema != GENERIC, f"{name} still has the generic passthrough schema"
        assert schema.get("type") == "object", name
        assert "properties" in schema, name


@pytest.mark.asyncio
async def test_list_models_schema_has_models_property() -> None:
    mcp = build_server()
    tool = await mcp.get_tool("list_models_tool")
    schema = tool.to_mcp_tool().outputSchema
    assert "models" in schema["properties"]
    assert "count" in schema["properties"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_server_schemas.py -v`
Expected: FAIL — wrappers currently return `dict[str, Any]`, so `outputSchema` equals the generic `{"additionalProperties": True, "type": "object"}` and the assertions fail.

- [ ] **Step 3: Write minimal implementation**

In `src/higgsfield_mcp/server.py`, add the import:

```python
from higgsfield_mcp.schemas import (
    CancelResult,
    JobStatusResult,
    ModelList,
    PreflightResult,
    SubmitResult,
    UploadResult,
)
```

Then change each wrapper's return annotation and wrap its return value. Apply these exactly (signatures/args unchanged — only the `-> ...` annotation and the `return` line change):

`list_models_tool`: annotate `-> ModelList`; change `return await list_models(...)` to `return ModelList.model_validate(await list_models(kind=kind, backend=backend, include_unverified=include_unverified))`.

`generate_image_tool`: annotate `-> SubmitResult`; wrap: `return SubmitResult.model_validate(await generate_image(pool, model_id=model_id, prompt=prompt, aspect_ratio=aspect_ratio, resolution=resolution, quality=quality, image_url=image_url, input_image_urls=input_image_urls, seed=seed, batch_size=batch_size, enhance_prompt=enhance_prompt))`.

`generate_video_tool`: annotate `-> SubmitResult`; wrap: `return SubmitResult.model_validate(await generate_video(pool, model_id=model_id, prompt=prompt, image_url=image_url, end_image_url=end_image_url, duration=duration, resolution=resolution, sound=sound, seed=seed))`.

`get_status_tool`: annotate `-> JobStatusResult`; wrap: `return JobStatusResult.model_validate(await get_status(pool, job_handle=job_handle))`.

`cancel_job_tool`: annotate `-> CancelResult`; wrap: `return CancelResult.model_validate(await cancel_job(pool, job_handle=job_handle))`.

`upload_image_tool`: annotate `-> UploadResult`; wrap: `return UploadResult.model_validate(await upload_image(pool, path=path, data_base64=data_base64, mime=mime, backend=backend))`.

`subscribe_tool`: annotate `-> JobStatusResult`; wrap: `return JobStatusResult.model_validate(await subscribe(pool, job_handle=job_handle, poll_interval=poll_interval, timeout_seconds=timeout_seconds))`.

`preflight_check_tool`: annotate `-> PreflightResult`; wrap: `return PreflightResult.model_validate(await preflight_check(pool))`.

Leave each wrapper's docstring and parameter list intact (those drive the input schema and tool description).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_server_schemas.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Full suite, lint, format, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
uv run --extra dev ruff format --check src tests
uv run --extra dev mypy src
git add src/higgsfield_mcp/server.py tests/test_server_schemas.py
git commit -m "feat: return typed pydantic models from MCP tools for structured output"
```

---

### Task 3: Tighten the fastmcp floor and lock

**Files:**
- Modify: `pyproject.toml:21` (the `fastmcp>=0.2.0` dependency line)
- Modify: `uv.lock` (only if `uv lock` produces a diff)

**Interfaces:**
- Produces: `pyproject.toml` declares `"fastmcp>=3.2.0"` (matching the already-resolved 3.2.4) so structured output is guaranteed available; `uv.lock` stays consistent (CI runs `uv sync --frozen`).

- [ ] **Step 1: Update the dependency floor**

In `src/.../pyproject.toml`, change the dependency line `"fastmcp>=0.2.0",` to `"fastmcp>=3.2.0",`.

- [ ] **Step 2: Refresh the lock and confirm consistency**

Run: `cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified && uv lock`
Expected: succeeds. The resolved `fastmcp` version is already 3.2.4, so this should be a no-op or a trivial metadata change.

- [ ] **Step 3: Verify the frozen sync still works (mirrors CI)**

Run: `cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified && uv sync --all-extras --frozen`
Expected: succeeds with no "lockfile is out of date" error.

- [ ] **Step 4: Full verification (mirrors CI)**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy src
uv run --extra dev python -c "from higgsfield_mcp.server import build_server; build_server(); print('ok')"
```

Expected: all green; "ok" printed.

- [ ] **Step 5: Commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
git add pyproject.toml uv.lock
git commit -m "build: raise fastmcp floor to >=3.2.0 for structured output"
```

---

## Final verification

- [ ] **Run all gates exactly as CI does**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv sync --all-extras --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

Expected: all green; test count is 67 (Phase 1a) + 5 (test_schemas) + 2 (test_server_schemas) = 74 passing.

## Self-review against the spec

- Spec §7 "FastMCP / SDK usage": structured output via Pydantic returns so FastMCP emits `outputSchema` + `structuredContent` — Tasks 1–2. The fastmcp version is already 3.2.x (no major bump needed); floor tightened — Task 3.
- MCP resources, prompts, progress reporting, and elicitation from spec §7 are deferred to later phases (Phase 2 adds resources; prompts land in Phase 4) — out of scope here.
- Global constraints honored: `models.py`/registry/backends untouched; `tools.py` dict returns unchanged (existing tests stay green); no new deps; tool names preserved.

## Out of scope (later plans)

- Phase 2: registry rebuild with confidence tiers, MCP resources (`higgsfield://models`), `recommend_model`, `estimate_credits`, `validate_params`, status-poll TTL cache, web→official fallback.
- Phase 3: Soul characters, `list_jobs`, `get_balance`, `generate_speech_video`, soul-styles/motions.
- Phase 4: cloud creative suite, MCP prompts, `generate_batch`, README/docs, PyPI release.

# Phase 2 — Registry Confidence Tiers + Discovery Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the model registry `verified`/`inferred` confidence tiers, expand it with the newest models (gated as `inferred`, endpoints labeled unverified), expose the catalog as MCP resources, and add two local discovery tools (`recommend_model`, `validate_params`). No live API calls; `estimate_credits` is intentionally deferred (no authoritative pricing).

**Architecture:** `models.py` gains a `confidence` field replacing `pending_verification`; `Registry.list(include_unverified=...)` filters on it. New models are added as data only. A new `resources.py` registers `higgsfield://models` + `higgsfield://models/{kind}`. `recommend_model` and `validate_params` are pure local functions in `tools.py` (registry-only, no network), surfaced as typed MCP tools.

**Tech Stack:** Python 3.10+, FastMCP 3.2.4, pydantic v2, pytest + pytest-asyncio, ruff, mypy --strict.

## Global Constraints

- All shell commands run inside the repo: prefix with `cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified &&`.
- On branch `feat/phase2-registry-discovery`. Commit there. NEVER push, open a PR, or switch branches.
- Tooling uses the dev extra: `uv run --extra dev pytest -q`, `uv run --extra dev ruff check .`, `uv run --extra dev ruff format --check .`, `uv run --extra dev mypy src`. All four must be clean (CI enforces `ruff format --check`).
- Do NOT modify anything under `backends/` or the `auth/` modules. Do NOT add runtime dependencies.
- Do NOT change `tools.py` existing function bodies except to ADD the two new functions (`recommend_model`, `validate_params`); leave the existing tools' dict shapes intact.
- New inferred models are DATA ONLY: every newly added web model carries `confidence="inferred"` and a `notes` string ending in "endpoint unverified — confirm with live auth." Their endpoints are best-guesses; they are hidden from `list_models()` by default.
- Every new module starts with `from __future__ import annotations`.
- The full pre-existing suite (74 tests) must stay green except for the registry-count assertions in `tests/test_models.py`, which this plan updates deliberately.

---

### Task 1: Confidence tiers (refactor, no new models)

**Files:**
- Modify: `src/higgsfield_mcp/models.py`
- Modify: `src/higgsfield_mcp/schemas.py` (`ModelInfo`)
- Modify: `tests/test_models.py`, `tests/test_schemas.py`

**Interfaces:**
- Produces: `ModelSpec.confidence: Confidence` (`Confidence = Literal["verified", "inferred"]`, default `"verified"`) replacing `pending_verification: bool`. `Registry.list(..., include_unverified=False)` hides `confidence == "inferred"` entries. `ModelInfo.confidence: str` replaces `ModelInfo.pending_verification`.

- [ ] **Step 1: Update the failing tests first**

Replace `tests/test_models.py`'s `test_unverified_hidden_by_default` with:

```python
def test_inferred_hidden_by_default() -> None:
    assert any(s.confidence == "inferred" for s in REGISTRY.by_id.values())
    assert all(s.confidence == "verified" for s in REGISTRY.list())
```

In `tests/test_schemas.py`, in `test_modellist_validates_registry_dict`, change the model dict key `"pending_verification": False,` to `"confidence": "verified",`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_models.py tests/test_schemas.py -q`
Expected: FAIL — `AttributeError: 'ModelSpec' object has no attribute 'confidence'` (and the schema test errors on the unknown field).

- [ ] **Step 3: Implement the refactor**

In `src/higgsfield_mcp/models.py`:

Add the type alias near the other aliases (after `Kind = Literal[...]`):

```python
Confidence = Literal["verified", "inferred"]
```

In the `ModelSpec` dataclass, replace the line `pending_verification: bool = False` with:

```python
    confidence: Confidence = "verified"
```

In `Registry.list`, replace the block:

```python
            if spec.pending_verification and not include_unverified:
                continue
```

with:

```python
            if spec.confidence == "inferred" and not include_unverified:
                continue
```

In the `nano-banana-1` entry, replace `pending_verification=True,` with `confidence="inferred",`.

In `src/higgsfield_mcp/schemas.py`, in `ModelInfo`, replace `pending_verification: bool = False` with:

```python
    confidence: str = "verified"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_models.py tests/test_schemas.py -q`
Expected: PASS (count assertions unchanged: 27 total / 8 official / 19 web; 1 inferred).

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/models.py src/higgsfield_mcp/schemas.py tests/test_models.py tests/test_schemas.py
git commit -m "refactor: replace pending_verification with confidence tier on ModelSpec"
```

---

### Task 2: Expand the registry with the newest models (inferred)

**Files:**
- Modify: `src/higgsfield_mcp/models.py` (add entries to `_OFFICIAL`, `_WEB_IMAGE`, `_WEB_VIDEO`)
- Modify: `tests/test_models.py` (count assertions)

**Interfaces:**
- Produces: registry grows to 43 specs — 9 official (5 image / 4 video) and 34 web (12 image / 22 video); 27 `verified`, 16 `inferred`. Endpoints of the new web models are best-guesses from research, marked `inferred`.

Source of slugs: the official `higgsfield-ai/cli` `MODELS.md`. Endpoints: best-guess from the research dossier (some were corrected away from the naive `/jobs/v2/<slug>` pattern, e.g. `flux_2` → `/jobs/flux-2`, `z_image` → `/jobs/z-image`, `veo3_1` → `/jobs/veo3_1`). All new web entries are `confidence="inferred"`.

- [ ] **Step 1: Update count tests first**

In `tests/test_models.py` replace the bodies of these tests:

```python
def test_registry_has_all_known_models() -> None:
    assert len(REGISTRY.by_id) == 43, "expected 9 official + 34 web"


def test_split_by_backend() -> None:
    official = REGISTRY.list(backend="official", include_unverified=True)
    web = REGISTRY.list(backend="web", include_unverified=True)
    assert len(official) == 9
    assert len(web) == 34


def test_split_by_kind() -> None:
    images = REGISTRY.list(kind="image", include_unverified=True)
    videos = REGISTRY.list(kind="video", include_unverified=True)
    assert len(images) == 17
    assert len(videos) == 26


def test_verified_default_count() -> None:
    assert len(REGISTRY.list()) == 27
    assert sum(1 for s in REGISTRY.by_id.values() if s.confidence == "inferred") == 16
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_models.py -q`
Expected: FAIL — counts are still 27/8/19.

- [ ] **Step 3: Add the model entries**

In `_OFFICIAL`, add one verified entry (before the closing `)`):

```python
    ModelSpec(
        id="flux-pro/kontext/max/text-to-image",
        label="FLUX.1 Kontext Max — text-to-image",
        kind="image",
        backend="official",
        endpoint="flux-pro/kontext/max/text-to-image",
        supports=("prompt", "aspect_ratio", "seed"),
        constraints=("safety_tolerance: 0-6",),
    ),
```

In `_WEB_IMAGE`, add (all `confidence="inferred"`):

```python
    ModelSpec(
        id="flux_2", label="FLUX.2", kind="image", backend="web",
        endpoint="/jobs/flux-2",
        supports=("prompt", "aspect_ratio", "resolution", "seed"),
        constraints=("resolution: 1k | 2k", "model: pro | flex | max"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="z_image", label="Z-Image", kind="image", backend="web",
        endpoint="/jobs/z-image",
        supports=("prompt", "aspect_ratio"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="recraft_v4_1", label="Recraft v4.1", kind="image", backend="web",
        endpoint="/jobs/v2/recraft_v4_1",
        supports=("prompt", "aspect_ratio", "resolution"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="soul_cinematic", label="Soul Cinematic", kind="image", backend="web",
        endpoint="/jobs/v2/soul_cinematic",
        supports=("prompt", "aspect_ratio", "input_image_urls"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="soul_location", label="Soul Location", kind="image", backend="web",
        endpoint="/jobs/v2/soul_location",
        supports=("prompt", "aspect_ratio"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="grok_image", label="Grok Image", kind="image", backend="web",
        endpoint="/jobs/v2/grok_image",
        supports=("prompt", "aspect_ratio", "input_image_urls"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="kling_omni_image", label="Kling O1 Image", kind="image", backend="web",
        endpoint="/jobs/v2/kling_omni_image",
        supports=("prompt", "aspect_ratio", "resolution", "input_image_urls"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="cinematic_studio_2_5", label="Cinematic Studio 2.5", kind="image", backend="web",
        endpoint="/jobs/v2/cinematic_studio_2_5",
        supports=("prompt", "aspect_ratio", "resolution"),
        constraints=("resolution: 1k | 2k | 4k",),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
```

In `_WEB_VIDEO`, add (all `confidence="inferred"`):

```python
    ModelSpec(
        id="veo3_1", label="Veo 3.1", kind="video", backend="web",
        endpoint="/jobs/veo3_1",
        supports=("prompt", "image_url", "aspect_ratio", "duration"),
        constraints=("duration: 4 | 6 | 8", "aspect_ratio: 16:9 | 9:16"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="veo3_1_lite", label="Veo 3.1 Lite", kind="video", backend="web",
        endpoint="/jobs/veo3_1_lite",
        supports=("prompt", "aspect_ratio", "duration"),
        constraints=("duration: 4 | 6 | 8",),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="wan2_7", label="Wan 2.7", kind="video", backend="web",
        endpoint="/jobs/v2/wan2_7",
        supports=("prompt", "image_url", "duration", "resolution"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="kling3_0_turbo", label="Kling 3.0 Turbo", kind="video", backend="web",
        endpoint="/jobs/v2/kling3_0_turbo",
        supports=("prompt", "image_url", "duration", "resolution"),
        constraints=("duration: 3-15", "resolution: 720p | 1080p"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="minimax_hailuo", label="MiniMax Hailuo 02", kind="video", backend="web",
        endpoint="/jobs/v2/minimax_hailuo",
        supports=("prompt", "duration", "resolution"),
        constraints=("duration: 6 | 10", "resolution: 512 | 768 | 1080"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="grok_video_v15", label="Grok Video 1.5", kind="video", backend="web",
        endpoint="/jobs/v2/grok_video_v15",
        supports=("prompt", "image_url", "duration", "resolution"),
        constraints=("duration: 2-15", "resolution: 480p | 720p"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="cinematic_studio_3_0", label="Cinematic Studio 3.0", kind="video", backend="web",
        endpoint="/jobs/v2/cinematic_studio_3_0",
        supports=("prompt", "aspect_ratio", "duration"),
        constraints=("duration: 4-15",),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_models.py -q`
Expected: PASS (43/9/34/17/26; 27 verified, 16 inferred).

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/models.py tests/test_models.py
git commit -m "feat: add newest Higgsfield models as inferred registry entries"
```

---

### Task 3: Expose the catalog as MCP resources

**Files:**
- Create: `src/higgsfield_mcp/resources.py`
- Modify: `src/higgsfield_mcp/server.py` (call `register_resources(mcp)` in `build_server`)
- Test: `tests/test_resources.py`

**Interfaces:**
- Consumes: `tools.list_models`, `models.Kind`.
- Produces: `register_resources(mcp: FastMCP) -> None` registering `higgsfield://models` (full catalog incl. inferred) and `higgsfield://models/{kind}` (filtered). Read via the in-memory `fastmcp.Client`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resources.py
from __future__ import annotations

import json

import pytest
from fastmcp import Client

from higgsfield_mcp.server import build_server


@pytest.mark.asyncio
async def test_models_resource_lists_full_catalog() -> None:
    async with Client(build_server()) as c:
        uris = [str(r.uri) for r in await c.list_resources()]
        assert "higgsfield://models" in uris
        out = await c.read_resource("higgsfield://models")
        data = json.loads(out[0].text)
        assert data["count"] >= 43
        assert any(m["id"] == "higgsfield-ai/soul/standard" for m in data["models"])


@pytest.mark.asyncio
async def test_models_by_kind_template() -> None:
    async with Client(build_server()) as c:
        tmpls = [t.uriTemplate for t in await c.list_resource_templates()]
        assert "higgsfield://models/{kind}" in tmpls
        out = await c.read_resource("higgsfield://models/video")
        data = json.loads(out[0].text)
        assert data["count"] >= 1
        assert all(m["kind"] == "video" for m in data["models"])


@pytest.mark.asyncio
async def test_models_by_kind_unknown_kind() -> None:
    async with Client(build_server()) as c:
        out = await c.read_resource("higgsfield://models/bogus")
        data = json.loads(out[0].text)
        assert data["count"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_resources.py -q`
Expected: FAIL — resources not registered; `read_resource` raises / returns nothing.

- [ ] **Step 3: Implement**

```python
# src/higgsfield_mcp/resources.py
"""MCP resources exposing the model catalog.

`higgsfield://models` returns the full catalog (including inferred models);
`higgsfield://models/{kind}` filters by kind. Clients that support resources
can subscribe to the catalog instead of calling list_models repeatedly.
"""

from __future__ import annotations

from typing import Any, cast

from fastmcp import FastMCP

from higgsfield_mcp.models import Kind
from higgsfield_mcp.tools import list_models

_KINDS = ("image", "video", "speech")


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource("higgsfield://models")
    async def all_models() -> dict[str, Any]:
        """The full Higgsfield model catalog, including inferred (unverified) models."""
        return await list_models(include_unverified=True)

    @mcp.resource("higgsfield://models/{kind}")
    async def models_by_kind(kind: str) -> dict[str, Any]:
        """Models of a single kind: image, video, or speech."""
        if kind not in _KINDS:
            return {"count": 0, "models": [], "error": f"unknown kind: {kind!r}"}
        return await list_models(kind=cast(Kind, kind), include_unverified=True)
```

In `src/higgsfield_mcp/server.py`, add the import and the call inside `build_server` (after `pool = BackendPool()`):

```python
from higgsfield_mcp.resources import register_resources
```

```python
    register_resources(mcp)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_resources.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/resources.py src/higgsfield_mcp/server.py tests/test_resources.py
git commit -m "feat: expose model catalog as MCP resources"
```

---

### Task 4: `recommend_model` tool

**Files:**
- Modify: `src/higgsfield_mcp/tools.py` (add `recommend_model`)
- Modify: `src/higgsfield_mcp/schemas.py` (add `RecommendItem`, `RecommendResult`)
- Modify: `src/higgsfield_mcp/server.py` (register `recommend_model_tool`)
- Test: `tests/test_recommend.py`

**Interfaces:**
- Produces: `recommend_model(intent: str, kind: Kind | None = None, top: int = 5, include_unverified: bool = False) -> dict` — scores registry entries by keyword overlap between the lowercased intent and each model's id/label/constraints/notes, returns the top N. Schema `RecommendResult { intent: str, recommendations: list[RecommendItem] }`, `RecommendItem { model_id, label, kind, backend, score: int, why: str }`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend.py
from __future__ import annotations

import pytest

from higgsfield_mcp.tools import recommend_model


@pytest.mark.asyncio
async def test_recommend_respects_kind_filter() -> None:
    out = await recommend_model("anything", kind="image", top=5)
    assert out["intent"] == "anything"
    assert 0 < len(out["recommendations"]) <= 5
    assert all(r["kind"] == "image" for r in out["recommendations"])


@pytest.mark.asyncio
async def test_recommend_scores_keyword_match_higher() -> None:
    out = await recommend_model("kling video", kind="video", top=3)
    assert out["recommendations"], "expected at least one recommendation"
    # the top result should mention kling (keyword overlap wins)
    assert "kling" in out["recommendations"][0]["model_id"].lower()
    assert out["recommendations"][0]["score"] >= 1


@pytest.mark.asyncio
async def test_recommend_excludes_inferred_by_default() -> None:
    out = await recommend_model("veo", kind="video", top=20)
    ids = {r["model_id"] for r in out["recommendations"]}
    assert "veo3_1" not in ids  # inferred, hidden by default
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_recommend.py -q`
Expected: FAIL — `ImportError: cannot import name 'recommend_model'`.

- [ ] **Step 3: Implement**

Add to `src/higgsfield_mcp/schemas.py`:

```python
class RecommendItem(BaseModel):
    model_id: str
    label: str
    kind: str
    backend: str
    score: int
    why: str


class RecommendResult(BaseModel):
    intent: str
    recommendations: list[RecommendItem]
```

Add to `src/higgsfield_mcp/tools.py` (it already imports `REGISTRY`, `Kind`; add `import re` at the top with the other stdlib imports):

```python
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
        score = len(hits)
        scored.append(
            {
                "model_id": spec.id,
                "label": spec.label,
                "kind": spec.kind,
                "backend": spec.backend,
                "score": score,
                "why": "matched: " + ", ".join(hits) if hits else "no keyword match",
            }
        )
    scored.sort(key=lambda r: (-r["score"], r["model_id"]))
    return {"intent": intent, "recommendations": scored[: max(0, top)]}
```

In `src/higgsfield_mcp/server.py`, import `recommend_model` from tools and `RecommendResult` from schemas, then register:

```python
    @mcp.tool
    async def recommend_model_tool(
        intent: str,
        kind: Kind | None = None,
        top: int = 5,
        include_unverified: bool = False,
    ) -> RecommendResult:
        """Suggest models for a described goal. Ranks by keyword overlap; verified-only by default."""
        return RecommendResult.model_validate(
            await recommend_model(
                intent=intent, kind=kind, top=top, include_unverified=include_unverified
            )
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_recommend.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/tools.py src/higgsfield_mcp/schemas.py src/higgsfield_mcp/server.py tests/test_recommend.py
git commit -m "feat: add recommend_model discovery tool"
```

---

### Task 5: `validate_params` tool

**Files:**
- Modify: `src/higgsfield_mcp/tools.py` (add `validate_params`)
- Modify: `src/higgsfield_mcp/schemas.py` (add `ValidateResult`)
- Modify: `src/higgsfield_mcp/server.py` (register `validate_params_tool`)
- Test: `tests/test_validate.py`

**Interfaces:**
- Produces: `validate_params(model_id: str, params: dict[str, Any]) -> dict` — checks supplied params against a model's `supports`, without calling any backend. Schema `ValidateResult { model_id, known_model: bool, valid: bool, unsupported: list[str], supported: list[str], constraints: list[str] }`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate.py
from __future__ import annotations

import pytest

from higgsfield_mcp.tools import validate_params


@pytest.mark.asyncio
async def test_validate_flags_unsupported_param() -> None:
    out = await validate_params(
        "higgsfield-ai/soul/standard", {"prompt": "x", "bogus": 1}
    )
    assert out["known_model"] is True
    assert out["valid"] is False
    assert out["unsupported"] == ["bogus"]


@pytest.mark.asyncio
async def test_validate_all_supported_is_valid() -> None:
    out = await validate_params(
        "higgsfield-ai/soul/standard", {"prompt": "x", "aspect_ratio": "16:9"}
    )
    assert out["valid"] is True
    assert out["unsupported"] == []


@pytest.mark.asyncio
async def test_validate_unknown_model() -> None:
    out = await validate_params("not-a-model", {"prompt": "x"})
    assert out["known_model"] is False
    assert out["valid"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/test_validate.py -q`
Expected: FAIL — `ImportError: cannot import name 'validate_params'`.

- [ ] **Step 3: Implement**

Add to `src/higgsfield_mcp/schemas.py`:

```python
class ValidateResult(BaseModel):
    model_id: str
    known_model: bool
    valid: bool
    unsupported: list[str]
    supported: list[str]
    constraints: list[str]
```

Add to `src/higgsfield_mcp/tools.py` (uses `REGISTRY`, `UnknownModelError` — add `UnknownModelError` to the existing `from higgsfield_mcp.models import ...` line):

```python
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
```

In `src/higgsfield_mcp/server.py`, import `validate_params` and `ValidateResult`, then register:

```python
    @mcp.tool
    async def validate_params_tool(
        model_id: str, params: dict[str, Any]
    ) -> ValidateResult:
        """Pre-flight check params against a model's supported set (no generation)."""
        return ValidateResult.model_validate(await validate_params(model_id, params))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_validate.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Full suite, gates, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src
git add src/higgsfield_mcp/tools.py src/higgsfield_mcp/schemas.py src/higgsfield_mcp/server.py tests/test_validate.py
git commit -m "feat: add validate_params discovery tool"
```

---

## Final verification

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv sync --all-extras --frozen
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q
```

Expected: all green; new tests in `test_resources.py` (3) + `test_recommend.py` (3) + `test_validate.py` (3) plus the updated `test_models.py`/`test_schemas.py`.

## Self-review against the spec

- Spec "Model registry": confidence tiers (Task 1), newest models added as inferred and hidden by default (Task 2). Covered.
- Spec §7 "Resources": `higgsfield://models` + `/{kind}` (Task 3). Covered.
- Spec §5 new tools: `recommend_model` (Task 4), `validate_params` (Task 5). Covered. `estimate_credits` deferred (no authoritative pricing) — documented decision, not a gap.
- Deferred to later: status-poll TTL cache and web→official fallback (spec §6) — they belong with live-verification work; `generate_batch` and prompts (Phase 4).
- Global constraints: `backends/`, `auth/` untouched; no new deps; new inferred models are data-only with unverified notes and hidden by default.

## Out of scope (later)

- Live endpoint verification to promote inferred→verified (needs credentials); wiring new web models into `V2_MODELS` body-shape selection happens then.
- `estimate_credits` (needs authoritative pricing); Phase 3 (Soul characters, history, balance, speech-video); Phase 4 (creative suite, prompts, batch, PyPI).

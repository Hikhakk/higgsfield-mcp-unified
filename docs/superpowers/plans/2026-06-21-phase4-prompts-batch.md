# Phase 4 (partial) — Prompts, Batch, README

Scope (user-approved): MCP prompt templates + `generate_batch` + README refresh.
Deferred: cloud creative suite (audio/3d/upscale/edit — needs live endpoint verification); PyPI publish (needs explicit go + token).

## Tasks
1. `prompts.py` + `register_prompts(mcp)` — cinematic/product `@mcp.prompt` templates; wired in `build_server`. Test via in-memory `fastmcp.Client`.
2. `generate_batch(pool, requests)` — fan out image/video submits concurrently (`asyncio.gather`, per-item ok/error), typed `BatchResult`. New tool `generate_batch_tool`.
3. README refresh — reflect 19→21 tools, 43-model catalog with confidence tiers, reliability, resources/prompts, discovery + character/account tools.

Gates each task: `uv run --extra dev pytest -q` + `ruff check` + `ruff format --check` + `mypy src`. Branch → PR → merge.

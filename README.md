# higgsfield-mcp-unified

Unified Model Context Protocol (MCP) server for [Higgsfield AI](https://higgsfield.ai/). Combines two backends behind one server so any MCP client (Claude Desktop, Cursor, Claude Code, etc.) can drive any of **27 Higgsfield image and video models** — Sora 2, Veo 3, Kling 3.0, Seedance, Soul, DOP, Nano Banana, and more — through a single tool surface.

> **Status: alpha (v0.1.0).** README is the source of truth for installable commands; rich docs live alongside the code in `docs/`.

## Why

Higgsfield exposes two surfaces:

- **Official REST API** (`platform.higgsfield.ai`) — stable, documented, key+secret auth, ~8 model IDs.
- **Cloud web app** (`cloud.higgsfield.ai`) — ~19 modern slugs (Sora 2, Veo 3, Kling 3.0, Seedance 2.0, Wan 2.6, …) but only reachable via Clerk JWT auth, undocumented, may break without notice.

Existing MCPs cover one side or the other. This server routes per-model to whichever backend supports it, so you never have to switch tools mid-conversation.

## Install

```bash
uvx higgsfield-mcp        # one-shot, recommended for client configs
# or
pipx install higgsfield-mcp-unified
```

## Configure

Two environment variables are mandatory:

```bash
export HIGGSFIELD_API_KEY=...        # from platform.higgsfield.ai dashboard
export HIGGSFIELD_SECRET=...
```

To unlock Sora 2 / Veo 3 / Kling 3.0 / etc., opt in to the web backend:

```bash
export HIGGSFIELD_ENABLE_WEB_BACKEND=1
export HIGGSFIELD_JWT=...            # paste a JWT from cloud.higgsfield.ai (DevTools → cookies)
```

**Heads up on the web backend:**
- Uses unofficial web-app auth that may break at any time.
- Probably outside Higgsfield's published terms of use — review them before turning this on.
- Off by default. Without `HIGGSFIELD_ENABLE_WEB_BACKEND=1`, only the 8 official models are reachable.

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "higgsfield": {
      "command": "uvx",
      "args": ["higgsfield-mcp"],
      "env": {
        "HIGGSFIELD_API_KEY": "...",
        "HIGGSFIELD_SECRET": "..."
      }
    }
  }
}
```

### Cursor / Claude Code / any stdio MCP client

Same idea — point at the `higgsfield-mcp` binary and pass env vars.

See `examples/` for working snippets.

## Tools

| Tool | What it does |
|---|---|
| `list_models(kind?)` | Returns the full registry. Use this to discover `model_id` values. |
| `generate_image(model_id, prompt, **params)` | Submits a text-to-image (or image-edit) job. |
| `generate_video(model_id, prompt, image_url?, **params)` | Submits a text-to-video or image-to-video job. |
| `generate_speech_video(model_id, ...)` | Talking-head route (official backend only). |
| `get_status(request_id)` | Returns `queued` / `in_progress` / `completed` / `failed` / `nsfw` plus output URLs. |
| `cancel_job(request_id)` | Cancels a pending request. |
| `upload_image(path_or_bytes)` | Uploads a local file and returns a hosted URL for use as `image_url`. |
| `subscribe(request_id)` | Long-polls until the job reaches a terminal state — convenience wrapper. |

## Models

Run `list_models()` for the live catalog. Highlights:

**Official backend** (`platform.higgsfield.ai`)
- Image: `higgsfield-ai/soul/standard`, `reve/text-to-image`, `bytedance/seedream/v4/text-to-image`, `bytedance/seedream/v4/edit`
- Video: `higgsfield-ai/dop/preview`, `higgsfield-ai/dop/standard`, `bytedance/seedance/v1/pro/image-to-video`, `kling-video/v2.1/pro/image-to-video`

**Web backend** (`cloud.higgsfield.ai`, opt-in)
- Image: `nano-banana-2`, `nano-banana-1`, `soul-v2`, `openai-hazel`
- Video: `kling3`, `kling-o3-flf`, `kling2-6`, `kling2-5-turbo`, `kling`, `grok`, `wan2-6`, `wan2-5-video`, `seedance1-5`, `seedance`, `seedance2`, `seedance2-fast`, `veo3`, `sora2-video`, `image2video`

## Development

```bash
git clone https://github.com/Hikhakk/higgsfield-mcp-unified
cd higgsfield-mcp-unified
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy src
```

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). All merges to `main` require code-owner approval (`@Hikhakk`) and green CI.

## Credits

Built on top of two earlier community efforts whose authors deserve credit even though this is a from-scratch rewrite:

- [`geopopos/geo_higgsfield_ai_mcp`](https://github.com/geopopos/geo_higgsfield_ai_mcp) — first Python MCP for the official API.
- [`jfikrat/higgsfield-mcp`](https://github.com/jfikrat/higgsfield-mcp) — first MCP to expose the cloud web models, source of the model registry.

## License

MIT — see [LICENSE](LICENSE).

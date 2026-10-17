# higgsfield-mcp-unified

A local-first [Model Context Protocol](https://modelcontextprotocol.io) server for [Higgsfield AI](https://higgsfield.ai/).
It puts **85 models from the official Higgsfield API**: Seedance 2.5, Kling 3.0 / O3 / Omni, Wan 3, Genjutsu, Cinema Studio 4, Soul, Marketing Studio, Recraft, Ideogram and more.
Soul character training, webhooks, cost estimates and preset catalogs sit behind the same typed tool surface, which any MCP client (Claude Desktop, Claude Code, Cursor, …) can use.
An opt-in experimental backend adds 34 consumer-app models such as Sora 2, Veo 3 and Nano Banana.

> **Status: alpha.** Install from source; this isn't on PyPI yet.
> The official-API path follows [docs.higgsfield.ai](https://docs.higgsfield.ai/docs) and has been cross-checked against the [open.higgsfield.ai](https://open.higgsfield.ai/explore) console.

## Why this over the hosted MCP

The official hosted MCP (`mcp.higgsfield.ai`) runs on Higgsfield's servers behind OAuth.
This one runs **on your machine** with your API key, and adds:

- **The full API catalog, typed.** Every documented endpoint has its parameters, enums, ranges and defaults, so the model picks valid values before spending credits.
- **Discovery that costs nothing.** `estimate_cost` prices a request, while `recommend_model`, `validate_params` and `preflight_check` work without running a generation.
- **Structured output.** Every tool returns a schema'd result (`outputSchema` + `structuredContent`), not an opaque blob.
- **Built-in reliability.**
  - Every submit carries an idempotency key, so retries (backoff with jitter, plus a circuit breaker) never double-charge.
  - Errors come back as typed cases: auth, out of credits, concurrency limit, bot challenge, network.
- **Webhooks and every output type.** It surfaces images, video, audio and the extra video/3D files (zip, mov, jsx, fbx, ply).

## Install

Clone and run with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Hikhakk/higgsfield-mcp-unified
cd higgsfield-mcp-unified
uv sync
uv run higgsfield-mcp        # starts the stdio MCP server
```

## Configure

Create an API key at [open.higgsfield.ai](https://open.higgsfield.ai) → **API keys**, then set:

```bash
export HIGGSFIELD_API_KEY=...        # key ID
export HIGGSFIELD_SECRET=...         # key secret
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "higgsfield": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/higgsfield-mcp-unified", "higgsfield-mcp"],
      "env": {
        "HIGGSFIELD_API_KEY": "...",
        "HIGGSFIELD_SECRET": "..."
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add higgsfield \
  -e HIGGSFIELD_API_KEY=... -e HIGGSFIELD_SECRET=... \
  -- uv run --directory /path/to/higgsfield-mcp-unified higgsfield-mcp
```

Cursor and other stdio clients use the same command; see [`examples/`](examples/).

### First run

1. `preflight_check()` confirms that credentials are configured.
2. `estimate_cost("higgsfield-ai/soul/v2/standard", {"prompt": "…"})` prices a request for free.
3. `generate_image(...)` returns a `job_handle`.
   Pass it to `subscribe(job_handle)` to wait for the output URLs.

Outputs are kept for at least 7 days, so download anything you want to keep.

## Tools

| Tool | What it does |
|---|---|
| `list_models(kind?, backend?, include_unverified?)` | The model registry: each model's `supports` (accepted params) and `constraints` (enums, ranges, defaults, required fields). |
| `recommend_model(intent, kind?, top?)` | Ranks models for a described goal (local, no API call). |
| `validate_params(model_id, params)` | Checks params against a model before submitting. |
| `estimate_cost(model_id, params)` | Prices a request in credits + USD without submitting it. |
| `preflight_check()` | Checks credentials and backend configuration without spending a generation. |
| `generate_image(model_id, prompt?, …, extra_params?, webhook_url?)` | Text-to-image, image editing, Soul character generations, ads and character sheets. |
| `generate_video(model_id, prompt?, image_url?, …, extra_params?, webhook_url?)` | Text-, image-, reference- and video-to-video, edits, extensions and motion transfer. |
| `generate_batch(requests[])` | Submits many image/video jobs concurrently; one failure never sinks the rest. |
| `get_status(job_handle)` / `subscribe(job_handle)` | Polls, or waits (2s → 10s backoff) until done. Returns `images`, `video_url`, `audio_urls` and `artifacts`. |
| `cancel_job(job_handle)` | Cancels a job that is still queued (refunded). |
| `upload_image(path \| data_base64, mime?)` | Uploads a local image, WAV or MP4 and returns a URL to pass as `image_url` / `audio_url` / `video_url`. |
| `list_model_presets(model_id, search?, size?, cursor?)` | Genjutsu Restyle styles, Marketing Studio Image presets and AI Influencer appearance options. |
| `create_character(name, image_urls, model_version?)` / `get_character` / `list_characters` / `delete_character` | Trains and manages Soul ID characters (`v1` / `v2` / `cinema`) for use as `soul_id`. |
| `get_balance()` / `list_jobs()` / `list_soul_styles()` / `list_motions()` / `generate_speech_video(...)` | Account and legacy helpers on undocumented `/v1` routes; best-effort. |

Model-specific fields beyond the named arguments go in `extra_params`, for example `image_urls`, `video_url`, `generate_audio`, `negative_prompt`, `preset_id` or `multi_prompt`.
Keys a model doesn't list in `supports` are dropped before the request is sent.

### Webhooks

Pass `webhook_url` (public HTTPS, official models only), and Higgsfield POSTs the final result to that URL. It's sent as the documented `hf_webhook` query parameter.

Your receiver should expect:

- **Payload:** `{request_id, status, error, payload}`, with the outputs under `payload`.
- **Duplicates:** deliveries can repeat, so dedupe by `request_id` + `status`.
- **Retries:** network errors and `5xx` responses are retried for up to 2 hours.

`get_status` is the fallback if a delivery is lost.
See [Webhooks](https://docs.higgsfield.ai/docs/how-to/webhooks).

## Resources & prompts

- **Resources:**
  - `higgsfield://models` is the full catalog.
  - `higgsfield://models/{kind}` filters it by kind.
  - Clients can read these instead of calling `list_models` repeatedly.
- **Prompts:** `cinematic_shot`, `product_360`, `animate_portrait`, `action_sequence`, `b_roll`.
  These are parameterized scaffolds for the generation tools.

## Models

Run `list_models()` for the live catalog.

**Official API (85, verified).** The registry is generated from each model page on [docs.higgsfield.ai](https://docs.higgsfield.ai/docs/models.md), using its endpoint ID and complete JSON schema.
It's then cross-checked against the [open.higgsfield.ai](https://open.higgsfield.ai/explore) console.
Where the two sources disagree, the model's `constraints` say so.

| | Models |
|---|---|
| **Image** | Soul, Soul V2 (text- and image-to-image), Soul Cinema, AI Influencer, Ads Studio, Marketing Studio Image (2.0, Flare, Sunburst), Grok Image 2, Ideogram 4, Qwen Image 3, Recraft v4.1 (+ Pro, Utility), Z-Image Turbo |
| **Video** | Seedance 2.0 / 2.5, Kling 2.5 Turbo / 2.6 / 3.0 (std, pro, 4K, turbo) / O3 / Omni, Kling Motion Control 2.6 / 3.0, Wan 2.6 / 2.7 / 3.0 / 3.0 Prime, Happy Horse 1.0 / 1.1, Genjutsu (motion transfer, object swap, restyle), Cinema Studio 4.0, MiniMax Hailuo 2.3 / H3, LTX 2.5, PixVerse v6, Grok Video 1.5 |

Availability depends on your account; the console is the source of truth.

**Web backend (34, opt-in).** Sora 2, Veo 3 / 3.1, Nano Banana, OpenAI Hazel, Soul v2, Kling, Seedance, Wan, Grok and others, all from the consumer app.
16 of them are marked `inferred`: the slug is real, but the endpoint is a best guess.
They're hidden unless you pass `include_unverified=true`.

## Experimental web backend

Some models only exist in the consumer app at `higgsfield.ai`.
To reach them:

```bash
export HIGGSFIELD_ENABLE_WEB_BACKEND=1
export HIGGSFIELD_CLERK_CLIENT=...   # __client cookie from higgsfield.ai (rotates ~weekly)
# or, for one-shot tests only:
export HIGGSFIELD_JWT=...            # __session cookie (expires in ~1 minute)
```

> **This will break.** `fnf.higgsfield.ai` is the consumer app's private backend, not a public API.
> It was integrated by reverse-engineering.
> Expect the following:
>
> - **Auth churn.** The session JWT lasts about 1 minute and is refreshed from the `__client` cookie.
>   Clerk rotates that cookie roughly every week; when it does, paste a new one.
> - **Bot protection.** Cloudflare fingerprints TLS. Browser-impersonating TLS (`curl_cffi`) gets through today, but it's brittle.
> - **Schema drift.** Paths and body keys are undocumented and change without notice.
> - **Probably against the terms of service.** Review them before you enable this.
>
> It's off by default.
> Without the flag, only the official API is used.

## Development

```bash
uv sync --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check .
uv run --extra dev mypy src
```

Design specs and phased plans live in `docs/superpowers/`.

## Contributing

PRs are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
Merges to `main` require code-owner approval (`@Hikhakk`) and green CI.

## Credits

This builds on two earlier community efforts:

- [`geopopos/geo_higgsfield_ai_mcp`](https://github.com/geopopos/geo_higgsfield_ai_mcp), the first Python MCP for the official API.
- [`jfikrat/higgsfield-mcp`](https://github.com/jfikrat/higgsfield-mcp), the first MCP to expose the web models and the source of the original web registry.

## License

MIT; see [LICENSE](LICENSE).

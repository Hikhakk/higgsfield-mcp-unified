# higgsfield-mcp-unified

Unified Model Context Protocol (MCP) server for [Higgsfield AI](https://higgsfield.ai/).
It puts **43 Higgsfield image and video models** — Sora 2, Veo 3.x, Kling 3.0, Seedance 2.0, Wan, Soul, DOP, Nano Banana, FLUX, and more — plus Soul character training, account/history, and talking-head speech behind a single, typed tool surface for any MCP client (Claude Desktop, Claude Code, Cursor, …).

> **Status: alpha.** Local/self-hosted and not yet on PyPI — install from source (below). The cloud web backend is opt-in and experimental.

## Why this over the hosted MCP

The official hosted MCP (`mcp.higgsfield.ai`) is great but runs on Higgsfield's servers behind OAuth. This one is **local-first** and adds things a hosted server can't:

- **Runs on your machine** — prompts and media go straight to Higgsfield, no intermediary proxy.
- **Dual backend under one surface** — routes per model across the official REST API and the cloud web app.
- **Typed structured output** — every tool returns a schema'd result (`outputSchema` + `structuredContent`), not an opaque blob.
- **Discovery without burning a generation** — `recommend_model`, `validate_params`, `preflight_check`, and an MCP resource catalog.
- **Reliability built in** — retries with backoff + jitter (honoring `Retry-After`), a circuit breaker, idempotency keys, and a structured error taxonomy.
- **MCP prompt templates** — reusable cinematic/product scaffolds.

## Backends

- **Official REST API** (`platform.higgsfield.ai`) — stable, `KEY:SECRET` auth. Default; rock-solid.
- **Cloud web app** (`fnf.higgsfield.ai`) — the newest models, reachable only via a Clerk cookie. Opt-in and experimental (see warning below).

## Install (from source)

Not published to PyPI yet. Clone and run with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Hikhakk/higgsfield-mcp-unified
cd higgsfield-mcp-unified
uv sync
uv run higgsfield-mcp        # starts the stdio MCP server
```

## Configure

The official backend needs two environment variables:

```bash
export HIGGSFIELD_API_KEY=...        # from the platform.higgsfield.ai dashboard
export HIGGSFIELD_SECRET=...
```

To unlock the cloud-only models (Sora 2 / Veo 3.x / Kling 3.0 / …), opt in to the web backend:

```bash
export HIGGSFIELD_ENABLE_WEB_BACKEND=1
export HIGGSFIELD_CLERK_CLIENT=...   # __client cookie from cloud.higgsfield.ai (lasts ~7 days)
# or, for one-shot tests only:
export HIGGSFIELD_JWT=...            # __session cookie (expires in ~1 minute)
```

Run `preflight_check` from your client to confirm both backends are reachable before generating.

> ## Web backend is experimental and will likely break
>
> The `cloud.higgsfield.ai` / `fnf.higgsfield.ai` surface is **not a public API** — it is the consumer web app's private backend, integrated by reverse-engineering. Expect:
>
> - **Auth churn.** The Clerk JWT lives ~1 minute. The server refreshes it from a long-lived `__client` cookie, but Clerk rotates that cookie too (~7 days). When it rotates, paste a new one.
> - **Bot protection.** `fnf.higgsfield.ai` sits behind Cloudflare's managed challenge (TLS fingerprinting). Browser-impersonating TLS (`curl_cffi`) clears it today, but it is brittle.
> - **Schema drift.** Endpoint paths, body keys, and slugs are undocumented and change without notice. Several of the newest model endpoints in this server are marked `inferred` (best-guess, hidden by default) until verified against live traffic.
> - **Probably against ToS.** Driving the consumer app programmatically is almost certainly unsupported. Review the terms before enabling it.
>
> Off by default. Without `HIGGSFIELD_ENABLE_WEB_BACKEND=1`, only the official-API models are reachable, and that path is solid.

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

Cursor / Claude Code / any stdio MCP client: point at the same `uv run … higgsfield-mcp` command and pass env vars. See `examples/`.

## Tools

| Tool | What it does |
|---|---|
| `list_models(kind?, backend?, include_unverified?)` | The model registry. Inferred (unverified) models are hidden unless `include_unverified`. |
| `recommend_model(intent, kind?, top?)` | Rank models for a described goal (local, no API call). |
| `validate_params(model_id, params)` | Check params against a model's supported set before submitting. |
| `preflight_check()` | Validate auth + reachability for both backends without spending a generation. |
| `generate_image(model_id, prompt, …, soul_id?)` | Submit a text-to-image / image-edit job (supports Soul character refs). |
| `generate_video(model_id, prompt, image_url?, …)` | Submit a text-to-video / image-to-video job. |
| `generate_batch(requests[])` | Fan out multiple image/video submits concurrently. |
| `generate_speech_video(image_url, audio_url, prompt?)` | Talking-head video from a face image + WAV audio. |
| `get_status(job_handle)` / `subscribe(job_handle)` | Poll, or long-poll until terminal, with output URLs. |
| `cancel_job(job_handle)` | Cancel a queued/in-progress job. |
| `upload_image(path \| data_base64, backend?)` | Upload a local image and get a hosted URL. |
| `create_character` / `get_character` / `list_characters` / `delete_character` | Train and manage reusable Soul characters. |
| `list_soul_styles()` / `list_motions()` | Soul style and DOP motion presets, by name. |
| `get_balance()` | Available credits + plan (official backend). **Currently fails honestly** — no working balance/credits route exists in this API version (AOF-274); raises `EndpointUnavailableError` rather than a bare 404. |
| `list_jobs(page?, page_size?)` | Recent generations (history). |

## Resources & prompts

- **Resources:** `higgsfield://models` (full catalog) and `higgsfield://models/{kind}` — subscribe to the catalog instead of repeatedly calling `list_models`.
- **Prompts:** `cinematic_shot`, `product_360`, `animate_portrait`, `action_sequence`, `b_roll` — parameterized scaffolds to feed into the generation tools.

## Models

Run `list_models()` (or read the `higgsfield://models` resource) for the live catalog. The registry carries a `confidence` tier:

- **`verified`** — endpoint confirmed against SDK source / live probe (shown by default).
- **`inferred`** — slug confirmed real but the endpoint is a best-guess pending live verification (hidden unless `include_unverified=true`, and noted as such).

Official backend (verified): Soul, Reve, Seedream v4 (text-to-image + edit), FLUX.1 Kontext Max, DOP (preview/standard), Seedance v1 Pro, Kling v2.1 Pro.
Cloud backend: Kling 3.0 / O3 FLF, Seedance 2.0 / 1.5, Wan 2.6, Veo 3, Grok, Sora 2, Nano Banana, Soul v2, OpenAI Hazel, and newest-tier `inferred` entries (Veo 3.1, Wan 2.7, Kling 3.0 Turbo, Hailuo 02, FLUX.2, Z-Image, Cinematic Studio, …).

## Development

```bash
uv sync --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check .
uv run --extra dev mypy src
```

Design specs and phased implementation plans live in `docs/superpowers/`.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Merges to `main` require code-owner approval (`@Hikhakk`) and green CI.

## Credits

Built on two earlier community efforts:

- [`geopopos/geo_higgsfield_ai_mcp`](https://github.com/geopopos/geo_higgsfield_ai_mcp) — first Python MCP for the official API.
- [`jfikrat/higgsfield-mcp`](https://github.com/jfikrat/higgsfield-mcp) — first MCP to expose the cloud web models; source of the original model registry.

## License

MIT — see [LICENSE](LICENSE).

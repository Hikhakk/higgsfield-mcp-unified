# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-17

First public release.

### Added

- **Official backend.** Runs against `api.higgsfield.ai` with `Authorization: Key KEY_ID:SECRET`; keys come from `open.higgsfield.ai`.
- **85 official models.**
  - 83 are generated from the per-model pages on docs.higgsfield.ai (endpoint ID + complete JSON schema).
  - AI Influencer and Soul 2 image-to-image come from the open.higgsfield.ai console.
  - Each model lists its params, enums, ranges, defaults and required fields.
  - Where the docs and the console disagree, the model's constraints say so.
- **Generation tools.**
  - `generate_image`, `generate_video` and `generate_batch` take `extra_params` for model-specific fields and an optional `prompt`.
  - They also take `webhook_url`, sent as `hf_webhook`.
  - On official Kling models, `sound` is mapped to `on` / `off`.
- **Results.**
  - `get_status` and `subscribe` return images, video, `audio_urls` and `artifacts` (zip / mov / jsx / fbx / ply).
  - `subscribe` backs off from 2s to 10s between polls.
- **Discovery tools.**
  - `list_models`, `recommend_model` and `validate_params` work locally.
  - `estimate_cost` calls `POST /estimate/{model}`.
  - `preflight_check` checks configuration.
  - `list_model_presets` returns Genjutsu Restyle styles, Marketing Studio Image presets and AI Influencer options.
- **Uploads.** `upload_image` uploads through a presigned URL (forwarding the returned `upload_headers`) and accepts the documented image, WAV and MP4 types.
- **Soul ID characters.** `create_character` / `get_character` / `list_characters` / `delete_character` train and manage Soul ID characters with `model_version` (`v1` / `v2` / `cinema`).
- **Best-effort helpers on undocumented `/v1` routes:** `get_balance`, `list_jobs`, `list_soul_styles`, `list_motions`, `generate_speech_video`.
- **Reliability.**
  - Every submit sends an `Idempotency-Key` and is retried on 429 / 5xx with backoff and jitter.
  - A circuit breaker stops calls to a backend that keeps failing.
  - Errors are typed: auth, out of credits, concurrency/rate limit, bot challenge, network, schema.
- **MCP surface.**
  - Every tool has a typed output schema.
  - Resources: `higgsfield://models` and `higgsfield://models/{kind}`.
  - Prompt templates: `cinematic_shot`, `product_360`, `animate_portrait`, `action_sequence`, `b_roll`.
- **Experimental web backend (opt-in).**
  - Reaches 34 consumer-app models (Sora 2, Veo 3, Nano Banana, …).
  - Authenticates with an explicit `HIGGSFIELD_JWT`, or a `HIGGSFIELD_CLERK_CLIENT` cookie with Clerk-side refresh.
  - Uses `curl_cffi` TLS impersonation and an optional `HIGGSFIELD_DATADOME_COOKIE` passthrough.
  - Prints a startup warning when enabled.

### Known limitations

- **Untested against the live API.** The official endpoints are verified against the docs and the console, but no paid generation was run before release.
- **Web backend.**
  - `fnf.higgsfield.ai` is the consumer app's private backend, not a public API, and is probably outside Higgsfield's terms of use.
    Cloudflare and Datadome rate-limit and IP-block programmatic clients; TLS impersonation clears the basic check but does not survive sustained traffic.
  - The Clerk session JWT lives about a minute, and the `__client` cookie that mints it rotates roughly weekly.
    Tokens minted on `cloud.higgsfield.ai` (`azp=cloud.higgsfield.ai`) are rejected; use the consumer-app login at `higgsfield.ai`.
  - Some web slugs are stale relative to the live app, and 16 web models are marked `inferred` (hidden by default).

[Unreleased]: https://github.com/Hikhakk/higgsfield-mcp-unified/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Hikhakk/higgsfield-mcp-unified/releases/tag/v0.1.0

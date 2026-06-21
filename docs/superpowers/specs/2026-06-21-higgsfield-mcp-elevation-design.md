# Higgsfield MCP Unified — Elevation Design

Date: 2026-06-21
Status: proposed (awaiting approval)
Topic: make `higgsfield-mcp-unified` a local-only MCP server that is objectively better than the official hosted MCP at `https://mcp.higgsfield.ai/mcp`.

## Goal

Turn the alpha `higgsfield-mcp-unified` into the best Higgsfield MCP available, beating the official hosted server on the axes a local OSS server can win: privacy, breadth under one tool surface, reliability, typed/structured output, and agent ergonomics.

Strategic choices locked with the user:

- Ambition: full superset of the high-value creative surface.
- Architecture: local-only, two backends, pluggable so federation can be added later — but no federation and no hosted/credit-billed path in v1.
- Web backend: keep but harden.
- Audience: public OSS users; ship at OSS quality (docs, tests, PyPI-installable).

## Background — what we are competing with

The official hosted MCP exposes 47 tools (enumerated live; its auth gate validates token shape, not validity).

Grouped:

- Generate: `generate_image`, `generate_video`, `generate_audio`, `generate_3d`.
- Edit/transform: `upscale_image`, `upscale_video`, `remove_background`, `outpaint_image`, `reframe`, `motion_control`, `voice_change`, `dubbing`.
- Characters/elements: `show_characters` (Soul train/list), `show_reference_elements`.
- Discovery: `models_explore`, `list_voices`, `presets_show`, `animation_actions`.
- Jobs/history/media: `job_status`, `job_display`, `reveal_generation`, `show_generations`, `show_marketing_studio_generations`, `show_medias`, `media_upload`, `media_import_url`, `media_confirm`, `media_upload_widget`.
- Billing: `balance`, `transactions`, `show_plans_and_credits`, `confirm_billing_purchase`.
- Hosted-platform-only: `show_marketing_studio`, `virality_predictor`, `personal_clipper_*`, `video_analysis_*`, `list_workspaces`, `select_workspace`, `sync_agents`, `deploy_game`, `publish_game`, `get_game_creation_*`.

The hosted-platform-only group depends on Higgsfield's hosted Apps UI, widgets, workspaces, and marketplace; it is out of scope for a local server (see Non-goals).

## Ground truth established by research (adversarially verified)

- Auth audiences: official REST (`platform.higgsfield.ai`) uses `Authorization: Key KEY:SECRET` only and rejects bearer/OAuth tokens; the cloud backend (`fnf.higgsfield.ai`) uses short-lived Clerk JWTs minted from a `__client` cookie; device-code tokens (`fnf-device-auth.higgsfield.ai`) carry `aud=mcp.higgsfield.ai` and only authorize the hosted MCP.
- Canonical sources: `higgsfield-ai/cli` (with `MODELS.md`), `higgsfield-ai/higgsfield-js`, `higgsfield-ai/higgsfield-client` (Python SDK), `higgsfield-ai/skills`; docs at `docs.higgsfield.ai/docs/...`.
- Official REST submit is `POST https://platform.higgsfield.ai/{model_path}` with a flat JSON body (no `params` wrapper); webhooks via `?hf_webhook=<url>`; status `GET /requests/{id}/status`; cancel `POST /requests/{id}/cancel`; upload via `POST /files/generate-upload-url` then `PUT`.
- Legacy v1 routes exist and use two headers `hf-api-key` + `hf-secret` (not `Key KEY:SECRET`): Soul image `POST /v1/text2image/soul`, talking-head `POST /v1/speak/higgsfield`, lookups `GET /v1/motions` and `GET /v1/text2image/soul-styles`.
- Soul characters: `POST /v1/custom-references` (create), `GET /v1/custom-references/list` (list), `DELETE /v1/custom-references/{id}` (delete); `GET /v1/custom-references/{id}` is a polling artifact; there is no update. Generation uses `custom_reference_id` + `custom_reference_strength` on `/v1/text2image/soul`.
- History: `POST /agents/jobs` (official; confirmed present) and `GET /jobs?size=N` (cloud).
- Credits/account: `POST /v1/billing/credits`, plus `/v1/account`, `/v1/user`, `/v1/balance` exist and are POST-only and auth-gated; response schemas are undocumented and must be probed with real credentials.
- Cloud bot protection is Cloudflare managed-challenge (TLS fingerprint), not Datadome; `curl_cffi` Chrome impersonation currently passes.
- Many newest cloud slugs are confirmed real (via `higgsfield-ai/cli` `MODELS.md`) but their exact `/jobs/...` paths are unverified and inconsistent (`/jobs/v2/<slug>` vs `/jobs/<slug>` vs hyphenated). These must be confirmed with authenticated traffic before being shipped as verified.
- FastMCP: client OAuth helpers do not support device-code and ship no persistent token store; resources support `listChanged` but not per-resource `subscribe`; `ctx.elicit()`/`ctx.sample()` are server-complete but client support is sparse (Claude Code does not support elicit).

## Architecture

Keep the existing clean layering and the pluggable backend protocol; extend rather than rewrite.

```
server.py        FastMCP wiring: tool/resource/prompt registration, lifespan
tools.py         tool implementations + routing + value-add logic
models.py        model registry (two-tier confidence) + intent scoring
pricing.py       static credit/cost table for estimate_credits (new)
prompts.py       MCP prompt templates (new)
resources.py     MCP resource handlers for the catalog (new)
errors.py        structured error taxonomy (new)
reliability.py   retry/backoff, circuit breaker, idempotency helpers (new)
backends/
  base.py        BackendDriver protocol, JobHandle, JobStatus, error base
  official.py    platform.higgsfield.ai (Key:Secret v2 slug paths + v1 two-header)
  web.py         fnf.higgsfield.ai (Clerk JWT, hardened)
auth/
  api_key.py     Key:Secret loader (+ v1 hf-api-key/hf-secret split)
  clerk.py       __client cookie -> session JWT minting
models/          Pydantic output models for structured tool results (new)
```

Design constraints:

- Each backend stays independently testable behind `BackendDriver`; the registry maps `model_id -> backend + endpoint`.
- The backend protocol must remain forward-compatible with a future `hosted-mcp` federation driver, but that driver is not built in v1.
- Tools return Pydantic models (not bare dicts) so FastMCP emits `outputSchema` + `structuredContent`.

## Auth design

Priority order, all local, no hosted dependency:

- Official REST: `HIGGSFIELD_API_KEY` + `HIGGSFIELD_SECRET` -> `Authorization: Key KEY:SECRET` for v2 slug paths (already implemented and correct).
- Official REST v1 routes: same credentials re-expressed as `hf-api-key` + `hf-secret` headers, used only for `/v1/...` paths (Soul characters, talking-head, soul-styles, motions). `auth/api_key.py` gains a `v1_headers()` helper; `official.py` selects header style by path prefix.
- Cloud backend: `HIGGSFIELD_CLERK_CLIENT` (`__client` cookie) minted into short-lived JWTs (already implemented). Smooth the UX: clearer setup errors, a `preflight_check` tool that reports cookie/JWT health and time-to-expiry, and reduce the refresh slack from 30s toward ~10s to match Clerk SDK behavior while staying safe.
- `HIGGSFIELD_JWT` remains a one-shot override.

Out of scope for v1: device-code OAuth and PKCE. Rationale: device-code tokens only authorize the hosted MCP, which we are not federating in v1, so the client would have nothing local to authenticate. Re-add it together with a federation backend if that is ever pursued.

## Model registry

Rebuild `models.py` from `higgsfield-ai/cli` `MODELS.md` as the canonical slug source, reconciled against the live consumer app and `jfikrat` paths.

Each `ModelSpec` gains a confidence field:

- `verified` — endpoint confirmed by SDK source, traffic capture, or live probe.
- `inferred` — slug confirmed real, endpoint inferred by naming convention; surfaced only with `include_unverified=True` and labeled.

Rules:

- Official-backend models use multi-segment slug paths (`bytedance/seedream/v4/text-to-image`); never `/jobs/v2/` for the official backend.
- Cloud-backend models use `/jobs/...` or `/jobs/v2/...`; the prefix is not deterministic, so each entry is explicit, not derived.
- Reconcile known stale entries: `nano-banana-1` (bad upstream path), `seedance2-fast` (should be `mode=fast` on `seedance_2_0`, not a separate slug), and any `imagegen_2_0`/`open_sora_video` layering.
- Per-model `constraints` encode real duration/resolution enums; never a global "4K/15s" claim.
- Add newest models as `inferred` until a live authenticated probe promotes them to `verified`; `list_models` hides `inferred` by default.

## Tool surface

Existing (keep, upgrade to typed output + routing/reliability): `list_models`, `generate_image`, `generate_video`, `get_status`, `cancel_job`, `upload_image`, `subscribe`.

New, locally implementable against verified or probe-confirmable endpoints:

- `create_character` — train a Soul ID from reference image URLs (`POST /v1/custom-references`, v1 two-header auth); returns `character_id`.
- `get_character` — poll Soul ID training status.
- `list_characters` — enumerate trained Soul IDs (`GET /v1/custom-references/list`).
- `delete_character` — remove a Soul ID (`DELETE /v1/custom-references/{id}`).
- `list_soul_styles` — return Soul style presets (`GET /v1/text2image/soul-styles`).
- `list_motions` — return DOP motion presets (`GET /v1/motions`).
- `generate_speech_video` — talking-head (`POST /v1/speak/higgsfield`, WAV-only enforced at tool level).
- `list_jobs` — generation history (official `POST /agents/jobs`; cloud `GET /jobs`); recovers handles after restart.
- `get_balance` — credits/plan (`POST /v1/billing/credits`, best-effort, graceful on undocumented schema).
- `recommend_model` — map a natural-language intent to ranked models (local scoring over the registry); our answer to `models_explore`.
- `estimate_credits` — local dry-run cost estimate from `pricing.py` (no API call).
- `validate_params` — local pre-flight of params against `ModelSpec.supports`/`constraints`.
- `generate_batch` — fan out multiple submits concurrently; returns a list of job handles.
- `preflight_check` — validate auth + reachability for both backends before spending a generation.

New parameters on existing tools:

- `generate_image`: `soul_id` + `soul_strength` (mapped to `custom_reference_id`/`custom_reference_strength`), plus `style` for Soul styles.
- `generate_video`: `negative_prompt`, `cfg_scale`, `mode`, `genre`, `sound` for Kling/Seedance families.
- Wire `OfficialBackend.upload()` to `POST /files/generate-upload-url` + `PUT` so `upload_image(backend="official")` works.

Phase-gated on live endpoint verification (cloud creative suite):

- `generate_audio` (TTS), `generate_3d` (GLB), `upscale_image`, `upscale_video`, `remove_background`, `outpaint_image`, `reframe`, `motion_control`, `voice_change`, `dubbing`, `list_voices`.

Naming stays bare snake_case (`generate_image`), matching the documented public convention.

## Reliability hardening (code-tied)

- `reliability.py`: `retrying_request()` wrapping `curl_cffi` and `httpx` calls; retry on 429/502/503/504 and transport errors with exponential backoff + jitter; honor `Retry-After`; never retry 400/401/403; caps 4 (submit) / 3 (status).
- Per-backend auth-refresh lock in `web.py` `_auth_header()` to avoid double-mint races on the `HIGGSFIELD_JWT` path; keep the existing `ClerkRefresher` lock for the cookie path.
- Smarter status: probe whether `GET /jobs/{id}` exists; if not, add a short TTL cache around the full-list poll so concurrent polls share one round-trip.
- Concurrency cap (`asyncio.Semaphore`) on the cloud backend across submit/status/cancel/upload.
- Module-level circuit breaker keyed by base URL; OPEN after repeated failures, HALF-OPEN probe after cooldown, fail fast with an actionable message.
- Idempotency: a stable `X-Idempotency-Key` per `submit()`, constant across retries.
- `errors.py` taxonomy: `AuthError`, `RateLimitError(retry_after)`, `BotChallengeError`, `SchemaError`, `NetworkError`, each mapped to an actionable user message. Rename the "Datadome" wording to "Cloudflare TLS-fingerprint challenge".
- Graceful fallback: on `AuthError`/`BotChallengeError`/circuit-open for a cloud model, if an equivalent official model exists and a key is set, re-route and flag `fallback_used: true`; otherwise return a structured error naming the nearest official model.

## FastMCP / SDK usage

- Bump `fastmcp` to a current 3.x to get structured output, per-tool metadata, and `ToolResult(is_error=True)`.
- Structured output: every tool returns a Pydantic model so FastMCP auto-emits `outputSchema` + `structuredContent`.
- Resources: `higgsfield://models` and `higgsfield://models/{kind}` expose the catalog; fire `listChanged` on refresh. Keep `list_models` as a fallback for resource-blind clients. Do not rely on per-resource `subscribe` (unsupported).
- Prompts: `@mcp.prompt` cinematic/product templates (for example action-sequence, product-360, animate-portrait).
- Progress: `ctx.report_progress` inside `subscribe` and `generate_batch`.
- Do not depend on `ctx.elicit()` for required flows (Claude Code lacks support); use it only as an optional enhancement with a non-interactive fallback.

## Differentiators vs the official hosted MCP

- Local/self-hosted: prompts and media go directly to Higgsfield with no intermediary OAuth/proxy.
- Dual-backend per-model routing with automatic web to official fallback.
- API-key default auth with no browser redirect.
- `estimate_credits`, `validate_params`, `recommend_model`, `generate_batch`, `preflight_check` — agent-ergonomic tools the hosted MCP does not expose.
- Structured `outputSchema` on every tool, catalog as MCP resources, MCP prompt templates.
- Reliability suite (retry/breaker/idempotency/error taxonomy/fallback).

## Non-goals (v1)

- Federation of the hosted MCP and device-code OAuth (deferred together; no credit-billed/hosted path).
- Hosted-platform-only tools: marketing studio, virality predictor, personal clipper, video analysis, workspaces, `sync_agents`, billing-purchase widgets, game build/deploy/publish.
- Any Cloudflare/Datadome detection-evasion work beyond the existing `curl_cffi` impersonation already in the repo; hardening targets robustness/correctness only.

## Open questions to resolve during implementation (probe with real credentials)

- Exact `/jobs/...` paths for the ~14 inferred newest cloud slugs (veo3_1, veo3_1_lite, wan2_7, kling3_0_turbo, minimax_hailuo, grok_video_v15, gpt_image_2, flux_2, flux_kontext, seedream_v5_lite, seedream_v4_5, recraft_v4_1, cinematic_studio_3_0, marketing_studio_*).
- Response schemas for `POST /v1/billing/credits`, `/v1/account`, `/agents/jobs`.
- Whether `GET /jobs/{id}` exists on the cloud backend.
- Official `upload()` whether a post-PUT confirm step is required.
- Soul training minimum image count and whether a v2 Key-auth character endpoint exists.
- Endpoints for the cloud creative suite (`generate_audio`, `generate_3d`, upscale/edit family, `list_voices`).

## Testing

- Unit: registry shape/uniqueness/confidence; param filtering; routing; error taxonomy mapping; reliability (retry/backoff/breaker) with mocked transports via `respx`.
- Backend contract tests against recorded fixtures for official and cloud submit/status/cancel/upload.
- Pydantic output-model validation for each tool.
- Keep `mypy --strict` and `ruff` green; expand CI matrix as needed.

## Milestones (for the implementation plan)

- Phase 0: merge the three Dependabot PRs (#2 setup-uv, #3 uv-build, #4 checkout) once CI is green; bump `fastmcp`; repo hygiene.
- Phase 1 (foundation): structured output models, `errors.py`, `reliability.py`, web-backend hardening, `preflight_check`, official `upload()`, auth smoothing.
- Phase 2 (catalog): rebuild registry with confidence tiers, MCP resources, `recommend_model`, `estimate_credits`, `validate_params`.
- Phase 3 (parity): Soul characters suite, `soul_id`/`style` params, `list_jobs`, `get_balance`, `generate_speech_video`, `list_soul_styles`, `list_motions`.
- Phase 4 (creative+): cloud creative suite tools gated on live verification, MCP prompts, `generate_batch`, README/docs refresh, PyPI release.

## Success criteria

- Tool count and creative coverage meet or exceed the official MCP's locally-relevant surface.
- All official-backend paths work end-to-end with real credentials; cloud paths work where verified and degrade gracefully where not.
- `mypy --strict` + `ruff` clean; tests cover routing, reliability, and output schemas.
- README repositions the project around local/private, dual-backend, reliability, and the value-add tools; installable via `uvx higgsfield-mcp`.

# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial unified MCP server combining official `platform.higgsfield.ai` API and opt-in `cloud.higgsfield.ai` / `fnf.higgsfield.ai` web backend.
- Model registry covering 27 image and video models (8 official, 4 web image, 15 web video).
- MCP tools: `list_models`, `generate_image`, `generate_video`, `get_status`, `cancel_job`, `upload_image`, `subscribe`.
- Three-tier auth for the web backend: explicit `HIGGSFIELD_JWT` override, long-lived `HIGGSFIELD_CLERK_CLIENT` cookie with Clerk-side refresh, or hard fail with an actionable error.
- `curl_cffi` Chrome TLS impersonation for web-backend traffic to clear Datadome's TLS-fingerprint check.
- `HIGGSFIELD_DATADOME_COOKIE` passthrough for sessions where the cookie has been pinned externally.
- Startup stderr warning when the experimental web backend is enabled.

### Verified

- `higgsfield-ai/soul/standard` end-to-end against `platform.higgsfield.ai` (submit + poll + image URL returned).

### Known limitations (web backend only)

- The `fnf.higgsfield.ai` host is the consumer web app's private backend, not a public API.
  Cloudflare and Datadome aggressively rate-limit and IP-block programmatic clients after a small number of requests.
  TLS impersonation clears the basic check but does not survive sustained traffic.
- The Clerk session JWT lives roughly one minute.
  The `__client` cookie that mints fresh JWTs rotates roughly every seven days; users must re-paste it when that happens.
- JWT audience matters: tokens minted on `cloud.higgsfield.ai` (the developer dashboard) are scoped `azp=cloud.higgsfield.ai` and are rejected by `fnf.higgsfield.ai`.
  The consumer-app login at `higgsfield.ai` is what produces the right `azp=higgsfield.ai` token.
- Several upstream slugs in the registry (`seedance2`, `kling3`, `kling-o3-flf`, `nano-banana-1`) are stale relative to the live consumer app, which uses underscored model slugs (`seedance_2_0`, `kling3_0`, `kling-omni-flf`, `imagegen_2_0`, `veo-3-1-preview`, `wan2_7`, `open_sora_video`).
  These will be reconciled in a future release after a clean live capture.
- The web backend is almost certainly outside Higgsfield's published terms of use.
  Driving it from an MCP server is at the user's own risk.

# Contributing

Thanks for considering a contribution. This project is owner-gated: all PRs require an approving review from a code owner before merge. Anyone can fork, open issues, and submit PRs — that's encouraged.

## Quick start

```bash
git clone https://github.com/Hikhakk/higgsfield-mcp-unified
cd higgsfield-mcp-unified
uv sync --extra dev
uv run pytest
```

## Pull request rules

1. **One logical change per PR.** Smaller is faster to review.
2. **Tests required.** New code must come with pytest coverage. Bug fixes must include a regression test.
3. **Lint must pass.** Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src` locally before pushing.
4. **Don't commit secrets.** No real API keys, JWTs, or session cookies in fixtures.

## Adding a new model

1. Append a `ModelSpec` entry to `src/higgsfield_mcp/models.py`.
2. Provide a public source for the `endpoint`/`model_id` (Higgsfield docs link, official SDK example, or a reproducible network capture).
3. Add a registry test in `tests/test_models.py` asserting the new entry parses cleanly.
4. Use the **New model** issue template if you're requesting rather than implementing.

## Reporting auth/web-backend breakage

The web backend (`cloud.higgsfield.ai`) is opt-in and inherently fragile because it relies on web-app authentication that may change without notice. When it breaks:

1. File a `web-backend` issue with the failing slug, the HTTP response body, and the date.
2. Do not include cookies or JWTs in the report.

## Code review

All merges to `main` require at least one approval from `@Hikhakk`. External reviews are welcome and read carefully, but only code-owner approvals satisfy branch protection.

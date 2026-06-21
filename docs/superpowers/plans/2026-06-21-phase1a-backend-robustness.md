# Phase 1a — Backend Robustness Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make both Higgsfield backends production-robust — typed error taxonomy, retry/backoff with circuit breaking, correct v1 vs v2 auth, a working official-backend uploader, and a `preflight_check` tool — without touching the model registry or FastMCP version.

**Architecture:** Add two small transport-agnostic modules (`errors.py`, `reliability.py`) and wire them into the existing `OfficialBackend` (httpx) and `WebBackend` (curl_cffi) drivers behind their existing dependency-injection seams. Add a `preflight_check` tool that reports auth/reachability for both backends. All new logic is unit-tested in isolation; backend integration uses injected fakes so no network is required.

**Tech Stack:** Python 3.10+, httpx, curl_cffi, pydantic v2, pytest + pytest-asyncio + respx, ruff, mypy --strict.

## Global Constraints

- Python floor: `requires-python >= 3.10`; code must pass `mypy --strict` and `ruff check .` (select E,F,I,B,UP,SIM,RUF; line-length 100; E501 ignored).
- Keep dependencies minimal — do NOT add new runtime deps (no `tenacity`, no `pybreaker`); hand-roll retry/breaker.
- Do NOT modify `src/higgsfield_mcp/models.py` or the registry in this plan; `tests/test_models.py` (27 models: 8 official + 19 web) must stay green.
- Do NOT bump `fastmcp` in this plan; tool return values stay plain `dict[str, Any]` (structured output is Phase 1b).
- Preserve existing public import paths: `BackendError` stays importable from `higgsfield_mcp.backends.base`; `_build_body`, `_extract_job_id`, `WebBackend`, `OfficialBackend`, `BackendPool` keep their names.
- Use `from __future__ import annotations` at the top of every module (matches the codebase).
- Prefer `const`-style immutability: frozen dataclasses where state is not mutated; functional helpers over classes when practical.
- Commit after every task with a short imperative message; one logical change per commit. Do NOT push (the human lands work via branch → PR → merge).

---

### Task 1: Error taxonomy (`errors.py`)

**Files:**
- Create: `src/higgsfield_mcp/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: `BackendError` from `higgsfield_mcp.backends.base` (existing: constructor `BackendError(message, *, status_code=None, body=None)`).
- Produces:
  - `class AuthError(BackendError)`
  - `class RateLimitError(BackendError)` with extra attr `retry_after: float | None`
  - `class BotChallengeError(BackendError)`
  - `class SchemaError(BackendError)`
  - `class NetworkError(BackendError)`
  - `class CircuitOpenError(BackendError)`
  - `def parse_retry_after(value: str | None) -> float | None`
  - `def classify_http(status_code: int, body: str | None = None, headers: Mapping[str, str] | None = None) -> BackendError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_errors.py
from __future__ import annotations

import pytest

from higgsfield_mcp.backends.base import BackendError
from higgsfield_mcp.errors import (
    AuthError,
    BotChallengeError,
    RateLimitError,
    classify_http,
    parse_retry_after,
)


def test_parse_retry_after_seconds() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("not-a-number") is None


def test_classify_401_is_auth_error() -> None:
    err = classify_http(401, body="bad key")
    assert isinstance(err, AuthError)
    assert err.status_code == 401


def test_classify_403_cloudflare_is_bot_challenge() -> None:
    err = classify_http(403, body="Just a moment...", headers={"cf-mitigated": "challenge"})
    assert isinstance(err, BotChallengeError)


def test_classify_403_plain_is_auth_error() -> None:
    err = classify_http(403, body="forbidden")
    assert isinstance(err, AuthError)


def test_classify_429_carries_retry_after() -> None:
    err = classify_http(429, headers={"retry-after": "5"})
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 5.0


def test_classify_500_is_plain_backend_error() -> None:
    err = classify_http(500, body="boom")
    assert isinstance(err, BackendError)
    assert not isinstance(err, (AuthError, RateLimitError, BotChallengeError))
    assert err.status_code == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'higgsfield_mcp.errors'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/higgsfield_mcp/errors.py
"""Structured error taxonomy for backend failures.

Each subclass maps a class of HTTP/transport failure to an actionable message.
``classify_http`` turns a raw HTTP failure into the right typed error so callers
(and the retry layer) can branch on type instead of parsing strings.
"""

from __future__ import annotations

from collections.abc import Mapping

from higgsfield_mcp.backends.base import BackendError


class AuthError(BackendError):
    """401/403 with no bot-challenge signal: credentials are missing or invalid."""


class RateLimitError(BackendError):
    """429: too many requests. ``retry_after`` is seconds from the Retry-After header."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, body=body)
        self.retry_after = retry_after


class BotChallengeError(BackendError):
    """403 Cloudflare managed challenge (TLS fingerprint). Not an auth problem."""


class SchemaError(BackendError):
    """2xx response whose body is missing required fields (e.g. no job id)."""


class NetworkError(BackendError):
    """Transport-level failure (connection reset, timeout, DNS)."""


class CircuitOpenError(BackendError):
    """The circuit breaker is open: the backend is failing and is cooling down."""


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header value in delta-seconds form. HTTP-date form is ignored."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_http(
    status_code: int,
    body: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> BackendError:
    """Map an HTTP failure to a typed error."""
    headers = headers or {}
    text = (body or "")[:500]
    lower_headers = {k.lower(): v for k, v in headers.items()}

    if status_code == 403:
        cf = str(lower_headers.get("cf-mitigated", "")).lower()
        if "challenge" in cf or "just a moment" in text.lower():
            return BotChallengeError(
                "Cloudflare TLS-fingerprint challenge (HTTP 403). "
                "Upgrade curl-cffi or retry later from a residential IP.",
                status_code=status_code,
                body=text,
            )
    if status_code in (401, 403):
        return AuthError(
            f"Authentication failed (HTTP {status_code}). Check credentials. {text}",
            status_code=status_code,
            body=text,
        )
    if status_code == 429:
        return RateLimitError(
            "Rate limited (HTTP 429).",
            retry_after=parse_retry_after(lower_headers.get("retry-after")),
            status_code=status_code,
            body=text,
        )
    return BackendError(f"HTTP {status_code}: {text}", status_code=status_code, body=text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_errors.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run ruff check src/higgsfield_mcp/errors.py tests/test_errors.py
uv run mypy src/higgsfield_mcp/errors.py
git add src/higgsfield_mcp/errors.py tests/test_errors.py
git commit -m "feat: add structured backend error taxonomy"
```

---

### Task 2: Retry with backoff + jitter (`reliability.py`)

**Files:**
- Create: `src/higgsfield_mcp/reliability.py`
- Test: `tests/test_reliability.py`

**Interfaces:**
- Consumes: `NetworkError`, `RateLimitError` from `higgsfield_mcp.errors`.
- Produces:
  - `def backoff_delay(attempt: int, base: float = 0.5, cap: float = 60.0, rand: Callable[[], float] = random.random) -> float`
  - `RETRYABLE_STATUS: frozenset[int]` = `{429, 502, 503, 504}`
  - `def new_idempotency_key() -> str`
  - `async def retrying_request(send: Callable[[], Awaitable[ResponseLike]], *, max_attempts: int = 4, base: float = 0.5, cap: float = 60.0, retry_status: frozenset[int] = RETRYABLE_STATUS, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, rand: Callable[[], float] = random.random) -> ResponseLike` — `send()` returns an object exposing `.status_code: int` and `.headers: Mapping[str, str]`, or raises `NetworkError`. Retries on `NetworkError` and on a status in `retry_status`; honors `Retry-After`; re-raises/returns the last result when attempts are exhausted.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reliability.py
from __future__ import annotations

import pytest

from higgsfield_mcp.errors import NetworkError
from higgsfield_mcp.reliability import (
    RETRYABLE_STATUS,
    backoff_delay,
    new_idempotency_key,
    retrying_request,
)


class FakeResp:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


def test_backoff_grows_and_is_capped() -> None:
    # rand fixed to 1.0 -> jitter factor 1.0 (max of 0.5..1.0 band)
    assert backoff_delay(0, base=1.0, cap=60.0, rand=lambda: 1.0) == 1.0
    assert backoff_delay(1, base=1.0, cap=60.0, rand=lambda: 1.0) == 2.0
    assert backoff_delay(10, base=1.0, cap=5.0, rand=lambda: 1.0) == 5.0


def test_backoff_jitter_floor() -> None:
    # rand=0.0 -> jitter factor 0.5
    assert backoff_delay(0, base=2.0, cap=60.0, rand=lambda: 0.0) == 1.0


def test_idempotency_key_is_unique_hex() -> None:
    a, b = new_idempotency_key(), new_idempotency_key()
    assert a != b
    assert len(a) == 32 and all(c in "0123456789abcdef" for c in a)


@pytest.mark.asyncio
async def test_returns_first_success_without_sleeping() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    async def send() -> FakeResp:
        calls["n"] += 1
        return FakeResp(200)

    async def fake_sleep(d: float) -> None:
        slept.append(d)

    resp = await retrying_request(send, sleep=fake_sleep)
    assert resp.status_code == 200
    assert calls["n"] == 1
    assert slept == []


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds() -> None:
    seq = [FakeResp(429, {"retry-after": "0"}), FakeResp(200)]
    slept: list[float] = []

    async def send() -> FakeResp:
        return seq.pop(0)

    async def fake_sleep(d: float) -> None:
        slept.append(d)

    resp = await retrying_request(send, sleep=fake_sleep)
    assert resp.status_code == 200
    assert slept == [0.0]  # honored Retry-After: 0


@pytest.mark.asyncio
async def test_retries_on_network_error_then_raises() -> None:
    attempts = {"n": 0}

    async def send() -> FakeResp:
        attempts["n"] += 1
        raise NetworkError("reset")

    async def fake_sleep(d: float) -> None:
        return None

    with pytest.raises(NetworkError):
        await retrying_request(send, max_attempts=3, sleep=fake_sleep)
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_non_retryable_status_returned_immediately() -> None:
    async def send() -> FakeResp:
        return FakeResp(400)

    async def fake_sleep(d: float) -> None:
        return None

    resp = await retrying_request(send, sleep=fake_sleep)
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reliability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'higgsfield_mcp.reliability'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/higgsfield_mcp/reliability.py
"""Transport-agnostic reliability helpers: retry/backoff and idempotency keys.

The retry wrapper takes any async ``send`` returning a response-like object with
``.status_code`` and ``.headers`` (httpx.Response and curl_cffi responses both
qualify), so it works for both backends without importing either HTTP library.
``sleep`` and ``rand`` are injected so tests run instantly and deterministically.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from higgsfield_mcp.errors import NetworkError, parse_retry_after

RETRYABLE_STATUS: frozenset[int] = frozenset({429, 502, 503, 504})


class ResponseLike(Protocol):
    status_code: int

    @property
    def headers(self) -> object: ...


def new_idempotency_key() -> str:
    """A stable-per-submit idempotency token (hex uuid4)."""
    return uuid.uuid4().hex


def backoff_delay(
    attempt: int,
    base: float = 0.5,
    cap: float = 60.0,
    rand: Callable[[], float] = random.random,
) -> float:
    """Exponential backoff with 50–100% jitter, capped. ``attempt`` is 0-based."""
    raw = min(cap, base * (2**attempt))
    return raw * (0.5 + rand() / 2)


def _retry_after_seconds(resp: object) -> float | None:
    headers = getattr(resp, "headers", {}) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")  # type: ignore[union-attr]
    except AttributeError:
        return None
    return parse_retry_after(value)


async def retrying_request(
    send: Callable[[], Awaitable["ResponseLike"]],
    *,
    max_attempts: int = 4,
    base: float = 0.5,
    cap: float = 60.0,
    retry_status: frozenset[int] = RETRYABLE_STATUS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> "ResponseLike":
    """Call ``send`` with retries on transient failures.

    Retries on ``NetworkError`` and on any status in ``retry_status``; honors
    ``Retry-After`` when present; otherwise uses exponential backoff with jitter.
    Returns the response for non-retryable statuses or after the final attempt.
    """
    last_exc: NetworkError | None = None
    resp: ResponseLike | None = None
    for attempt in range(max_attempts):
        try:
            resp = await send()
        except NetworkError as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                raise
            await sleep(backoff_delay(attempt, base, cap, rand))
            continue
        if resp.status_code in retry_status and attempt < max_attempts - 1:
            after = _retry_after_seconds(resp)
            await sleep(after if after is not None else backoff_delay(attempt, base, cap, rand))
            continue
        return resp
    if last_exc is not None:
        raise last_exc
    assert resp is not None
    return resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reliability.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run ruff check src/higgsfield_mcp/reliability.py tests/test_reliability.py
uv run mypy src/higgsfield_mcp/reliability.py
git add src/higgsfield_mcp/reliability.py tests/test_reliability.py
git commit -m "feat: add retry/backoff reliability helper"
```

---

### Task 3: Circuit breaker (`reliability.py`)

**Files:**
- Modify: `src/higgsfield_mcp/reliability.py`
- Test: `tests/test_reliability.py` (append)

**Interfaces:**
- Produces:
  - `class CircuitBreaker` with `__init__(self, *, fail_max: int = 5, reset_timeout: float = 120.0, clock: Callable[[], float] = time.monotonic)`, methods `check() -> None` (raises `CircuitOpenError` while open), `record_success() -> None`, `record_failure() -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reliability.py  (append)
from higgsfield_mcp.errors import CircuitOpenError
from higgsfield_mcp.reliability import CircuitBreaker


def test_circuit_opens_after_fail_max() -> None:
    t = {"now": 0.0}
    cb = CircuitBreaker(fail_max=2, reset_timeout=10.0, clock=lambda: t["now"])
    cb.check()  # closed: ok
    cb.record_failure()
    cb.check()  # still closed after 1 failure
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()  # open after 2 failures


def test_circuit_half_opens_after_timeout_then_success_closes() -> None:
    t = {"now": 0.0}
    cb = CircuitBreaker(fail_max=1, reset_timeout=10.0, clock=lambda: t["now"])
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()
    t["now"] = 11.0  # past reset_timeout -> half-open allows a probe
    cb.check()  # no raise
    cb.record_success()
    t["now"] = 12.0
    cb.check()  # fully closed again
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reliability.py -k circuit -v`
Expected: FAIL — `ImportError: cannot import name 'CircuitBreaker'`

- [ ] **Step 3: Write minimal implementation**

Add to the top imports of `reliability.py`: `import time`. Then append:

```python
# src/higgsfield_mcp/reliability.py  (append)
class CircuitBreaker:
    """Fail-fast breaker, one instance per backend.

    A single-process local server, so a per-instance breaker is our interpretation
    of the spec's "module-level, keyed by base URL" wording. Opens after ``fail_max``
    consecutive failures. After ``reset_timeout`` elapses, ``check()`` stops failing
    fast and lets requests through (half-open); the next ``record_success`` closes it,
    the next ``record_failure`` re-opens it. Probe gating is not concurrency-strict,
    which is acceptable for our low-concurrency local use.
    """

    def __init__(
        self,
        *,
        fail_max: int = 5,
        reset_timeout: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._clock = clock
        self._fails = 0
        self._opened_at: float | None = None

    def check(self) -> None:
        if self._opened_at is None:
            return
        if self._clock() - self._opened_at >= self._reset_timeout:
            return  # half-open: allow one probe
        raise CircuitOpenError(
            "Backend circuit is open after repeated failures; cooling down. Retry shortly."
        )

    def record_success(self) -> None:
        self._fails = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._fails += 1
        if self._fails >= self._fail_max:
            self._opened_at = self._clock()
```

Add `CircuitOpenError` to the imports from `higgsfield_mcp.errors`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reliability.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run ruff check src/higgsfield_mcp/reliability.py tests/test_reliability.py
uv run mypy src/higgsfield_mcp/reliability.py
git add src/higgsfield_mcp/reliability.py tests/test_reliability.py
git commit -m "feat: add circuit breaker to reliability layer"
```

---

### Task 4: Auth correctness — v1 two-header + Clerk slack

**Files:**
- Modify: `src/higgsfield_mcp/auth/api_key.py`
- Modify: `src/higgsfield_mcp/auth/clerk.py:56-59`
- Test: `tests/test_auth.py` (create)

**Interfaces:**
- Consumes: existing `ApiKeyAuth(api_key, secret)` with `.header -> "Key key:secret"`.
- Produces: `ApiKeyAuth.v1_headers` property -> `dict[str, str]` = `{"hf-api-key": api_key, "hf-secret": secret}`. `JWTAuth.is_expired` default slack changed from 30 to 10.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
from __future__ import annotations

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.auth.clerk import JWTAuth


def test_v2_header_unchanged() -> None:
    auth = ApiKeyAuth(api_key="k", secret="s")
    assert auth.header == "Key k:s"


def test_v1_headers_use_split_scheme() -> None:
    auth = ApiKeyAuth(api_key="k", secret="s")
    assert auth.v1_headers == {"hf-api-key": "k", "hf-secret": "s"}


def test_clerk_default_slack_is_10s() -> None:
    # exp 5s in the future: with 10s slack it is considered expired
    import time

    auth = JWTAuth(jwt="a.b.c", expires_at=time.time() + 5)
    assert auth.is_expired() is True
    # exp 20s in the future: not expired under 10s slack
    auth2 = JWTAuth(jwt="a.b.c", expires_at=time.time() + 20)
    assert auth2.is_expired() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `AttributeError: 'ApiKeyAuth' object has no attribute 'v1_headers'`

- [ ] **Step 3: Write minimal implementation**

In `src/higgsfield_mcp/auth/api_key.py`, add to the `ApiKeyAuth` dataclass (below the existing `header` property):

```python
    @property
    def v1_headers(self) -> dict[str, str]:
        """Legacy /v1/ routes authenticate with split headers, not the Key scheme."""
        return {"hf-api-key": self.api_key, "hf-secret": self.secret}
```

In `src/higgsfield_mcp/auth/clerk.py`, change the `is_expired` signature default:

```python
    def is_expired(self, slack: int = 10) -> bool:
```

Also update the module docstring line (clerk.py:16) that reads "within 30s of expiry" to "within 10s of expiry" so the comment matches the new default.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run full suite (no regressions), commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run pytest -q
uv run ruff check src/higgsfield_mcp/auth tests/test_auth.py
uv run mypy src/higgsfield_mcp/auth
git add src/higgsfield_mcp/auth/api_key.py src/higgsfield_mcp/auth/clerk.py tests/test_auth.py
git commit -m "feat: add v1 split-header auth and tighten Clerk refresh slack"
```

---

### Task 5: Implement official-backend upload

**Files:**
- Modify: `src/higgsfield_mcp/backends/official.py:97-103` (the `upload` method that currently raises)
- Test: `tests/test_official_backend.py` (append)

**Interfaces:**
- Consumes: existing `OfficialBackend(auth=..., base_url=...)`, its `self._client` (httpx.AsyncClient), `self._json_or_raise`.
- Produces: `OfficialBackend.upload(self, data: bytes, mime: str) -> str` returns a public URL. Flow: `POST /files/generate-upload-url` with `{"content_type": mime}` -> `{upload_url, public_url}`, then `PUT upload_url` raw bytes with `Content-Type: mime` (no auth header on the PUT).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_official_backend.py  (append)
@pytest.mark.asyncio
async def test_upload_two_step(auth: ApiKeyAuth) -> None:
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(f"{BASE_URL}/files/generate-upload-url").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "upload_url": "https://s3.example/put?sig=1",
                        "public_url": "https://cdn.higgsfield/abc.png",
                    },
                )
            )
            put = mock.put("https://s3.example/put").mock(return_value=httpx.Response(200))
            url = await backend.upload(b"\x89PNG...", "image/png")
        assert url == "https://cdn.higgsfield/abc.png"
        assert put.calls.last.request.headers["Content-Type"] == "image/png"
        assert "Authorization" not in put.calls.last.request.headers
    finally:
        await backend.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_official_backend.py::test_upload_two_step -v`
Expected: FAIL — `BackendError: Official backend uploads are not implemented yet`

- [ ] **Step 3: Write minimal implementation**

Replace the body of `OfficialBackend.upload` in `src/higgsfield_mcp/backends/official.py`:

```python
    async def upload(self, data: bytes, mime: str) -> str:
        resp = await self._client.post(
            "/files/generate-upload-url", json={"content_type": mime}
        )
        body = self._json_or_raise(resp)
        upload_url = body.get("upload_url")
        public_url = body.get("public_url") or body.get("url")
        if not upload_url or not public_url:
            raise BackendError(
                f"generate-upload-url response missing upload_url/public_url: {body!r}",
                status_code=resp.status_code,
            )
        # The signed PUT must NOT carry the platform Authorization header.
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as raw:
            put = await raw.put(upload_url, content=data, headers={"Content-Type": mime})
            if put.status_code >= 400:
                raise BackendError(
                    f"Signed upload PUT failed: HTTP {put.status_code}",
                    status_code=put.status_code,
                    body=put.text,
                )
        return str(public_url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_official_backend.py -v`
Expected: PASS (all official-backend tests, including the new one)

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run ruff check src/higgsfield_mcp/backends/official.py tests/test_official_backend.py
uv run mypy src/higgsfield_mcp/backends/official.py
git add src/higgsfield_mcp/backends/official.py tests/test_official_backend.py
git commit -m "feat: implement official-backend signed upload"
```

---

### Task 6: Wire reliability + error taxonomy into the official backend

**Files:**
- Modify: `src/higgsfield_mcp/backends/official.py` (`__init__`, `submit`, `status`, `_json_or_raise`)
- Test: `tests/test_official_backend.py` (append)

**Interfaces:**
- Consumes: `classify_http` (errors), `retrying_request`, `CircuitBreaker` (reliability).
- Produces: `OfficialBackend` gains `self._breaker: CircuitBreaker`. `submit` and `status` route their HTTP call through `retrying_request` and raise typed errors via `classify_http`. `_json_or_raise` uses `classify_http`. Behavior for existing tests is preserved (a 401 still raises a `BackendError` subclass — `AuthError` — with `.status_code == 401`; `AuthError` is a `BackendError`, so existing `pytest.raises(BackendError)` still matches).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_official_backend.py  (append)
from higgsfield_mcp.errors import AuthError


@pytest.mark.asyncio
async def test_401_raises_auth_error(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.post(f"/{spec.endpoint}").mock(return_value=httpx.Response(401, text="bad"))
            with pytest.raises(AuthError):
                await backend.submit(spec, {"prompt": "p"})
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_429_retries_with_constant_idempotency_key(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(f"/{spec.endpoint}").mock(
                side_effect=[
                    httpx.Response(429, headers={"retry-after": "0"}),
                    httpx.Response(200, json={"request_id": "ok-1"}),
                ]
            )
            handle = await backend.submit(spec, {"prompt": "p"})
        assert handle.request_id == "ok-1"
        assert route.call_count == 2
        # the idempotency key is generated once and reused across retries
        keys = {c.request.headers["x-idempotency-key"] for c in route.calls}
        assert len(keys) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_transport_error_retries_then_succeeds(auth: ApiKeyAuth) -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    backend = OfficialBackend(auth=auth)
    try:
        with respx.mock(base_url=BASE_URL) as mock:
            route = mock.post(f"/{spec.endpoint}").mock(
                side_effect=[
                    httpx.ConnectError("boom"),
                    httpx.Response(200, json={"request_id": "ok-2"}),
                ]
            )
            handle = await backend.submit(spec, {"prompt": "p"})
        assert handle.request_id == "ok-2"
        assert route.call_count == 2
    finally:
        await backend.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_official_backend.py -k "auth_error or retries" -v`
Expected: FAIL — `test_401_raises_auth_error` fails (plain `BackendError` raised, not `AuthError`); `test_429_retries_with_constant_idempotency_key` and `test_transport_error_retries_then_succeeds` fail (no retry, no idempotency header yet).

- [ ] **Step 3: Write minimal implementation**

In `src/higgsfield_mcp/backends/official.py`:

Add imports near the top (`httpx` is already imported):

```python
from higgsfield_mcp.errors import NetworkError, SchemaError, classify_http
from higgsfield_mcp.reliability import CircuitBreaker, new_idempotency_key, retrying_request
```

In `__init__`, after building `self._client`, add:

```python
        self._breaker = CircuitBreaker()
```

Replace `submit`'s HTTP call. The `_send` helper translates httpx transport errors into `NetworkError` (so `retrying_request` actually retries them — `retrying_request` only catches `NetworkError`, never raw `httpx.HTTPError`) and attaches a stable idempotency key that stays constant across retries because the lambda closes over `idem`. Change the line `resp = await self._client.post(f"/{model.endpoint}", json=params)` to:

```python
        self._breaker.check()
        idem = new_idempotency_key()

        async def _send() -> httpx.Response:
            try:
                return await self._client.post(
                    f"/{model.endpoint}", json=params, headers={"X-Idempotency-Key": idem}
                )
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc

        try:
            resp = await retrying_request(_send)
        except Exception:
            self._breaker.record_failure()
            raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
```

Also change the existing missing-`request_id` guard in `submit` from `BackendError(...)` to `SchemaError(...)` (a `BackendError` subclass, so existing `pytest.raises(BackendError)` still matches).

Spell out the same wrap for `status` — replace `resp = await self._client.get(f"/requests/{handle.request_id}/status")` with:

```python
        self._breaker.check()

        async def _send() -> httpx.Response:
            try:
                return await self._client.get(f"/requests/{handle.request_id}/status")
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc

        try:
            resp = await retrying_request(_send)
        except Exception:
            self._breaker.record_failure()
            raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
```

Replace `_json_or_raise` so failures classify:

```python
    @staticmethod
    def _json_or_raise(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise classify_http(resp.status_code, resp.text, dict(resp.headers))
        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise BackendError(f"Invalid JSON response: {resp.text[:200]}") from exc
        return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_official_backend.py -v`
Expected: PASS (all official-backend tests, including the prior `test_http_error_wrapped` which checks `.status_code == 401` — still true because `AuthError` carries it).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run ruff check src/higgsfield_mcp/backends/official.py tests/test_official_backend.py
uv run mypy src/higgsfield_mcp/backends/official.py
git add src/higgsfield_mcp/backends/official.py tests/test_official_backend.py
git commit -m "feat: add retries, circuit breaking, typed errors to official backend"
```

---

### Task 7: Harden the web backend (retry, auth lock, semaphore, Cloudflare wording, session seam)

**Files:**
- Modify: `src/higgsfield_mcp/backends/web.py` (`__init__`, `_ensure_session`, `_auth_header`, `submit`, `status`, `_json_or_raise`, module docstring/comments)
- Test: `tests/test_web_backend.py` (append)

**Interfaces:**
- Consumes: `classify_http` (errors); `retrying_request`, `CircuitBreaker` (reliability).
- Produces:
  - `WebBackend.__init__` gains an optional `session: Any | None = None` injection seam (mirrors `auth=`), `self._auth_lock: asyncio.Lock`, `self._sem: asyncio.Semaphore` (value 3), `self._breaker: CircuitBreaker`.
  - `_ensure_session` returns the injected session when provided.
  - `_auth_header` body wrapped in `self._auth_lock`.
  - `submit`/`status` route through `retrying_request` and `self._sem`, classify errors via `_json_or_raise`.
  - All user-facing "Datadome" wording changed to "Cloudflare TLS-fingerprint challenge". The optional `HIGGSFIELD_DATADOME_COOKIE` env var name is preserved (back-compat) but documented as a legacy cookie hint.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_backend.py
# NOTE: add `from typing import Any` to the EXISTING top-of-file import block
# (do not append it inline mid-file — that trips ruff import-ordering / F811).


class FakeResp:
    def __init__(self, status_code: int, json_body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._json = json_body
        self.headers = headers or {}
        self.text = str(json_body)

    def json(self) -> dict[str, Any]:
        return self._json


class FakeSession:
    """Stand-in for curl_cffi AsyncSession that returns a queued list of responses."""

    def __init__(self, responses: list[FakeResp]) -> None:
        self._responses = responses
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResp:
        self.posts.append({"url": url, **kwargs})
        return self._responses.pop(0)

    async def get(self, url: str, **kwargs: Any) -> FakeResp:
        self.gets.append({"url": url, **kwargs})
        return self._responses.pop(0)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_submit_retries_on_429_with_constant_idempotency_key(jwt_auth: JWTAuth) -> None:
    spec = REGISTRY.get("seedance2")
    session = FakeSession(
        [
            FakeResp(429, {}, {"retry-after": "0"}),
            FakeResp(200, {"job_sets": [{"jobs": [{"id": "job-9"}]}]}),
        ]
    )
    backend = WebBackend(auth=jwt_auth, session=session)
    try:
        handle = await backend.submit(spec, {"prompt": "p"})
        assert handle.request_id == "job-9"
        assert len(session.posts) == 2
        keys = {p["headers"]["X-Idempotency-Key"] for p in session.posts}
        assert len(keys) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_submit_401_raises_auth_error(jwt_auth: JWTAuth) -> None:
    from higgsfield_mcp.errors import AuthError

    spec = REGISTRY.get("seedance2")
    session = FakeSession([FakeResp(401, {"detail": "Invalid credentials"})])
    backend = WebBackend(auth=jwt_auth, session=session)
    try:
        with pytest.raises(AuthError):
            await backend.submit(spec, {"prompt": "p"})
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_status_retries_on_429(jwt_auth: JWTAuth) -> None:
    from higgsfield_mcp.backends.base import JobHandle

    session = FakeSession(
        [
            FakeResp(429, {}, {"retry-after": "0"}),
            FakeResp(
                200,
                {"jobs": [{"id": "r1", "status": "completed", "results": [{"url": "https://cdn/x.png"}]}]},
            ),
        ]
    )
    backend = WebBackend(auth=jwt_auth, session=session)
    try:
        status = await backend.status(JobHandle(backend="web", request_id="r1"))
        assert status.state == "completed"
        assert len(session.gets) == 2
    finally:
        await backend.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_backend.py -k "retries_on_429 or 401_raises" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'session'`

- [ ] **Step 3: Write minimal implementation**

In `src/higgsfield_mcp/backends/web.py`:

Add imports near the top. `from typing import Any` is ALREADY present (web.py:24) — do not duplicate it. Add:

```python
import asyncio

from higgsfield_mcp.errors import NetworkError, SchemaError, classify_http
from higgsfield_mcp.reliability import CircuitBreaker, new_idempotency_key, retrying_request
```

Add a module-level transport-error tuple just below the imports (curl_cffi's error module path varies by version, so guard the import):

```python
try:  # curl_cffi >= 0.7
    from curl_cffi.requests.exceptions import RequestsError as _CurlError
except ImportError:  # pragma: no cover - older curl_cffi layout
    try:
        from curl_cffi.requests.errors import RequestsError as _CurlError
    except ImportError:  # pragma: no cover
        _CurlError = Exception  # type: ignore[assignment,misc]

_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (_CurlError, OSError)
```

Update `__init__` to accept and store the seam plus new concurrency state:

```python
    def __init__(
        self,
        *,
        auth: JWTAuth | None = None,
        base_url: str = BASE_URL,
        session: Any | None = None,
    ) -> None:
        assert_enabled()
        self._auth = auth
        self._base_url = base_url
        self._session: Any | None = session
        self._datadome = os.getenv("HIGGSFIELD_DATADOME_COOKIE")
        self._auth_lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(3)
        self._breaker = CircuitBreaker()
```

Update `_ensure_session` to honor an injected session:

```python
    async def _ensure_session(self) -> Any:
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome120", timeout=60)
        return self._session
```

Wrap `_auth_header` body in the lock:

```python
    async def _auth_header(self) -> dict[str, str]:
        async with self._auth_lock:
            if self._auth is None or self._auth.is_expired():
                self._auth = await load_jwt()
            return {"Authorization": self._auth.header}
```

In `submit`, route the POST through the semaphore + retry + breaker. The `_send` helper translates curl_cffi transport errors into `NetworkError` (so they retry) and attaches a stable idempotency key constant across retries. Replace the existing `resp = await session.post(...)` with:

```python
        self._breaker.check()
        idem = new_idempotency_key()

        async def _send() -> Any:
            try:
                return await session.post(
                    f"{self._base_url}{model.endpoint}",
                    json=body,
                    headers={**headers, "X-Idempotency-Key": idem},
                    cookies=self._cookies(),
                )
            except _TRANSPORT_ERRORS as exc:
                raise NetworkError(str(exc)) from exc

        async with self._sem:
            try:
                resp = await retrying_request(_send)
            except Exception:
                self._breaker.record_failure()
                raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
```

Also change the existing missing-`job_id` guard in `submit` from `BackendError(...)` to `SchemaError(...)`.

Spell out the same wrap for `status` — replace `resp = await session.get(f"{self._base_url}/jobs", params={"size": 100}, headers=headers, cookies=self._cookies())` with (the `headers` local is already built from `_BROWSER_HEADERS` + `_auth_header()` just above):

```python
        self._breaker.check()

        async def _send() -> Any:
            try:
                return await session.get(
                    f"{self._base_url}/jobs",
                    params={"size": 100},
                    headers=headers,
                    cookies=self._cookies(),
                )
            except _TRANSPORT_ERRORS as exc:
                raise NetworkError(str(exc)) from exc

        async with self._sem:
            try:
                resp = await retrying_request(_send)
            except Exception:
                self._breaker.record_failure()
                raise
        if resp.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
```

Replace `_json_or_raise` to classify:

```python
    @staticmethod
    def _json_or_raise(resp: Any) -> dict[str, Any]:
        if resp.status_code >= 400:
            headers = dict(getattr(resp, "headers", {}) or {})
            raise classify_http(resp.status_code, getattr(resp, "text", ""), headers)
        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise BackendError(f"Invalid JSON response: {resp.text[:200]}") from exc
        return data
```

Update the module docstring and the inline comment that says "Datadome" to read "Cloudflare TLS-fingerprint challenge"; in the `_maybe_warn_web_backend` wording (server.py) leave as-is for now (covered in Phase 1b docs pass). Keep the `HIGGSFIELD_DATADOME_COOKIE` env name; update its comment to "legacy Cloudflare cookie hint".

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_web_backend.py -v`
Expected: PASS (all web-backend tests, including the two new ones)

- [ ] **Step 5: Lint, type-check, full suite, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run pytest -q
uv run ruff check src/higgsfield_mcp/backends/web.py tests/test_web_backend.py
uv run mypy src/higgsfield_mcp/backends/web.py
git add src/higgsfield_mcp/backends/web.py tests/test_web_backend.py
git commit -m "feat: harden web backend with retries, auth lock, concurrency cap, typed errors"
```

---

### Task 8: `preflight_check` tool

**Files:**
- Modify: `src/higgsfield_mcp/tools.py` (add `preflight_check` function)
- Modify: `src/higgsfield_mcp/server.py` (register `preflight_check_tool`)
- Test: `tests/test_preflight.py` (create)

**Interfaces:**
- Consumes: `BackendPool`, env vars (`HIGGSFIELD_API_KEY`/`HIGGSFIELD_SECRET`, `ENABLE_FLAG`, Clerk creds), `MissingCredentialsError`, `WebBackendDisabledError`, `MissingJWTError`.
- Produces: `async def preflight_check(pool: BackendPool) -> dict[str, Any]` returning `{"official": {"configured": bool, "ok": bool, "error": str | None}, "web": {"enabled": bool, "ok": bool, "error": str | None}}`. "ok" reflects whether credentials are loadable (no network call in this phase — credential presence + JWT mintability only); a server-side wording note: do not perform a generation.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preflight.py
from __future__ import annotations

import pytest

from higgsfield_mcp.backends.web import ENABLE_FLAG
from higgsfield_mcp.tools import BackendPool, preflight_check


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("HIGGSFIELD_API_KEY", "HIGGSFIELD_SECRET", ENABLE_FLAG, "HIGGSFIELD_JWT", "HIGGSFIELD_CLERK_CLIENT"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.asyncio
async def test_preflight_reports_unconfigured() -> None:
    result = await preflight_check(BackendPool())
    assert result["official"]["configured"] is False
    assert result["official"]["ok"] is False
    assert result["web"]["enabled"] is False


@pytest.mark.asyncio
async def test_preflight_official_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "k")
    monkeypatch.setenv("HIGGSFIELD_SECRET", "s")
    result = await preflight_check(BackendPool())
    assert result["official"]["configured"] is True
    assert result["official"]["ok"] is True
    assert result["official"]["error"] is None


@pytest.mark.asyncio
async def test_preflight_web_enabled_with_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLE_FLAG, "1")
    monkeypatch.setenv("HIGGSFIELD_JWT", "a.b.c")
    result = await preflight_check(BackendPool())
    assert result["web"]["enabled"] is True
    assert result["web"]["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: FAIL — `ImportError: cannot import name 'preflight_check' from 'higgsfield_mcp.tools'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/higgsfield_mcp/tools.py`:

```python
async def preflight_check(pool: BackendPool) -> dict[str, Any]:
    """Validate credentials/reachability for both backends without spending a generation."""
    from higgsfield_mcp.auth.api_key import MissingCredentialsError, load_from_env
    from higgsfield_mcp.auth.clerk import MissingJWTError, load_jwt
    from higgsfield_mcp.backends.web import ENABLE_FLAG, assert_enabled
    from higgsfield_mcp.backends.web import WebBackendDisabledError

    official: dict[str, Any] = {"configured": False, "ok": False, "error": None}
    try:
        load_from_env()
        official.update(configured=True, ok=True)
    except MissingCredentialsError as exc:
        official["error"] = str(exc)

    web: dict[str, Any] = {"enabled": False, "ok": False, "error": None}
    try:
        assert_enabled()
        web["enabled"] = True
        try:
            await load_jwt()
            web["ok"] = True
        except MissingJWTError as exc:
            web["error"] = str(exc)
    except WebBackendDisabledError as exc:
        web["error"] = str(exc)

    return {"official": official, "web": web}
```

Register it in `src/higgsfield_mcp/server.py` inside `build_server`, alongside the other `@mcp.tool` definitions:

```python
    @mcp.tool
    async def preflight_check_tool() -> dict[str, Any]:
        """Check auth + config for both backends before submitting a generation."""
        return await preflight_check(pool)
```

Add `preflight_check` to the import from `higgsfield_mcp.tools` at the top of `server.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Full suite, lint, type-check, commit**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run pytest -q
uv run ruff check src tests
uv run mypy src
git add src/higgsfield_mcp/tools.py src/higgsfield_mcp/server.py tests/test_preflight.py
git commit -m "feat: add preflight_check tool for backend auth/config validation"
```

---

## Final verification

- [ ] **Run the whole suite and quality gates**

```bash
cd /Users/hikhakk/Desktop/mcpdev/higgsfield-mcp-unified
uv run pytest -q
uv run ruff check .
uv run mypy src
```

Expected: all tests pass (original 27-model + backend tests still green, plus new `test_errors`, `test_reliability`, `test_auth`, `test_preflight`, and the new official/web tests); ruff and mypy clean.

- [ ] **Smoke-import the server**

```bash
uv run python -c "from higgsfield_mcp.server import build_server; print(len(build_server().__class__.__name__))"
```

Expected: prints a number (server builds without error).

## Self-review against the spec

- Reliability hardening (spec §6): retry/backoff + Retry-After (Task 2), transport-error retry via `NetworkError` translation at the send boundary (Tasks 6–7), circuit breaker (Task 3), idempotency key wired into both submits and held constant across retries (Tasks 6–7), per-backend auth lock + concurrency cap + Cloudflare rename + session seam (Task 7), error taxonomy incl. `SchemaError` on missing-field responses (Task 1, wired Tasks 6–7), official upload (Task 5). Covered.
- Auth design (spec §"Auth design"): v1 two-header helper + Clerk slack/docstring (Task 4). Covered. (Smoothed setup errors surfaced via `preflight_check`, Task 8.)
- Status-poll TTL cache and web→official fallback routing from spec §6 are intentionally deferred to the catalog/tools plan (they depend on registry equivalence mapping) — see "Out of scope".
- Circuit breaker is per-instance (one backend instance per process via `BackendPool`) — our interpretation of the spec's "module-level/base-URL" wording, noted in the `CircuitBreaker` docstring (Task 3).
- No registry or FastMCP changes (Global Constraints) — confirmed; `test_models.py` untouched.

## Out of scope (later plans)

- Phase 1b: FastMCP major bump + Pydantic structured-output models for all tools.
- Phase 2: registry rebuild with confidence tiers, MCP resources, `recommend_model`, `estimate_credits`, `validate_params`, status-poll TTL cache, web→official fallback routing.
- Phase 3: Soul characters, `list_jobs`, `get_balance`, `generate_speech_video`, soul-styles/motions.
- Phase 4: cloud creative suite, MCP prompts, `generate_batch`, README/docs, PyPI release.

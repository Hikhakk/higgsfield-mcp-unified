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
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from higgsfield_mcp.errors import CircuitOpenError, NetworkError, parse_retry_after

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
    """Exponential backoff with 50-100% jitter, capped. ``attempt`` is 0-based."""
    raw: float = min(cap, base * (2**attempt))
    return raw * (0.5 + rand() / 2)


def _retry_after_seconds(resp: object) -> float | None:
    headers: dict[str, str] = getattr(resp, "headers", {}) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    return parse_retry_after(value)


async def retrying_request(
    send: Callable[[], Awaitable[ResponseLike]],
    *,
    max_attempts: int = 4,
    base: float = 0.5,
    cap: float = 60.0,
    retry_status: frozenset[int] = RETRYABLE_STATUS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> ResponseLike:
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

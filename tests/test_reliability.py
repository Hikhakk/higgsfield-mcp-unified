# tests/test_reliability.py
from __future__ import annotations

import pytest

from higgsfield_mcp.errors import CircuitOpenError, NetworkError
from higgsfield_mcp.reliability import (
    RETRYABLE_STATUS,  # noqa: F401
    CircuitBreaker,
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

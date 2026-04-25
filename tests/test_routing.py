"""Backend routing tests: model_id -> correct backend."""

from __future__ import annotations

import pytest

from higgsfield_mcp.backends.web import ENABLE_FLAG, WebBackendDisabledError
from higgsfield_mcp.tools import BackendPool


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLE_FLAG, raising=False)
    monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
    monkeypatch.delenv("HIGGSFIELD_SECRET", raising=False)
    monkeypatch.delenv("HIGGSFIELD_JWT", raising=False)


def test_official_backend_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "k")
    monkeypatch.setenv("HIGGSFIELD_SECRET", "s")
    pool = BackendPool()
    backend = pool.get("official")
    assert backend.name == "official"


def test_official_missing_creds_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = BackendPool()
    with pytest.raises(Exception, match="HIGGSFIELD_API_KEY"):
        pool.get("official")


def test_web_backend_blocked_without_flag() -> None:
    pool = BackendPool()
    with pytest.raises(WebBackendDisabledError):
        pool.get("web")


def test_web_backend_unblocked_by_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLE_FLAG, "1")
    monkeypatch.setenv("HIGGSFIELD_JWT", "fake.jwt.token")
    pool = BackendPool()
    backend = pool.get("web")
    assert backend.name == "web"


def test_pool_caches_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "k")
    monkeypatch.setenv("HIGGSFIELD_SECRET", "s")
    pool = BackendPool()
    a = pool.get("official")
    b = pool.get("official")
    assert a is b

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

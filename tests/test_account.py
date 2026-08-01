from __future__ import annotations

import httpx
import pytest
import respx

from higgsfield_mcp.auth.api_key import ApiKeyAuth
from higgsfield_mcp.backends.official import BASE_URL, OfficialBackend
from higgsfield_mcp.errors import AuthError, EndpointUnavailableError
from higgsfield_mcp.tools import BackendPool, get_balance, list_soul_styles


@pytest.fixture
def pool():
    p = BackendPool()
    p._official = OfficialBackend(auth=ApiKeyAuth(api_key="kid", secret="sec"))
    return p


@pytest.mark.asyncio
async def test_get_balance_defensive(pool) -> None:
    """If the credits route ever starts returning 200 with real data, the
    parsing path still works — this is a regression guard on the parsing
    logic, not a claim that the route currently exists (see AOF-274; it
    404s in production as of 2026-07-31, exercised by
    test_get_balance_404_fails_honestly below)."""
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/billing/credits").mock(
            return_value=httpx.Response(200, json={"credits": 1234, "plan": "pro"})
        )
        out = await get_balance(pool)
    assert out["credits"] == 1234
    assert out["plan"] == "pro"
    await pool.aclose()


@pytest.mark.asyncio
async def test_get_balance_404_fails_honestly(pool) -> None:
    """AOF-274: POST /v1/billing/credits 404s with model_not_found in
    production (confirmed live, byte-identical to a fabricated control
    path — the route is swallowed by the generic model-submission
    catch-all, not served by a dedicated handler). get_balance() must
    raise a clear, typed error here, never return a fabricated or
    silently-zero balance."""
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/billing/credits").mock(
            return_value=httpx.Response(404, json={"detail": "model_not_found"})
        )
        with pytest.raises(EndpointUnavailableError) as excinfo:
            await get_balance(pool)
    assert excinfo.value.status_code == 404
    assert "no working" in str(excinfo.value).lower() or "unavailable" in str(excinfo.value).lower()
    await pool.aclose()


@pytest.mark.asyncio
async def test_get_balance_401_still_raises_auth_error(pool) -> None:
    """Mutation guard: the 404-specific honest-failure branch must not
    swallow other status codes. A 401 (bad/expired credentials) has to
    keep raising AuthError, not the 404-flavored EndpointUnavailableError,
    so a genuine auth problem is never misreported as 'endpoint doesn't
    exist'."""
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/billing/credits").mock(return_value=httpx.Response(401, text="bad key"))
        with pytest.raises(AuthError):
            await get_balance(pool)
    await pool.aclose()


@pytest.mark.asyncio
async def test_list_soul_styles_handles_list_or_dict(pool) -> None:
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/v1/text2image/soul-styles").mock(
            return_value=httpx.Response(200, json=["cinematic", "anime", "noir"])
        )
        out = await list_soul_styles(pool)
    assert out["count"] == 3
    assert "cinematic" in out["names"]
    await pool.aclose()

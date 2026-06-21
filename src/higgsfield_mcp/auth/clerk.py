"""Clerk-JWT loader for the opt-in web backend.

Higgsfield's web app uses Clerk for auth. The browser holds two cookies:

* ``__client`` — long-lived (~7 days, refreshed on activity) device-bound
  authentication token. This is what we ask the user to paste so the MCP can
  mint short-lived session JWTs without requiring a fresh paste every 4 minutes.
* ``__session`` — short-lived (~1 minute) JWT, the actual bearer token attached
  to API requests. Issued by Clerk on demand from a ``__client`` cookie.

Strategy (most-preferred first):

1. **Long-lived auth via __client** (recommended). User sets
   ``HIGGSFIELD_CLERK_CLIENT``; we hit ``GET /v1/client`` to discover the active
   session id, then ``POST /v1/client/sessions/{sid}/tokens`` to mint a fresh
   JWT. We cache the JWT in memory until it's within 10s of expiry. The user
   only needs to re-paste the cookie roughly weekly.
2. **Manual JWT** (``HIGGSFIELD_JWT``). Single short-lived paste — useful for
   smoke tests but expires in ~4 minutes. Always wins if set, so it's a clean
   override.
3. **Hard fail** with a useful message pointing the user at the cookie.

All Clerk traffic flows through ``curl_cffi`` impersonating Chrome — the same
TLS-fingerprint workaround we use for Datadome on ``fnf.higgsfield.ai``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from base64 import urlsafe_b64decode
from dataclasses import dataclass

from curl_cffi.requests import AsyncSession

CLERK_BASE = "https://clerk.higgsfield.ai"
CLERK_VERSION_PARAMS = {"__clerk_api_version": "2024-10-01", "_clerk_js_version": "5.95.0"}
COMMON_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://cloud.higgsfield.ai",
    "Referer": "https://cloud.higgsfield.ai/",
}


@dataclass
class JWTAuth:
    jwt: str
    expires_at: float | None = None

    @property
    def header(self) -> str:
        return f"Bearer {self.jwt}"

    def is_expired(self, slack: int = 10) -> bool:
        if self.expires_at is None:
            return False
        return time.time() + slack >= self.expires_at


class MissingJWTError(RuntimeError):
    """No usable Clerk credentials are configured."""


def _decode_exp(jwt: str) -> float | None:
    try:
        payload_b64 = jwt.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(urlsafe_b64decode(padded))
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


async def _discover_session_id(session: AsyncSession, client_cookie: str) -> str | None:  # type: ignore[type-arg]
    """Call ``/v1/client`` with the ``__client`` cookie to find the active session id."""
    resp = await session.get(
        f"{CLERK_BASE}/v1/client",
        params=CLERK_VERSION_PARAMS,
        headers=COMMON_HEADERS,
        cookies={"__client": client_cookie},
    )
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    response = data.get("response") if isinstance(data, dict) else None
    if not isinstance(response, dict):
        return None
    last_active = response.get("last_active_session_id")
    if isinstance(last_active, str) and last_active:
        return last_active
    sessions = response.get("sessions")
    if isinstance(sessions, list):
        for s in sessions:
            if isinstance(s, dict):
                sid = s.get("id")
                status = s.get("status")
                if isinstance(sid, str) and (status is None or status == "active"):
                    return sid
    return None


async def _mint_token(session: AsyncSession, client_cookie: str, sid: str) -> str | None:  # type: ignore[type-arg]
    """Mint a fresh session JWT via Clerk's tokens endpoint."""
    resp = await session.post(
        f"{CLERK_BASE}/v1/client/sessions/{sid}/tokens",
        params=CLERK_VERSION_PARAMS,
        headers=COMMON_HEADERS,
        cookies={"__client": client_cookie},
        data="",  # Clerk expects an empty form body, not JSON
    )
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    jwt = body.get("jwt") if isinstance(body, dict) else None
    return str(jwt) if isinstance(jwt, str) else None


class ClerkRefresher:
    """Caches the active session id and the most recent minted JWT in memory."""

    def __init__(self, client_cookie: str) -> None:
        self._client_cookie = client_cookie
        self._sid: str | None = None
        self._jwt: JWTAuth | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> JWTAuth:
        async with self._lock:
            if self._jwt is not None and not self._jwt.is_expired():
                return self._jwt
            async with AsyncSession(impersonate="chrome120") as session:
                if self._sid is None:
                    self._sid = await _discover_session_id(session, self._client_cookie)
                    if self._sid is None:
                        raise MissingJWTError(
                            "Clerk /v1/client returned no active session for the supplied "
                            "__client cookie. The cookie may be expired or invalid; copy a "
                            "fresh value from cloud.higgsfield.ai DevTools."
                        )
                jwt = await _mint_token(session, self._client_cookie, self._sid)
                if jwt is None:
                    # Try once more after re-discovering the sid (it may have rotated).
                    self._sid = await _discover_session_id(session, self._client_cookie)
                    if self._sid is not None:
                        jwt = await _mint_token(session, self._client_cookie, self._sid)
                if jwt is None:
                    raise MissingJWTError(
                        "Clerk refused to mint a session JWT. The __client cookie is "
                        "probably expired or stale. Copy a fresh value from "
                        "cloud.higgsfield.ai DevTools and re-export HIGGSFIELD_CLERK_CLIENT."
                    )
                self._jwt = JWTAuth(jwt=jwt, expires_at=_decode_exp(jwt))
                return self._jwt


_REFRESHER: ClerkRefresher | None = None


async def load_jwt() -> JWTAuth:
    """Resolve a Bearer JWT for the web backend, refreshing if needed."""
    # 1. explicit env override
    env_jwt = os.getenv("HIGGSFIELD_JWT")
    if env_jwt:
        return JWTAuth(jwt=env_jwt, expires_at=_decode_exp(env_jwt))

    # 2. long-lived __client cookie via Clerk refresh
    client_cookie = os.getenv("HIGGSFIELD_CLERK_CLIENT")
    if client_cookie:
        global _REFRESHER
        if _REFRESHER is None or _REFRESHER._client_cookie != client_cookie:
            _REFRESHER = ClerkRefresher(client_cookie)
        return await _REFRESHER.get()

    raise MissingJWTError(
        "No Clerk credentials configured. Set HIGGSFIELD_CLERK_CLIENT to the value of "
        "the __client cookie from cloud.higgsfield.ai (recommended; lasts ~7 days), or "
        "set HIGGSFIELD_JWT to a __session cookie (expires in ~4 minutes). "
        "Open DevTools -> Application -> Cookies on cloud.higgsfield.ai to find them."
    )

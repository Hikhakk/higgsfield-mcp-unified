"""Clerk-JWT loader for the opt-in web backend (``cloud.higgsfield.ai``).

Three-tier strategy, ported from ``jfikrat/higgsfield-mcp/src/auth.ts`` with
Python-friendly fallbacks:

1. **Cached refresh** — read a JWT plus refresh metadata from
   ``~/.config/higgsfield-mcp/settings.json``. If the JWT is expired but a
   refresh cookie is present, hit Clerk's ``/v1/client`` endpoint to get a new
   one and write it back.
2. **Manual env override** — ``HIGGSFIELD_JWT`` always wins. Useful for
   ephemeral shells, CI smoke tests, and "I just pasted the cookie".
3. **Hard fail with a useful message** — if neither path yields a token, raise
   ``MissingJWTError`` with instructions on where to grab the cookie.

We deliberately do not try to scrape browser cookies on disk (the upstream
"Helm browser daemon" path) — it's brittle, requires extra deps, and is best
left to a separate optional package.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from base64 import urlsafe_b64decode
from dataclasses import dataclass
from pathlib import Path

import httpx

CLERK_REFRESH_URL = "https://clerk.higgsfield.ai/v1/client/sessions/{sid}/tokens"
SETTINGS_PATH = Path.home() / ".config" / "higgsfield-mcp" / "settings.json"


@dataclass
class JWTAuth:
    jwt: str
    expires_at: float | None = None  # epoch seconds, when known

    @property
    def header(self) -> str:
        return f"Bearer {self.jwt}"

    def is_expired(self, slack: int = 30) -> bool:
        if self.expires_at is None:
            return False
        return time.time() + slack >= self.expires_at


class MissingJWTError(RuntimeError):
    """No usable JWT could be loaded for the web backend."""


def _decode_exp(jwt: str) -> float | None:
    """Best-effort extraction of the ``exp`` claim from a JWT. Never raises."""
    try:
        payload_b64 = jwt.split(".")[1]
        # base64 in JWTs is url-safe and may be missing padding
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(urlsafe_b64decode(padded))
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


def _load_settings() -> dict[str, object]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data: dict[str, object] = json.loads(SETTINGS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data


def _save_settings(data: dict[str, object]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))
    # Tighten perms — the file holds a session token.
    with contextlib.suppress(OSError):
        SETTINGS_PATH.chmod(0o600)


async def _refresh(session_id: str, client_token: str) -> str | None:
    """Try the Clerk refresh endpoint. Returns a new JWT or None."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                CLERK_REFRESH_URL.format(sid=session_id),
                headers={"Authorization": f"Bearer {client_token}"},
            )
        except httpx.HTTPError:
            return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    jwt = body.get("jwt") if isinstance(body, dict) else None
    return str(jwt) if isinstance(jwt, str) else None


async def load_jwt() -> JWTAuth:
    """Load a JWT for the web backend, refreshing if needed."""
    # 1. explicit env override
    env_jwt = os.getenv("HIGGSFIELD_JWT")
    if env_jwt:
        return JWTAuth(jwt=env_jwt, expires_at=_decode_exp(env_jwt))

    # 2. cached settings
    settings = _load_settings()
    cached_jwt = settings.get("jwt") if isinstance(settings.get("jwt"), str) else None
    if isinstance(cached_jwt, str):
        auth = JWTAuth(jwt=cached_jwt, expires_at=_decode_exp(cached_jwt))
        if not auth.is_expired():
            return auth
        sid = settings.get("session_id")
        client_token = settings.get("client_token")
        if isinstance(sid, str) and isinstance(client_token, str):
            new_jwt = await _refresh(sid, client_token)
            if new_jwt:
                refreshed = JWTAuth(jwt=new_jwt, expires_at=_decode_exp(new_jwt))
                settings["jwt"] = new_jwt
                _save_settings(settings)
                return refreshed

    raise MissingJWTError(
        "No valid JWT for cloud.higgsfield.ai. Set HIGGSFIELD_JWT to a token "
        "copied from your browser DevTools (Application -> Cookies -> __session "
        "on cloud.higgsfield.ai), or write one to "
        f"{SETTINGS_PATH}. The web backend is opt-in; consider whether you "
        "really need it before paste-bypassing official auth."
    )

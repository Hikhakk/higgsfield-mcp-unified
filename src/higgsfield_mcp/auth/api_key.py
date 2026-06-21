"""Loader for the official-backend API key + secret pair."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiKeyAuth:
    api_key: str
    secret: str

    @property
    def header(self) -> str:
        return f"Key {self.api_key}:{self.secret}"

    @property
    def v1_headers(self) -> dict[str, str]:
        """Legacy /v1/ routes authenticate with split headers, not the Key scheme."""
        return {"hf-api-key": self.api_key, "hf-secret": self.secret}


class MissingCredentialsError(RuntimeError):
    """Raised when the official backend is invoked without credentials."""


def load_from_env() -> ApiKeyAuth:
    key = os.getenv("HIGGSFIELD_API_KEY")
    secret = os.getenv("HIGGSFIELD_SECRET")
    if not key or not secret:
        raise MissingCredentialsError(
            "HIGGSFIELD_API_KEY and HIGGSFIELD_SECRET must be set to use the official backend. "
            "Get credentials from https://platform.higgsfield.ai/."
        )
    return ApiKeyAuth(api_key=key, secret=secret)

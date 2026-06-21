"""MCP resources exposing the model catalog.

``higgsfield://models`` returns the full catalog (including inferred models);
``higgsfield://models/{kind}`` filters by kind. Clients that support resources
can subscribe to the catalog instead of calling list_models repeatedly.
"""

from __future__ import annotations

from typing import Any, cast

from fastmcp import FastMCP

from higgsfield_mcp.models import Kind
from higgsfield_mcp.tools import list_models

_KINDS = ("image", "video", "speech")


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource("higgsfield://models")
    async def all_models() -> dict[str, Any]:
        """The full Higgsfield model catalog, including inferred (unverified) models."""
        return await list_models(include_unverified=True)

    @mcp.resource("higgsfield://models/{kind}")
    async def models_by_kind(kind: str) -> dict[str, Any]:
        """Models of a single kind: image, video, or speech."""
        if kind not in _KINDS:
            return {"count": 0, "models": [], "error": f"unknown kind: {kind!r}"}
        return await list_models(kind=cast(Kind, kind), include_unverified=True)

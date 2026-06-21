from __future__ import annotations

import json

import pytest
from fastmcp import Client

from higgsfield_mcp.server import build_server


@pytest.mark.asyncio
async def test_models_resource_lists_full_catalog() -> None:
    async with Client(build_server()) as c:
        uris = [str(r.uri) for r in await c.list_resources()]
        assert "higgsfield://models" in uris
        out = await c.read_resource("higgsfield://models")
        data = json.loads(out[0].text)
        assert data["count"] >= 43
        assert any(m["id"] == "higgsfield-ai/soul/standard" for m in data["models"])


@pytest.mark.asyncio
async def test_models_by_kind_template() -> None:
    async with Client(build_server()) as c:
        tmpls = [t.uriTemplate for t in await c.list_resource_templates()]
        assert "higgsfield://models/{kind}" in tmpls
        out = await c.read_resource("higgsfield://models/video")
        data = json.loads(out[0].text)
        assert data["count"] >= 1
        assert all(m["kind"] == "video" for m in data["models"])


@pytest.mark.asyncio
async def test_models_by_kind_unknown_kind() -> None:
    async with Client(build_server()) as c:
        out = await c.read_resource("higgsfield://models/bogus")
        data = json.loads(out[0].text)
        assert data["count"] == 0

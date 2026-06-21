from __future__ import annotations

import pytest
from fastmcp import Client

from higgsfield_mcp.server import build_server

EXPECTED = {"cinematic_shot", "product_360", "animate_portrait", "action_sequence", "b_roll"}


@pytest.mark.asyncio
async def test_prompts_registered() -> None:
    async with Client(build_server()) as c:
        names = {p.name for p in await c.list_prompts()}
        assert names >= EXPECTED


@pytest.mark.asyncio
async def test_cinematic_shot_renders_subject() -> None:
    async with Client(build_server()) as c:
        got = await c.get_prompt("cinematic_shot", {"subject": "a red fox", "mood": "noir"})
        text = got.messages[0].content.text
        assert "a red fox" in text
        assert "noir" in text

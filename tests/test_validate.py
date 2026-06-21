from __future__ import annotations

import pytest

from higgsfield_mcp.tools import validate_params


@pytest.mark.asyncio
async def test_validate_flags_unsupported_param() -> None:
    out = await validate_params("higgsfield-ai/soul/standard", {"prompt": "x", "bogus": 1})
    assert out["known_model"] is True
    assert out["valid"] is False
    assert out["unsupported"] == ["bogus"]


@pytest.mark.asyncio
async def test_validate_all_supported_is_valid() -> None:
    out = await validate_params(
        "higgsfield-ai/soul/standard", {"prompt": "x", "aspect_ratio": "16:9"}
    )
    assert out["valid"] is True
    assert out["unsupported"] == []


@pytest.mark.asyncio
async def test_validate_unknown_model() -> None:
    out = await validate_params("not-a-model", {"prompt": "x"})
    assert out["known_model"] is False
    assert out["valid"] is False

from __future__ import annotations

import pytest

from higgsfield_mcp.tools import recommend_model


@pytest.mark.asyncio
async def test_recommend_respects_kind_filter() -> None:
    out = await recommend_model("anything", kind="image", top=5)
    assert out["intent"] == "anything"
    assert 0 < len(out["recommendations"]) <= 5
    assert all(r["kind"] == "image" for r in out["recommendations"])


@pytest.mark.asyncio
async def test_recommend_scores_keyword_match_higher() -> None:
    out = await recommend_model("kling video", kind="video", top=3)
    assert out["recommendations"], "expected at least one recommendation"
    assert "kling" in out["recommendations"][0]["model_id"].lower()
    assert out["recommendations"][0]["score"] >= 1


@pytest.mark.asyncio
async def test_recommend_excludes_inferred_by_default() -> None:
    out = await recommend_model("veo", kind="video", top=20)
    ids = {r["model_id"] for r in out["recommendations"]}
    assert "veo3_1" not in ids  # inferred, hidden by default

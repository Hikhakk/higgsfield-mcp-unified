from __future__ import annotations

import pytest

from higgsfield_mcp.server import build_server

GENERIC = {"additionalProperties": True, "type": "object"}

TOOLS = [
    "list_models_tool",
    "generate_image_tool",
    "generate_video_tool",
    "get_status_tool",
    "cancel_job_tool",
    "upload_image_tool",
    "subscribe_tool",
    "preflight_check_tool",
]


@pytest.mark.asyncio
async def test_every_tool_has_specific_output_schema() -> None:
    mcp = build_server()
    for name in TOOLS:
        tool = await mcp.get_tool(name)
        schema = tool.to_mcp_tool().outputSchema
        assert schema is not None, f"{name} has no outputSchema"
        assert schema != GENERIC, f"{name} still has the generic passthrough schema"
        assert schema.get("type") == "object", name
        assert "properties" in schema, name


@pytest.mark.asyncio
async def test_list_models_schema_has_models_property() -> None:
    mcp = build_server()
    tool = await mcp.get_tool("list_models_tool")
    schema = tool.to_mcp_tool().outputSchema
    assert "models" in schema["properties"]
    assert "count" in schema["properties"]

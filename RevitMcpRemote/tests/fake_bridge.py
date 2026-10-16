# -*- coding: utf-8 -*-
"""Stand-in for bridge_core in tests: same build_server() contract, no Revit or licence needed."""
from mcp.server.fastmcp import FastMCP


def build_server():
    mcp = FastMCP("Revit MCP Server", host="127.0.0.1", port=8000, stateless_http=True, json_response=True)

    @mcp.tool()
    async def revit_status() -> dict:
        """Fake status."""
        return {"connected": True, "document_title": "B002_Fake"}

    @mcp.tool()
    async def execute_revit_code(code: str) -> str:
        """Fake code runner."""
        return "ran %d chars" % len(code)

    return mcp, "fake-extension-dir"

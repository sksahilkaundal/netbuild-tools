# -*- coding: utf-8 -*-
import sys
import httpx
import anyio
from mcp.server.fastmcp import FastMCP, Image, Context
import base64
import functools
from urllib.parse import urlencode
from typing import Optional, Dict, Any, Union
from revit_mcp_safety import check_revit_status, call_revit_route
from revit_mcp_router import router, RouterError

# Create a generic MCP server for interacting with Revit
# Use stateless_http=True and json_response=True for better compatibility
mcp = FastMCP(
    "Revit MCP Server", 
    host="127.0.0.1", 
    port=8000,
    stateless_http=True,
    json_response=True
)

# Configuration
# Port is resolved per call by revit_mcp_router: pyRevit gives each running
# Revit its own port (48884, 48885, ...). See revit_list_sessions /
# revit_select_session below, or env REVIT_MCP_TARGET in ~/.claude.json.
REVIT_HOST = "127.0.0.1"
REVIT_PORT = 48884
BASE_URL = f"http://{REVIT_HOST}:{REVIT_PORT}/revit_mcp"
# revit_mcp_safety.REVIT_BASE_URL has no route root, so every endpoint below
# ("/status/", "/execute_code/", ...) is prefixed with this before being sent.
ROUTE_PREFIX = "/revit_mcp"


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple GET request to Revit API"""
    return await _revit_call("GET", endpoint, ctx=ctx, **kwargs)


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple POST request to Revit API"""
    return await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs)


async def revit_image(endpoint: str, ctx: Context = None) -> Union[Image, str]:
    """GET request that returns an Image object"""
    try:
        result = await _safe_route("GET", endpoint, timeout=60.0)
        if result.get("success"):
            image_bytes = base64.b64decode(result["data"]["image_data"])
            return Image(data=image_bytes, format="png")
        return f"Error: {result.get('error')}"
    except Exception as e:
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"


async def _safe_route(method: str, endpoint: str, data: Dict = None,
                      timeout: float = 30.0, params: Dict = None) -> Dict:
    """Run call_revit_route() from revit_mcp_safety in a worker thread.

    call_revit_route() is synchronous (blocking httpx), so it is pushed to a
    thread to keep the MCP event loop responsive during long Revit operations.
    It never raises; it always returns {"success": bool, "data"|"error": ...}.
    """
    route = f"{ROUTE_PREFIX}{endpoint}"
    if params:
        route = f"{route}?{urlencode(params)}"
    return await anyio.to_thread.run_sync(
        functools.partial(call_revit_route, route, method=method, payload=data, timeout=timeout)
    )


async def _revit_call(method: str, endpoint: str, data: Dict = None, ctx: Context = None,
                     timeout: float = 30.0, params: Dict = None) -> Union[Dict, str]:
    """Internal function handling all HTTP calls (routed through revit_mcp_safety)"""
    try:
        result = await _safe_route(method, endpoint, data=data, timeout=timeout, params=params)
        # Preserve the historical contract: dict on success, "Error: ..." string otherwise.
        if result.get("success"):
            return result["data"]
        return f"Error: {result.get('error')}"
    except Exception as e:
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"


# Register all tools BEFORE the main block
from tools import register_tools
register_tools(mcp, revit_get, revit_post, revit_image)


@mcp.tool()
async def revit_status(ctx: Context = None) -> dict:
    """Check whether Revit + pyRevit Routes are alive. Never raises.
    Run this before any tool that modifies the model."""
    return await anyio.to_thread.run_sync(check_revit_status)


@mcp.tool()
async def revit_list_sessions(ctx: Context = None) -> dict:
    """List every running Revit instance reachable through pyRevit Routes
    (port, Revit version, pid, active document) and which one THIS Claude
    session's tools are currently routed to. Use it when more than one Revit
    is open, or when a tool reports it cannot reach Revit."""
    return await anyio.to_thread.run_sync(router.describe, True)


@mcp.tool()
async def revit_select_session(target: str = "auto", ctx: Context = None) -> dict:
    """Route this Claude session's Revit tools to one specific Revit instance.
    target: 'auto' (only one Revit open), 'port:48885', 'doc:<active document
    title substring>', 'version:2026', 'pid:<Revit pid>'. A doc: target is
    safest - it follows that document even if Revit restarts on another port,
    and refuses to run if that document is no longer the active one.
    Other Claude sessions are not affected. Returns the routed session."""
    def _select():
        try:
            return router.set_target(target)
        except RouterError as e:
            return {"success": False, "error": str(e), "sessions": router.describe(rescan=False)["sessions"]}
    return await anyio.to_thread.run_sync(_select)


async def run_combined_async():
    """Run server with both SSE and streamable-http endpoints.

    This allows clients to connect via either:
    - SSE: GET /sse, POST /messages/
    - Streamable-HTTP: POST/GET /mcp
    """
    import uvicorn

    # Get the streamable-http app first - it has the proper lifespan
    # that initializes the session manager's task group
    http_app = mcp.streamable_http_app()

    # Get SSE routes (SSE doesn't need special lifespan - it creates
    # task groups per-request in connect_sse())
    sse_app = mcp.sse_app()

    # Add SSE routes to the http app (preserving its lifespan)
    for route in sse_app.routes:
        http_app.routes.append(route)

    config = uvicorn.Config(
        http_app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    transport = "stdio"

    if "--sse" in sys.argv:
        transport = "sse"
    elif "--http" in sys.argv or "--streamable-http" in sys.argv:
        transport = "streamable-http"
    elif "--combined" in sys.argv:
        # Run both SSE and streamable-http transports simultaneously
        print("Starting combined server with SSE (/sse, /messages/) and streamable-http (/mcp) endpoints...")
        anyio.run(run_combined_async)
        sys.exit(0)

    mcp.run(transport=transport)
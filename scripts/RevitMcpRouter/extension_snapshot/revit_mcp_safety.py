"""
Hardened connection helpers for a pyRevit MCP bridge.

Drop these into main.py (or import them) alongside your existing MCP tools.
Goal: a Revit crash or a slow response NEVER raises an unhandled exception
that kills the main.py process — it always returns a clean error dict instead.
"""

import httpx

from revit_mcp_router import router, RouterError

# Legacy constants, kept for anything that imports them. The live base URL is
# now resolved per call by revit_mcp_router (one port per running Revit).
REVIT_BASE_URL = "http://127.0.0.1:48884"
STATUS_ENDPOINT = f"{REVIT_BASE_URL}/revit_mcp/status/"

DEFAULT_STATUS_TIMEOUT = 5.0   # quick check, should return almost instantly
DEFAULT_CALL_TIMEOUT = 15.0    # real operations may take longer


def check_revit_status(timeout: float = DEFAULT_STATUS_TIMEOUT) -> dict:
    """
    Resolve the routed Revit session and ping its health endpoint. Never raises.
    Call this FIRST in any tool that's about to touch the live model.
    """
    try:
        session = router.resolve()
    except RouterError as e:
        return {"connected": False, "error": str(e), "target": router.describe(rescan=False)["target"]}
    except Exception as e:
        return {"connected": False, "error": f"Router failure: {e}"}
    try:
        response = httpx.get(session["base_url"] + "/revit_mcp/status/", timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return {
            "connected": True,
            "revit_available": data.get("revit_available", False),
            "document_title": data.get("document_title"),
            "session": router._public(session),
        }
    except httpx.ConnectError:
        router.invalidate()
        return {
            "connected": False,
            "error": f"Cannot reach Revit on port {session['port']} — it may have just closed; retry.",
        }
    except httpx.TimeoutException:
        return {
            "connected": False,
            "error": "Revit did not respond in time — it may be busy, hung, or has crashed.",
        }
    except Exception as e:
        return {"connected": False, "error": f"Unexpected error checking status: {e}"}


def call_revit_route(
    endpoint: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = DEFAULT_CALL_TIMEOUT,
) -> dict:
    """
    Safely call any pyRevit Routes endpoint (e.g. "/revit_mcp/walls/tag_all/")
    on the Revit session the router currently points at. Never raises.
    A connection failure triggers one re-discovery + retry (Revit restarted on
    another port, or the router was pointed at a closed instance).
    """
    for attempt in (1, 2):
        try:
            session = router.resolve()
        except RouterError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Router failure: {e}"}
        url = f"{session['base_url']}{endpoint}"
        try:
            if method.upper() == "GET":
                response = httpx.get(url, timeout=timeout)
            else:
                response = httpx.post(url, json=payload or {}, timeout=timeout)
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.ConnectError:
            router.invalidate()
            if attempt == 1:
                continue
            return {
                "success": False,
                "error": f"Cannot reach Revit on port {session['port']} — check if it crashed or Routes server stopped.",
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": f"Revit (port {session['port']}) did not respond within the timeout window.",
            }
        except Exception as e:
            return {"success": False, "error": f"Unhandled error calling Revit route: {e}"}
    return {"success": False, "error": "unreachable"}


# --- Example MCP tool registration (adjust to your framework's decorator) ---
#
# from mcp.server.fastmcp import FastMCP
# mcp = FastMCP("Revit Connector")
#
# @mcp.tool()
# def revit_status() -> dict:
#     """Check whether Revit + pyRevit Routes are alive. Run this before any
#     tool that modifies the model."""
#     return check_revit_status()
#
# @mcp.tool()
# def tag_all_walls() -> dict:
#     """Tag all walls in the current view."""
#     status = check_revit_status()
#     if not status["connected"]:
#         return status  # fail fast with a clear message instead of hanging
#     return call_revit_route("/revit_mcp/walls/tag_all/", method="POST")

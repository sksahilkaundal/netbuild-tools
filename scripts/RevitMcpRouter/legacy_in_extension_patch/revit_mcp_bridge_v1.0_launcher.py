# -*- coding: utf-8 -*-
"""
Update-proof launcher for the Revit MCP bridge.

Point ~/.claude.json at THIS file instead of the extension's main.py:

    "revit": {
      "command": "C:\\Users\\user\\AppData\\Roaming\\pyRevit\\Extensions\\mcp-server-for-revit-python.extension\\.venv\\Scripts\\python.exe",
      "args":    ["C:\\SK\\OneDrive\\Netbuild\\scripts\\RevitMcpRouter\\revit_mcp_bridge.py"]
    }

Why a separate launcher
-----------------------
The multi-session router used to be patched INTO the extension's main.py and
revit_mcp_safety.py. Any extension update (pyRevit "Update" button / git pull)
overwrites those files and silently drops the router. This launcher lives
outside the extension and never modifies it:

  * it imports the extension's own `tools` package (so updated/new tools are
    picked up automatically) and gives them ROUTED revit_get/post/image
    helpers backed by revit_mcp_router.py (kept beside this file),
  * it re-adds the hardened status/session tools (revit_status,
    revit_list_sessions, revit_select_session),
  * if the extension's venv was re-created without mcp/httpx it installs them
    (uv pip) before starting, so a resynced venv does not break the bridge.

The extension's main.py is not used at all. Nothing in the extension folder
needs to be patched any more.

    python revit_mcp_bridge.py --check     -> prints tool count + discovered Revits, exits
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.environ.get("REVIT_MCP_EXTENSION_DIR") or os.path.join(
    os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mcp-server-for-revit-python.extension")
REQUIRED = ['mcp[cli]<2', 'httpx']


def _log(msg):
    sys.stderr.write("[revit_mcp_bridge] %s\n" % msg)
    sys.stderr.flush()


def _die(msg, code=1):
    _log("FATAL: " + msg)
    sys.exit(code)


# ----------------------------------------------------------------------------
# 0. sanity: extension present, sys.path, deps
# ----------------------------------------------------------------------------
if not os.path.isfile(os.path.join(EXT_DIR, "tools", "__init__.py")):
    _die("extension not found at %s (set REVIT_MCP_EXTENSION_DIR)" % EXT_DIR)

# our router first (never shadowed by a copy inside the extension), then the extension
for p in (EXT_DIR, HERE):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)
os.chdir(EXT_DIR)


def _ensure_deps():
    try:
        import mcp.server.fastmcp  # noqa: F401
        import httpx  # noqa: F401
        import anyio  # noqa: F401
        return
    except ImportError as e:
        _log("missing dependency in %s: %s - installing %s" % (sys.executable, e, REQUIRED))
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    candidates = [shutil.which("uv"),
                  os.path.join(home, "uv-portable", "uv.exe"),
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "uv", "uv.exe"),
                  os.path.join(home, ".local", "bin", "uv.exe")]
    uv = next((c for c in candidates if c and os.path.isfile(c)), None)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if uv:
        cmd = [uv, "pip", "install", "--python", sys.executable] + REQUIRED
    else:  # uv-made venvs have no pip: bootstrap it, then pip install
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True, text=True, creationflags=flags)
        cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + REQUIRED
    _log("running: " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    _log((r.stdout or "")[-2000:] + (r.stderr or "")[-2000:])
    # Freshly installed packages may need .pth processing (pywin32 for mcp on
    # Windows), which only happens at interpreter start: re-run ourselves in a
    # child that inherits stdin/stdout, so the MCP stdio pipes stay intact.
    if os.environ.get("REVIT_MCP_BRIDGE_REEXEC") == "1":
        _die("dependencies still missing after install; run manually: %s" % " ".join(cmd))
    env = dict(os.environ, REVIT_MCP_BRIDGE_REEXEC="1")
    _log("restarting with the installed dependencies")
    sys.exit(subprocess.call([sys.executable] + sys.argv, env=env))


_ensure_deps()

# ----------------------------------------------------------------------------
# 1. the bridge
# ----------------------------------------------------------------------------
import base64  # noqa: E402
import functools  # noqa: E402
from typing import Any, Dict, Union  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

import anyio  # noqa: E402
import httpx  # noqa: E402
from mcp.server.fastmcp import Context, FastMCP, Image  # noqa: E402

from revit_mcp_router import RouterError, router  # noqa: E402

mcp = FastMCP("Revit MCP Server", host="127.0.0.1", port=8000, stateless_http=True, json_response=True)

ROUTE_PREFIX = "/revit_mcp"
DEFAULT_STATUS_TIMEOUT = 5.0
DEFAULT_CALL_TIMEOUT = 15.0


# -- hardened, routed HTTP layer (never raises) -------------------------------
def check_revit_status(timeout: float = DEFAULT_STATUS_TIMEOUT) -> dict:
    try:
        session = router.resolve()
    except RouterError as e:
        return {"connected": False, "error": str(e), "target": router.describe(rescan=False)["target"]}
    except Exception as e:
        return {"connected": False, "error": "Router failure: %s" % e}
    try:
        response = httpx.get(session["base_url"] + ROUTE_PREFIX + "/status/", timeout=timeout)
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
        return {"connected": False, "error": "Cannot reach Revit on port %d - it may have just closed; retry." % session["port"]}
    except httpx.TimeoutException:
        return {"connected": False, "error": "Revit did not respond in time - it may be busy, hung, or has crashed."}
    except Exception as e:
        return {"connected": False, "error": "Unexpected error checking status: %s" % e}


def call_revit_route(endpoint: str, method: str = "GET", payload: dict = None,
                     timeout: float = DEFAULT_CALL_TIMEOUT) -> dict:
    """Call a pyRevit Routes endpoint on the routed Revit; one re-discovery + retry on ConnectError."""
    for attempt in (1, 2):
        try:
            session = router.resolve()
        except RouterError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": "Router failure: %s" % e}
        url = session["base_url"] + endpoint
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
            return {"success": False, "error": "Cannot reach Revit on port %d - check if it crashed or Routes server stopped." % session["port"]}
        except httpx.TimeoutException:
            return {"success": False, "error": "Revit (port %d) did not respond within the timeout window." % session["port"]}
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:800]
            except Exception:
                pass
            return {"success": False, "error": "HTTP %s from Revit (port %d): %s" % (e.response.status_code, session["port"], body)}
        except Exception as e:
            return {"success": False, "error": "Unhandled error calling Revit route: %s" % e}
    return {"success": False, "error": "unreachable"}


# -- helpers handed to the extension's tools package --------------------------
async def _safe_route(method: str, endpoint: str, data: Dict = None, timeout: float = 30.0, params: Dict = None) -> Dict:
    route = ROUTE_PREFIX + endpoint
    if params:
        route = "%s?%s" % (route, urlencode(params))
    return await anyio.to_thread.run_sync(
        functools.partial(call_revit_route, route, method=method, payload=data, timeout=timeout))


async def _revit_call(method: str, endpoint: str, data: Dict = None, ctx: Context = None,
                      timeout: float = 30.0, params: Dict = None) -> Union[Dict, str]:
    try:
        result = await _safe_route(method, endpoint, data=data, timeout=timeout, params=params)
        if result.get("success"):
            return result["data"]
        return "Error: %s" % result.get("error")
    except Exception as e:
        return "Error: %s" % (str(e) or type(e).__name__)


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    return await _revit_call("GET", endpoint, ctx=ctx, **kwargs)


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    return await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs)


async def revit_image(endpoint: str, ctx: Context = None) -> Union[Image, str]:
    try:
        result = await _safe_route("GET", endpoint, timeout=60.0)
        if result.get("success"):
            return Image(data=base64.b64decode(result["data"]["image_data"]), format="png")
        return "Error: %s" % result.get("error")
    except Exception as e:
        return "Error: %s" % (str(e) or type(e).__name__)


# -- the extension's own tools (whatever version is installed) ----------------
try:
    from tools import register_tools
except Exception as e:
    _die("cannot import the extension's tools package from %s: %s" % (EXT_DIR, e))
try:
    register_tools(mcp, revit_get, revit_post, revit_image)
except TypeError as e:
    _die("tools.register_tools signature changed upstream (%s) - update revit_mcp_bridge.py" % e)


# -- session / status tools ----------------------------------------------------
@mcp.tool()
async def revit_status(ctx: Context = None) -> dict:
    """Check whether Revit + pyRevit Routes are alive on the Revit this session is
    routed to, and which document is active there. Never raises. Run this before
    any tool that modifies the model."""
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


# ----------------------------------------------------------------------------
# 2. run
# ----------------------------------------------------------------------------
def _check():
    import json
    names = sorted(mcp._tool_manager._tools.keys())
    print("bridge:     %s" % os.path.abspath(__file__))
    print("extension:  %s" % EXT_DIR)
    print("python:     %s" % sys.executable)
    print("tools (%d): %s" % (len(names), ", ".join(names)))
    try:
        router.resolve()
    except RouterError as e:
        print("router:     %s" % e)
    print(json.dumps(router.describe(rescan=False), indent=2))


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
        sys.exit(0)
    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"
    elif "--http" in sys.argv or "--streamable-http" in sys.argv:
        transport = "streamable-http"
    mcp.run(transport=transport)

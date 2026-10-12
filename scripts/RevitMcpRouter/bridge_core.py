# -*- coding: utf-8 -*-
"""
Revit MCP Router - bridge core (compiled to a .pyd for release; run by RevitMcpBridge.exe).

Self-contained MCP stdio server: bundles mcp/httpx/anyio, imports the pyRevit
MCP extension's `tools` package from disk (whatever version is installed) and
hands it ROUTED revit_get/post/image helpers backed by revit_mcp_router.
Adds revit_status / revit_list_sessions / revit_select_session, and the
multi-model tools revit_list_documents / revit_run_on_documents (multimodel_core).
Client-agnostic stdio server: Claude Code, Claude Desktop and Codex all launch it.

Licence: checked once at start (nb_license). Unlicensed -> the server still
answers so Claude can explain why, but every Revit call returns the message.

Extension folder resolution: REVIT_MCP_EXTENSION_DIR env, then
%LOCALAPPDATA%\\RevitMcpRouter\\config.json {"extension_dir": ...} written by
Setup, then the pyRevit default location.
"""
import base64
import functools
import json
import os
import sys
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import anyio
import httpx
from mcp.server.fastmcp import Context, FastMCP, Image

import multimodel_core
import nb_license
from revit_mcp_router import RouterError, router

ROUTE_PREFIX = "/revit_mcp"
DEFAULT_STATUS_TIMEOUT = 5.0
DEFAULT_CALL_TIMEOUT = 15.0
CONFIG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RevitMcpRouter", "config.json")


def _log(msg):
    sys.stderr.write("[revit_mcp_bridge] %s\n" % msg)
    sys.stderr.flush()


def extension_dir():
    cands = [os.environ.get("REVIT_MCP_EXTENSION_DIR")]
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            cands.append(json.load(fh).get("extension_dir"))
    except Exception:
        pass
    cands.append(os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mcp-server-for-revit-python.extension"))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "tools", "__init__.py")):
            return c
    return None


LICENSE_STATE, LICENSE_INFO = nb_license.license_state()
LICENSED = LICENSE_STATE == "ok"


def _unlicensed():
    return nb_license.unlicensed_message() + " (state: %s)" % LICENSE_STATE


# -- hardened, routed HTTP layer (never raises) -------------------------------
def check_revit_status(timeout: float = DEFAULT_STATUS_TIMEOUT) -> dict:
    if not LICENSED:
        return {"connected": False, "error": _unlicensed(), "license": LICENSE_STATE}
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
        return {"connected": True, "revit_available": data.get("revit_available", False),
                "document_title": data.get("document_title"), "session": router._public(session),
                "license": "ok"}
    except httpx.HTTPStatusError as e:
        # the listener answers 503 + JSON while Revit is up with no model open (Home screen)
        try:
            data = e.response.json()
        except Exception:
            data = None
        if e.response.status_code == 503 and isinstance(data, dict):
            return {"connected": True, "revit_available": False, "document_title": None,
                    "note": data.get("error") or "No active Revit document - open a model",
                    "session": router._public(session), "license": "ok"}
        return {"connected": False, "error": "HTTP %s from Revit (port %d)" % (e.response.status_code, session["port"])}
    except httpx.ConnectError:
        router.invalidate()
        return {"connected": False, "error": "Cannot reach Revit on port %d - it may have just closed; retry." % session["port"]}
    except httpx.TimeoutException:
        return {"connected": False, "error": "Revit did not respond in time - it may be busy, hung, or has crashed."}
    except Exception as e:
        return {"connected": False, "error": "Unexpected error checking status: %s" % e}


def call_revit_route(endpoint: str, method: str = "GET", payload: dict = None,
                     timeout: float = DEFAULT_CALL_TIMEOUT) -> dict:
    if not LICENSED:
        return {"success": False, "error": _unlicensed()}
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


def execute_code(code: str, description: str, timeout: float):
    """POST IronPython to the routed Revit's execute_code route. Returns (output, error); never raises.
    Unlike call_revit_route it keeps the printed output of a failed run (the listener answers 500 + JSON)."""
    if not LICENSED:
        return "", _unlicensed()
    for attempt in (1, 2):
        try:
            session = router.resolve()
        except RouterError as e:
            return "", str(e)
        except Exception as e:
            return "", "Router failure: %s" % e
        try:
            r = httpx.post(session["base_url"] + ROUTE_PREFIX + "/execute_code/", timeout=timeout,
                           json={"code": code, "description": description, "use_transaction": False})
        except httpx.ConnectError:
            router.invalidate()
            if attempt == 1:
                continue
            return "", "Cannot reach Revit on port %d - check if it crashed or Routes server stopped." % session["port"]
        except httpx.TimeoutException:
            return "", "Revit (port %d) did not answer within %ds." % (session["port"], timeout)
        except Exception as e:
            return "", "Unhandled error calling Revit: %s" % e
        try:
            d = r.json()
        except Exception:
            return r.text, ("" if r.status_code == 200 else "HTTP %s: %s" % (r.status_code, r.text[-800:]))
        if not isinstance(d, dict):
            return r.text, ""
        out = d.get("output") or d.get("partial_output") or ""
        if d.get("status") == "success" and r.status_code == 200:
            return out, ""
        tb = d.get("traceback") or ""
        return out, (d.get("error") or "HTTP %s" % r.status_code) + ("\n" + tb[-1500:] if tb else "")
    return "", "unreachable"


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


# -- server ----------------------------------------------------------------------
def build_server():
    ext = extension_dir()
    if not ext:
        _log("FATAL: Revit MCP connector not found (run Revit MCP Router Setup)")
        sys.exit(2)
    if ext not in sys.path:
        sys.path.insert(0, ext)
    os.chdir(ext)
    mcp = FastMCP("Revit MCP Server", host="127.0.0.1", port=8000, stateless_http=True, json_response=True)
    try:
        from tools import register_tools
        register_tools(mcp, revit_get, revit_post, revit_image)
    except TypeError as e:
        _log("FATAL: tools.register_tools signature changed upstream (%s)" % e)
        sys.exit(2)
    except Exception as e:
        _log("FATAL: Revit MCP connector at %s could not be loaded: %s" % (ext, e))
        sys.exit(2)

    @mcp.tool()
    async def revit_status(ctx: Context = None) -> dict:
        """Check whether Revit and its MCP connector are alive on the Revit this session is
        routed to, which document is active there, and the licence state. Never raises.
        Run this before any tool that modifies the model."""
        return await anyio.to_thread.run_sync(check_revit_status)

    @mcp.tool()
    async def revit_list_sessions(ctx: Context = None) -> dict:
        """List every running Revit instance reachable through the Revit MCP connector
        (port, Revit version, pid, active document) and which one THIS Claude
        session's tools are currently routed to. Use it when more than one Revit
        is open, or when a tool reports it cannot reach Revit."""
        if not LICENSED:
            return {"error": _unlicensed()}
        return await anyio.to_thread.run_sync(router.describe, True)

    @mcp.tool()
    async def revit_select_session(target: str = "auto", ctx: Context = None) -> dict:
        """Route this Claude session's Revit tools to one specific Revit instance.
        target: 'auto' (only one Revit open), 'port:48885', 'doc:<active document
        title substring>', 'version:2026', 'pid:<Revit pid>', or 'off' (alias
        'disconnect'): unbind, so every Revit tool refuses until a new target is
        selected. A doc: target is safest - it follows that document even if Revit
        restarts on another port, and refuses to run if that document is no longer
        the active one. A pid: target refuses once that Revit closes, even if a new
        Revit takes over its port. Other Claude sessions are not affected.
        Returns the routed session."""
        if not LICENSED:
            return {"success": False, "error": _unlicensed()}

        def _select():
            try:
                return router.set_target(target)
            except RouterError as e:
                return {"success": False, "error": str(e), "sessions": router.describe(rescan=False)["sessions"]}
        return await anyio.to_thread.run_sync(_select)

    @mcp.tool()
    async def revit_list_documents(ctx: Context = None) -> dict:
        """List every model open in the Revit this session is routed to - not just the
        active window: title, path, active / linked / family / workshared / read-only.
        Use the titles with revit_run_on_documents."""
        def _list():
            try:
                return {"success": True, "documents": multimodel_core.list_documents(execute_code)}
            except multimodel_core.MultiModelError as e:
                return {"success": False, "error": str(e)}
        return await anyio.to_thread.run_sync(_list)

    @mcp.tool()
    async def revit_run_on_documents(titles: Optional[List[str]] = None, code: Optional[str] = None,
                                     task_file: Optional[str] = None,
                                     apply: bool = False, swallow_warnings: bool = False,
                                     stop_on_fail: bool = False, ctx: Context = None) -> dict:
        """Run ONE IronPython 2.7 task on SEVERAL models open in the same Revit, one model
        at a time, each bound by document title - the active window does not matter.

        titles: document titles or unique substrings (e.g. ["B001", "B002"]); an exact
          title beats a substring; an unknown or ambiguous one stops before anything runs.
          Empty = the active model only.
        code / task_file: the task source, or an absolute path to a .py task file.
          In the task: doc (the TARGET model), uidoc (only if it is the active window,
          else None), DB, revit, ctx.title, ctx.dry_run, ctx.log(msg),
          `with ctx.transaction("name") as t:` for every change, and assign a
          JSON-serialisable dict to `result` for the summary. print() output is returned.
        apply: False (default) = DRY RUN: the task really runs, then the model is rolled
          back, so counts are real but nothing is kept. True = commit, one undo step per
          model. Always dry-run first and apply only after the user says so.
        swallow_warnings: auto-dismiss Revit warnings (never errors) in task transactions.

        Nothing is synced or saved - the result lists unsynced_models. Rules: no f-strings,
        str(e.Id) not .IntegerValue (Revit 2026), DB.Element.Name.__get__(e) for names."""
        return await anyio.to_thread.run_sync(functools.partial(
            multimodel_core.run, execute_code, titles or [], code=code, task_file=task_file, apply=apply,
            swallow_warnings=swallow_warnings, stop_on_fail=stop_on_fail))

    return mcp, ext


def check(mcp, ext):
    names = sorted(mcp._tool_manager._tools.keys())
    print("bridge:     %s" % (sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)))
    print("extension:  %s" % ext)
    print("licence:    %s" % nb_license.status_text())
    print("tools (%d): %s" % (len(names), ", ".join(names)))
    try:
        router.resolve()
    except RouterError as e:
        print("router:     %s" % e)
    print(json.dumps(router.describe(rescan=False), indent=2))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--license-status" in argv:
        print(nb_license.status_text())
        return 0
    if "--activate" in argv:
        i = argv.index("--activate")
        ok, msg = nb_license.try_activate(argv[i + 1] if i + 1 < len(argv) else "")
        print(msg)
        return 0 if ok else 1
    if not LICENSED:
        _log("licence: " + nb_license.status_text())
    mcp, ext = build_server()
    if "--check" in argv:
        check(mcp, ext)
        return 0
    transport = "stdio"
    if "--sse" in argv:
        transport = "sse"
    elif "--http" in argv or "--streamable-http" in argv:
        transport = "streamable-http"
    mcp.run(transport=transport)
    return 0

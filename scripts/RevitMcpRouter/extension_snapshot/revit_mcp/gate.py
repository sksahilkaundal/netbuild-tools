# -*- coding: UTF-8 -*-
"""On/off gate for the Revit MCP server, toggled by the 'MCP Status' pyRevit
button (Studio-Claude.extension > SK's Tool 1 > MCP Status). When disabled,
every /revit_mcp/... route responds with a clear 503 'paused' message
instead of running -- this does not touch the underlying HTTP listener
(pyRevit's routes host), it just gates the request handlers registered by
this extension.

Default (no flag file yet, or unreadable) is ENABLED, so a fresh install
never silently blocks Claude Code.
"""
import json
import os

GATE_FILE = os.path.join(
    os.environ.get("APPDATA", ""), "pyRevit", "revit_mcp_gate.json"
)


def is_enabled():
    if not os.path.exists(GATE_FILE):
        return True
    try:
        with open(GATE_FILE, "r") as f:
            data = json.load(f)
        return bool(data.get("enabled", True))
    except Exception:
        return True


def paused_response():
    """Shared 503 payload every gated route returns when stopped. Building
    this here (instead of duplicating it per route file) keeps the message
    consistent and makes it trivial to keep in sync with the MCP Status
    button's wording."""
    from pyrevit import routes
    return routes.make_response(
        data={
            "status": "paused",
            "health": "paused",
            "revit_available": False,
            "error": (
                "Revit MCP has been manually stopped via the 'MCP Status' "
                "button in Revit (SK's Tool 1 tab). Click it and choose "
                "'Start MCP' to resume."
            ),
        },
        status=503,
    )


def set_enabled(value):
    try:
        folder = os.path.dirname(GATE_FILE)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with open(GATE_FILE, "w") as f:
            json.dump({"enabled": bool(value)}, f)
        return True
    except Exception:
        return False

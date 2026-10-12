# -*- coding: utf-8 -*-
"""
Revit MCP Remote - the Revit MCP Router, reachable from Claude on the web.

Same tools, same routing as the local router (it loads bridge_core.build_server()
from the RevitMcpRouter folder, so revit_list_sessions / revit_select_session /
the pyRevit extension tools all behave identically), but served as a REMOTE MCP
server over Streamable HTTP instead of stdio:

    Claude (web / desktop / mobile)  --HTTPS-->  Cloudflare Tunnel
        --> 127.0.0.1:8765  [OAuth gate]  --> MCP tools --> router --> Revit 48884..

Nothing listens on the network directly: the server binds 127.0.0.1 only and
the tunnel (cloudflared, outbound connection) is the only way in. Every MCP
request needs a bearer token, obtained by signing in with your passphrase.

Usage (Windows, from this folder):
    py -3.14 revit_mcp_remote.py --setup            once: passphrase + static token
    py -3.14 revit_mcp_remote.py --tunnel quick     serve + print the connector URL
    py -3.14 revit_mcp_remote.py --check            list tools, test routing, exit
    py -3.14 revit_mcp_remote.py --revoke-all       sign every client out
"""
from __future__ import annotations

import argparse
import contextlib
import getpass
import importlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import oauth_gate  # noqa: E402

VERSION = "0.2.0"
DEFAULT_PORT = 8765
ROUTER_DIR_CANDIDATES = (
    os.path.join(os.path.dirname(HERE), "RevitMcpRouter"),             # Netbuild\scripts\RevitMcpRemote
    os.path.join(os.path.dirname(HERE), "scripts", "RevitMcpRouter"),  # repo root layout
    r"C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter",
)


def _log(msg):
    sys.stderr.write("[revit_mcp_remote] %s\n" % msg)
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Loading the existing router (never copied here - its source stays private)
# ---------------------------------------------------------------------------
def find_router_dir(explicit=None):
    for c in (explicit, os.environ.get("RMR_ROUTER_DIR")) + ROUTER_DIR_CANDIDATES:
        if c and os.path.isfile(os.path.join(c, "bridge_core.py")):
            return c
    return None


def load_bridge(router_dir, module_name="bridge_core"):
    if router_dir and router_dir not in sys.path:
        sys.path.insert(0, router_dir)
    return importlib.import_module(module_name)


def build_mcp(bridge, deny_tools=()):
    """bridge.build_server() -> FastMCP with every Revit tool, re-configured for remote HTTP."""
    mcp, ext = bridge.build_server()
    s = mcp.settings
    s.host, s.port = "127.0.0.1", DEFAULT_PORT
    s.stateless_http = True        # Claude may open several connections; no session affinity needed
    s.json_response = False        # stream (SSE) so long Revit calls start answering at once
    if hasattr(s, "transport_security"):
        # The tunnel delivers a public Host header; the OAuth gate is the protection here.
        try:
            from mcp.server.transport_security import TransportSecuritySettings
            s.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        except ImportError:
            pass
    tools = mcp._tool_manager._tools
    for name in deny_tools:
        if tools.pop(name, None) is not None:
            _log("tool disabled for remote use: %s" % name)
    return mcp, ext


def warm_router(bridge):
    """Kick off Revit discovery in the background at startup so the first tool call after a
    client connects doesn't pay the full pyRevit scan/probe cost. Best-effort, never fatal."""
    router = getattr(bridge, "router", None)
    if router is None or not hasattr(router, "discover"):
        return

    def _warm():
        try:
            router.discover(force=True)
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True).start()


def build_app(mcp, store):
    from starlette.applications import Starlette
    from starlette.routing import Mount

    inner = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    path = getattr(mcp.settings, "streamable_http_path", "/mcp")
    gate = oauth_gate.OAuthGate(inner, store, mcp_path=path)
    return Starlette(routes=[Mount("/", app=gate)], lifespan=lifespan)


# ---------------------------------------------------------------------------
# Cloudflare Tunnel
# ---------------------------------------------------------------------------
def find_cloudflared(explicit=None):
    for c in (explicit, os.environ.get("RMR_CLOUDFLARED"),
              os.path.join(HERE, "cloudflared.exe"), shutil.which("cloudflared")):
        if c and os.path.isfile(c):
            return c
    return None


def start_tunnel(kind, port, exe, name=None, public_url=None, mcp_path="/mcp"):
    origin = "http://127.0.0.1:%d" % port
    # QUIC cuts a round trip off the TLS/connection handshake vs http2 and is Cloudflare's
    # preferred transport; it falls back to http2 on its own if UDP/7844 is blocked.
    proto = os.environ.get("RMR_TUNNEL_PROTOCOL", "quic").strip()
    # Keep the edge<->origin HTTP connections warm so back-to-back tool calls reuse them.
    tune = ["--proxy-keepalive-connections", os.environ.get("RMR_TUNNEL_KEEPALIVE", "8"),
            "--proxy-keepalive-timeout", os.environ.get("RMR_TUNNEL_KEEPALIVE_TIMEOUT", "90s")]
    flags = ["--no-autoupdate"] + (["--protocol", proto] if proto and proto != "auto" else [])
    if kind == "quick":
        cmd = [exe, "tunnel"] + flags + tune + ["--url", origin]
    else:
        cmd = [exe, "tunnel"] + flags + ["run"] + tune + ["--url", origin, name]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")

    def announce(url):
        bar = "=" * 72
        _log("\n%s\n  Connector URL for Claude:  %s%s\n  Claude > Settings > Connectors > Add custom connector, paste it,\n"
             "  then Connect and enter your passphrase.\n%s" % (bar, url, mcp_path, bar))

    def pump():
        announced = False
        for line in proc.stdout:
            if os.environ.get("RMR_TUNNEL_VERBOSE"):
                _log("cloudflared: " + line.rstrip())
            if kind == "quick" and not announced:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m:
                    announced = True
                    announce(m.group(0))
            elif "ERR" in line and not os.environ.get("RMR_TUNNEL_VERBOSE"):
                _log("cloudflared: " + line.rstrip())
        _log("cloudflared exited (code %s) - Claude can no longer reach this PC." % proc.poll())

    threading.Thread(target=pump, daemon=True).start()
    if kind == "named" and public_url:
        announce(public_url.rstrip("/"))
    return proc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_setup(store, rotate_only=False):
    if not rotate_only:
        while True:
            p1 = getpass.getpass("New passphrase for Claude sign-in (min 12 chars): ")
            if len(p1) < 12:
                print("Too short.")
                continue
            if getpass.getpass("Repeat: ") != p1:
                print("Did not match.")
                continue
            break
        store.data["passphrase"] = oauth_gate.hash_passphrase(p1)
    token = "rmrs_" + secrets.token_urlsafe(32)
    store.data["static_token_sha"] = oauth_gate._sha(token)
    store.save()
    print("\nSaved to %s" % store.path)
    print("Static bearer token (shown ONCE - for Claude Code / scripts, not needed for Claude web):")
    print("  " + token)
    print('  claude mcp add --transport http revit-remote <URL>/mcp --header "Authorization: Bearer %s"' % token)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Revit MCP Remote %s" % VERSION)
    ap.add_argument("--setup", action="store_true", help="set the passphrase and a new static token")
    ap.add_argument("--rotate-token", action="store_true", help="replace the static bearer token only")
    ap.add_argument("--revoke-all", action="store_true", help="forget every OAuth client and token")
    ap.add_argument("--check", action="store_true", help="load the tools, test routing, exit")
    ap.add_argument("--port", type=int, default=int(os.environ.get("RMR_PORT", DEFAULT_PORT)))
    ap.add_argument("--tunnel", choices=("none", "quick", "named"), default=os.environ.get("RMR_TUNNEL", "none"))
    ap.add_argument("--tunnel-name", default=os.environ.get("RMR_TUNNEL_NAME"))
    ap.add_argument("--public-url", default=os.environ.get("RMR_PUBLIC_URL"),
                    help="fixed public https origin (named tunnel / own domain)")
    ap.add_argument("--cloudflared", help="path to cloudflared.exe")
    ap.add_argument("--router-dir", help="folder holding bridge_core.py (the existing RevitMcpRouter)")
    ap.add_argument("--bridge-module", default=os.environ.get("RMR_BRIDGE_MODULE", "bridge_core"))
    ap.add_argument("--deny-tools", default=os.environ.get("RMR_DENY_TOOLS", ""),
                    help="comma list of tool names to hide from remote clients")
    a = ap.parse_args(argv)

    store = oauth_gate.Store()
    if a.setup or a.rotate_token:
        return cmd_setup(store, rotate_only=a.rotate_token and not a.setup)
    if a.revoke_all:
        store.revoke_all()
        print("All OAuth clients and tokens revoked. Re-connect the connector in Claude.")
        return 0

    router_dir = find_router_dir(a.router_dir) if a.bridge_module == "bridge_core" else a.router_dir
    if a.bridge_module == "bridge_core" and not router_dir:
        _log("FATAL: RevitMcpRouter folder (bridge_core.py) not found. Pass --router-dir or set RMR_ROUTER_DIR.")
        return 2
    bridge = load_bridge(router_dir, a.bridge_module)
    deny = [t.strip() for t in a.deny_tools.split(",") if t.strip()]
    mcp, ext = build_mcp(bridge, deny)
    mcp.settings.port = a.port

    if a.check:
        if hasattr(bridge, "check"):
            bridge.check(mcp, ext)
        else:
            print("tools: " + ", ".join(sorted(mcp._tool_manager._tools)))
        print("auth configured: %s (%s)" % (store.configured, store.path))
        return 0

    if not store.configured:
        _log("FATAL: no passphrase/token yet - run once with --setup.")
        return 2
    if a.public_url:
        os.environ["RMR_PUBLIC_URL"] = a.public_url

    tunnel = None
    if a.tunnel != "none":
        exe = find_cloudflared(a.cloudflared)
        if not exe:
            _log("FATAL: cloudflared not found. Install it (winget install --id Cloudflare.cloudflared) "
                 "or drop cloudflared.exe next to this script.")
            return 2
        if a.tunnel == "named" and not a.tunnel_name:
            _log("FATAL: --tunnel named needs --tunnel-name (and --public-url).")
            return 2
        tunnel = start_tunnel(a.tunnel, a.port, exe, a.tunnel_name, a.public_url,
                              getattr(mcp.settings, "streamable_http_path", "/mcp"))

    warm_router(bridge)

    import uvicorn
    _log("Revit MCP Remote %s on http://127.0.0.1:%d (%d tools, router: %s)"
         % (VERSION, a.port, len(mcp._tool_manager._tools), router_dir or a.bridge_module))
    try:
        # timeout_keep_alive holds the edge<->origin connection open between tool calls so a
        # burst of calls in one chat reuses it instead of re-handshaking each time.
        uvicorn.run(build_app(mcp, store), host="127.0.0.1", port=a.port,
                    log_level=os.environ.get("RMR_LOG_LEVEL", "warning"),
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                    timeout_keep_alive=int(os.environ.get("RMR_KEEPALIVE", "90")))
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

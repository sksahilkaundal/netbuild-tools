# -*- coding: utf-8 -*-
"""
Remote Router by Netbuild - Revit MCP Router by Netbuild, reachable from Claude on the web.
(c) 2026 SKAEC.COM. All rights reserved. Proprietary - see LICENSE.txt; product info in remote_about.py.

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
    py -3.14 revit_mcp_remote.py --about            product info, requirements, licence
    py -3.14 revit_mcp_remote.py --version

Privacy hardening (useful on a managed / Work PC):
    --no-exec       hide the arbitrary-code tools (execute_revit_code, revit_run_on_documents)
                    so proprietary code is never sent over the connector
    --no-log        no request/access logging from the remote layer (the connector URL is
                    still printed; the router / pyRevit keep their own logging)
    --state-dir D   keep the passphrase/token store in D (e.g. your user profile only)
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
import tempfile
import threading
import time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import oauth_gate  # noqa: E402
import remote_about  # noqa: E402

VERSION = remote_about.VERSION
DEFAULT_PORT = 8765

# Tools that run an arbitrary code string inside Revit. --no-exec hides these from the
# remote connector so your proprietary logic is never shipped over the wire as a payload;
# the structured Revit tools (list/select sessions, documents, status, extension tools)
# stay available.
EXEC_TOOLS = ("execute_revit_code", "revit_run_on_documents")
ROUTER_DIR_CANDIDATES = (
    os.path.join(os.path.dirname(HERE), "RevitMcpRouter"),             # Netbuild\scripts\RevitMcpRemote
    os.path.join(os.path.dirname(HERE), "scripts", "RevitMcpRouter"),  # repo root layout
    r"C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter",
)


def _safe(text, stream):
    """text the stream can print (a console without the (c) sign gets '?')."""
    enc = getattr(stream, "encoding", None) or "utf-8"
    return text.encode(enc, "replace").decode(enc)


def _log(msg):
    sys.stderr.write(_safe("[revit_mcp_remote] %s\n" % msg, sys.stderr))
    sys.stderr.flush()


def _envflag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


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


def start_tunnel(kind, port, exe, name=None, public_url=None, mcp_path="/mcp", label=None):
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
        tag = ("  (%s)" % label) if label else ""
        _log("\n%s\n  Connector URL for Claude:  %s%s%s\n  Claude > Settings > Connectors > Add custom connector, paste it,\n"
             "  then Connect and enter your passphrase.\n%s" % (bar, url, mcp_path, tag, bar))

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


def slot_hosts(public_url, n):
    """Expand a {n} template into n hostnames. 'https://revit{n}.example.com', 3 ->
    ['revit1.example.com', 'revit2.example.com', 'revit3.example.com']. For n == 1 a
    template without {n} is allowed and used as-is."""
    tmpl = (public_url or "").strip()
    if n > 1 and "{n}" not in tmpl:
        return None
    hosts = []
    for k in range(1, n + 1):
        url = tmpl.replace("{n}", str(k))
        host = urlparse(url if "://" in url else "https://" + url).hostname
        if not host:
            return None
        hosts.append(host)
    return hosts


def write_ingress_config(tunnel_name, hosts, base_port):
    """A cloudflared ingress config mapping each hostname to a local slot port, so one named
    tunnel fronts every slot. Returns the config file path (caller removes it)."""
    lines = ["tunnel: %s" % tunnel_name, "ingress:"]
    for i, host in enumerate(hosts):
        lines.append("  - hostname: %s" % host)
        lines.append("    service: http://127.0.0.1:%d" % (base_port + i))
    lines.append("  - service: http_status:404")
    fd, path = tempfile.mkstemp(prefix="rmr_ingress_", suffix=".yml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def route_dns(exe, tunnel_name, hosts):
    """Point each hostname's DNS at the tunnel (idempotent: 'already exists' is fine)."""
    for host in hosts:
        try:
            r = subprocess.run([exe, "tunnel", "route", "dns", tunnel_name, host],
                               capture_output=True, text=True, timeout=30)
            out = (r.stdout + r.stderr).strip().splitlines()
            msg = out[-1] if out else ""
            if r.returncode == 0:
                _log("DNS route ready: %s" % host)
            elif "already exists" in msg.lower() or "record with that host" in msg.lower():
                _log("DNS route already present: %s" % host)
            else:
                _log("DNS route for %s may need manual setup: %s" % (host, msg))
        except Exception as e:
            _log("DNS route for %s could not be set automatically (%s); run "
                 "'cloudflared tunnel route dns %s %s' yourself." % (host, e, tunnel_name, host))


def start_named_tunnel_multi(exe, tunnel_name, config_path, hosts, mcp_path="/mcp"):
    """One `cloudflared tunnel run` using the ingress config, fronting every slot."""
    proto = os.environ.get("RMR_TUNNEL_PROTOCOL", "quic").strip()
    tune = ["--proxy-keepalive-connections", os.environ.get("RMR_TUNNEL_KEEPALIVE", "8"),
            "--proxy-keepalive-timeout", os.environ.get("RMR_TUNNEL_KEEPALIVE_TIMEOUT", "90s")]
    flags = ["--no-autoupdate"] + (["--protocol", proto] if proto and proto != "auto" else [])
    cmd = [exe, "tunnel", "--config", config_path] + flags + ["run"] + tune + [tunnel_name]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")

    def pump():
        for line in proc.stdout:
            if os.environ.get("RMR_TUNNEL_VERBOSE") or "ERR" in line:
                _log("cloudflared: " + line.rstrip())
        _log("cloudflared exited (code %s) - Claude can no longer reach this PC." % proc.poll())

    threading.Thread(target=pump, daemon=True).start()
    bar = "=" * 72
    for i, host in enumerate(hosts):
        _log("\n%s\n  Connector URL for Claude (Revit slot %d of %d):  https://%s%s\n"
             "  Claude > Settings > Connectors > Add custom connector, paste it,\n"
             "  then Connect and enter your passphrase.\n%s"
             % (bar, i + 1, len(hosts), host, mcp_path, bar))
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


def run_multi(a, router_dir, n):
    """Run n independent single-instance servers (ports a.port .. a.port+n-1), each its own OS
    process so each keeps its OWN selected Revit, and front each with its own tunnel/URL. They
    share the one auth store (same passphrase), so you sign in the same way on every slot."""
    store = oauth_gate.Store()
    if not store.configured:
        _log("FATAL: no passphrase/token yet - run once with --setup.")
        return 2

    exe = None
    named_hosts = None
    named_config = None
    if a.tunnel in ("quick", "named"):
        exe = find_cloudflared(a.cloudflared)
        if not exe:
            _log("FATAL: cloudflared not found. Install it (winget install --id Cloudflare.cloudflared) "
                 "or drop cloudflared.exe next to this script.")
            return 2
    if a.tunnel == "named":
        if not a.tunnel_name:
            _log("FATAL: --tunnel named needs --tunnel-name (the cloudflared tunnel you created).")
            return 2
        named_hosts = slot_hosts(a.public_url, n)
        if not named_hosts:
            _log("FATAL: --tunnel named with --instances %d needs --public-url with a {n} placeholder, "
                 'e.g. --public-url "https://revit{n}.yourdomain.com" (one hostname per slot).' % n)
            return 2

    workers, tunnels = [], []

    def spawn_worker(port):
        cmd = [sys.executable, os.path.abspath(__file__), "--instances", "1", "--tunnel", "none",
               "--port", str(port), "--bridge-module", a.bridge_module, "--deny-tools", a.deny_tools]
        if router_dir:
            cmd += ["--router-dir", router_dir]
        if a.no_exec:
            cmd += ["--no-exec"]
        if a.no_log:
            cmd += ["--no-log"]
        return subprocess.Popen(cmd)   # inherits env incl. shared RMR_STATE_DIR

    try:
        for k in range(n):
            port = a.port + k
            workers.append(spawn_worker(port))
            if a.tunnel == "quick":
                tunnels.append(start_tunnel("quick", port, exe, label="Revit slot %d of %d" % (k + 1, n)))
        if a.tunnel == "named":
            route_dns(exe, a.tunnel_name, named_hosts)
            named_config = write_ingress_config(a.tunnel_name, named_hosts, a.port)
            tunnels.append(start_named_tunnel_multi(exe, a.tunnel_name, named_config, named_hosts))
        _log("%s - %d independent slots on ports %d-%d. Each connector URL above "
             "is a separate Revit selection; set each with revit_select_session in its own chat."
             % (remote_about.title(), n, a.port, a.port + n - 1))
        if a.tunnel == "none":
            for k in range(n):
                _log("  slot %d: http://127.0.0.1:%d/mcp (bring your own tunnel)" % (k + 1, a.port + k))
        # Wait on the workers; if one dies, stop.
        while True:
            dead = [w for w in workers if w.poll() is not None]
            if dead:
                _log("a slot server exited (code %s) - shutting the rest down." % dead[0].poll())
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        for p in tunnels + workers:
            if p.poll() is None:
                p.terminate()
        if named_config:
            with contextlib.suppress(OSError):
                os.remove(named_config)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=(
        "%s %s -- Revit MCP Router by Netbuild served to Claude on the web as a remote MCP connector. %s"
        % (remote_about.PRODUCT, VERSION, remote_about.COPYRIGHT)),
        epilog="%s  |  %s (--about)" % (remote_about.WEBSITE, remote_about.LICENSE_NAME))
    ap.add_argument("--version", action="version", version="%s %s" % (remote_about.PRODUCT, VERSION))
    ap.add_argument("--about", action="store_true", help="product info, requirements and licence, then exit")
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
    ap.add_argument("--no-exec", action="store_true",
                    default=_envflag("RMR_NO_EXEC"),
                    help="hide arbitrary-code tools (%s) so proprietary code is never sent "
                         "over the connector" % ", ".join(EXEC_TOOLS))
    ap.add_argument("--no-log", action="store_true",
                    default=_envflag("RMR_NO_LOG"),
                    help="no request/access logging from the remote layer (URL is still printed)")
    ap.add_argument("--state-dir", default=os.environ.get("RMR_STATE_DIR"),
                    help="folder for the passphrase/token store (default %%LOCALAPPDATA%%\\RevitMcpRemote)")
    ap.add_argument("--instances", type=int, default=int(os.environ.get("RMR_INSTANCES", "1")),
                    help="run N (1-10) independent servers, each its own connector URL and its own "
                         "selected Revit, so N Claude chats can each drive a different Revit at once")
    a = ap.parse_args(argv)
    if a.about:
        print(_safe(remote_about.about_text(), sys.stdout))
        return 0

    # --state-dir must be in place before the Store reads/writes the passphrase file.
    if a.state_dir:
        os.environ["RMR_STATE_DIR"] = a.state_dir

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

    n = max(1, min(10, a.instances))
    if n > 1 and not (a.setup or a.rotate_token or a.revoke_all or a.check):
        return run_multi(a, router_dir, n)

    bridge = load_bridge(router_dir, a.bridge_module)
    deny = [t.strip() for t in a.deny_tools.split(",") if t.strip()]
    if a.no_exec:
        deny = list(dict.fromkeys(deny + list(EXEC_TOOLS)))
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
    _log("%s on http://127.0.0.1:%d (%d tools, router: %s)  %s"
         % (remote_about.title(), a.port, len(mcp._tool_manager._tools), router_dir or a.bridge_module,
            remote_about.COPYRIGHT))
    try:
        # timeout_keep_alive holds the edge<->origin connection open between tool calls so a
        # burst of calls in one chat reuses it instead of re-handshaking each time.
        # --no-log silences uvicorn's access/error logging (request lines can carry the path
        # and query), leaving the startup banner / connector URL (printed via _log) intact.
        log_level = "critical" if a.no_log else os.environ.get("RMR_LOG_LEVEL", "warning")
        uvicorn.run(build_app(mcp, store), host="127.0.0.1", port=a.port,
                    log_level=log_level, access_log=not a.no_log,
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                    timeout_keep_alive=int(os.environ.get("RMR_KEEPALIVE", "90")))
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

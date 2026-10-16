# -*- coding: utf-8 -*-
"""
Multi-Revit-session router for the pyRevit MCP bridge (main.py).

Why this exists
---------------
pyRevit's Routes engine gives EVERY running Revit instance its own port:
the first Revit to load pyRevit binds 48884, the next one 48885, and so on
(see pyrevitlib/pyrevit/routes/server/serverinfo.py). The bridge used to
hard-code 48884, so with two Revits open (say 2025 + 2026, or two models) the
MCP tools could only ever reach the first one, and a Revit restart that landed
on a different port looked like a dead connection.

This module resolves, on every call, WHICH Revit the bridge should talk to:

  * discovers live Routes servers (pickle registry + parallel port probe),
  * routes by an explicit target ("doc:B002", "port:48885", "version:2026",
    "pid:1234") or automatically when only one Revit is up,
  * is sticky: once routed it keeps that Revit until it dies, then follows
    the same document to wherever it re-appears (auto-reconnect),
  * re-reads WHICH Revit process owns the routed port (pid / version) from
    the live registry on every re-check, so a new Revit that takes over the
    port of one that closed is never mistaken for it (a pid: or version:
    target then refuses instead of following the newcomer),
  * refuses to guess when several Revits are up and nothing selects one
    (so a bulk edit never lands on the wrong model),
  * writes its state to %LOCALAPPDATA%\\RevitStatus\\router\\<pid>.json so the
    "Revit Status" tray app can show session -> Revit mapping.

Target sources, highest priority first:
  1. revit_select_session(...) MCP tool  (this Claude session only, in memory)
  2. env REVIT_MCP_TARGET                (set per project in ~/.claude.json
                                          "mcpServers": {"revit": {"env": {...}}})
  3. "auto"

Target grammar (case-insensitive):
  auto | port:48885 | 48885 | pid:31204 | version:2026 | 2026 | doc:<substring>
  | off (= disconnect / none: every Revit tool refuses until a new target is set)
  Anything else is treated as a document-title substring.

Stdlib + httpx only (no psutil dependency in the bridge venv).
"""
from __future__ import annotations

import atexit
import copyreg
import ctypes
import glob
import json
import os
import pickle
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import httpx

# ----------------------------------------------------------------------------
# Configuration (env overridable)
# ----------------------------------------------------------------------------
HOST = os.environ.get("REVIT_MCP_HOST", "127.0.0.1")
BASE_PORT = int(os.environ.get("REVIT_MCP_BASE_PORT", "48884"))
# Always probe BASE_PORT .. BASE_PORT+SCAN_PORTS-1 even if the registry is
# empty/stale, plus every port the pyRevit registry lists for a live Revit.
SCAN_PORTS = int(os.environ.get("REVIT_MCP_SCAN_PORTS", "4"))
# Bitdefender drops SYNs to closed loopback ports instead of refusing them,
# so a closed port costs the full timeout -> probes run in parallel.
PROBE_TIMEOUT = float(os.environ.get("REVIT_MCP_PROBE_TIMEOUT", "1.0"))
DISCOVER_TTL = 2.0      # seconds a discovery result is reused
VERIFY_TTL = 3.0        # seconds before the current route is re-pinged
ROUTE_ROOT = "/revit_mcp"
STATUS_PATH = ROUTE_ROOT + "/status/"

STATE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RevitStatus", "router")
PYREVIT_APPDATA = os.environ.get(
    "REVIT_MCP_REGISTRY_DIR", os.path.join(os.environ.get("APPDATA", ""), "pyRevit"))

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


OFF_ALIASES = ("off", "disconnect", "disconnected", "unbind", "none")
OFF_MESSAGE = ("This session is disconnected from Revit (revit_select_session 'off'): every Revit tool "
               "is refused until a Revit is selected again with revit_select_session auto | port:<n> "
               "| doc:<title> | version:<YYYY> | pid:<pid>.")


class RouterError(RuntimeError):
    """Raised when no Revit session satisfies the current target."""


# ----------------------------------------------------------------------------
# pyRevit registry: %APPDATA%\pyRevit\<ver>\pyRevit_<ver>_<pid>_serverinfo.pickle
# (Python-2 protocol-0 pickles of pyrevit.routes.server.serverinfo.RoutesServerInfo)
# ----------------------------------------------------------------------------
class _ServerInfoStub(object):
    pass


class _ServerInfoUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if name == "RoutesServerInfo":
            return _ServerInfoStub
        if name == "_reconstructor" and module in ("copy_reg", "copyreg"):
            return copyreg._reconstructor
        if name == "object" and module in ("__builtin__", "builtins"):
            return object
        raise pickle.UnpicklingError("refusing to load %s.%s" % (module, name))


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # optional
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def read_registry() -> List[Dict]:
    """Return [{port, pid, version, host}] for every LIVE Revit that pyRevit registered.
    Oldest registration first, so {r["port"]: r for r in read_registry()} keeps the newest
    owner of a port (a crashed Revit's pickle whose pid was reused by another process)."""
    out = []
    paths = glob.glob(os.path.join(PYREVIT_APPDATA, "*", "pyRevit_*_serverinfo.pickle"))
    for path in sorted(paths, key=_mtime):
        try:
            with open(path, "rb") as fh:
                info = _ServerInfoUnpickler(fh, encoding="latin-1").load()
            d = getattr(info, "__dict__", {})
            pid = int(d.get("process_id", 0))
            port = int(d.get("server_port", 0))
            if not pid or not port or not _pid_alive(pid):
                continue
            out.append({
                "port": port,
                "pid": pid,
                "version": str(d.get("version", "")),
                "host": str(d.get("host", "")),
            })
        except Exception:
            continue
    return out


# ----------------------------------------------------------------------------
# Probing
# ----------------------------------------------------------------------------
def base_url_for(port: int) -> str:
    return "http://%s:%d" % (HOST, port)


def probe(port: int, timeout: float = PROBE_TIMEOUT) -> Dict:
    """Ping /revit_mcp/status/ on one port. Never raises."""
    info = {
        "port": port,
        "base_url": base_url_for(port),
        "alive": False,
        "listener": "down",          # down | ok | no-mcp-routes | paused | error
        "revit_available": False,
        "document_title": None,
        "error": None,
    }
    try:
        r = httpx.get(base_url_for(port) + STATUS_PATH, timeout=timeout)
    except httpx.ConnectError:
        return info
    except httpx.TimeoutException:
        info["error"] = "timeout"
        return info
    except Exception as e:
        info["error"] = str(e) or type(e).__name__
        return info

    info["alive"] = True
    if r.status_code == 404:
        info["listener"] = "no-mcp-routes"
        info["error"] = "Revit is running but the MCP connector is not loaded in it"
        return info
    try:
        data = r.json()
    except Exception:
        info["listener"] = "error"
        info["error"] = "non-JSON status (%s)" % r.status_code
        return info
    if isinstance(data, dict) and data.get("status") == "paused":
        info["listener"] = "paused"
        info["error"] = data.get("error") or "MCP paused in this Revit"
        return info
    info["listener"] = "ok"
    info["revit_available"] = bool(data.get("revit_available", False))
    info["document_title"] = data.get("document_title")
    if not info["revit_available"]:
        info["error"] = data.get("error") or "no active document"
    return info


# ----------------------------------------------------------------------------
# Target parsing
# ----------------------------------------------------------------------------
def parse_target(spec: Optional[str]) -> Dict:
    """'auto' | 'off' | port:N | N | pid:N | version:YYYY | YYYY | doc:<substr> | <substr>"""
    s = (spec or "").strip()
    if not s or s.lower() in ("auto", "any", "default"):
        return {"kind": "auto"}
    if s.lower() in OFF_ALIASES:
        return {"kind": "off"}
    m = re.match(r"^(port|pid|version|revit|doc|document|title)\s*[:=]\s*(.+)$", s, re.I)
    if m:
        kind, val = m.group(1).lower(), m.group(2).strip()
        if kind in ("revit",):
            kind = "version"
        if kind in ("document", "title"):
            kind = "doc"
        if kind in ("port", "pid"):
            if not val.isdigit():
                raise RouterError("target %s needs a number, got %r" % (kind, val))
            return {"kind": kind, "value": int(val)}
        if kind == "version":
            return {"kind": "version", "value": val}
        return {"kind": "doc", "value": val}
    if re.fullmatch(r"20\d\d", s):
        return {"kind": "version", "value": s}
    if s.isdigit() and int(s) >= 1024:
        return {"kind": "port", "value": int(s)}
    return {"kind": "doc", "value": s}


def format_target(t: Dict) -> str:
    return t["kind"] if "value" not in t else "%s:%s" % (t["kind"], t["value"])


# ----------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------
def _stamp(probed: Dict, registry: Dict[int, Dict]) -> Dict:
    """Put the identity (pid / version / host) of the Revit that NOW owns the probed port on the
    probe result, from a fresh read_registry(); None when the port has no live registration."""
    reg = registry.get(probed["port"], {})
    for k in ("pid", "version", "host"):
        probed[k] = reg.get(k)
    return probed


def _route_key(s: Dict):
    return s["port"], s.get("pid"), s.get("document_title")


class RevitRouter(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._target = parse_target(os.environ.get("REVIT_MCP_TARGET"))
        self._target_source = "env" if self._target["kind"] != "auto" else "default"
        self._current: Optional[Dict] = None
        self._verified_at = 0.0
        self._sessions: List[Dict] = []
        self._discovered_at = 0.0
        self._last_title: Optional[str] = None   # follows a document across restarts
        self._state_file = os.path.join(STATE_DIR, "%d.json" % os.getpid())
        atexit.register(self._remove_state)

    # -- discovery ----------------------------------------------------------
    def discover(self, force: bool = False) -> List[Dict]:
        with self._lock:
            if not force and time.time() - self._discovered_at < DISCOVER_TTL:
                return list(self._sessions)
            registry = {r["port"]: r for r in read_registry()}
            ports = sorted(set(range(BASE_PORT, BASE_PORT + SCAN_PORTS)) | set(registry))
            with ThreadPoolExecutor(max_workers=max(1, len(ports))) as ex:
                probed = list(ex.map(probe, ports))
            sessions = [_stamp(p, registry) for p in probed if p["alive"]]
            self._sessions = sessions
            self._discovered_at = time.time()
            return list(sessions)

    # -- target ---------------------------------------------------------------
    @property
    def target(self) -> Dict:
        return dict(self._target)

    def set_target(self, spec: Optional[str]) -> Dict:
        """Change the target and route immediately. Raises RouterError if nothing matches.
        'off' unbinds: nothing is routed and every Revit call refuses until the next set_target."""
        with self._lock:
            new = parse_target(spec)
            self._target = new
            self._target_source = "tool"
            self._current = None
            self._verified_at = 0.0
            if new["kind"] == "off":
                self._write_state()
                return {"target": "off", "session": None, "disconnected": True, "note": OFF_MESSAGE}
            try:
                picked = self.resolve()
            except RouterError:
                self._write_state()      # the tray app must not keep showing the previous route
                raise
            return {"target": format_target(new), "session": self._public(picked)}

    def invalidate(self):
        """Force a re-probe/re-scan on the next resolve() (call after a ConnectError)."""
        with self._lock:
            self._verified_at = 0.0
            self._discovered_at = 0.0

    # -- resolution -----------------------------------------------------------
    def _matches(self, s: Dict) -> bool:
        t = self._target
        k = t["kind"]
        if s["listener"] != "ok" or k == "off":
            return False
        if k == "auto":
            return True
        if k == "port":
            return s["port"] == t["value"]
        if k == "pid":
            return s.get("pid") == t["value"]
        if k == "version":
            return str(s.get("version") or "") == str(t["value"])
        if k == "doc":
            title = s.get("document_title") or ""
            return t["value"].lower() in title.lower()
        return False

    def _select(self, sessions: List[Dict]) -> Dict:
        t = self._target
        candidates = [s for s in sessions if self._matches(s)]
        if not candidates:
            raise RouterError(self._no_match_message(sessions))
        if len(candidates) == 1:
            return candidates[0]
        # Several match: follow the document we were on, else exact title, else
        # the ones with a document open; refuse to guess in auto mode.
        if self._last_title:
            same = [s for s in candidates if s.get("document_title") == self._last_title]
            if len(same) == 1:
                return same[0]
        if t["kind"] == "doc":
            exact = [s for s in candidates
                     if (s.get("document_title") or "").lower() == t["value"].lower()]
            if len(exact) == 1:
                return exact[0]
        with_doc = [s for s in candidates if s.get("revit_available")]
        if len(with_doc) == 1:
            return with_doc[0]
        raise RouterError(
            "%d Revit sessions match target '%s' - call revit_select_session with "
            "port:<n> or doc:<title> to pick one.\n%s"
            % (len(candidates), format_target(t), self._table(candidates)))

    def resolve(self) -> Dict:
        """Return the session dict to use now (has 'base_url'). Raises RouterError."""
        with self._lock:
            if self._target["kind"] == "off":
                raise RouterError(OFF_MESSAGE)
            now = time.time()
            cur = self._current
            if cur is not None:
                # within the TTL only the routed Revit's pid is checked (one OpenProcess, no HTTP)
                if now - self._verified_at < VERIFY_TTL and (cur.get("pid") is None or _pid_alive(cur["pid"])):
                    return cur
                fresh = probe(cur["port"])
                if fresh["alive"]:
                    # identity from the LIVE registry, never copied from cur: a new Revit can bind
                    # the port of one that closed (2026-10-02: pid:19540 silently followed pid 28568)
                    _stamp(fresh, {r["port"]: r for r in read_registry()})
                    same_revit = cur.get("pid") is None or fresh.get("pid") == cur.get("pid")
                    if same_revit and self._matches(fresh):
                        self._current = fresh
                        self._verified_at = now
                        self._note(fresh)
                        if _route_key(fresh) != _route_key(cur):
                            self._write_state()
                        return fresh
                # dead, replaced by another Revit process, or no longer matching -> rescan
            sessions = self.discover(force=True)
            try:
                picked = self._select(sessions)
            except RouterError:
                if cur is not None:      # nothing is routed now: never keep reporting the old Revit
                    self._current = None
                    self._write_state()
                raise
            changed = cur is None or _route_key(cur) != _route_key(picked)
            self._current = picked
            self._verified_at = now
            self._note(picked)
            if changed:
                self._write_state()
            return picked

    def base_url(self) -> str:
        return self.resolve()["base_url"]

    def _note(self, s: Dict):
        if s.get("document_title"):
            self._last_title = s["document_title"]

    # -- reporting ------------------------------------------------------------
    @staticmethod
    def _public(s: Optional[Dict]) -> Optional[Dict]:
        if not s:
            return None
        return {
            "port": s["port"],
            "revit_version": s.get("version"),
            "revit_pid": s.get("pid"),
            "document_title": s.get("document_title"),
            "revit_available": s.get("revit_available"),
            "listener": s.get("listener"),
        }

    @staticmethod
    def _table(sessions: List[Dict]) -> str:
        if not sessions:
            return "  (no Revit MCP connector answered on ports %d-%d)" % (
                BASE_PORT, BASE_PORT + SCAN_PORTS - 1)
        lines = []
        for s in sessions:
            doc = s.get("document_title") or "<no document>"
            lines.append("  port %d: Revit %s pid %s - %s [%s]" % (
                s["port"], s.get("version") or "?", s.get("pid") or "?", doc, s["listener"]))
        return "\n".join(lines)

    def _no_match_message(self, sessions: List[Dict]) -> str:
        t = self._target
        if not sessions:
            return ("Cannot reach Revit - no Revit MCP connector on ports %d-%d. "
                    "Is Revit running with the Revit MCP connector loaded (ribbon fully initialised)?"
                    % (BASE_PORT, BASE_PORT + SCAN_PORTS - 1))
        if t["kind"] == "auto":
            return ("No usable Revit session (target auto).\n" + self._table(sessions))
        if t["kind"] == "doc":
            return ("No Revit session has a document matching '%s' as its ACTIVE document. "
                    "Switch to it in Revit, or call revit_select_session with another target.\n%s"
                    % (t["value"], self._table(sessions)))
        if t["kind"] == "pid":
            return ("Revit pid %s is no longer running the Revit MCP connector. A pid: target never follows "
                    "another Revit process (even one on the same port) - call revit_select_session to pick "
                    "one of these.\n%s" % (t["value"], self._table(sessions)))
        return ("No live Revit session matches target '%s'.\n%s"
                % (format_target(t), self._table(sessions)))

    def describe(self, rescan: bool = True) -> Dict:
        with self._lock:
            started = time.time()
            if rescan and self._current is not None:
                # re-verify the route now so 'current' never names a Revit that has gone
                self._verified_at = 0.0
                try:
                    self.resolve()
                except RouterError:
                    pass                     # resolve() cleared the route
            # one scan per call: skip it if resolve() just rescanned
            sessions = self.discover(force=rescan and self._discovered_at < started)
            cur = self._current
            out = {
                "target": format_target(self._target),
                "target_source": self._target_source,
                "current": self._public(cur),
                "sessions": [dict(self._public(s), selected=bool(cur) and _route_key(s)[:2] == _route_key(cur)[:2])
                             for s in sessions],
                "hint": ("revit_select_session accepts: auto | port:48885 | doc:<title substring> "
                         "| version:2026 | pid:<revit pid> | off (disconnect)"),
            }
            if self._target["kind"] == "off":
                out["note"] = OFF_MESSAGE
            return out

    # -- state file for the Revit Status tray app ------------------------------
    def _write_state(self):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            cur = self._current or {}
            payload = {
                "bridge_pid": os.getpid(),
                "target": format_target(self._target),
                "target_source": self._target_source,
                "routed": bool(cur),
                "port": cur.get("port"),
                "revit_pid": cur.get("pid"),
                "revit_version": cur.get("version"),
                "document_title": cur.get("document_title"),
                "updated": time.time(),
            }
            tmp = self._state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self._state_file)
        except Exception:
            pass

    def _remove_state(self):
        try:
            os.remove(self._state_file)
        except Exception:
            pass


router = RevitRouter()


# ----------------------------------------------------------------------------
# CLI: python revit_mcp_router.py [target]   -> prints discovery + routing
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    spec = sys.argv[1] if len(sys.argv) > 1 else None
    t0 = time.time()
    if spec:
        try:
            print(json.dumps(router.set_target(spec), indent=2))
        except RouterError as e:
            print("RouterError:", e)
    else:
        try:
            router.resolve()
        except RouterError as e:
            print("RouterError:", e)
    print(json.dumps(router.describe(rescan=False), indent=2))
    print("(%.2f s)" % (time.time() - t0))

# -*- coding: utf-8 -*-
"""
Revit Status by Netbuild
========================
Small always-available window + system-tray icon that shows, live:

  * every running Revit (pyRevit Routes listener on 48884, 48885, ...): version,
    pid, the document it has open with an "active since" timer, and which Code
    sessions are routed to it;
  * every Claude Code session on this machine, whether it has a live Bridge
    process to Revit, which Revit/port + document the Revit MCP Router routed it
    to (%LOCALAPPDATA%/RevitStatus/router/<bridge pid>.json), when that bridge
    started and how long it has been up;
  * click a session row to bring that session to the front in the Claude app
    (claude://claude.ai/epitaxy/<hostSessionId>).

Tray behaviour:
  * the tray icon colour is the overall state: green = Revit healthy and at least
    one session bridged, amber = Revit reachable but no document / no bridge,
    red = Revit listener not reachable. Tooltip = document + connected count.
  * closing or minimising the window hides it to the tray; left-click the icon
    (or launch the app again) to bring it back; right-click for Refresh / Exit.

How the mapping works (no config needed):
  ~/.claude/sessions/<pid>.json  -> one file per running Claude Code process:
                                    sessionId, hostSessionId, name, cwd, status
  bridge process                 -> python.exe / uv.exe whose command line contains
                                    "mcp-server-for-revit-python" and whose PARENT
                                    pid is one of those session pids.

Command-line switches:
  --tray       start hidden in the system tray (the Startup shortcut uses this)
  --selftest   write selftest_result.txt beside the exe with one collected snapshot
  --dump       print one snapshot as JSON to stdout and exit
  (F5 / "Refresh now" wakes both pollers immediately, e.g. after switching the active document)
"""
import copyreg
import datetime as _dt
import glob
import hashlib
import hmac
import json
import os
import pickle
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

import psutil


def _rt():
    """Shared Revit Tools theme (design/revittools_theme.py; bundled into the frozen app)."""
    try:
        import revittools_theme as rt
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "design"))
        import revittools_theme as rt
    return rt

# ----------------------------------------------------------------- config ---
HOST = "127.0.0.1"
BASE_PORT = 48884       # pyRevit Routes: first Revit = 48884, next = 48885, ...
SCAN_PORTS = 6          # always probe BASE_PORT .. BASE_PORT+SCAN_PORTS-1 (+ registry ports)
STATUS_PATH = "/revit_mcp/status/"
STATUS_URL = "http://%s:%d%s" % (HOST, BASE_PORT, STATUS_PATH)
SESSIONS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "sessions")
# pyRevit registry: %APPDATA%\pyRevit\<ver>\pyRevit_<ver>_<pid>_serverinfo.pickle
PYREVIT_APPDATA = os.path.join(os.environ.get("APPDATA", ""), "pyRevit")
# per-bridge routing state written by the Revit MCP Router (<bridge pid>.json)
ROUTER_STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RevitStatus", "router")
BRIDGE_MARKER = "mcp-server-for-revit-python"
LINK_FMT = "claude://claude.ai/epitaxy/{host}"
POLL_PROC_S = 2.0      # process scan interval
POLL_HTTP_S = 3.0      # Revit listener poll interval
HTTP_TIMEOUT_S = 1.5   # per port; probes run in parallel (a closed port costs the full timeout)
APP_TITLE = "Revit Status"        # part of the key derivation (_k2) and license.json - never change
VERSION = "1.2.4"
APP_DISPLAY = "Revit Status by Netbuild"           # product name shown to the customer
WINDOW_TITLE = "%s v%s" % (APP_DISPLAY, VERSION)  # main window (also found by title by a second launch)
PUBLISHER = "SKAEC.COM"
WEBSITE = "https://skaec.com"
# This module is compiled to a native .pyd for release (build_revitstatus_release.py);
# RevitStatus.pyw is only a 10-line stub that calls main().
MUTEX_NAME = "Local\\RevitStatusApp.SingleInstance"
SHOW_EVENT_NAME = "Local\\RevitStatusApp.Show"

# ------------------------------------------------------------- licensing ---
COPYRIGHT = "© 2026 SKAEC.COM. All rights reserved."
DEVELOPER_NAME = "Sahil Kaundal (Netbuild2026)"
DEVELOPER_EMAIL = "info@skaec.com"
LICENSE_FILE = "license.json"
_PW_SALT = "REMOVED"
# The key-signing secret is never stored as one literal: rebuilt at run time from
# two arrays so a hex-editor search on the compiled module finds nothing.
_K1 = b""  # removed (rotated; see netbuild_secrets)
# _K2 is DERIVED at run time (never stored), so the two halves are not adjacent constants
# in the compiled module. A compiled copy of this module imported from a foreign
# interpreter (i.e. not one of our own frozen executables) yields a decoy secret, so
# keys/signatures it produces are invalid.
_ALLOWED_EXES = ("Revit Status.exe", "Revit Status KeyGen.exe", "RevitMcpBridge.exe", "Revit MCP Router Setup.exe")


def _k2(n=None):
    seed = ("%s|%s|k2" % (_PW_SALT, APP_TITLE)).encode("utf-8")
    out, i = b"", 0
    while len(out) < (n or len(_K1)):
        out += hashlib.sha256(seed + str(i).encode("ascii")).digest()
        i += 1
    return out[:n or len(_K1)]


def _trusted_host():
    compiled = "__compiled__" in globals()
    if not compiled:
        return True                       # plain source: developer machine
    frozen = getattr(sys, "frozen", False)
    exe = os.path.basename(sys.executable) if frozen else ""
    return bool(frozen) and exe in _ALLOWED_EXES


def _key_secret():
    k2 = _k2()
    real = bytes(a ^ b for a, b in zip(_K1, k2))
    if _trusted_host():
        return real
    return hashlib.sha256(real + b"decoy" + os.urandom(8)).digest()
# Online allow-list: a Google Sheet published to the web as CSV with the columns
#   Key, Type, Status, Machine_ID, Note
# Key = password hash (RevitStatus_KeyGen.py --hash) or machine key (--key),
# Type = password | key, Status = active | revoked. Only rows with Status=active
# are accepted. The sheet is fetched at every start and cached; if it cannot be
# reached the cached copy stays valid for LICENSE_CACHE_GRACE_DAYS.
# ONE sheet for every Netbuild app ("Netbuild Licensing", first tab published as CSV) holds the
# rows of all products; keys/hashes differ per product so rows never clash.
LICENSE_SHEET_URL = ("https://docs.google.com/spreadsheets/d/e/"
                     "REMOVED"
                     "/pub?gid=1189617866&single=true&output=csv")
LICENSE_SHEET_TIMEOUT_S = 6.0
LICENSE_CACHE_GRACE_DAYS = 7
LICENSE_CACHE_FILE = "license_cache.json"
# Built-in fallback, used ONLY while the sheet has never been fetched on this PC
# (e.g. first run with no network). Add with RevitStatus_KeyGen.py --hash.
ALLOWED_PASSWORD_HASHES = {
    "REMOVED",
}


# --------------------------------------------------------------- helpers ---
def _fmt_clock(ts):
    if not ts:
        return "-"
    return _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _fmt_elapsed(ts, now=None):
    if not ts:
        return "-"
    secs = int(max(0, (now or time.time()) - ts))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s)


def _short_folder(path):
    if not path:
        return ""
    return os.path.basename(path.rstrip("\\/")) or path


# ----------------------------------------------------- pyRevit registry ---
class _ServerInfoStub(object):
    pass


class _ServerInfoUnpickler(pickle.Unpickler):
    """Loads pyRevit's Python-2 RoutesServerInfo pickles without executing anything else."""

    def find_class(self, module, name):
        if name == "RoutesServerInfo":
            return _ServerInfoStub
        if name == "_reconstructor" and module in ("copy_reg", "copyreg"):
            return copyreg._reconstructor
        if name == "object" and module in ("__builtin__", "builtins"):
            return object
        raise pickle.UnpicklingError("refusing to load %s.%s" % (module, name))


def read_registry():
    """{port: {pid, version}} for every LIVE Revit that pyRevit registered a Routes server for."""
    out = {}
    for path in glob.glob(os.path.join(PYREVIT_APPDATA, "*", "pyRevit_*_serverinfo.pickle")):
        try:
            with open(path, "rb") as fh:
                info = _ServerInfoUnpickler(fh, encoding="latin-1").load()
            d = getattr(info, "__dict__", {})
            pid = int(d.get("process_id", 0))
            port = int(d.get("server_port", 0))
            if not pid or not port or not psutil.pid_exists(pid):
                continue
            out[port] = {"pid": pid, "version": str(d.get("version", ""))}
        except Exception:
            continue
    return out


def read_router_state():
    """{bridge pid: state} from the Revit MCP Router's per-bridge files (dead pids skipped)."""
    out = {}
    if not os.path.isdir(ROUTER_STATE_DIR):
        return out
    for name in os.listdir(ROUTER_STATE_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(ROUTER_STATE_DIR, name), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            pid = int(data.get("bridge_pid") or 0)
        except Exception:
            continue
        if pid and psutil.pid_exists(pid):
            out[pid] = data
    return out


def probe_port(port, timeout=HTTP_TIMEOUT_S):
    """Ping /revit_mcp/status/ on one port. Never raises."""
    result = {"port": port, "reachable": False, "http": None, "payload": None, "error": None}
    body = None
    try:
        req = urllib.request.Request("http://%s:%d%s" % (HOST, port, STATUS_PATH), headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result["http"] = resp.status
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:      # 503 = listener up, no document
        result["http"] = e.code
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
    except Exception as e:
        result["error"] = str(e).split("\n")[0]
    if body is not None:
        result["reachable"] = True
        try:
            result["payload"] = json.loads(body)
        except Exception:
            result["payload"] = {"raw": body[:200]}
    payload = result["payload"] or {}
    if result["http"] == 404:
        result["listener"] = "no MCP connector"
    elif payload.get("status") == "paused":
        result["listener"] = "paused"
    elif result["reachable"]:
        result["listener"] = "ok"
    else:
        result["listener"] = "down"
    result["document_title"] = payload.get("document_title") if result["listener"] == "ok" else None
    result["revit_available"] = bool(payload.get("revit_available")) if result["reachable"] else False
    result["health"] = payload.get("health") or payload.get("status")
    result["listener_error"] = payload.get("error")
    return result


# ------------------------------------------------------------- collector ---
class Collector:
    """Background poller. Everything the UI reads lives in self.snapshot."""

    def __init__(self):
        self.lock = threading.Lock()
        self.snapshot = {
            "sessions": [],          # list of dicts, see _scan_processes
            "revit": {},             # see _poll_revit: primary listener + "instances" (one per port)
            "errors": [],
            "proc_scanned_at": None,
            "revit_polled_at": None,
        }
        self._doc_seen = {}          # port -> {"title", "since"} for the "active since" timers
        self._registry = {}          # port -> {pid, version} (last read, shared by both pollers)
        self._stop = threading.Event()
        # one wake-up event per poller so a manual refresh hits both at once
        self._kick_proc = threading.Event()
        self._kick_http = threading.Event()

    # -- public ---------------------------------------------------------
    def start(self):
        threading.Thread(target=self._proc_loop, name="proc-scan", daemon=True).start()
        threading.Thread(target=self._http_loop, name="revit-poll", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._kick_proc.set()
        self._kick_http.set()

    def refresh_now(self):
        """Wake both pollers immediately (Refresh button / F5 / tray menu), e.g.
        after switching the active document in Revit."""
        self._kick_proc.set()
        self._kick_http.set()

    def once(self):
        """One synchronous collection (used by --selftest / --dump)."""
        self._scan_processes()
        self._poll_revit()
        with self.lock:
            return json.loads(json.dumps(self.snapshot, default=str))

    # -- loops ----------------------------------------------------------
    def _proc_loop(self):
        while not self._stop.is_set():
            try:
                self._scan_processes()
            except Exception as e:  # never let the poller die
                self._push_error("process scan: %s" % e)
            self._kick_proc.wait(POLL_PROC_S)
            self._kick_proc.clear()

    def _http_loop(self):
        while not self._stop.is_set():
            try:
                self._poll_revit()
            except Exception as e:
                self._push_error("revit poll: %s" % e)
            self._kick_http.wait(POLL_HTTP_S)
            self._kick_http.clear()

    def _push_error(self, msg):
        with self.lock:
            errs = self.snapshot["errors"]
            errs.append("%s %s" % (_fmt_clock(time.time()), msg))
            del errs[:-5]

    # -- sessions + bridges --------------------------------------------
    def _read_session_files(self):
        out = {}
        if not os.path.isdir(SESSIONS_DIR):
            return out
        for name in os.listdir(SESSIONS_DIR):
            if not name.endswith(".json"):
                continue
            path = os.path.join(SESSIONS_DIR, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            pid = data.get("pid")
            if not isinstance(pid, int):
                continue
            out[pid] = data
        return out

    def _scan_processes(self):
        session_files = self._read_session_files()
        alive = {}
        for pid, data in session_files.items():
            try:
                p = psutil.Process(pid)
                if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                    continue
                alive[pid] = (data, p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # bridges: processes whose cmdline names the extension and whose parent
        # is a live session pid. The venv python.exe is a launcher that spawns
        # the real interpreter, so requiring ppid ∈ sessions picks the top one.
        bridges = {}   # session pid -> bridge info
        revit_procs = []
        # Only ask for command lines of processes that could be a bridge AND whose
        # parent is a session: reading every process's cmdline on Windows is slow.
        for proc in psutil.process_iter(["pid", "ppid", "name", "create_time"]):
            info = proc.info
            name = (info.get("name") or "").lower()
            if name == "revit.exe":
                revit_procs.append(info)
                continue
            ppid = info.get("ppid")
            if ppid not in alive or ppid in bridges:
                continue
            is_router = name.startswith("revitmcpbridge")          # Revit MCP Router bridge exe
            if not (is_router or name.startswith("python") or name.startswith("uv")):
                continue
            if not is_router:
                try:
                    cmd = proc.cmdline() or []
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                if not cmd or BRIDGE_MARKER not in " ".join(cmd).lower():
                    continue
            bridges[ppid] = {
                "pid": info["pid"],
                "create_time": info.get("create_time"),
                "launcher": "Revit MCP Router" if is_router else "bridge",
                "route": None,
            }

        # Router state files are keyed by the pid of the process that runs the
        # router - usually the real interpreter spawned by the launcher python,
        # i.e. a child (or grandchild) of the bridge pid above. Walk up from the
        # state file's pid until a live session pid is met.
        bridge_by_session = {b["pid"]: spid for spid, b in bridges.items()}
        for bpid, state in read_router_state().items():
            pid, hops = bpid, 0
            while pid and hops < 5:
                if pid in bridge_by_session:
                    bridges[bridge_by_session[pid]]["route"] = {
                        "target": state.get("target"),
                        "target_source": state.get("target_source"),
                        "port": state.get("port"),
                        "revit_pid": state.get("revit_pid"),
                        "revit_version": state.get("revit_version"),
                        "document_title": state.get("document_title"),
                        "updated": state.get("updated"),
                    }
                    break
                try:
                    pid = psutil.Process(pid).ppid()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break
                hops += 1

        sessions = []
        for pid, (data, p) in alive.items():
            try:
                proc_start = p.create_time()
            except Exception:
                proc_start = None
            started_at = data.get("startedAt")
            started_at = started_at / 1000.0 if isinstance(started_at, (int, float)) else proc_start
            b = bridges.get(pid)
            sessions.append({
                "pid": pid,
                "session_id": data.get("sessionId"),
                "host_id": data.get("hostSessionId"),
                "name": data.get("name") or data.get("sessionId") or str(pid),
                "cwd": data.get("cwd") or "",
                "status": data.get("status") or "",
                "kind": data.get("kind") or "",
                "entrypoint": data.get("entrypoint") or "",
                "started_at": started_at,
                "bridge": b,
            })
        # connected first, then newest session first
        sessions.sort(key=lambda s: (s["bridge"] is None, -(s["started_at"] or 0)))

        with self.lock:
            self.snapshot["sessions"] = sessions
            self.snapshot["proc_scanned_at"] = time.time()
            rp = sorted(revit_procs, key=lambda r: r.get("create_time") or 0)
            self.snapshot.setdefault("revit", {})["processes"] = [
                {"pid": r["pid"], "create_time": r.get("create_time")} for r in rp
            ]

    # -- Revit listener -------------------------------------------------
    def _poll_revit(self):
        """Probe every Revit listener in parallel (registry ports ∪ BASE_PORT..+SCAN_PORTS)."""
        registry = read_registry()
        self._registry = registry
        ports = sorted(set(range(BASE_PORT, BASE_PORT + SCAN_PORTS)) | set(registry))
        results = {}
        threads = []

        def _one(port):
            results[port] = probe_port(port)

        for port in ports:
            t = threading.Thread(target=_one, args=(port,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(HTTP_TIMEOUT_S + 1.0)

        now = time.time()
        instances = []
        for port in ports:
            r = results.get(port)
            if r is None:
                continue
            reg = registry.get(port) or {}
            if not r["reachable"] and not reg:
                continue                      # nothing on this port
            title = r.get("document_title")
            seen = self._doc_seen.get(port)
            if seen is None or title != seen["title"]:
                seen = {"title": title, "since": now if title else None}
                self._doc_seen[port] = seen
            create_time = None
            if reg.get("pid"):
                try:
                    create_time = psutil.Process(reg["pid"]).create_time()
                except Exception:
                    pass
            r.update({
                "pid": reg.get("pid"),
                "version": reg.get("version") or "",
                "create_time": create_time,
                "document_since": seen["since"],
            })
            instances.append(r)
        for port in list(self._doc_seen):
            if port not in results or not results[port]["reachable"]:
                self._doc_seen.pop(port, None)

        # "primary" = the first listener (backwards-compatible single-Revit fields)
        primary = instances[0] if instances else probe_port(BASE_PORT, 0.01)
        result = {k: primary.get(k) for k in ("reachable", "http", "payload", "error", "document_title",
                                               "document_since", "health", "listener_error")}
        result["instances"] = instances
        with self.lock:
            revit = self.snapshot.setdefault("revit", {})
            revit.update(result)
            self.snapshot["revit_polled_at"] = now


# ------------------------------------------------------------- tray icon ---
STATE_COLORS = {                   # design tokens tray-* (Autodesk Access / Weave fills)
    "connected": (43, 194, 117),   # green #2bc275: Revit healthy + at least one bridge
    "partial": (255, 194, 26),     # amber #ffc21a: Revit reachable but no document / no bridge
    "down": (217, 85, 41),         # red #d95529: Revit listener not reachable
}
STATE_INK = {"connected": "black", "partial": "black", "down": "white"}   # Weave ink-on-fill-*
_ICON_CACHE = {}


def _instances_by_port(snap):
    return {i["port"]: i for i in ((snap.get("revit") or {}).get("instances") or [])}


def _session_link(s, by_port):
    """(text, tag, instance) describing what a session's bridge is talking to."""
    b = s.get("bridge")
    if not b:
        return "no bridge", "nobridge", None
    route = b.get("route") or {}
    inst = by_port.get(route.get("port")) if route.get("port") else None
    router = " (Revit MCP Router)" if b.get("launcher") == "Revit MCP Router" else ""
    if inst is None:
        if route.get("port"):
            return "bridge up, Revit on port %s is gone" % route["port"], "partial", None
        if len(by_port) == 1:                      # single Revit: auto-routing will land there
            inst = next(iter(by_port.values()))
            return ("connected" + router if inst.get("document_title") else "bridge up, no document"), \
                   ("connected" if inst.get("document_title") else "partial"), inst
        if not by_port:
            return "bridge up, Revit down", "partial", None
        return "bridge up, not routed yet", "partial", None
    if inst.get("listener") != "ok":
        return "bridge up, listener %s" % inst.get("listener"), "partial", inst
    if inst.get("document_title"):
        return "connected" + router, "connected", inst
    return "bridge up, no document", "partial", inst


# ------------------------------------------------------ Revit window focus ---
def _revit_window(pid):
    """Largest visible, unowned top-level window of process `pid` (Revit's main frame), or None.
    Reads window data only (no messages are sent), so it is safe even when Revit is hung."""
    import ctypes
    import ctypes.wintypes as w
    u = ctypes.windll.user32
    u.GetWindow.restype = w.HWND
    u.GetWindow.argtypes = [w.HWND, w.UINT]
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, _l):
        if u.IsWindowVisible(h) and not u.GetWindow(h, 4):          # GW_OWNER = 4
            owner = w.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(owner))
            if owner.value == pid:
                n = u.GetWindowTextLengthW(h)
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, buf, n + 1)
                r = w.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                found.append(("Autodesk Revit" in buf.value, (r.right - r.left) * (r.bottom - r.top), h))
        return True
    u.EnumWindows(cb, 0)
    return max(found)[2] if found else None


def _window_responsive(hwnd, timeout_ms=400):
    """False when Windows flags the window as hung OR it does not answer a no-op message within timeout_ms.
    SMTO_ABORTIFHUNG returns at once for a hung window, so a stuck Revit is never waited on or poked further."""
    import ctypes
    import ctypes.wintypes as w
    u = ctypes.windll.user32
    u.IsHungAppWindow.argtypes = [w.HWND]
    if u.IsHungAppWindow(hwnd):
        return False
    u.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
    res = ctypes.c_size_t()
    return bool(u.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0002, timeout_ms, ctypes.byref(res)))   # WM_NULL, SMTO_ABORTIFHUNG


def focus_revit(pid):
    """Bring the Revit with process id `pid` to the front. Returns (ok, message).
    A hung / busy Revit is left completely alone: switching to it can make it crash."""
    import ctypes
    import ctypes.wintypes as w
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False, "No process id for this Revit."
    hwnd = _revit_window(pid)
    if not hwnd:
        return False, "No window found for Revit (PID %d)." % pid
    if not _window_responsive(hwnd):
        return False, "Revit (PID %d) is not responding - left alone so it is not disturbed." % pid
    u = ctypes.windll.user32
    u.IsIconic.argtypes = [w.HWND]
    u.ShowWindowAsync.argtypes = [w.HWND, ctypes.c_int]
    u.SetForegroundWindow.argtypes = [w.HWND]
    if u.IsIconic(hwnd):
        u.ShowWindowAsync(hwnd, 9)                  # SW_RESTORE, asynchronous: never blocks on Revit
    u.SetForegroundWindow(hwnd)
    return True, "Switched to Revit (PID %d)." % pid


def _overall_state(snap):
    by_port = _instances_by_port(snap)
    if not any(i.get("reachable") for i in by_port.values()):
        return "down"
    for s in snap.get("sessions") or []:
        if _session_link(s, by_port)[1] == "connected":
            return "connected"
    return "partial"


def _tray_tooltip(snap):
    revit = snap.get("revit") or {}
    by_port = _instances_by_port(snap)
    n = sum(1 for s in (snap.get("sessions") or []) if s.get("bridge"))
    docs = [i["document_title"] for i in by_port.values() if i.get("document_title")]
    if not any(i.get("reachable") for i in by_port.values()):
        doc = "Revit not reachable" if revit.get("processes") else "Revit not running"
    elif docs:
        doc = "; ".join(docs)
    else:
        doc = "%d Revit%s, no active document" % (len(by_port), "" if len(by_port) == 1 else "s")
    tip = "%s\n%s\n%d session%s connected" % (APP_TITLE, doc, n, "" if n == 1 else "s")
    return tip[:127]   # NOTIFYICONDATA tooltip limit


def _icon_image(state, size=64):
    """Rounded square in the state colour with a white 'R'. Cached per state/size."""
    key = (state, size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((1, 1, size - 2, size - 2), radius=max(3, size // 5),
                        fill=STATE_COLORS[state] + (255,))
    font = None
    for name in ("HelveticaWorld-Bold.ttf", "Helvetica-Bold.ttf", "arialbd.ttf", "arial.ttf"):   # house face, Arial fallback
        try:
            font = ImageFont.truetype(name, int(size * 0.72))
            break
        except Exception:
            continue
    try:
        if font is None:
            font = ImageFont.load_default(size=int(size * 0.72))
        d.text((size / 2, size / 2 + size * 0.02), "R", fill=STATE_INK[state], font=font, anchor="mm")
    except Exception:
        d.text((size * 0.3, size * 0.2), "R", fill=STATE_INK[state])
    _ICON_CACHE[key] = img
    return img


# --------------------------------------------------- single instance IPC ---
def _k32():
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)   # so ctypes.get_last_error() is reliable
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k.CreateEventW.restype = ctypes.c_void_p
    k.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    k.OpenEventW.restype = ctypes.c_void_p
    k.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
    k.SetEvent.argtypes = [ctypes.c_void_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.WaitForSingleObject.restype = ctypes.c_uint
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    return k


_MUTEX_HANDLE = None


def _single_instance_or_focus():
    """Windows: if Revit Status is already running (e.g. started from the
    Startup folder into the tray), ask it to show its window and tell the
    caller to exit."""
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    import ctypes
    k32 = _k32()
    handle = k32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        if not _signal_show_event(k32):
            # fallback: poke the window directly
            u32 = ctypes.windll.user32
            hwnd = u32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                u32.ShowWindow(hwnd, 9)  # SW_RESTORE
                u32.SetForegroundWindow(hwnd)
        return False
    _MUTEX_HANDLE = handle  # keep the handle alive for the life of the process
    return True


def _create_show_event():
    """Named auto-reset event: a second instance signals it to say 'show yourself'."""
    if os.name != "nt":
        return None
    try:
        return _k32().CreateEventW(None, False, False, SHOW_EVENT_NAME) or None
    except Exception:
        return None


def _event_signaled(k32, handle):
    return k32.WaitForSingleObject(handle, 0) == 0   # WAIT_OBJECT_0; auto-reset clears it


def _signal_show_event(k32):
    EVENT_MODIFY_STATE = 0x0002
    h = k32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
    if not h:
        return False
    k32.SetEvent(h)
    k32.CloseHandle(h)
    return True


# ------------------------------------------------------------- licensing ---
# Rules:
#   * A password (from ALLOWED_PASSWORD_HASHES) activates the machine it is
#     first used on. The activation is written to license.json beside the exe
#     (travels with the Portable folder / OneDrive) and to %LOCALAPPDATA%.
#   * Any other machine that finds that password already bound elsewhere, or
#     finds a licence file for a different machine, is refused with a popup
#     asking to email DEVELOPER_EMAIL with its Machine ID.
#   * The developer can issue a per-machine KEY for a given Machine ID
#     (RevitStatus_KeyGen.py --key <machine id>); it is only valid there.
def _base_dir():
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))


def password_hash(password):
    import hashlib
    return hashlib.sha256((_PW_SALT + "\x1f" + password).encode("utf-8")).hexdigest()


def machine_id():
    """Stable per-PC id: Windows MachineGuid (+ hostname), shown as XXXX-XXXX-XXXX-XXXX."""
    import hashlib
    import socket
    guid = ""
    if os.name == "nt":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                               0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
            guid = winreg.QueryValueEx(k, "MachineGuid")[0]
        except Exception:
            guid = ""
    if not guid:
        import uuid
        guid = "%012x" % uuid.getnode()
    raw = hashlib.sha256(("machine\x1f" + guid + "\x1f" + socket.gethostname().lower()).encode("utf-8")).hexdigest()[:16].upper()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def machine_key(mid):
    """Developer-issued key for one Machine ID (HMAC of the id)."""
    import hashlib
    import hmac
    digest = hmac.new(_key_secret(), mid.replace("-", "").upper().encode("ascii"), hashlib.sha256).hexdigest()[:20].upper()
    return "-".join(digest[i:i + 5] for i in range(0, 20, 5))


def _license_paths():
    paths = [os.path.join(_base_dir(), LICENSE_FILE)]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(os.path.join(local, "RevitStatus", LICENSE_FILE))
    override = os.environ.get("REVITSTATUS_LICENSE_DIR")      # tests only
    if override:
        paths = [os.path.join(override, LICENSE_FILE)]
    return paths


def _sign(act):
    """HMAC over (hash, machine_id): a copied, edited or hand-written licence record is rejected."""
    import hashlib
    import hmac
    msg = ("%s%s" % (act.get("hash", ""), act.get("machine_id", ""))).encode("utf-8")
    return hmac.new(_key_secret(), msg, hashlib.sha256).hexdigest()[:32]


_UNSIGNED = []


def load_activations():
    """Merged list of {hash, machine_id, machine_name, activated, sig} from every licence file.
    Records whose signature does not verify are ignored."""
    seen, out = set(), []
    del _UNSIGNED[:]
    for p in _license_paths():
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        for a in data.get("activations", []) if isinstance(data, dict) else []:
            key = (a.get("hash"), a.get("machine_id"))
            if not (a.get("hash") and a.get("machine_id")) or key in seen:
                continue
            try:
                ok = hmac.compare_digest(str(a.get("sig", "")).encode("utf-8"), _sign(a).encode("ascii"))
            except Exception:
                ok = False
            if not ok:
                if a.get("sig") is None:
                    _UNSIGNED.append(a)       # pre-2026-09-21 record: migrated after the live sheet confirms it
                continue
            seen.add(key)
            out.append(a)
    return out


def save_activations(activations):
    for a in activations:
        a["sig"] = _sign(a)
    data = {"app": APP_TITLE, "copyright": COPYRIGHT, "activations": activations}
    written = 0
    for p in _license_paths():
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            written += 1
        except Exception:
            continue
    return written


# -- online allow-list (Google Sheet CSV) -----------------------------------
def _cache_path():
    for p in _license_paths():
        return os.path.join(os.path.dirname(p), LICENSE_CACHE_FILE)
    return os.path.join(_base_dir(), LICENSE_CACHE_FILE)


def _parse_sheet(text):
    """CSV text -> {key: {"type":..,"status":..,"machine_id":..,"note":..}} (keys normalised)."""
    import csv
    import io as _io
    rows = {}
    reader = csv.DictReader(_io.StringIO(text.lstrip("﻿")))
    for r in reader:
        norm = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in r.items()}
        key = norm.get("key", "")
        if not key:
            continue
        # Type is inferred from the key's shape (the Type column is informational
        # only, so a typo there can never lock anyone out): 64 hex chars = password
        # hash, 20 alphanumerics (with or without dashes) = machine key.
        compact = key.replace("-", "")
        if len(compact) == 20 and compact.isalnum() and len(key) != 64:
            typ, key = "key", compact.upper()
        else:
            typ, key = "password", key.lower()
        rows[key] = {"type": typ, "status": norm.get("status", "").lower(),
                     "machine_id": norm.get("machine_id", ""), "note": norm.get("note", "") or norm.get("type", "")}
    return rows


def fetch_allow_list(timeout=LICENSE_SHEET_TIMEOUT_S):
    """Fetch + cache the sheet. Returns (rows_or_None, source, error) with source in
    fetched | cache | none. A stale cache (older than the grace period) counts as none."""
    cache = _cache_path()
    try:
        req = urllib.request.Request(LICENSE_SHEET_URL, headers={"User-Agent": "RevitStatus/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8-sig", "replace")
        if "<html" in body[:400].lower():
            raise ValueError("sheet URL returned a web page, not CSV (is it published to the web as CSV?)")
        rows = _parse_sheet(body)
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"fetched": time.time(), "rows": rows, "sig": _cache_sig(time.time(), rows)}, fh)
        except Exception:
            pass
        return rows, "fetched", None
    except Exception as e:
        err = str(e).split("\n")[0]
    try:
        with open(cache, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        fetched = float(data.get("fetched", 0))
        if fetched > time.time() + 300 or not hmac.compare_digest(str(data.get("sig", "")), _cache_sig(fetched, data.get("rows", {}))):
            return None, "none", "%s (cached licence list is invalid)" % err
        age_days = (time.time() - fetched) / 86400.0
        if age_days <= LICENSE_CACHE_GRACE_DAYS:
            return data.get("rows", {}), "cache", err
        return None, "none", "%s (cached list is %.0f days old, older than the %d-day grace period)" % (err, age_days, LICENSE_CACHE_GRACE_DAYS)
    except Exception:
        return None, "none", err


def _cache_sig(fetched, rows):
    msg = ("%s|%.0f|%s" % (machine_id(), float(fetched), json.dumps(rows, sort_keys=True))).encode("utf-8")
    return hmac.new(_key_secret(), msg, hashlib.sha256).hexdigest()[:32]


# -- one-PC password lock (live, through the licence sheet's Apps Script) ----------------------
# POST {"action":"claim","product":CODE,"password":<plain>,"machine_id":MID}: the SCRIPT hashes the
# password itself (only someone who knows it can claim), finds this product's active password row
# and writes the Machine_ID if it is empty -> claimed | mine | other | revoked | unknown.
LICENCE_API_URL = ("https://script.google.com/macros/s/"
                   "REMOVED/exec")
CLAIM_PRODUCT_CODE = "RS"
FRESH_ACTIVATION_GRACE_S = 30 * 60   # a brand-new password row takes minutes to reach the published copy


def _post_json(url, body, timeout):
    """POST JSON to the Apps Script; follow Google's 302 to googleusercontent.com with a GET by hand."""
    import urllib.error

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(_NoRedirect)
    ua = {"User-Agent": CLAIM_PRODUCT_CODE + "/1.0"}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=dict(ua, **{"Content-Type": "application/json"}))
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            resp = opener.open(urllib.request.Request(e.headers["Location"], headers=ua), timeout=timeout)
        else:
            raise
    return json.loads(resp.read().decode("utf-8", "replace"))


def claim_password(password, mid, timeout=15.0):
    """'claimed' | 'mine' | 'other' | 'revoked' | 'unknown' | None (licence server unreachable)."""
    for _ in range(3):
        try:
            data = _post_json(LICENCE_API_URL, {"action": "claim", "product": CLAIM_PRODUCT_CODE,
                                                "password": password, "machine_id": mid}, timeout)
            c = data.get("claim") if data.get("ok") else None
            if c in ("claimed", "mine", "other", "revoked", "unknown"):
                return c
        except Exception:
            pass
        time.sleep(1.5)
    return None


def _fresh(act):
    try:
        t = _dt.datetime.strptime(act.get("activated", ""), "%Y-%m-%d %H:%M:%S")
        return 0 <= (_dt.datetime.now() - t).total_seconds() <= FRESH_ACTIVATION_GRACE_S
    except Exception:
        return False


def _verdict(rows, act, mid):
    """'ok' | 'taken' (its password is now locked to another PC) | 'revoked' - for one local activation."""
    if act["hash"].startswith("key:"):
        row = rows.get(machine_key(mid).replace("-", ""))
    else:
        row = rows.get(act["hash"])
        if row is None and _fresh(act):
            return "ok"      # verified live (claim) moments ago; the published copy lags
    if row is None or row.get("status") != "active":
        return "revoked"
    if not act["hash"].startswith("key:"):
        owner = (row.get("machine_id") or "").replace("-", "").upper()
        if owner and owner != mid.replace("-", "").upper():
            return "taken"
    return "ok"


def _machine_row_active(rows, mine, mid):
    return any(_verdict(rows, a, mid) == "ok" for a in mine)


def license_state():
    """('ok', None) | ('locked', other_activation) | ('unactivated', None) | ('revoked', info) | ('taken', info) | ('offline', err).
    Checks the machine's activation AND that its key/password is still active (and still this PC's) in the sheet."""
    mid = machine_id()
    acts = load_activations()
    mine = [a for a in acts if a["machine_id"] == mid]
    if mine:
        # Google serves a freshly edited published sheet from several cache
        # nodes for a few minutes, so one fetch can still see the old copy:
        # try up to 3 times and accept as soon as one copy says active.
        rows, source, err, verdicts = None, "none", None, []
        for attempt in range(3):
            rows, source, err = fetch_allow_list()
            if rows is None:
                break
            verdicts = [_verdict(rows, a, mid) for a in mine]
            if "ok" in verdicts:
                return "ok", None
            time.sleep(1.5)
        if rows is None:
            return "offline", {"error": err or "licence server unreachable"}
        if "taken" in verdicts:
            return "taken", {"machine_id": mid}
        return "revoked", {"machine_id": mid}
    old = [a for a in _UNSIGNED if a.get("machine_id") == mid]
    if old:
        rows, source, err = fetch_allow_list()
        if source == "fetched" and _machine_row_active(rows, old, mid):
            keep = [a for a in old if (rows.get(machine_key(mid).replace("-", "")) if a["hash"].startswith("key:") else rows.get(a["hash"])) is not None]
            if keep and save_activations(acts + keep):
                return "ok", None
    if acts:
        return "locked", acts[0]
    return "unactivated", None


def try_activate(secret):
    """Accept a per-machine key or a one-PC password. Returns (ok, message).
    A password is locked to the first PC that activates it (claimed live in the licence sheet)."""
    import socket
    secret = (secret or "").strip()
    if not secret:
        return False, "Enter the password or key."
    mid = machine_id()
    acts = load_activations()
    is_key = secret.replace("-", "").upper() == machine_key(mid).replace("-", "")
    if is_key:
        lookup = machine_key(mid).replace("-", "")
        rows, source, err = None, "none", None
        for attempt in range(3):          # a just-edited published sheet can still serve the old copy
            rows, source, err = fetch_allow_list()
            if rows is None or (rows.get(lookup) or {}).get("status") == "active":
                break
            time.sleep(1.5)
        if source != "fetched" or rows is None:
            return False, ("The licence server could not be reached (%s).\nActivation needs an internet connection; please retry." % (err or "no connection"))
        row = rows.get(lookup)
        if row is None:
            return False, "Incorrect password or key."
        if row["status"] != "active":
            return False, "This key has been revoked."
        tag = "key:" + mid
    else:
        claim = claim_password(secret, mid)
        if claim is None:
            return False, ("The licence server could not be reached.\n"
                           "Activation needs an internet connection; please retry.")
        if claim == "unknown":
            return False, "Incorrect password or key."
        if claim == "revoked":
            return False, "This password has been revoked."
        if claim == "other":
            return False, ("This password is already activated on another PC.\n"
                           "Each password works on one PC only - ask the developer for your own.")
        tag = password_hash(secret)
    if not any(a["hash"] == tag and a["machine_id"] == mid for a in acts):
        acts.append({"hash": tag, "machine_id": mid, "machine_name": socket.gethostname(),
                     "activated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    if save_activations(acts) == 0:
        return False, "Activated, but the licence file could not be written (folder read-only?)."
    return True, "Activated on this machine."


def _center(win, w, h):
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))
    win.lift()
    win.attributes("-topmost", True)
    win.after(300, lambda: win.attributes("-topmost", False))
    win.focus_force()


def _copy_to_clipboard(root, text):
    root.clipboard_clear()
    root.clipboard_append(text)


def email_developer(root=None):
    """Open a pre-filled licence-request email; falls back to copying the Machine ID."""
    import urllib.parse
    mid = machine_id()
    subject = "%s licence - Machine ID %s" % (APP_DISPLAY, mid)
    body = ("Hello,\n\nProduct: %s v%s\nMachine ID: %s\nComputer: %s\n\nPlease issue a key for this machine.\n\nThanks."
            % (APP_DISPLAY, VERSION, mid, __import__("socket").gethostname()))
    try:
        os.startfile("mailto:%s?subject=%s&body=%s" % (DEVELOPER_EMAIL, urllib.parse.quote(subject), urllib.parse.quote(body)))
    except Exception:
        if root is not None:
            _copy_to_clipboard(root, mid)


def activation_dialog(root):
    """Modal 'enter password / key' dialog on top of `root`. Returns True when activated."""
    import tkinter as tk
    from tkinter import ttk
    mid = machine_id()
    rt = _rt()
    result = {"ok": False}
    dlg = tk.Toplevel(root)
    rt.on_change(dlg, lambda p: dlg.configure(background=p["surface"]))
    dlg.title("%s - Activation" % APP_DISPLAY)
    dlg.resizable(False, False)
    if root.winfo_viewable():
        dlg.transient(root)   # a transient of a withdrawn root is never shown (Tk): the start-up gate's root is withdrawn
    frm = ttk.Frame(dlg, padding=(18, 14))
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Enter the password or key to activate %s on this machine." % APP_TITLE).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, text="Machine ID:", style="Dim.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
    ttk.Label(frm, text=mid, font=("Consolas", 10, "bold")).grid(row=1, column=1, sticky="w", pady=(10, 0))
    ttk.Button(frm, text="Copy", width=7, command=lambda: _copy_to_clipboard(root, mid)).grid(row=1, column=2, sticky="e", pady=(10, 0))
    ttk.Label(frm, text="Password / key:", style="Dim.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
    var = tk.StringVar()
    ent = ttk.Entry(frm, textvariable=var, show="•", width=34)
    ent.grid(row=2, column=1, columnspan=2, sticky="we", pady=(8, 0))
    msg = tk.StringVar(value="")
    ttk.Label(frm, textvariable=msg, style=rt.style_for("state-down"), wraplength=360).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
    attempts = {"left": 3}

    def submit(event=None):
        ok, text = try_activate(var.get())
        if ok:
            result["ok"] = True
            dlg.destroy()
            return
        attempts["left"] -= 1
        var.set("")
        if attempts["left"] <= 0:
            msg.set(text + "\nNo attempts left.")
            dlg.after(1200, dlg.destroy)
        else:
            msg.set("%s  (%d attempt%s left)" % (text, attempts["left"], "" if attempts["left"] == 1 else "s"))

    btns = ttk.Frame(frm)
    btns.grid(row=4, column=0, columnspan=3, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Activate", command=submit, default="active").pack(side="left")
    ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
    ttk.Label(frm, text=COPYRIGHT, style="Faint.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))
    ent.bind("<Return>", submit)
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    _center(dlg, 470, 215)
    ent.focus_set()
    dlg.grab_set()
    root.wait_window(dlg)
    return result["ok"]


def ensure_activated():
    """Gate before the main window. Returns True to continue, False to exit."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    state, other = license_state()
    if state == "ok":
        return True

    root = tk.Tk()
    root.withdraw()
    _rt().apply(root)
    result = {"ok": False}
    mid = machine_id()

    center = _center

    def copy_id():
        _copy_to_clipboard(root, mid)

    def email_dev():
        email_developer(root)

    def password_dialog():
        result["ok"] = activation_dialog(root)

    def locked_dialog(other_act):
        dlg = tk.Toplevel(root)
        dlg.title("%s - Licence" % APP_DISPLAY)
        dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=(18, 14))
        frm.pack(fill="both", expand=True)
        who = other_act.get("machine_name") or other_act.get("machine_id")
        ttk.Label(frm, text="%s is already activated on another machine." % APP_TITLE, font=_rt().FONTS["ui-body-strong"]).pack(anchor="w")
        ttk.Label(frm, text="Licensed machine: %s (ID %s)\nEach licence runs on one machine only." % (who, other_act.get("machine_id"))).pack(anchor="w", pady=(6, 0))
        ttk.Label(frm, text="To use %s on this machine, email the developer at" % APP_TITLE).pack(anchor="w", pady=(10, 0))
        ttk.Label(frm, text=DEVELOPER_EMAIL, font=_rt().FONTS["ui-body-strong"]).pack(anchor="w")
        ttk.Label(frm, text="and include this Machine ID:").pack(anchor="w", pady=(6, 0))
        idrow = ttk.Frame(frm)
        idrow.pack(anchor="w")
        ttk.Label(idrow, text=mid, font=("Consolas", 11, "bold")).pack(side="left")
        ttk.Button(idrow, text="Copy", width=7, command=copy_id).pack(side="left", padx=(10, 0))
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Email developer", command=email_dev).pack(side="left")

        def have_key():
            dlg.destroy()
            password_dialog()

        ttk.Button(btns, text="I have a key…", command=have_key).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Close", command=dlg.destroy).pack(side="right")
        ttk.Label(frm, text=COPYRIGHT, style="Faint.TLabel").pack(anchor="w", pady=(12, 0))
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        center(dlg, 470, 290)
        root.wait_window(dlg)

    def simple_lock(title_text, body_text):
        dlg = tk.Toplevel(root)
        dlg.title("%s - Licence" % APP_DISPLAY)
        dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=(18, 14))
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=title_text, font=_rt().FONTS["ui-body-strong"]).pack(anchor="w")
        ttk.Label(frm, text=body_text, wraplength=430, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(frm, text="Email the developer at", ).pack(anchor="w", pady=(10, 0))
        ttk.Label(frm, text=DEVELOPER_EMAIL, font=_rt().FONTS["ui-body-strong"]).pack(anchor="w")
        idrow = ttk.Frame(frm)
        idrow.pack(anchor="w", pady=(6, 0))
        ttk.Label(idrow, text="Machine ID  ").pack(side="left")
        ttk.Label(idrow, text=mid, font=("Consolas", 11, "bold")).pack(side="left")
        ttk.Button(idrow, text="Copy", width=7, command=copy_id).pack(side="left", padx=(10, 0))
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Email developer", command=email_dev).pack(side="left")

        def have_key():
            dlg.destroy()
            password_dialog()

        ttk.Button(btns, text="I have a key…", command=have_key).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Close", command=dlg.destroy).pack(side="right")
        ttk.Label(frm, text=COPYRIGHT, style="Faint.TLabel").pack(anchor="w", pady=(12, 0))
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        center(dlg, 490, 290)
        root.wait_window(dlg)

    if state == "locked":
        locked_dialog(other)
    elif state == "revoked":
        simple_lock("This machine's licence has been revoked.",
                    "The password or key used on this machine is no longer active in the licence list.")
    elif state == "taken":
        simple_lock("This password is now activated on another computer.",
                    "Each password works on one computer only. Contact the developer for your own key or password.")
    elif state == "offline":
        simple_lock("The licence could not be verified.",
                    "%s\n\n%s checks its licence online at start-up and allows %d days without a connection." % (
                        (other or {}).get("error", "no connection"), APP_TITLE, LICENSE_CACHE_GRACE_DAYS))
    else:
        password_dialog()
    try:
        root.destroy()
    except Exception:
        pass
    return result["ok"]


# ------------------------------------------------------------------- UI ---
# Same text as RevitStatus_LICENSE.txt beside this file (revitstatus_branding_test.py checks it).
LICENSE_TEXT = """Revit Status by Netbuild -- Licence Agreement

Copyright (c) 2026 SKAEC.COM. All rights reserved.

This software is licensed, not sold. SKAEC.COM grants you a non-exclusive, non-transferable licence to install and use this software on the computer(s) for which a valid licence was issued, for the term of that licence.

You may not: copy or distribute the software except for your own backup; sell, rent, lease, sublicense or share the software or its licence keys; modify, decompile, disassemble or reverse engineer it, or bypass its licence checks, except where the law expressly allows it; or remove copyright or licence notices.

SKAEC.COM may revoke a licence if these terms are broken. Moving a licence to another computer requires a transfer from SKAEC.COM.

The software is provided "as is", without warranty of any kind. To the extent permitted by law, SKAEC.COM is not liable for any damages arising from its use, including loss of data or of work in Autodesk Revit models. Keep backups of your models.

Autodesk and Revit are registered trademarks of Autodesk, Inc. pyRevit, the Model Context Protocol SDK and other third-party components are used under their own licences. This product is not affiliated with or endorsed by Autodesk or Anthropic.

Contact: https://skaec.com
"""


def run_gui(collector, start_hidden=False):
    import tkinter as tk
    from tkinter import ttk
    try:
        import pystray
    except Exception:
        pystray = None
    try:
        from PIL import ImageTk
    except Exception:
        ImageTk = None

    root = tk.Tk()
    if start_hidden:
        root.withdraw()          # never flash the window when launched at login
    root.title(WINDOW_TITLE)
    root.geometry("1180x720")
    root.minsize(760, 420)

    rt = _rt()
    rt.apply(root)                       # saved choice: As per system / Light / Dark
    ttk.Style(root).configure("Big.TLabel", font=rt.FONTS["ui-heading"])   # Revit Status uses the 11pt heading

    # Footer + status bar are packed FIRST at the bottom so they are never
    # squeezed out when the window is short; the sessions table absorbs the
    # remaining space.
    foot = ttk.Frame(root, padding=(10, 0, 10, 6))
    foot.pack(side="bottom", fill="x")
    ttk.Label(foot, text="%s v%s   %s" % (APP_DISPLAY, VERSION, COPYRIGHT), style="Faint.TLabel").pack(side="left")
    lic_foot_var = tk.StringVar(value="Machine ID %s" % machine_id())
    ttk.Label(foot, textvariable=lic_foot_var, style="FaintMono.TLabel").pack(side="right")
    bar = ttk.Frame(root, padding=(10, 4))
    bar.pack(side="bottom", fill="x")

    # -- tabs: Status (Revit + sessions) and Licence --------------------
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))
    tab_status = ttk.Frame(nb)
    tab_lic = ttk.Frame(nb)
    nb.add(tab_status, text="  Status  ")
    nb.add(tab_lic, text="  Licence  ")
    tab_about = ttk.Frame(nb)
    nb.add(tab_about, text="  About  ")

    # -- About tab: what the app does and what it needs ------------------
    ab = ttk.Frame(tab_about, padding=(16, 10))
    ab.pack(fill="both", expand=True)
    ttk.Label(ab, text="%s v%s" % (APP_DISPLAY, VERSION), font=rt.FONTS["ui-title"]).pack(anchor="w")
    ttk.Label(ab, text="Publisher: %s   |   %s   |   %s" % (PUBLISHER, WEBSITE, COPYRIGHT),
              style="Dim.TLabel").pack(anchor="w")
    ttk.Label(ab, text="A system-tray monitor that shows every open Revit and every Claude Code session on this "
                       "computer, and which Revit each session is talking to.",
              style="Dim.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(2, 12))
    about_sections = (
        ("What it does", (
            "Lists every running Revit (one row each, MCP listener ports 48884-48889 and any registered pyRevit port): "
            "version, process id, the open document, how long it has been active and whether its listener is healthy.",
            "Lists every Claude Code session: whether it has a live bridge to Revit, which Revit it is routed to and "
            "the document open there.",
            "Click a Revit row to switch to that Revit (skipped when Revit is not responding, so a stuck Revit is never "
            "disturbed). Click a session row to open it in the Claude app. Click a column heading to sort; double-click "
            "a heading divider to fit the column.",
            "Runs in the system tray (a Startup-folder shortcut with --tray starts it at Windows login). Icon colour: "
            "green = connected, amber = Revit reachable but no document or bridge, red = no Revit reachable.",
        )),
        ("Requirements", (
            "Windows 10 or 11 (64-bit). No installation, no admin rights and no Python needed: keep the "
            "\"Revit Status\" folder together.",
            "Autodesk Revit 2023-2026 with pyRevit and the Revit MCP connector loaded (it provides the status "
            "listener on port 48884 and up). The app reads whatever Revit pyRevit registers; it does not check the version.",
            "Claude Code (desktop app) for the Code Sessions list and session links.",
            "Optional: Revit MCP Router, to route each Claude session to a chosen Revit.",
            "An internet connection to activate, and at start-up for the licence check; it keeps working offline for "
            "up to %d days after the last successful check. One licence per computer (Machine ID)." % LICENSE_CACHE_GRACE_DAYS,
            "From source instead of the .exe (developer only): Python 3 with tkinter, psutil, pystray and Pillow.",
        )),
    )
    for head, bullets in about_sections:
        ttk.Label(ab, text=head, font=rt.FONTS["ui-heading"]).pack(anchor="w", pady=(4, 2))
        for b_txt in bullets:
            ttk.Label(ab, text="•  " + b_txt, wraplength=900, justify="left").pack(anchor="w", padx=(8, 0), pady=1)
    ttk.Separator(ab, orient="horizontal").pack(fill="x", pady=8)
    # bottom row: licence status + contacts (left), the licence agreement text (right)
    ab_low = ttk.Frame(ab)
    ab_low.pack(fill="both", expand=True)
    ab_info = ttk.Frame(ab_low)
    ab_info.pack(side="left", fill="y", anchor="n", padx=(0, 12))
    about_lic_var = tk.StringVar(value="Licence: checking…")      # same state as the Licence tab
    ttk.Label(ab_info, textvariable=about_lic_var, wraplength=480, justify="left").pack(anchor="w")
    ttk.Label(ab_info, text="Developer: %s  ·  %s" % (DEVELOPER_NAME, DEVELOPER_EMAIL)).pack(anchor="w", pady=(4, 0))
    ttk.Label(ab_info, text=COPYRIGHT, style="Faint.TLabel").pack(anchor="w", pady=(4, 0))
    about_btns = ttk.Frame(ab_info)
    about_btns.pack(anchor="w", pady=(8, 0))
    ttk.Button(about_btns, text="Open %s" % WEBSITE, command=lambda: __import__("webbrowser").open(WEBSITE)).pack(side="left")
    ttk.Button(about_btns, text="Copy licence text", command=lambda: _copy_to_clipboard(root, LICENSE_TEXT)).pack(side="left", padx=6)
    ab_txt = ttk.Frame(ab_low)
    ab_txt.pack(side="left", fill="both", expand=True)
    ttk.Label(ab_txt, text="Licence agreement (LICENSE.txt)", font=rt.FONTS["ui-heading"]).pack(anchor="w", pady=(0, 2))
    lic_box = rt.console(ab_txt, wrap="word")
    lic_box.configure(height=6)
    lic_box.insert("1.0", LICENSE_TEXT)
    lic_box.configure(state="disabled")
    lic_box.pack(fill="both", expand=True)

    # -- Revit panel: one row per running Revit (port = pyRevit Routes listener) --
    top = ttk.LabelFrame(tab_status, text=" Revit Sessions  (one row per open Revit; click a row to switch to it) ", padding=(6, 4))
    top.pack(fill="x", padx=10, pady=(10, 4))
    doc_var = tk.StringVar(value="…")          # one-line summary above the table
    ttk.Label(top, textvariable=doc_var, style="Dim.TLabel").pack(anchor="w", padx=2, pady=(0, 3))

    # -- sorting: click a column heading (again to reverse); kept across the 1 s refreshes
    import re as _re
    sort_state = {}                      # tree -> (column, descending)
    heading_text = {}                    # (tree, column) -> plain heading label

    def _sort_key(v):
        """Natural order (numbers as numbers: ports, PIDs, clocks, 'h:mm:ss'); blanks flagged."""
        txt = str(v).strip()
        if txt in ("", "-", "?") or txt.startswith("("):
            return (1, [])
        return (0, [(0, int(tk_), "") if tk_.isdigit() else (1, 0, tk_.lower()) for tk_ in _re.findall(r"\d+|\D+", txt)])

    def sort_rows(t, rows):
        """rows: [(values, ...)] -> sorted by the chosen column; blanks ('-', '?', '(no ...)') always last."""
        col, desc = sort_state.get(t, (None, False))
        if col is None:
            return rows
        i = list(t["columns"]).index(col)
        full = [r for r in rows if _sort_key(r[0][i])[0] == 0]
        empty = [r for r in rows if _sort_key(r[0][i])[0] == 1]
        full.sort(key=lambda r: _sort_key(r[0][i]), reverse=desc)
        return full + empty

    def sort_by(t, col):
        cur, desc = sort_state.get(t, (None, False))
        sort_state[t] = (col, (not desc) if cur == col else False)
        for c in t["columns"]:
            label = heading_text[(t, c)]
            if c == col:
                label += "  \u25bc" if sort_state[t][1] else "  \u25b2"
            t.heading(c, text=label)
        refresh(reschedule=False)

    rcols = ("port", "version", "rpid", "doc", "since", "elapsed", "listener", "sessions")
    rbox = ttk.Frame(top)
    rbox.pack(fill="x", expand=True)
    rtree = ttk.Treeview(rbox, columns=rcols, show="headings", selectmode="browse", height=3)
    rheads = {
        "port": ("Port", 60, "center"),
        "version": ("Revit", 60, "center"),
        "rpid": ("PID", 60, "center"),
        "doc": ("Document / model", 300, "w"),
        "since": ("Active since", 90, "center"),
        "elapsed": ("Active for", 80, "center"),
        "listener": ("Listener", 90, "center"),
        "sessions": ("Code sessions routed here", 240, "w"),
    }
    for c in rcols:
        text, width, anchor = rheads[c]
        rtree.heading(c, text=text, command=lambda c=c: sort_by(rtree, c))
        heading_text[(rtree, c)] = text
        # wrapped columns may be dragged narrower (text re-wraps, rows grow); fixed ones keep their width
        rtree.column(c, width=width, minwidth=(60 if c in ("doc", "listener", "sessions") else width), anchor=anchor,
                     stretch=(c in ("doc", "sessions")))
    rvsb = ttk.Scrollbar(rbox, orient="vertical", command=rtree.yview)
    rhsb = ttk.Scrollbar(rbox, orient="horizontal", command=rtree.xview)
    rtree.configure(yscrollcommand=rvsb.set, xscrollcommand=rhsb.set)
    rtree.grid(row=0, column=0, sticky="nsew")
    rvsb.grid(row=0, column=1, sticky="ns")
    rhsb.grid(row=1, column=0, sticky="ew")
    rbox.columnconfigure(0, weight=1)
    rt.tag_tree(rtree)

    # -- Sessions table -------------------------------------------------
    mid = ttk.LabelFrame(tab_status, text=" Code Sessions  (click a row to open it) ", padding=(6, 4))
    mid.pack(fill="both", expand=True, padx=10, pady=4)

    cols = ("session", "state", "mcp", "revit", "doc", "since", "elapsed", "folder")
    tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
    heads = {
        "session": ("Session", 220, "w"),
        "state": ("State", 55, "center"),
        "mcp": ("Bridge", 240, "w"),
        "revit": ("Revit (port)", 95, "center"),
        "doc": ("Document / model", 200, "w"),
        "since": ("Connected at", 90, "center"),
        "elapsed": ("Connected for", 90, "center"),
        "folder": ("Folder", 110, "w"),
    }
    for c in cols:
        text, width, anchor = heads[c]
        tree.heading(c, text=text, command=lambda c=c: sort_by(tree, c))
        heading_text[(tree, c)] = text
        tree.column(c, width=width, minwidth=(60 if c in ("session", "mcp", "doc", "folder") else width), anchor=anchor,
                    stretch=(c in ("session", "doc", "folder")))
    vsb = ttk.Scrollbar(mid, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(mid, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    mid.columnconfigure(0, weight=1)
    mid.rowconfigure(0, weight=1)
    rt.tag_tree(tree)

    # -- wrapped cells: Tk tables cannot wrap, so text is broken to the column width here and
    #    the table's (uniform) row height grows to the tallest cell, up to WRAP_MAX_LINES lines
    import tkinter.font as tkfont
    cell_font = tkfont.Font(root=root, font=rt.FONTS["ui-body"])
    WRAP_MAX_LINES = 4
    wrapped = {}                         # tree -> {"cols", "raw": {item: values}, "style"}

    def wrap_cell(text, width):
        width = max(40, width - 14)      # cell padding
        out = []
        for para in str(text).split("\n"):
            line = ""
            for word in para.split(" "):
                cand = word if not line else line + " " + word
                if not line or cell_font.measure(cand) <= width:
                    line = cand
                else:
                    out.append(line)
                    line = word
                while len(line) > 1 and cell_font.measure(line) > width:     # one very long word
                    cut = len(line) - 1
                    while cut > 1 and cell_font.measure(line[:cut]) > width:
                        cut -= 1
                    out.append(line[:cut])
                    line = line[cut:]
            out.append(line)
        return out

    def rewrap(t):
        info = wrapped[t]
        cols_all = list(t["columns"])
        lines = 1
        for item in list(info["raw"]):
            if not t.exists(item):
                del info["raw"][item]
                continue
            vals = list(info["raw"][item])
            for c in info["cols"]:
                i = cols_all.index(c)
                parts = wrap_cell(vals[i], t.column(c, "width"))
                if len(parts) > WRAP_MAX_LINES:
                    parts = parts[:WRAP_MAX_LINES]
                    parts[-1] = parts[-1].rstrip() + "…"
                lines = max(lines, len(parts))
                vals[i] = "\n".join(parts)
            t.item(item, values=vals)
        ttk.Style(root).configure(info["style"], rowheight=max(rt.ROW_HEIGHT, lines * cell_font.metrics("linespace") + 8))

    def setup_wrap(t, wrap_cols, style):
        ttk.Style(root).configure(style, rowheight=rt.ROW_HEIGHT)
        t.configure(style=style)
        wrapped[t] = {"cols": wrap_cols, "raw": {}, "style": style}
        t.bind("<Configure>", lambda e: rewrap(t), add="+")
        # live re-wrap while a column separator is dragged (throttled), and once more on release
        drag = {"on": False, "pending": False}

        def press(e):
            drag["on"] = t.identify_region(e.x, e.y) == "separator"

        def motion(_e):
            if drag["on"] and not drag["pending"]:
                drag["pending"] = True
                t.after(40, lambda: (drag.update(pending=False), rewrap(t)))

        def release(_e):
            if drag["on"]:
                drag["on"] = False
                rewrap(t)
        t.bind("<ButtonPress-1>", press, add="+")
        t.bind("<B1-Motion>", motion, add="+")
        t.bind("<ButtonRelease-1>", release, add="+")

        # double-click a heading divider = auto-fit the column to its left to its content (like Excel)
        def autofit(e):
            if t.identify_region(e.x, e.y) != "separator":
                return
            col_id = t.identify_column(e.x - 4)             # "#n", the column left of the divider
            try:
                col = t["columns"][int(col_id[1:]) - 1]
            except (ValueError, IndexError):
                return
            i = list(t["columns"]).index(col)
            head_font = tkfont.Font(root=root, font=rt.FONTS["ui-table-heading"])
            need = head_font.measure(t.heading(col, "text")) + 24
            rows = wrapped[t]["raw"].values() if wrapped[t]["raw"] else (t.item(it, "values") for it in t.get_children())
            for vals in rows:
                for line in str(vals[i]).split("\n"):
                    need = max(need, cell_font.measure(line) + 18)
            t.column(col, width=min(need, 900))
            rewrap(t)
            return "break"
        t.bind("<Double-1>", autofit, add="+")

    setup_wrap(rtree, ("doc", "listener", "sessions"), "Revit.Treeview")
    setup_wrap(tree, ("session", "mcp", "doc", "folder"), "Sessions.Treeview")

    # -- Licence tab (same layout as the Revit MCP Router Setup app) ------
    lic = ttk.Frame(tab_lic, padding=(16, 10))
    lic.pack(fill="both", expand=True)
    lic_state_lbl = ttk.Label(lic, text="Checking licence…", font=rt.FONTS["ui-title"])
    lic_state_lbl.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
    lic_detail_var = tk.StringVar(value="")
    ttk.Label(lic, textvariable=lic_detail_var, style="Dim.TLabel", wraplength=700, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

    ttk.Label(lic, text="Machine ID:").grid(row=2, column=0, sticky="w", pady=3)
    mid_var = tk.StringVar(value=machine_id())
    ttk.Entry(lic, textvariable=mid_var, width=26, state="readonly", font=("Consolas", 11)).grid(row=2, column=1, sticky="w")
    ttk.Button(lic, text="Copy", command=lambda: (_copy_to_clipboard(root, mid_var.get()), status_var.set("Machine ID copied"))).grid(row=2, column=2, sticky="w", padx=6)
    ttk.Label(lic, text="Computer:").grid(row=3, column=0, sticky="w", pady=3)
    pc_var = tk.StringVar(value=__import__("socket").gethostname())
    ttk.Label(lic, textvariable=pc_var).grid(row=3, column=1, columnspan=2, sticky="w")
    ttk.Label(lic, text="Activated:").grid(row=4, column=0, sticky="w", pady=3)
    act_var = tk.StringVar(value="-")
    ttk.Label(lic, textvariable=act_var).grid(row=4, column=1, columnspan=2, sticky="w")
    ttk.Label(lic, text="Licence terms:").grid(row=5, column=0, sticky="nw", pady=3)
    ttk.Label(lic, text="Licensed for use on this computer only (the Machine ID above). Keys are issued per machine by the developer "
                        "and are not transferable. Redistribution, copying or reverse engineering of this software is prohibited. "
                        "Full licence agreement: About tab (LICENSE.txt).",
              wraplength=560, justify="left").grid(row=5, column=1, columnspan=2, sticky="w")

    ttk.Separator(lic, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="we", pady=8)
    ttk.Label(lic, text="Developer", font=rt.FONTS["ui-title"]).grid(row=7, column=0, columnspan=3, sticky="w")
    ttk.Label(lic, text="Name:").grid(row=8, column=0, sticky="w", pady=3)
    ttk.Label(lic, text=DEVELOPER_NAME).grid(row=8, column=1, columnspan=2, sticky="w")
    ttk.Label(lic, text="Email:").grid(row=9, column=0, sticky="w", pady=3)
    ttk.Label(lic, text=DEVELOPER_EMAIL).grid(row=9, column=1, sticky="w")
    ttk.Button(lic, text="Copy", command=lambda: (_copy_to_clipboard(root, DEVELOPER_EMAIL), status_var.set("Email copied"))).grid(row=9, column=2, sticky="w", padx=6)
    ttk.Label(lic, text="For a licence key, a transfer to a new computer, or support, email the developer with your Machine ID.",
              style="Dim.TLabel", wraplength=560, justify="left").grid(row=10, column=1, columnspan=2, sticky="w", pady=(0, 4))

    lic_btns = ttk.Frame(lic)
    lic_btns.grid(row=11, column=0, columnspan=3, sticky="w", pady=(4, 0))
    ttk.Button(lic_btns, text="Email developer", command=lambda: email_developer(root)).pack(side="left", padx=(0, 6))

    ttk.Label(lic, text="This software and its licence keys are the property of %s. Unauthorised use is prohibited." % PUBLISHER,
              style="Dim.TLabel", wraplength=700, justify="left").grid(row=12, column=0, columnspan=3, sticky="w", pady=(12, 0))
    lic.columnconfigure(1, weight=1)

    # -- bottom bar (frame created above, before the table) --------------
    status_var = tk.StringVar(value="starting…")
    ttk.Label(bar, textvariable=status_var, style="Dim.TLabel").pack(side="left")
    topmost_var = tk.BooleanVar(value=False)
    last_error = {"msg": ""}

    def toggle_topmost():
        root.attributes("-topmost", topmost_var.get())

    def do_refresh(event=None):
        collector.refresh_now()
        status_var.set("Refreshing…")

    ttk.Button(bar, text="Refresh now  (F5)", command=do_refresh).pack(side="right")

    # -- licence tab actions (the online check runs off the Tk thread) ----
    lic_busy = {"on": False}

    def _apply_licence(state, info):
        lic_busy["on"] = False
        mid_now = machine_id()
        mine = [a for a in load_activations() if a.get("machine_id") == mid_now]
        lic_style = rt.licence_style(state)
        text = {"ok": "Licensed", "unactivated": "Not activated", "locked": "Licence belongs to another computer",
                "revoked": "Licence revoked", "taken": "Password in use on another computer",
                "offline": "Licence check pending (offline)"}.get(state, state)
        lic_state_lbl.configure(text=text, style=lic_style)
        if state == "ok":
            detail = "Verified online just now."
        elif state == "offline":
            detail = (info or {}).get("error", "")
        elif state == "revoked":
            detail = "This computer's licence has been revoked. Contact the developer."
        elif state == "taken":
            detail = "The password used here is now activated on another computer. Each password works on one computer only."
        elif state == "unactivated":
            detail = "Enter your password or key to activate this computer."
        elif state == "locked":
            other = info or {}
            detail = "Licensed machine: %s (ID %s). Each licence runs on one machine only." % (
                other.get("machine_name") or other.get("machine_id"), other.get("machine_id"))
        else:
            detail = ""
        lic_detail_var.set(detail)
        if mine:
            a = mine[0]
            act_var.set("%s  (%s)" % (a.get("activated", "?"), "machine key" if a.get("hash", "").startswith("key:") else "password"))
        else:
            act_var.set("-")
        lic_foot_var.set("%s  ·  Machine ID %s" % (text, mid_now))
        about_lic_var.set("Licence: %s  ·  Machine ID %s%s" % (text, mid_now, ("  ·  " + detail) if detail else ""))

    def refresh_licence():
        if lic_busy["on"]:
            return
        lic_busy["on"] = True
        lic_state_lbl.configure(text="Checking licence…", style="Dim.TLabel")
        lic_detail_var.set("Contacting the licence server…")

        def worker():
            try:
                state, info = license_state()
            except Exception as e:
                state, info = "offline", {"error": str(e)}
            root.after(0, lambda: _apply_licence(state, info))
        threading.Thread(target=worker, daemon=True).start()

    def change_key():
        if activation_dialog(root):
            status_var.set("Activated on this machine.")
        refresh_licence()

    ttk.Button(lic_btns, text="Enter / change key…", command=change_key).pack(side="left", padx=6)
    ttk.Button(lic_btns, text="Re-check licence", command=refresh_licence).pack(side="left", padx=6)
    ttk.Checkbutton(bar, text="Always on top", variable=topmost_var, command=toggle_topmost).pack(side="right", padx=(0, 12))
    rt.theme_picker(bar).pack(side="right", padx=(0, 16))
    root.bind("<F5>", do_refresh)

    # -- window show / hide / exit -------------------------------------
    tray = {"icon": None, "state": None, "tip": None, "photo": None}
    cmds = queue.Queue()   # tray-thread -> Tk-thread commands

    def show_window():
        root.deiconify()
        try:
            root.state("normal")
        except Exception:
            pass
        root.lift()
        try:
            root.focus_force()
        except Exception:
            pass

    def hide_window():
        if tray["icon"] is not None:
            root.withdraw()
        else:
            root.iconify()

    def exit_app():
        collector.stop()
        if tray["icon"] is not None:
            try:
                tray["icon"].stop()
            except Exception:
                pass
        root.destroy()

    def set_window_icon(state):
        if ImageTk is None:
            return
        try:
            tray["photo"] = ImageTk.PhotoImage(_icon_image(state, 32))
            root.iconphoto(True, tray["photo"])
        except Exception:
            pass

    set_window_icon("partial")

    # -- tray icon ------------------------------------------------------
    if pystray is not None:
        def _q(cmd):
            return lambda *a, **k: cmds.put(cmd)
        menu = pystray.Menu(
            pystray.MenuItem("Show " + APP_TITLE, _q("show"), default=True),
            pystray.MenuItem("Refresh now", _q("refresh")),
            pystray.MenuItem("Licence…", _q("licence")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", _q("exit")),
        )
        try:
            icon = pystray.Icon("RevitStatus", _icon_image("partial"), APP_TITLE, menu)
            icon.run_detached()
            tray["icon"] = icon
            tray["state"] = "partial"
        except Exception as e:
            tray["icon"] = None
            last_error["msg"] = "tray icon unavailable: %s" % e
    else:
        last_error["msg"] = "tray icon unavailable: pystray not installed"

    if tray["icon"] is not None:
        root.protocol("WM_DELETE_WINDOW", hide_window)       # X = hide to tray
        def on_unmap(event):                                 # minimise = hide to tray
            if event.widget is root and root.state() == "iconic":
                root.withdraw()
        root.bind("<Unmap>", on_unmap)
    else:
        root.protocol("WM_DELETE_WINDOW", exit_app)          # no tray: X really exits
        if start_hidden:
            root.deiconify()                                 # nothing to hide into

    # -- behaviour ------------------------------------------------------
    row_links = {}   # tree item id -> claude:// link

    def open_session(event=None):
        item = tree.identify_row(event.y) if event is not None else (tree.focus() or "")
        if not item:
            return
        link = row_links.get(item)
        if not link:
            status_var.set("This session has no host id, cannot open it.")
            return
        try:
            os.startfile(link)
            status_var.set("Opened %s" % link)
        except Exception as e:
            status_var.set("Could not open link: %s" % e)

    tree.bind("<ButtonRelease-1>", lambda e: open_session(e) if tree.identify_region(e.x, e.y) == "cell" else None, add="+")
    tree.bind("<Return>", open_session)

    def switch_to_revit(event=None):
        if event is not None and rtree.identify_region(event.x, event.y) != "cell":
            return
        item = rtree.identify_row(event.y) if event is not None else (rtree.focus() or "")
        if not item:
            return
        raw = wrapped[rtree]["raw"].get(item) or rtree.item(item, "values")
        ok, msg = focus_revit(raw[2])                       # PID column
        status_var.set(msg)

    rtree.bind("<ButtonRelease-1>", switch_to_revit, add="+")
    rtree.bind("<Return>", switch_to_revit)

    def refresh(reschedule=True):
        now = time.time()
        with collector.lock:
            snap = json.loads(json.dumps(collector.snapshot, default=str))
        revit = snap.get("revit") or {}
        sessions = snap.get("sessions") or []

        # Which Code sessions talk to which Revit (by routed port)
        procs = revit.get("processes") or []
        by_port = _instances_by_port(snap)
        links = {}                 # session pid -> (text, tag, instance)
        routed = {}                # port -> [session names]
        for s in sessions:
            lk = _session_link(s, by_port)
            links[s["pid"]] = lk
            if lk[2] is not None:
                routed.setdefault(lk[2]["port"], []).append(s["name"])

        # Revit panel (one row per listener)
        instances = revit.get("instances") or []
        n_up = sum(1 for i in instances if i.get("reachable"))
        n_docs = sum(1 for i in instances if i.get("document_title"))
        if not instances and not procs:
            doc_var.set("Revit is not running")
        elif not n_up:
            doc_var.set("%d Revit process%s running, no MCP listener reachable" % (len(procs), "" if len(procs) == 1 else "es"))
        else:
            doc_var.set("%d Revit listener%s up, %d with a document open, %d Revit process%s" % (
                n_up, "" if n_up == 1 else "s", n_docs, len(procs), "" if len(procs) == 1 else "es"))
        rsel = rtree.selection()
        rsel_port = rtree.item(rsel[0], "values")[0] if rsel else None
        rtree.delete(*rtree.get_children())
        rrows = []
        for inst in instances:
            title = inst.get("document_title")
            if inst.get("listener") == "ok":
                lst = "healthy" if title else (inst.get("listener_error") or "no document")
                tag = "connected" if title else "partial"
            elif inst.get("reachable"):
                lst, tag = inst.get("listener") or "error", "partial"
            else:
                lst, tag = "not reachable", "down"
            names = routed.get(inst["port"]) or []
            vals = (inst["port"], inst.get("version") or "?", inst.get("pid") or "?",
                    title or "(no active document)",
                    _fmt_clock(inst.get("document_since")) if title else "-",
                    _fmt_elapsed(inst.get("document_since"), now) if title else "-",
                    lst, ", ".join(names) if names else "-")
            rrows.append((vals, tag, inst))
        for vals, tag, inst in sort_rows(rtree, rrows):
            item = rtree.insert("", "end", values=vals, tags=(tag,))
            wrapped[rtree]["raw"][item] = vals
            if rsel_port is not None and str(inst["port"]) == str(rsel_port):
                rtree.selection_set(item)
        rtree.configure(height=max(1, min(4, len(instances))))
        rewrap(rtree)

        # Sessions table (rebuild in place, keep selection)
        selected_host = None
        sel = tree.selection()
        if sel:
            selected_host = row_links.get(sel[0])
        tree.delete(*tree.get_children())
        row_links.clear()
        crows = []
        for s in sessions:
            b = s.get("bridge")
            mcp_txt, tag, inst = links[s["pid"]]
            if b:
                since, elapsed = _fmt_clock(b.get("create_time")), _fmt_elapsed(b.get("create_time"), now)
                route = b.get("route") or {}
                if inst is not None:
                    rv_txt = "%s (%s)" % (inst.get("version") or "?", inst["port"])
                    doc_txt = inst.get("document_title") or "(no active document)"
                    # a doc: target whose document is no longer the active one in that Revit
                    if route.get("document_title") and route["document_title"] != inst.get("document_title"):
                        doc_txt += "   [routed to %s]" % route["document_title"]
                elif route.get("port"):
                    rv_txt, doc_txt = "port %s" % route["port"], route.get("document_title") or "-"
                else:
                    rv_txt, doc_txt = "-", "-"
            else:
                since, elapsed = "-", "-"
                rv_txt, doc_txt = "-", "-"
            label = s["name"]
            if s.get("kind") and s["kind"] != "interactive":
                label += "  [%s]" % s["kind"]
            state = s.get("status") or ""
            vals = (label, state, mcp_txt, rv_txt, doc_txt, since, elapsed, _short_folder(s.get("cwd")))
            crows.append((vals, tag, s))
        for vals, tag, s in sort_rows(tree, crows):
            item = tree.insert("", "end", values=vals, tags=(tag,))
            wrapped[tree]["raw"][item] = vals
            if s.get("host_id"):
                row_links[item] = LINK_FMT.format(host=s["host_id"])
            if selected_host and row_links.get(item) == selected_host:
                tree.selection_set(item)
        rewrap(tree)

        # tray icon colour + tooltip follow the overall state
        if tray["icon"] is not None:
            st = _overall_state(snap)
            if st != tray["state"]:
                try:
                    tray["icon"].icon = _icon_image(st)
                except Exception as e:
                    last_error["msg"] = "tray icon update: %s" % e
                tray["state"] = st
                set_window_icon(st)
            tip = _tray_tooltip(snap)
            if tip != tray["tip"]:
                try:
                    tray["icon"].title = tip
                except Exception:
                    pass
                tray["tip"] = tip

        n_conn = sum(1 for s in sessions if s.get("bridge"))
        msg = "%d Revit%s   |   %d session%s, %d with Bridge   |   scanned %s, Revit polled %s" % (
            len(instances), "" if len(instances) == 1 else "s",
            len(sessions), "" if len(sessions) == 1 else "s", n_conn,
            _fmt_clock(snap.get("proc_scanned_at")), _fmt_clock(snap.get("revit_polled_at")))
        errs = snap.get("errors") or []
        if errs:
            last_error["msg"] = errs[-1]
        elif snap.get("proc_scanned_at") is None:
            msg = "scanning processes…   |   Revit polled %s" % _fmt_clock(snap.get("revit_polled_at"))
        if last_error["msg"]:
            msg += "   |   " + last_error["msg"]
        if not status_var.get().startswith(("Opened", "Could not", "This session", "Switched", "Revit (PID", "No window", "No process")):
            status_var.set(msg)
        if reschedule:
            root.after(1000, refresh)

    def clear_status_later():
        # let "Opened ..." messages show for a few seconds, then resume the normal line
        if status_var.get().startswith(("Opened", "Could not", "This session", "Switched", "Revit (PID", "No window", "No process")):
            status_var.set("")
        root.after(4000, clear_status_later)

    # commands from the tray thread + "show yourself" signal from a second launch
    show_evt = _create_show_event()
    k32 = _k32() if show_evt is not None else None

    def pump():
        try:
            while True:
                cmd = cmds.get_nowait()
                if cmd == "show":
                    show_window()
                elif cmd == "refresh":
                    do_refresh()
                elif cmd == "licence":
                    show_window()
                    nb.select(tab_lic)
                elif cmd == "exit":
                    exit_app()
                    return
        except queue.Empty:
            pass
        if show_evt is not None and _event_signaled(k32, show_evt):
            show_window()
        root.after(250, pump)

    refresh()
    root.after(800, refresh_licence)
    root.after(4000, clear_status_later)
    root.after(250, pump)
    root.mainloop()


# ----------------------------------------------------------------- main ---
def main(argv):
    collector = Collector()
    if "--dump" in argv or "--selftest" in argv:
        snap = collector.once()
        text = json.dumps(snap, indent=2, default=str)
        if "--selftest" in argv:
            out = os.path.join(_base_dir(), "selftest_result.txt")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("frozen=%s psutil=%s python=%s\n" % (getattr(sys, "frozen", False), psutil.__version__, sys.version.split()[0]))
                try:
                    import pystray, PIL  # noqa: F401
                    fh.write("pystray=ok pillow=%s\n" % PIL.__version__)
                except Exception as e:
                    fh.write("tray libs missing: %s\n" % e)
                rows, source, err = fetch_allow_list()
                fh.write("licence sheet: source=%s rows=%s err=%s\n" % (source, len(rows) if rows is not None else "-", err))
                st, other = license_state()
                fh.write("machine_id=%s licence=%s%s\n" % (machine_id(), st, (" (%s)" % other) if other else ""))
                fh.write(text)
            return 0
        sys.stdout.write(text + "\n")
        return 0
    if not _single_instance_or_focus():
        return 0
    if not ensure_activated():
        return 0
    collector.start()
    run_gui(collector, start_hidden=("--tray" in argv))
    return 0



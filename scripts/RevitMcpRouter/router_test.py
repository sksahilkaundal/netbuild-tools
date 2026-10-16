"""End-to-end test of the multi-session router with FAKE Revit Routes servers.
Runs the real bridge over stdio and drives it with JSON-RPC. Works on any PC:
bridge = ROUTER_TEST_BRIDGE (.exe or .py) or revit_mcp_bridge.py beside this file;
extension = REVIT_MCP_EXTENSION_DIR, the installed pyRevit one, or extension_snapshot\\."""
import json, os, re, subprocess, sys, threading, time, tempfile, pickle
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = 48890
REG = tempfile.mkdtemp(prefix="revit_mcp_reg_")
os.environ["REVIT_MCP_BASE_PORT"] = str(BASE); os.environ["REVIT_MCP_SCAN_PORTS"] = "4"; os.environ["REVIT_MCP_REGISTRY_DIR"] = REG
EXT = next(e for e in (os.environ.get("REVIT_MCP_EXTENSION_DIR"),
                       os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mcp-server-for-revit-python.extension"),
                       os.path.join(HERE, "extension_snapshot")) if e and os.path.isfile(os.path.join(e, "tools", "__init__.py")))
os.environ["REVIT_MCP_EXTENSION_DIR"] = EXT   # the bridge child uses the same one
PY = os.path.join(EXT, r".venv\Scripts\python.exe")
if not os.path.isfile(PY):
    PY = sys.executable   # needs mcp + httpx (the build venv has them)
sys.path.insert(0, HERE)

# ---------------------------------------------------------------- fake Revit
def make_server(port, title):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path.startswith("/revit_mcp/status/"):
                body = json.dumps({"status": "active", "health": "healthy", "revit_available": bool(title),
                                   "document_title": title, "api_name": "revit_mcp"}).encode()
                self.send_response(200 if title else 503)
            else:
                body = b"not found"; self.send_response(404)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            # execute_code: answer the multi-model payloads like Revit would (two models open)
            code = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["code"]
            nonce = re.search(r"NONCE = '(\w+)'", code).group(1)
            m = re.search(r"TARGET = '([^']+)'", code)
            if m is None:
                res = [{"title": title, "active": True, "modifiable": True}, {"title": "B999_Other", "active": False, "modifiable": True}]
            else:
                res = {"ok": True, "title": m.group(1), "committed": "APPLY = True" in code, "data": {"port": port}, "nonce": nonce}
            body = json.dumps({"status": "success", "output": "task says hi\n@@RESULT:%s@@ %s" % (nonce, json.dumps(res))}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

# ------------------------------------------------------- unit: registry read
def py2_pickle(host, version, pid, port):
    # byte-exact format pyRevit (IronPython 2.7, protocol 0) writes
    NL = chr(10)
    parts = ["ccopy_reg", "_reconstructor", "p0", "(cpyrevit.routes.server.serverinfo", "RoutesServerInfo", "p1",
             "c__builtin__", "object", "p2", "Ntp3", "Rp4", "(dp5", "S'host'", "p6", "S'%s'" % host, "p7",
             "sS'version'", "p8", "S'%s'" % version, "p9", "sS'process_id'", "p10", "I%d" % pid,
             "sS'server_host'", "p11", "S''", "p12", "sS'server_port'", "p13", "I%d" % port, "sb."]
    return NL.join(parts).encode()

def register(reg_dir, pid, port, version):
    """Write the pickle pyRevit writes when a Revit's Routes server starts; returns its path."""
    path = os.path.join(reg_dir, version, "pyRevit_%s_%d_serverinfo.pickle" % (version, pid))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(py2_pickle("Autodesk Revit %s" % version, version, pid, port))
    return path

def test_registry():
    import revit_mcp_router as R
    d = REG; os.makedirs(os.path.join(d, "2026"), exist_ok=True)
    with open(os.path.join(d, "2026", "pyRevit_2026_%d_serverinfo.pickle" % os.getpid()), "wb") as fh:
        fh.write(py2_pickle("Autodesk Revit 2026.5", "2026", os.getpid(), BASE + 1))
    with open(os.path.join(d, "2026", "pyRevit_2024_999999_serverinfo.pickle"), "wb") as fh:
        fh.write(py2_pickle("dead", "2024", 999999, BASE + 2))
    R.PYREVIT_APPDATA = d
    regs = R.read_registry()
    assert regs == [{"port": BASE + 1, "pid": os.getpid(), "version": "2026", "host": "Autodesk Revit 2026.5"}], regs
    print("registry OK (live pid kept, dead pid dropped):", regs)
    R.PYREVIT_APPDATA = os.path.join(os.environ["APPDATA"], "pyRevit")
    print("real registry now:", R.read_registry())
    # two live registrations claim one port (a crashed Revit's pid reused) -> the newest pickle owns it
    d2 = tempfile.mkdtemp(prefix="revit_mcp_reg2_")
    old, new = register(d2, os.getpid(), BASE + 3, "2026"), register(d2, os.getppid(), BASE + 3, "2025")
    os.utime(old, (time.time() - 60, time.time() - 60))
    R.PYREVIT_APPDATA = d2
    assert {r["port"]: r for r in R.read_registry()}[BASE + 3]["pid"] == os.getppid()
    os.utime(new, (time.time() - 120, time.time() - 120))
    assert {r["port"]: r for r in R.read_registry()}[BASE + 3]["pid"] == os.getpid()
    print("registry OK (newest registration owns a shared port)")
    R.PYREVIT_APPDATA = d
    for k in ("auto", "port:48885", "48885", "pid:12", "version:2026", "2026", "doc:B002", "B002 AR", "title=x",
              "off", "disconnect", "none"):
        print("  parse", k, "->", R.parse_target(k))
    assert all(R.parse_target(k) == {"kind": "off"} for k in ("off", "OFF", "disconnect", "none", "unbind"))
    assert R.format_target({"kind": "off"}) == "off" and R.parse_target("auto") == {"kind": "auto"}

# ------------------------------------------------------- stdio bridge driver
class Bridge:
    def __init__(self):
        self.err = open("bridge_stderr.log", "w", encoding="utf-8")
        bridge = os.environ.get("ROUTER_TEST_BRIDGE", os.path.join(HERE, "revit_mcp_bridge.py"))
        cmd = [bridge] if bridge.lower().endswith(".exe") else [PY, bridge]
        self.p = subprocess.Popen(cmd, cwd=EXT, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=self.err, text=True, encoding="utf-8", bufsize=1)
        self.i = 0
    def call(self, method, params=None, notify=False):
        self.i += 1
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify: msg["id"] = self.i
        self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()
        if notify: return None
        while True:
            line = self.p.stdout.readline()
            if not line:
                time.sleep(1); self.err.flush()
                raise RuntimeError("bridge stdout EOF; returncode=%r; stderr tail: %s" % (self.p.poll(), open("bridge_stderr.log", encoding="utf-8").read()[-3000:]))
            r = json.loads(line)
            if r.get("id") == self.i: return r
    def tool(self, name, **args):
        r = self.call("tools/call", {"name": name, "arguments": args})
        res = r.get("result", r)
        txt = "".join(c.get("text", "") for c in res.get("content", [])) if isinstance(res, dict) else str(res)
        try:
            return json.loads(txt)
        except Exception:
            return txt
    def close(self):
        self.p.stdin.close(); self.p.wait(timeout=5)

P0, P1, P2, P3 = BASE, BASE + 1, BASE + 2, BASE + 3

def test_same_port_takeover(br):
    """12-15: a NEW Revit process on the SAME port must not inherit the old one's identity
    (2026-10-02: pid:19540 silently routed to pid 28568 on 48884), and 'off' unbinds."""
    procs = []
    def revit_proc(version):
        # a live pid standing in for Revit.exe + the pickle pyRevit writes for it on port P3
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"]); procs.append(p)
        register(REG, p.pid, P3, version)
        return p
    def restart(srv, old, version):
        srv.shutdown(); srv.server_close(); old.kill(); old.wait()   # crash: the old pickle stays behind
        new = revit_proc(version)
        srv = make_server(P3, "B007_AR_Model")                        # same port, same model
        time.sleep(3.2)                                               # let VERIFY_TTL expire
        return srv, new
    srv = None
    try:
        r1 = revit_proc("2026"); srv = make_server(P3, "B007_AR_Model")
        sel = br.tool("revit_select_session", target="pid:%d" % r1.pid)
        assert sel["session"]["port"] == P3 and sel["session"]["revit_pid"] == r1.pid, sel
        print("12 select pid:%d -> port P3" % r1.pid)

        srv, r2 = restart(srv, r1, "2026")
        s = br.tool("revit_status"); print("13 pid target after another Revit took its port ->", json.dumps(s)[:300])
        assert s["connected"] is False and ("pid %d" % r1.pid) in s["error"], s
        g = br.tool("get_revit_status"); assert "is no longer running" in str(g), g
        docs = br.tool("revit_list_documents"); assert not docs["success"] and "is no longer running" in docs["error"], docs
        ls = br.tool("revit_list_sessions")
        assert ls["current"] is None and [x["revit_pid"] for x in ls["sessions"]] == [r2.pid], ls
        st = [json.load(open(os.path.join(SD, f), encoding="utf-8")) for f in os.listdir(SD) if f.endswith(".json")]
        mine = [x for x in st if x.get("target") == "pid:%d" % r1.pid]
        assert mine and not mine[0]["routed"] and mine[0]["revit_pid"] is None, st
        print("   refused on every tool path; current=None; list shows pid %d; tray state unrouted" % r2.pid)

        sel = br.tool("revit_select_session", target="version:2026"); assert sel["session"]["revit_pid"] == r2.pid, sel
        srv, r3 = restart(srv, r2, "2025")
        s = br.tool("revit_status"); print("14 version:2026 after a 2025 took its port ->", json.dumps(s)[:200])
        assert s["connected"] is False and "version:2026" in s["error"], s
        sel = br.tool("revit_select_session", target="port:%d" % P3)
        assert sel["session"]["revit_pid"] == r3.pid and sel["session"]["revit_version"] == "2025", sel
        srv, r4 = restart(srv, r3, "2025")
        s = br.tool("revit_status"); assert s["connected"] and s["session"]["revit_pid"] == r4.pid, s
        print("   port: target follows the port and reports the NEW pid %d" % r4.pid)

        sel = br.tool("revit_select_session", target="off"); print("15 select off ->", json.dumps(sel)[:160])
        assert sel["target"] == "off" and sel["session"] is None, sel
        s = br.tool("revit_status"); assert not s["connected"] and "disconnected" in s["error"], s
        g = br.tool("get_revit_status"); assert "disconnected" in str(g), g
        mm = br.tool("revit_run_on_documents", titles=["B007"], code="x"); assert not mm["ok"] and "disconnected" in json.dumps(mm), mm
        ls = br.tool("revit_list_sessions")
        assert ls["target"] == "off" and ls["current"] is None and [x["port"] for x in ls["sessions"]] == [P3], ls
        sel = br.tool("revit_select_session", target="auto"); assert sel["session"]["port"] == P3, sel
        print("   every tool refused while off; auto reconnects")
    finally:
        if srv:
            srv.shutdown(); srv.server_close()
        for p in procs:
            p.kill(); p.wait()

SD = os.path.join(os.environ["LOCALAPPDATA"], "RevitStatus", "router")

def main():
    test_registry()
    a = make_server(P0, "B002_AR_Model"); b = make_server(P1, "B004_AR_Model")
    br = Bridge()
    r = br.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
    assert "result" in r, r
    br.call("notifications/initialized", notify=True)
    names = [t["name"] for t in br.call("tools/list")["result"]["tools"]]
    assert "revit_list_sessions" in names and "revit_select_session" in names, names
    print("tools:", len(names), "incl. session tools")

    t0 = time.time(); s = br.tool("revit_status"); print("1 revit_status (2 Revits, auto) %.2fs ->" % (time.time()-t0), json.dumps(s)[:300])
    assert s["connected"] is False and "2 Revit sessions match" in s["error"], s

    ls = br.tool("revit_list_sessions"); print("2 list ->", json.dumps(ls)[:400])
    assert sorted(x["port"] for x in ls["sessions"]) == [P0, P1]
    assert [x for x in ls["sessions"] if x["port"] == P1][0]["revit_version"] == "2026", "registry enrichment failed"

    sel = br.tool("revit_select_session", target="doc:B004"); print("3 select doc:B004 ->", json.dumps(sel)[:300])
    assert sel["session"]["port"] == P1, sel

    s = br.tool("revit_status"); assert s["connected"] and s["session"]["port"] == P1, s; print("4 status routed to P1 OK")
    g = br.tool("get_revit_status"); print("5 get_revit_status (via call_revit_route) ->", str(g)[:160])
    assert "B004" in str(g)

    # several models in the routed Revit: list, then run by title (must hit P1 only)
    docs = br.tool("revit_list_documents"); print("5a list_documents ->", json.dumps(docs)[:200])
    assert docs["success"] and [d["title"] for d in docs["documents"]] == ["B004_AR_Model", "B999_Other"], docs
    mm = br.tool("revit_run_on_documents", titles=["B004", "B999"], code="result = {}")
    print("5b run_on_documents (dry run) ->", json.dumps(mm)[:300])
    assert mm["ok"] and mm["models_ok"] == "2/2" and all(r["data"]["port"] == P1 and not r["committed"] for r in mm["results"]), mm
    assert mm["results"][0]["output"] == "task says hi", mm
    mm = br.tool("revit_run_on_documents", titles=["B"], code="x")
    assert not mm["ok"] and "ambiguous" in mm["error"], mm
    mm = br.tool("revit_run_on_documents", titles=["B999"], code="x", apply=True)
    assert mm["ok"] and mm["unsynced_models"] == ["B999_Other"], mm
    print("5c ambiguous refused, apply lists unsynced OK")

    # Revit "restarts" on a different port with the same document -> follow it
    b.shutdown(); b.server_close(); time.sleep(0.3)
    c = make_server(P2, "B004_AR_Model")
    time.sleep(3.2)  # let VERIFY_TTL expire
    t0 = time.time(); s = br.tool("revit_status"); print("6 after restart on P2 (%.2fs) ->" % (time.time()-t0), json.dumps(s)[:300])
    assert s["connected"] and s["session"]["port"] == P2, s

    # document switched away in that Revit -> doc target must refuse
    c.shutdown(); c.server_close(); time.sleep(0.3); c = make_server(P2, "B005_AR_Model"); time.sleep(3.2)
    s = br.tool("revit_status"); print("7 doc switched to B005 ->", json.dumps(s)[:300])
    assert s["connected"] is False and "B004" in s["error"], s

    sel = br.tool("revit_select_session", target="port:%d" % P0); assert sel["session"]["document_title"] == "B002_AR_Model", sel
    print("8 select port:P0 ->", sel["session"])
    sel = br.tool("revit_select_session", target="auto"); print("9 auto with 2 up (sticky: stays on the doc it was on) ->", str(sel)[:200])
    assert sel["session"]["port"] == P0, sel

    c.shutdown(); c.server_close(); time.sleep(3.2)
    sel = br.tool("revit_select_session", target="auto"); print("10 auto with 1 up ->", sel["session"]); assert sel["session"]["port"] == P0
    a.shutdown(); a.server_close(); time.sleep(3.2)
    s = br.tool("revit_status"); print("11 none up ->", s["error"][:120]); assert not s["connected"]
    print("state files:", os.listdir(SD))
    test_same_port_takeover(br)
    br.close()
    print("\nALL PASSED")

if __name__ == "__main__":
    main()

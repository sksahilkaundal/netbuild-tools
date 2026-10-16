# -*- coding: utf-8 -*-
"""
End-to-end test of Revit MCP Remote against a fake bridge (no Revit needed):
OAuth discovery -> DCR -> passphrase sign-in -> PKCE token -> MCP tools/list + call,
refresh rotation, static token, lock-out, redirect allow-list, deny-tools,
public read-only /license page.

    py -3.14 tests\\test_remote.py
"""
import asyncio
import base64
import hashlib
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
os.environ["RMR_STATE_DIR"] = tempfile.mkdtemp(prefix="rmr_test_")

import httpx  # noqa: E402
import uvicorn  # noqa: E402

import oauth_gate  # noqa: E402
import revit_mcp_remote as rmr  # noqa: E402

PASS = "correct horse battery staple"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
failures = []


def check(name, cond, detail=""):
    print("%s %s %s" % ("PASS" if cond else "FAIL", name, detail if not cond else ""))
    if not cond:
        failures.append(name)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(store, deny=()):
    bridge = rmr.load_bridge(None, "fake_bridge")
    mcp, _ = rmr.build_mcp(bridge, deny)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(rmr.build_app(mcp, store), host="127.0.0.1", port=port,
                                           log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return "http://127.0.0.1:%d" % port, server


def pkce():
    v = secrets.token_urlsafe(48)
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, c


async def mcp_session(base, token):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(base + "/mcp", headers={"Authorization": "Bearer " + token}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            res = await s.call_tool("revit_status", {})
            return sorted(t.name for t in tools.tools), res


def main():
    store = oauth_gate.Store()
    store.data["passphrase"] = oauth_gate.hash_passphrase(PASS)
    static = "rmrs_" + secrets.token_urlsafe(32)
    store.data["static_token_sha"] = oauth_gate._sha(static)
    store.save()
    base, server = serve(store)
    c = httpx.Client(base_url=base, follow_redirects=False)

    # 1. unauthenticated MCP -> 401 + resource metadata pointer
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    check("1 unauthenticated 401", r.status_code == 401 and "resource_metadata=" in r.headers.get("www-authenticate", ""),
          r.status_code)

    # 1b. /license (and /licence): public, read-only, static product + licence text only
    for path in ("/license", "/licence"):
        r = c.get(path, headers={"Host": "abc.trycloudflare.com"})
        check("1b %s page without a token" % path, r.status_code == 200
              and r.headers.get("content-type", "").startswith("text/html")
              and "Netbuild Software Licence Agreement" in r.text
              and "<h1>Remote Router by Netbuild %s</h1>" % rmr.VERSION in r.text
              and "Proprietary software -- owned by Netbuild" in r.text
              and "No separate key" in r.text and "https://skaec.com" in r.text
              and "&copy; 2026 Netbuild. All rights reserved." in r.text
              and "trycloudflare" not in r.text, r.status_code)
        check("1c %s headers" % path, r.headers.get("cache-control") == "no-store"
              and r.headers.get("x-frame-options") == "DENY", dict(r.headers))
    r = c.post("/license", json={})
    check("1d /license is read-only", r.status_code == 405, r.status_code)
    r = c.get("/license/x")
    check("1e only the exact path is public", r.status_code == 401, r.status_code)

    # 2. discovery uses the PUBLIC host (tunnel) and https
    r = c.get("/.well-known/oauth-protected-resource", headers={"Host": "abc.trycloudflare.com"})
    check("2 resource metadata", r.json()["authorization_servers"] == ["https://abc.trycloudflare.com"]
          and r.json()["resource"] == "https://abc.trycloudflare.com/mcp"
          and r.json()["resource_name"] == "Remote Router by Netbuild", r.text)
    r = c.get("/.well-known/oauth-authorization-server/mcp", headers={"Host": "abc.trycloudflare.com"})
    check("2b AS metadata", r.json()["token_endpoint"] == "https://abc.trycloudflare.com/token", r.text)

    # 3. DCR: foreign redirect refused, Claude callback accepted
    r = c.post("/register", json={"redirect_uris": ["https://evil.example/cb"]})
    check("3 foreign redirect refused", r.status_code == 400, r.status_code)
    r = c.post("/register", json={"client_name": "Claude", "redirect_uris": [CALLBACK]})
    check("3b register", r.status_code == 201, r.text)
    cid = r.json()["client_id"]

    # 4. authorize page, wrong passphrase, right passphrase
    v, ch = pkce()
    q = {"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "code_challenge": ch,
         "code_challenge_method": "S256", "state": "xyz", "scope": "revit"}
    r = c.get("/authorize", params=q)
    check("4 sign-in page", r.status_code == 200 and "passphrase" in r.text, r.status_code)
    check("4a sign-in page branding", "<h1>Remote Router by Netbuild</h1>" in r.text
          and "<title>Remote Router by Netbuild - sign in</title>" in r.text
          and "&copy; 2026 Netbuild. All rights reserved." in r.text
          and '<a href="/license" target="_blank" rel="noopener">Licence</a>' in r.text, r.text)
    r = c.get("/authorize", params=dict(q, code_challenge_method="plain"))
    check("4b plain PKCE refused", r.status_code == 400, r.status_code)
    r = c.post("/authorize", data=dict(q, passphrase="nope"))
    check("4c wrong passphrase", r.status_code == 401, r.status_code)
    r = c.post("/authorize", data=dict(q, passphrase=PASS))
    loc = urlparse(r.headers.get("location", ""))
    qs = parse_qs(loc.query)
    check("4d redirect with code+state", r.status_code == 302 and qs.get("state") == ["xyz"] and "code" in qs,
          r.status_code)
    code = qs["code"][0]

    # 5. token: bad verifier, then good; code is single-use
    r = c.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": cid,
                               "redirect_uri": CALLBACK, "code_verifier": "wrong"})
    check("5 bad verifier refused", r.status_code == 400, r.text)
    # the failed attempt consumed the code (single use) -> get a new one
    r = c.post("/authorize", data=dict(q, passphrase=PASS))
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    r = c.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": cid,
                               "redirect_uri": CALLBACK, "code_verifier": v})
    check("5b token issued", r.status_code == 200 and r.json().get("access_token"), r.text)
    tok = r.json()
    r = c.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": cid,
                               "redirect_uri": CALLBACK, "code_verifier": v})
    check("5c code single-use", r.status_code == 400, r.status_code)

    # 6. MCP over the gate with the OAuth token
    names, res = asyncio.run(mcp_session(base, tok["access_token"]))
    check("6 tools/list", names == ["execute_revit_code", "revit_status"], names)
    check("6b tool call", "B002_Fake" in str(res.content), res)

    # 7. refresh rotation
    r = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    check("7 refresh", r.status_code == 200, r.text)
    r2 = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    check("7b old refresh rejected", r2.status_code == 400, r2.status_code)

    # 8. static token works, garbage does not
    names, _ = asyncio.run(mcp_session(base, static))
    check("8 static token", "revit_status" in names, names)
    r = c.post("/mcp", headers={"Authorization": "Bearer garbage"}, json={})
    check("8b garbage token 401", r.status_code == 401 and "invalid_token" in r.headers["www-authenticate"])

    # 9. lock-out after 5 wrong passphrases (correct one then refused too)
    for _ in range(5):
        c.post("/authorize", data=dict(q, passphrase="nope"))
    r = c.post("/authorize", data=dict(q, passphrase=PASS))
    check("9 lock-out", r.status_code == 429, r.status_code)

    # 10. revoke-all kills tokens
    store.revoke_all()
    r = c.post("/mcp", headers={"Authorization": "Bearer " + tok["access_token"]}, json={})
    check("10 revoke-all", r.status_code == 401, r.status_code)
    server.should_exit = True

    # 11. deny-tools hides a tool
    store2 = oauth_gate.Store()
    base2, server2 = serve(store2, deny=["execute_revit_code"])
    names, _ = asyncio.run(mcp_session(base2, static))
    check("11 deny-tools", names == ["revit_status"], names)
    server2.should_exit = True

    # 12. --no-exec hides every arbitrary-code tool (here: execute_revit_code)
    store3 = oauth_gate.Store()
    base3, server3 = serve(store3, deny=list(rmr.EXEC_TOOLS))
    names, _ = asyncio.run(mcp_session(base3, static))
    check("12 no-exec hides exec tools", "execute_revit_code" not in names and "revit_status" in names, names)
    server3.should_exit = True

    # 13. --state-dir / RMR_STATE_DIR routes the passphrase store to the chosen folder
    sd = tempfile.mkdtemp(prefix="rmr_sd_")
    saved = os.environ.get("RMR_STATE_DIR")
    try:
        os.environ["RMR_STATE_DIR"] = sd
        st = oauth_gate.Store()
        check("13 state-dir routes the store", os.path.dirname(st.path) == sd, st.path)
    finally:
        if saved is not None:
            os.environ["RMR_STATE_DIR"] = saved

    # 14. named multi-instance: {n} template expands to one hostname per slot
    hosts = rmr.slot_hosts("https://revit{n}.example.com", 3)
    check("14 slot_hosts expands template", hosts == ["revit1.example.com", "revit2.example.com", "revit3.example.com"], hosts)
    check("14b slot_hosts needs {n} for N>1", rmr.slot_hosts("https://revit.example.com", 3) is None)
    check("14c slot_hosts allows bare host for N=1", rmr.slot_hosts("https://revit.example.com", 1) == ["revit.example.com"])

    # 15. ingress config maps each hostname to its slot port + has a catch-all
    cfgp = rmr.write_ingress_config("revit-mcp", ["revit1.example.com", "revit2.example.com"], 8765)
    cfg = open(cfgp).read()
    os.remove(cfgp)
    check("15 ingress config", "tunnel: revit-mcp" in cfg and "revit1.example.com" in cfg
          and "http://127.0.0.1:8765" in cfg and "http://127.0.0.1:8766" in cfg
          and "http_status:404" in cfg, cfg)

    print("\nALL PASSED" if not failures else "\nFAILED: %s" % ", ".join(failures))
    return 1 if failures else 0


class EndToEnd(unittest.TestCase):
    """Lets `python -m unittest discover -s tests` run the checks above."""

    def test_end_to_end(self):
        self.assertEqual(main(), 0, "FAILED: %s" % ", ".join(failures))


if __name__ == "__main__":
    sys.exit(main())

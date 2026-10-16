# -*- coding: utf-8 -*-
"""
Remote Router by Netbuild - auth gate in front of the MCP endpoint.

A minimal OAuth 2.1 authorisation server (RFC 8414 metadata, RFC 7591 dynamic
client registration, PKCE S256 only, refresh-token rotation) plus RFC 9728
protected-resource metadata, so Claude on the web ("Add custom connector")
can sign in. The sign-in page asks for the passphrase set with --setup.

A static bearer token (also from --setup) is accepted too, for clients that
send headers directly (Claude Code: --header "Authorization: Bearer ...").

Everything except /healthz, /license (static product + licence text) and the
OAuth endpoints needs a valid bearer token.
Secrets are only ever stored hashed. Stdlib + starlette (ships with mcp).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode, urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import remote_about

ACCESS_TTL = 3600                 # 1 h
REFRESH_TTL = 30 * 24 * 3600      # 30 days
CODE_TTL = 300                    # 5 min
MAX_FAILS = 5                     # wrong passphrases before lock-out
LOCK_SECONDS = 15 * 60
PBKDF2_ROUNDS = 200_000

# Redirect URIs a client may register. Claude web/desktop callbacks + loopback
# (Claude Code / MCP Inspector). Extend with RMR_EXTRA_REDIRECTS (comma list).
DEFAULT_REDIRECT_PREFIXES = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "http://localhost:",
    "http://127.0.0.1:",
)

LICENSE_PATHS = ("/license", "/licence")
PUBLIC_PATHS = ("/healthz", "/register", "/authorize", "/token", "/revoke") + LICENSE_PATHS
WELL_KNOWN = "/.well-known/"
PAGE_HEADERS = {"Cache-Control": "no-store", "X-Frame-Options": "DENY"}


def _copyright_html() -> str:
    """'&copy; 2026 Netbuild. All rights reserved.'"""
    return html.escape(remote_about.COPYRIGHT).replace(u"\u00a9", "&copy;")


def license_page() -> HTMLResponse:
    """GET /license: the Licence page (product, owner, licence key, full agreement). Static text from
    remote_about only -- no request data, no state, no secrets -- so it is served without a token."""
    product = html.escape(remote_about.PRODUCT)
    head = "".join("<p>%s</p>" % html.escape(line) for line in remote_about.license_lines()[1:]
                   if line != remote_about.COPYRIGHT)
    body = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s - licence</title>
<style>body{font-family:Segoe UI,system-ui,sans-serif;background:#f4f5f7;margin:0;padding:40px 16px}
.card{max-width:720px;margin:auto;background:#fff;border-radius:10px;padding:28px;box-shadow:0 2px 10px #0002}
h1{font-size:20px;margin:0 0 6px}p{color:#444;font-size:14px;margin:4px 0}
pre{white-space:pre-wrap;font-size:13px;color:#222;background:#f8f9fa;border-radius:6px;padding:16px;margin:16px 0 0}
.foot{color:#888;font-size:12px;margin:20px 0 0}</style>
</head><body><div class="card"><h1>%s %s</h1>
%s<pre>%s</pre>
<p class="foot">%s</p></div></body></html>""" % (
        product, product, html.escape(remote_about.VERSION), head,
        html.escape(remote_about.LICENSE_TEXT.rstrip()), _copyright_html())
    return HTMLResponse(body, headers=dict(PAGE_HEADERS))


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_passphrase(passphrase: str, salt: Optional[str] = None) -> Dict:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return {"salt": salt, "rounds": PBKDF2_ROUNDS, "hash": dk.hex()}


def check_passphrase(passphrase: str, rec: Dict) -> bool:
    if not rec or not rec.get("hash"):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(rec["salt"]),
                             int(rec.get("rounds", PBKDF2_ROUNDS)))
    return hmac.compare_digest(dk.hex(), rec["hash"])


# ---------------------------------------------------------------------------
# Persistent state: %LOCALAPPDATA%\RevitMcpRemote\remote.json
# ---------------------------------------------------------------------------
def state_dir() -> str:
    return os.environ.get("RMR_STATE_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RevitMcpRemote")


class Store(object):
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(state_dir(), "remote.json")
        self._lock = threading.RLock()
        self.data: Dict = {"passphrase": None, "static_token_sha": None,
                           "clients": {}, "access": {}, "refresh": {}}
        self.codes: Dict[str, Dict] = {}          # in memory only
        self.fails: List[float] = []
        self.locked_until = 0.0
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.data.update(json.load(fh))
        except FileNotFoundError:
            pass

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            now = time.time()
            for k in ("access", "refresh"):
                self.data[k] = {h: v for h, v in self.data[k].items() if v["exp"] > now}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1)
            os.replace(tmp, self.path)

    @property
    def configured(self) -> bool:
        return bool(self.data.get("passphrase")) or bool(self.data.get("static_token_sha"))

    # -- tokens ------------------------------------------------------------
    def issue_tokens(self, client_id: str, scope: str) -> Dict:
        with self._lock:
            access = "rmra_" + secrets.token_urlsafe(32)
            refresh = "rmrr_" + secrets.token_urlsafe(32)
            now = time.time()
            self.data["access"][_sha(access)] = {"client_id": client_id, "exp": now + ACCESS_TTL, "scope": scope}
            self.data["refresh"][_sha(refresh)] = {"client_id": client_id, "exp": now + REFRESH_TTL, "scope": scope}
            self.save()
        return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL,
                "refresh_token": refresh, "scope": scope}

    def check_bearer(self, token: str) -> bool:
        if not token:
            return False
        h = _sha(token)
        static = self.data.get("static_token_sha")
        if static and hmac.compare_digest(h, static):
            return True
        rec = self.data["access"].get(h)
        return bool(rec) and rec["exp"] > time.time()

    def revoke_all(self):
        with self._lock:
            self.data["clients"], self.data["access"], self.data["refresh"] = {}, {}, {}
            self.codes.clear()
            self.save()

    # -- brute-force guard --------------------------------------------------
    def is_locked(self) -> bool:
        return time.time() < self.locked_until

    def record_fail(self):
        now = time.time()
        self.fails = [t for t in self.fails if now - t < LOCK_SECONDS] + [now]
        if len(self.fails) >= MAX_FAILS:
            self.locked_until = now + LOCK_SECONDS
            self.fails = []


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------
def _redirect_allowed(uri: str) -> bool:
    extra = [p.strip() for p in os.environ.get("RMR_EXTRA_REDIRECTS", "").split(",") if p.strip()]
    return any(uri.startswith(p) for p in DEFAULT_REDIRECT_PREFIXES + tuple(extra))


def public_base(request: Request) -> str:
    """Public https origin as Claude sees it (the tunnel host), or RMR_PUBLIC_URL."""
    forced = os.environ.get("RMR_PUBLIC_URL", "").rstrip("/")
    if forced:
        return forced
    h = request.headers
    host = h.get("x-forwarded-host") or h.get("host") or "127.0.0.1"
    scheme = h.get("x-forwarded-proto") or request.url.scheme
    if not host.startswith(("127.0.0.1", "localhost")):
        scheme = "https"          # tunnels terminate TLS; never advertise http publicly
    return "%s://%s" % (scheme, host)


def _err(status: int, error: str, desc: str = "") -> JSONResponse:
    body = {"error": error}
    if desc:
        body["error_description"] = desc
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


class OAuthGate(object):
    """ASGI app: OAuth endpoints + bearer check, then hands off to the MCP app."""

    def __init__(self, inner, store: Store, mcp_path: str = "/mcp"):
        self.inner = inner
        self.store = store
        self.mcp_path = mcp_path

    # -- metadata -----------------------------------------------------------
    def resource_metadata(self, request: Request) -> JSONResponse:
        base = public_base(request)
        return JSONResponse({
            "resource": base + self.mcp_path,
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["revit"],
            "resource_name": remote_about.PRODUCT,
        })

    def as_metadata(self, request: Request) -> JSONResponse:
        base = public_base(request)
        return JSONResponse({
            "issuer": base,
            "authorization_endpoint": base + "/authorize",
            "token_endpoint": base + "/token",
            "registration_endpoint": base + "/register",
            "revocation_endpoint": base + "/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["revit"],
        })

    # -- RFC 7591 ------------------------------------------------------------
    async def register(self, request: Request) -> Response:
        try:
            meta = await request.json()
        except Exception:
            return _err(400, "invalid_client_metadata", "body must be JSON")
        uris = meta.get("redirect_uris") or []
        if not isinstance(uris, list) or not uris:
            return _err(400, "invalid_redirect_uri", "redirect_uris required")
        bad = [u for u in uris if not isinstance(u, str) or not _redirect_allowed(u)]
        if bad:
            return _err(400, "invalid_redirect_uri", "not allowed: %s" % ", ".join(map(str, bad)))
        client_id = "rmrc_" + secrets.token_urlsafe(16)
        rec = {
            "client_id": client_id,
            "client_name": str(meta.get("client_name") or "MCP client")[:100],
            "redirect_uris": uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "client_id_issued_at": int(time.time()),
        }
        with self.store._lock:
            self.store.data["clients"][client_id] = rec
            self.store.save()
        return JSONResponse(rec, status_code=201)

    # -- authorisation endpoint ----------------------------------------------
    def _validate_authz(self, p) -> Optional[str]:
        client = self.store.data["clients"].get(p.get("client_id", ""))
        if not client:
            return "Unknown client - remove and re-add the connector."
        if p.get("redirect_uri") not in client["redirect_uris"]:
            return "redirect_uri does not match the registered client."
        if p.get("response_type") != "code":
            return "response_type must be 'code'."
        if p.get("code_challenge_method") != "S256" or not p.get("code_challenge"):
            return "PKCE (S256) is required."
        return None

    def _page(self, p, error: str = "", status: int = 200) -> HTMLResponse:
        client = self.store.data["clients"].get(p.get("client_id", ""), {})
        hidden = "".join('<input type="hidden" name="%s" value="%s">' % (html.escape(k), html.escape(v))
                         for k, v in p.items() if k != "passphrase")
        err = '<p class="err">%s</p>' % html.escape(error) if error else ""
        redirect_host = html.escape(urlparse(p.get("redirect_uri", "")).netloc)
        product = html.escape(remote_about.PRODUCT)
        body = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s - sign in</title>
<style>body{font-family:Segoe UI,system-ui,sans-serif;background:#f4f5f7;margin:0;padding:40px 16px}
.card{max-width:420px;margin:auto;background:#fff;border-radius:10px;padding:28px;box-shadow:0 2px 10px #0002}
h1{font-size:20px;margin:0 0 6px}p{color:#444;font-size:14px}.err{color:#b00020}
input[type=password]{width:100%%;box-sizing:border-box;padding:10px;font-size:15px;margin:8px 0 16px}
button{background:#1f4e79;color:#fff;border:0;border-radius:6px;padding:10px 18px;font-size:15px;cursor:pointer}
.foot{color:#888;font-size:12px;margin:20px 0 0}</style>
</head><body><div class="card"><h1>%s</h1>
<p><b>%s</b> (%s) wants to drive Revit on this PC.</p>%s
<form method="post" action="/authorize">%s
<label>Passphrase<input type="password" name="passphrase" autofocus autocomplete="current-password"></label>
<button type="submit">Allow</button></form>
<p class="foot">%s &middot; <a href="/license" target="_blank" rel="noopener">Licence</a></p></div></body></html>""" % (
            product, product, html.escape(client.get("client_name", "?")), redirect_host, err, hidden,
            _copyright_html())
        return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store",
                                                                "X-Frame-Options": "DENY"})

    async def authorize(self, request: Request) -> Response:
        if request.method == "GET":
            p = dict(request.query_params)
            problem = self._validate_authz(p)
            if problem:
                return HTMLResponse("<h3>%s</h3>" % html.escape(problem), status_code=400)
            return self._page(p)

        form = await request.form()
        p = {k: str(v) for k, v in form.items()}
        problem = self._validate_authz(p)
        if problem:
            return HTMLResponse("<h3>%s</h3>" % html.escape(problem), status_code=400)
        if self.store.is_locked():
            return self._page(p, "Too many wrong passphrases - locked for 15 minutes.", 429)
        if not check_passphrase(p.get("passphrase", ""), self.store.data.get("passphrase")):
            self.store.record_fail()
            return self._page(p, "Wrong passphrase.", 401)
        self.store.fails = []
        code = secrets.token_urlsafe(32)
        self.store.codes[code] = {
            "client_id": p["client_id"], "redirect_uri": p["redirect_uri"],
            "challenge": p["code_challenge"], "scope": p.get("scope") or "revit",
            "exp": time.time() + CODE_TTL,
        }
        q = {"code": code}
        if p.get("state"):
            q["state"] = p["state"]
        sep = "&" if "?" in p["redirect_uri"] else "?"
        return RedirectResponse(p["redirect_uri"] + sep + urlencode(q), status_code=302)

    # -- token endpoint --------------------------------------------------------
    async def token(self, request: Request) -> Response:
        form = await request.form()
        f = {k: str(v) for k, v in form.items()}
        grant = f.get("grant_type")
        if grant == "authorization_code":
            rec = self.store.codes.pop(f.get("code", ""), None)
            if not rec or rec["exp"] < time.time():
                return _err(400, "invalid_grant", "code expired or unknown")
            if f.get("client_id") and f["client_id"] != rec["client_id"]:
                return _err(400, "invalid_grant", "client mismatch")
            if f.get("redirect_uri") and f["redirect_uri"] != rec["redirect_uri"]:
                return _err(400, "invalid_grant", "redirect_uri mismatch")
            verifier = f.get("code_verifier", "")
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii", "ignore")).digest())
            if not verifier or not hmac.compare_digest(digest.rstrip(b"=").decode(), rec["challenge"]):
                return _err(400, "invalid_grant", "PKCE verification failed")
            return JSONResponse(self.store.issue_tokens(rec["client_id"], rec["scope"]),
                                headers={"Cache-Control": "no-store"})
        if grant == "refresh_token":
            with self.store._lock:
                rec = self.store.data["refresh"].pop(_sha(f.get("refresh_token", "")), None)
            if not rec or rec["exp"] < time.time():
                return _err(400, "invalid_grant", "refresh token expired or unknown")
            if rec["client_id"] not in self.store.data["clients"]:
                return _err(400, "invalid_grant", "client revoked")
            return JSONResponse(self.store.issue_tokens(rec["client_id"], rec["scope"]),
                                headers={"Cache-Control": "no-store"})
        return _err(400, "unsupported_grant_type")

    async def revoke(self, request: Request) -> Response:
        form = await request.form()
        h = _sha(str(form.get("token", "")))
        with self.store._lock:
            self.store.data["access"].pop(h, None)
            self.store.data["refresh"].pop(h, None)
            self.store.save()
        return Response(status_code=200)

    # -- ASGI entry ------------------------------------------------------------
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        request = Request(scope, receive)
        path = scope["path"]
        method = scope["method"]

        response: Optional[Response] = None
        if path.startswith(WELL_KNOWN + "oauth-protected-resource"):
            response = self.resource_metadata(request)
        elif path.startswith(WELL_KNOWN + "oauth-authorization-server") or \
                path.startswith(WELL_KNOWN + "openid-configuration"):
            response = self.as_metadata(request)
        elif path == "/healthz":
            response = JSONResponse({"ok": True})
        elif path in LICENSE_PATHS and method == "GET":
            response = license_page()
        elif path == "/register" and method == "POST":
            response = await self.register(request)
        elif path == "/authorize" and method in ("GET", "POST"):
            response = await self.authorize(request)
        elif path == "/token" and method == "POST":
            response = await self.token(request)
        elif path == "/revoke" and method == "POST":
            response = await self.revoke(request)
        elif path in PUBLIC_PATHS or path.startswith(WELL_KNOWN):
            response = _err(405 if path in PUBLIC_PATHS else 404, "not_found")

        if response is not None:
            return await response(scope, receive, send)

        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not self.store.check_bearer(token):
            meta = public_base(request) + WELL_KNOWN + "oauth-protected-resource"
            challenge = 'Bearer resource_metadata="%s"' % meta
            if token:
                challenge += ', error="invalid_token"'
            response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": challenge})
            return await response(scope, receive, send)
        return await self.inner(scope, receive, send)

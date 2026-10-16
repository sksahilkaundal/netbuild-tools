"""Client for the Netbuild Licensing sheet Apps Script (NetbuildLicensing_SheetApi.gs).
Reads url + token from sheet_api.json / revitstatus_sheet_api.json next to the caller
(or REVITSTATUS_SHEET_API env var pointing at the file). Pure stdlib.

Apps Script quirk handled here: a POST to the /exec URL is answered with a 302 to a
script.googleusercontent.com URL that carries the result. Python's default redirect
handling would re-issue that as a GET without the body, so we follow it by hand and
retry the occasional transient 404/5xx Google returns on that hop.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

CONFIG_NAMES = ("sheet_api.json", "revitstatus_sheet_api.json")
UA = "RevitStatus/1.0"

# The ONE licence sheet every Netbuild app reads: "Netbuild Licensing" (its first tab is published as CSV).
LICENCE_SHEET_ID = "REMOVED"
LICENCE_SHEET_GID = 1189617866
LICENCE_SHEET_URL = "https://docs.google.com/spreadsheets/d/%s/edit#gid=%d" % (LICENCE_SHEET_ID, LICENCE_SHEET_GID)
_target = {"ok": False}      # set once the Apps Script has confirmed it writes to that sheet


def _config_paths():
    out = []
    env = os.environ.get("REVITSTATUS_SHEET_API")
    if env:
        out.append(env)
    bases = [os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None,
             os.path.dirname(os.path.abspath(__file__)), os.getcwd()]
    for b in bases:
        if b:
            out.extend(os.path.join(b, n) for n in CONFIG_NAMES)
    return out


def load_config():
    for p in _config_paths():
        try:
            with open(p, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if cfg.get("token"):
                cfg["_path"] = p
                return cfg
        except Exception:
            continue
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _read(resp):
    return resp.read().decode("utf-8", "replace")


def _post_once(url, body, timeout):
    """POST JSON; on a redirect, GET the Location. Returns (http_status, text)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        resp = _opener.open(req, timeout=timeout)
        return resp.status, _read(resp)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            r2 = urllib.request.Request(e.headers["Location"], headers={"User-Agent": UA})
            try:
                resp = _opener.open(r2, timeout=timeout)
                return resp.status, _read(resp)
            except urllib.error.HTTPError as e2:
                return e2.code, (_read(e2) if e2.fp else "")
        return e.code, (_read(e) if e.fp else "")


def target_check(timeout=20):
    """(True, "") when the Apps Script writes to the licence sheet the apps read, else (False, why).
    A script without sheet_id in its replies is the old copy bound to the retired sheet."""
    r = call("list", timeout=timeout)
    if not r.get("ok"):
        return False, r.get("error") or "no reply"
    if r.get("sheet_id") != LICENCE_SHEET_ID:
        return False, ("the sheet API writes to %s, not the Netbuild Licensing sheet the apps read - deploy "
                       "NetbuildLicensing_SheetApi.gs from that sheet (steps in its header), or edit the sheet by hand"
                       % ("spreadsheet " + r["sheet_id"] if r.get("sheet_id") else "an unknown sheet"))
    return True, ""


def call(action, timeout=20, **fields):
    """Returns the API's JSON dict; {'ok': False, 'error': ...} on any failure. Never raises.
    Any action that changes the sheet first checks, once per process, that the API writes to the licence sheet."""
    cfg = load_config()
    if not cfg:
        return {"ok": False, "error": "no sheet_api.json with a token found"}
    if not cfg.get("url"):
        return {"ok": False, "error": "sheet API url not set yet in %s" % cfg.get("_path")}
    if action != "list" and not _target["ok"]:
        ok, why = target_check(timeout)
        if not ok:
            return {"ok": False, "error": why}
        _target["ok"] = True
    body = dict(fields)
    body.update({"token": cfg["token"], "action": action})
    last = None
    for attempt in range(3):
        try:
            status, text = _post_once(cfg["url"], body, timeout)
        except Exception as e:
            last = {"ok": False, "error": "request failed: %s" % str(e).split("\n")[0]}
            time.sleep(1.5)
            continue
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            last = {"ok": False, "error": "unexpected reply: %s" % text[:200]}
        except Exception:
            last = {"ok": False, "error": "HTTP %s, non-JSON reply (web app deployed with access = Anyone?): %s" % (status, text[:160])}
        if status in (404, 429, 500, 502, 503):
            time.sleep(1.5)
            continue
        break
    return last or {"ok": False, "error": "no reply"}


def list_rows():
    return call("list")


def add_row(key, typ, note="", machine_id="", product=""):
    return call("add", key=key, type=typ, note=note, machine_id=machine_id, product=product)


def revoke(key):
    return call("revoke", key=key)


def activate(key):
    return call("activate", key=key)


def set_fields(key, **fields):
    return call("set", key=key, **fields)


def delete(key):
    return call("delete", key=key)

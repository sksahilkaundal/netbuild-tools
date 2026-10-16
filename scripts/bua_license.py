# -*- coding: utf-8 -*-
"""
Netbuild licensing core for BUA Workbook Builder.  (compiled to a .pyd for release)

Same model as the Revit MCP Router's nb_license, with its own secret/salt:
  * A KEY is issued by the developer for ONE Machine ID (HMAC of the id) and only
    ever works on that PC. A PASSWORD row activates the first PC it is used on.
  * Activation lives in %LOCALAPPDATA%\\BuaWorkbookBuilder\\license.json, HMAC-signed
    and bound to the Machine ID - copying the exe or the file to another PC does nothing.
  * Every start AND every Run re-reads the shared licence sheet (published CSV):
      - the machine's own row must be "active"  (revoke one PC = set its row to revoked)
      - KILL SWITCH: a row with Key "BUA-KILL-SWITCH". Status "revoked" disables EVERY
        copy on every PC at its next start / next Run. Status "active" (or no row) = normal.
    Offline, the last good copy of the sheet is honoured for LICENSE_CACHE_GRACE_DAYS.

Developer tools (never shipped): BuaLicenceAdmin.pyw (kill switch + keys GUI) and
RevitMcpRouter\\RevitMcpRouter_KeyGen.py --product bua.
"""
import datetime as _dt
import hashlib
import hmac
import json
import os
import socket
import sys
import time
import urllib.request


def _rt():
    """Shared Revit Tools theme (design/revittools_theme.py). GUI only."""
    try:
        import revittools_theme as rt
    except ImportError:
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(os.path.dirname(here), "design"))
        import revittools_theme as rt
    return rt


PRODUCT = "BUA Workbook Builder"
PRODUCT_CODE = "BUA"
COPYRIGHT = "© Netbuild2026 · All rights reserved"
DEVELOPER_NAME = "Sahil Kaundal (Netbuild2026)"
DEVELOPER_EMAIL = "info@skaec.com"

KILL_KEY = "BUA-KILL-SWITCH"
_KILL_NORM = KILL_KEY.replace("-", "").upper()
_KILLED_STATUSES = ("revoked", "killed", "disabled", "off")

_PW_SALT = "REMOVED"
# The signing secret is never one literal: rebuilt at run time from _K1 and a derived _K2.
_K1 = b""  # removed (rotated; see netbuild_secrets)
# A compiled copy imported from anything but our own frozen exe gets a decoy secret,
# so keys/signatures it produces or checks are invalid.
_ALLOWED_EXES = ("BUA Workbook Builder.exe",)


def _k2(n=None):
    seed = ("%s|%s|k2" % (_PW_SALT, PRODUCT)).encode("utf-8")
    out, i = b"", 0
    while len(out) < (n or len(_K1)):
        out += hashlib.sha256(seed + str(i).encode("ascii")).digest()
        i += 1
    return out[:n or len(_K1)]


def _trusted_host():
    if "__compiled__" not in globals():
        return True                       # plain source: developer machine
    frozen = getattr(sys, "frozen", False)
    exe = os.path.basename(sys.executable) if frozen else ""
    return bool(frozen) and exe in _ALLOWED_EXES


def _key_secret():
    real = bytes(a ^ b for a, b in zip(_K1, _k2()))
    if _trusted_host():
        return real
    return hashlib.sha256(real + b"decoy" + os.urandom(8)).digest()


# The ONE licence sheet every Netbuild app reads ("Netbuild Licensing", first tab published as CSV).
# Columns: Key, Type, Status, Machine_ID, Note, Product.
LICENSE_SHEET_URL = ("https://docs.google.com/spreadsheets/d/e/"
                     "REMOVED"
                     "/pub?gid=1189617866&single=true&output=csv")
LICENSE_SHEET_TIMEOUT_S = 6.0
LICENSE_CACHE_GRACE_DAYS = 3      # a killed/revoked copy kept offline stops after this many days

# The licence sheet's Apps Script (live, no publish cache). Two PUBLIC, token-less calls only:
#   GET  ?action=kill&product=BUA  -> the kill row's state (unreachable -> the published CSV decides)
#   POST {"action":"claim",...}    -> locks a one-PC password to the first PC that activates it
#                                     (the script hashes the password itself; activation needs it)
LICENCE_API_URL = ("https://script.google.com/macros/s/"
                   "REMOVED/exec")
KILL_API_TIMEOUT_S = 8.0

LICENSE_FILE = "license.json"
LICENSE_CACHE_FILE = "license_cache.json"


# ----------------------------------------------------------------------------
def license_dir():
    override = os.environ.get("BUA_LICENSE_DIR")            # tests only
    if override:
        return override
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "BuaWorkbookBuilder")


def password_hash(password):
    return hashlib.sha256((_PW_SALT + "\x1f" + password).encode("utf-8")).hexdigest()


def machine_id():
    """Stable per-PC id: Windows MachineGuid (+ hostname), shown as XXXX-XXXX-XXXX-XXXX."""
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
    raw = hashlib.sha256(("machine\x1f" + PRODUCT_CODE + "\x1f" + guid + "\x1f" + socket.gethostname().lower())
                         .encode("utf-8")).hexdigest()[:16].upper()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def machine_key(mid):
    """Developer-issued key for one Machine ID (HMAC of the id)."""
    digest = hmac.new(_key_secret(), mid.replace("-", "").upper().encode("ascii"), hashlib.sha256).hexdigest()[:20].upper()
    return "-".join(digest[i:i + 5] for i in range(0, 20, 5))


def _is_machine_key(secret, mid):
    return secret.replace("-", "").upper() == machine_key(mid).replace("-", "")


# ----------------------------------------------------------------------------
def _license_path():
    return os.path.join(license_dir(), LICENSE_FILE)


def _sign(act):
    msg = ("%s%s" % (act.get("hash", ""), act.get("machine_id", ""))).encode("utf-8")
    return hmac.new(_key_secret(), msg, hashlib.sha256).hexdigest()[:32]


def load_activations():
    try:
        with open(_license_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        out = []
        for a in data.get("activations", []):
            if not (a.get("hash") and a.get("machine_id")):
                continue
            try:
                if hmac.compare_digest(str(a.get("sig", "")).encode("utf-8"), _sign(a).encode("ascii")):
                    out.append(a)
            except Exception:
                pass
        return out
    except Exception:
        return []


def save_activations(activations):
    try:
        for a in activations:
            a["sig"] = _sign(a)
        os.makedirs(license_dir(), exist_ok=True)
        with open(_license_path(), "w", encoding="utf-8") as fh:
            json.dump({"product": PRODUCT, "copyright": COPYRIGHT, "activations": activations}, fh, indent=2)
        return True
    except Exception:
        return False


# -- online allow-list ---------------------------------------------------------
def _parse_sheet(text):
    import csv
    import io
    rows = {}
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        norm = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in r.items()}
        key = norm.get("key", "")
        if not key:
            continue
        compact = key.replace("-", "")
        entry = {"status": norm.get("status", "").lower(), "machine_id": norm.get("machine_id", ""),
                 "note": norm.get("note", ""), "product": norm.get("product", "")}
        if compact.upper() == _KILL_NORM:
            entry["type"] = "kill"
            rows["__kill__"] = entry
        elif len(compact) == 20 and compact.isalnum() and len(key) != 64:
            entry["type"] = "key"
            rows[compact.upper()] = entry
        else:
            entry["type"] = "password"
            rows[key.lower()] = entry
    return rows


def _cache_sig(fetched, rows):
    msg = ("%s|%.0f|%s" % (machine_id(), float(fetched), json.dumps(rows, sort_keys=True))).encode("utf-8")
    return hmac.new(_key_secret(), msg, hashlib.sha256).hexdigest()[:32]


def fetch_allow_list(timeout=LICENSE_SHEET_TIMEOUT_S):
    """(rows|None, source fetched|cache|none|disabled, error)"""
    if not LICENSE_SHEET_URL:
        return None, "disabled", None
    cache = os.path.join(license_dir(), LICENSE_CACHE_FILE)
    try:
        req = urllib.request.Request(LICENSE_SHEET_URL + "&_=%d" % int(time.time()),
                                     headers={"User-Agent": PRODUCT_CODE + "/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8-sig", "replace")
        if "<html" in body[:400].lower():
            raise ValueError("sheet URL returned a web page, not CSV")
        rows = _parse_sheet(body)
        try:
            os.makedirs(license_dir(), exist_ok=True)
            now = time.time()
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"fetched": now, "rows": rows, "sig": _cache_sig(now, rows)}, fh)
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
        age = (time.time() - fetched) / 86400.0
        if age <= LICENSE_CACHE_GRACE_DAYS:
            return data.get("rows", {}), "cache", err
        return None, "none", "%s (cached list is %.0f days old, past the %d-day grace)" % (err, age, LICENSE_CACHE_GRACE_DAYS)
    except Exception:
        return None, "none", err


def fetch_kill_live(timeout=KILL_API_TIMEOUT_S):
    """'killed' | 'active' | 'missing' straight from the sheet, or None if the script can't be reached."""
    if not LICENCE_API_URL:
        return None
    try:
        from urllib.parse import urlencode
        url = "%s?%s" % (LICENCE_API_URL, urlencode({"action": "kill", "product": PRODUCT_CODE, "_": int(time.time())}))
        req = urllib.request.Request(url, headers={"User-Agent": PRODUCT_CODE + "/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # GET follows Google's 302 by itself
            data = json.loads(resp.read().decode("utf-8", "replace"))
        state = data.get("kill") if data.get("ok") else None
        return state if state in ("killed", "active", "missing") else None
    except Exception:
        return None


def _post_json(url, body, timeout):
    """POST JSON to the Apps Script. Google answers with a 302 to googleusercontent.com that must be
    fetched with a GET by hand (urllib would re-send it without the body). Returns the reply dict."""
    import urllib.error

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": PRODUCT_CODE + "/1.0"})
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            resp = opener.open(urllib.request.Request(e.headers["Location"],
                                                      headers={"User-Agent": PRODUCT_CODE + "/1.0"}), timeout=timeout)
        else:
            raise
    return json.loads(resp.read().decode("utf-8", "replace"))


def claim_password(password, mid, timeout=15.0):
    """Lock a one-PC password to this PC in the live sheet.
    'claimed' (was free, now ours) | 'mine' | 'other' | 'revoked' | 'unknown' | None (unreachable)."""
    if not LICENCE_API_URL:
        return None
    for _ in range(3):
        try:
            data = _post_json(LICENCE_API_URL, {"action": "claim", "product": PRODUCT_CODE,
                                                "password": password, "machine_id": mid}, timeout)
            c = data.get("claim") if data.get("ok") else None
            if c in ("claimed", "mine", "other", "revoked", "unknown"):
                return c
        except Exception:
            pass
        time.sleep(1.5)
    return None


def _apply_live_kill(rows, live):
    """The live answer beats the (possibly stale) kill row in the published copy."""
    if rows is None or live is None:
        return rows
    rows = dict(rows)
    if live == "missing":
        rows.pop("__kill__", None)
    else:
        prev = rows.get("__kill__") or {"type": "kill", "machine_id": "", "note": ""}
        rows["__kill__"] = dict(prev, status="revoked" if live == "killed" else "active")
    return rows


def is_killed(rows):
    k = (rows or {}).get("__kill__")
    return bool(k) and k.get("status", "") in _KILLED_STATUSES


def kill_row_state(rows):
    """'killed' | 'active' | 'missing' - what the kill switch row says in `rows`."""
    k = (rows or {}).get("__kill__")
    if not k:
        return "missing"
    return "killed" if k.get("status", "") in _KILLED_STATUSES else "active"


def _row_for(rows, act, mid):
    if act["hash"].startswith("key:"):
        return rows.get(machine_key(mid).replace("-", ""))
    return rows.get(act["hash"])


# ----------------------------------------------------------------------------
FRESH_ACTIVATION_GRACE_S = 30 * 60   # a brand-new password row takes minutes to reach the published copy


def _fresh(act):
    try:
        t = _dt.datetime.strptime(act.get("activated", ""), "%Y-%m-%d %H:%M:%S")
        return 0 <= (_dt.datetime.now() - t).total_seconds() <= FRESH_ACTIVATION_GRACE_S
    except Exception:
        return False


def _verdict(rows, act, mid):
    """'ok' | 'taken' (its password is now locked to another PC) | 'revoked' - for one local activation."""
    row = _row_for(rows, act, mid)
    if row is None and not act["hash"].startswith("key:") and _fresh(act):
        return "ok"          # activation was verified live (claim) moments ago; the published copy lags
    row = row or {}
    if row.get("status") != "active":
        return "revoked"
    if not act["hash"].startswith("key:"):
        owner = (row.get("machine_id") or "").replace("-", "").upper()
        if owner and owner != mid.replace("-", "").upper():
            return "taken"
    return "ok"


def license_state(retries=3):
    """('ok'|'unactivated'|'locked'|'revoked'|'taken'|'killed'|'offline', info)"""
    mid = machine_id()
    acts = load_activations()
    mine = [a for a in acts if a["machine_id"] == mid]
    live = fetch_kill_live()             # instant and exact when the Apps Script answers
    if live == "killed":
        return "killed", {"machine_id": mid, "mode": "live"}
    rows, source, err = None, "none", None
    verdicts = []
    for i in range(max(1, retries)):     # a just-edited published sheet can serve a stale copy for minutes
        rows, source, err = fetch_allow_list()
        rows = _apply_live_kill(rows, live)
        if rows is None:
            break
        if not is_killed(rows):
            if not mine:
                break
            verdicts = [_verdict(rows, a, mid) for a in mine]
            if "ok" in verdicts:
                return "ok", {"mode": source, "machine_id": mid}
        if i < retries - 1:
            time.sleep(1.5)
    if rows is None:
        if not mine:
            return ("locked", acts[0]) if acts else ("unactivated", None)
        return "offline", {"error": err or "licence server unreachable", "machine_id": mid}
    if is_killed(rows):
        return "killed", {"machine_id": mid, "note": rows["__kill__"].get("note", "")}
    if not mine:
        return ("locked", acts[0]) if acts else ("unactivated", None)
    if "taken" in verdicts:
        return "taken", {"machine_id": mid}
    return "revoked", {"machine_id": mid}


def try_activate(secret):
    """Accept a per-machine key or a one-PC password -> (ok, message).
    A password is locked to the first PC that activates it (claimed live in the sheet)."""
    secret = (secret or "").strip()
    if not secret:
        return False, "Enter the password or key."
    mid = machine_id()
    acts = load_activations()
    is_key = _is_machine_key(secret, mid)
    live = fetch_kill_live()
    if live == "killed":
        return False, "%s has been disabled by the developer." % PRODUCT
    unreachable = ("The licence server could not be reached (%s).\n"
                   "Activation needs an internet connection; please retry.")
    if is_key:
        lookup = machine_key(mid).replace("-", "")
        rows, source, err = None, "none", None
        for _ in range(3):
            rows, source, err = fetch_allow_list()
            rows = _apply_live_kill(rows, live)
            if rows is None or ((rows.get(lookup) or {}).get("status") == "active" and not is_killed(rows)):
                break
            time.sleep(1.5)
        if source != "fetched" or rows is None:
            return False, unreachable % (err or "no connection")
        if is_killed(rows):
            return False, "%s has been disabled by the developer." % PRODUCT
        row = rows.get(lookup)
        if row is None:
            return False, "Incorrect password or key."
        if row["status"] != "active":
            return False, "This key has been revoked."
        tag = "key:" + mid
    else:
        claim = claim_password(secret, mid)
        if claim is None:
            return False, unreachable % "no answer"
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
    if not save_activations(acts):
        return False, "Activated, but the licence file could not be written."
    return True, "Activated on this machine."


STATE_TEXT = {
    "ok": "This computer is licensed.",
    "unactivated": "This computer is not activated yet.",
    "locked": "The licence on this computer was activated for another machine.",
    "revoked": "The licence for this computer has been revoked.",
    "taken": "The password used here is now activated on another PC - each password works on one PC only.",
    "killed": "This program has been disabled by the developer.",
    "offline": "The licence server could not be reached and the offline grace period is over.",
}


def status_text(state=None, info=None):
    if state is None:
        state, info = license_state()
    mid = machine_id()
    if state == "ok":
        return "Licensed (%s) · Machine ID %s" % ((info or {}).get("mode", "ok"), mid)
    if state == "offline":
        return "Licence server unreachable: %s · Machine ID %s" % ((info or {}).get("error"), mid)
    return "%s · Machine ID %s" % (STATE_TEXT.get(state, state), mid)


# ----------------------------------------------------------------------------
def ensure_activated(parent=None):
    """tk gate. Returns True when licensed (after activation if needed), False to exit."""
    state, _info = license_state()
    if state == "ok":
        return True
    return activation_dialog(parent, state)


def activation_dialog(parent=None, state=None):
    """Modal 'enter password or key' dialog. Returns True if an activation succeeded."""
    import tkinter as tk
    from tkinter import ttk

    if state is None:
        state = license_state()[0]
    mid = machine_id()
    own_root = parent is None
    root = tk.Tk() if own_root else parent
    rt = _rt()
    if own_root:
        root.withdraw()
        rt.apply(root)
    win = tk.Toplevel(root)
    rt.on_change(win, lambda p: win.configure(background=p["surface"]))
    win.title("%s - Licence" % PRODUCT)
    win.resizable(False, False)
    result = {"ok": False}
    reason = STATE_TEXT.get(state, state)
    if state == "ok":
        reason += " Enter a new password or key to replace the current activation."
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text=PRODUCT, font=(rt.UI, 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, text=reason, wraplength=420,
              style=rt.style_for("state-down") if state in ("killed", "revoked") else "TLabel"
              ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 8))
    ttk.Label(frm, text="Machine ID:").grid(row=2, column=0, sticky="w")
    mid_var = tk.StringVar(value=mid)
    ttk.Entry(frm, textvariable=mid_var, width=24, state="readonly").grid(row=2, column=1, sticky="w")

    def copy_mid():
        win.clipboard_clear()
        win.clipboard_append(mid)
    ttk.Button(frm, text="Copy", command=copy_mid).grid(row=2, column=2, sticky="w", padx=4)
    ttk.Label(frm, text="Password or key:").grid(row=3, column=0, sticky="w", pady=(8, 0))
    key_var = tk.StringVar()
    ent = ttk.Entry(frm, textvariable=key_var, width=32, show="•")
    ent.grid(row=3, column=1, columnspan=2, sticky="we", pady=(8, 0))
    msg = ttk.Label(frm, text="", style=rt.style_for("state-down"), wraplength=420)
    msg.grid(row=4, column=0, columnspan=3, sticky="w")

    def activate(*_):
        msg.configure(text="Checking with the licence server...")
        win.update_idletasks()
        ok, text = try_activate(key_var.get())
        if ok:
            result["ok"] = True
            win.destroy()
        else:
            msg.configure(text=text)
    ent.bind("<Return>", activate)
    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=3, sticky="e", pady=(10, 0))
    ttk.Button(btns, text="Activate", command=activate).pack(side="right", padx=4)

    def mail():
        import webbrowser
        from urllib.parse import quote
        webbrowser.open("mailto:%s?subject=%s&body=%s" % (DEVELOPER_EMAIL, quote("%s licence - Machine ID %s" % (PRODUCT, mid)),
                                                          quote("Product: %s\nMachine ID: %s\n" % (PRODUCT, mid))))
    ttk.Button(btns, text="Email developer", command=mail).pack(side="right", padx=4)
    ttk.Button(btns, text="Close" if state == "ok" else "Quit", command=win.destroy).pack(side="right", padx=4)
    ttk.Label(frm, text="%s · %s" % (DEVELOPER_NAME, DEVELOPER_EMAIL), style="Dim.TLabel").grid(
        row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Label(frm, text=COPYRIGHT, style="Faint.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry("+%d+%d" % ((win.winfo_screenwidth() - w) // 2, (win.winfo_screenheight() - h) // 2))
    win.attributes("-topmost", True)
    win.lift()
    ent.focus_set()
    win.grab_set()
    win.wait_window()
    if own_root:
        root.destroy()
    return result["ok"]

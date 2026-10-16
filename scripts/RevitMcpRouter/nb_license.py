# -*- coding: utf-8 -*-
"""
Netbuild licensing core for Revit MCP Router.  (compiled to a .pyd for release)

Rules
  * A PASSWORD (hash in ALLOWED_PASSWORD_HASHES or in the online allow-list)
    activates the first machine it is used on and is refused on any other.
  * A KEY is issued by the developer for ONE Machine ID (HMAC of the id with the
    secret compiled into this module) and only ever works there.
  * Activation is stored in %LOCALAPPDATA%\\RevitMcpRouter\\license.json, bound
    to the Machine ID (Windows MachineGuid + hostname) - copying the file to
    another PC does nothing.
  * If LICENSE_SHEET_URL is set, every start re-checks the machine's key or
    password against the published Google-Sheet CSV (revocation), with a
    LICENSE_CACHE_GRACE_DAYS offline grace. With the URL empty the product runs
    in offline mode: built-in password hashes + machine keys, no revocation.

Developer tools: RevitMcpRouter_KeyGen.py (--this-machine, --key, --hash, --new-password).
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
    """Shared Revit Tools theme (design/revittools_theme.py; bundled into the Setup exe). GUI only."""
    try:
        import revittools_theme as rt
    except ImportError:
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(here)), "design"))
        import revittools_theme as rt
    return rt

PRODUCT = "Revit MCP Router"          # part of the key derivation (_k2) and license.json - never change
PRODUCT_CODE = "RMR"
PRODUCT_DISPLAY = "Revit MCP Router by Netbuild"   # what the customer sees (titles, dialogs, About)
PUBLISHER = "SKAEC.COM"
WEBSITE = "https://skaec.com"
COPYRIGHT = "© 2026 SKAEC.COM. All rights reserved."
DEVELOPER_NAME = "Sahil Kaundal (Netbuild2026)"
DEVELOPER_EMAIL = "info@skaec.com"

_PW_SALT = "REMOVED"
# The signing secret is never stored as one literal: it is rebuilt at run time
# from two arrays (see _key_secret), so a hex-editor search on the compiled
# module does not reveal it.
_K1 = b""  # removed (rotated; see netbuild_secrets)
# _K2 is DERIVED at run time (never stored), so the two halves are not adjacent constants
# in the compiled module. A compiled copy of this module imported from a foreign
# interpreter (i.e. not one of our own frozen executables) yields a decoy secret, so
# keys/signatures it produces are invalid.
_ALLOWED_EXES = ("Revit Status.exe", "Revit Status KeyGen.exe", "RevitMcpBridge.exe", "Revit MCP Router Setup.exe")


def _k2(n=None):
    seed = ("%s|%s|k2" % (_PW_SALT, PRODUCT)).encode("utf-8")
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

# "Netbuild Licensing" Google Sheet (ONE sheet for every Netbuild app), first tab published to the web as
# CSV; columns: Key, Type, Status, Machine_ID, Note, Product. Empty = offline mode.
LICENSE_SHEET_URL = ("https://docs.google.com/spreadsheets/d/e/"
                     "REMOVED"
                     "/pub?gid=1189617866&single=true&output=csv")
LICENSE_SHEET_TIMEOUT_S = 6.0
LICENSE_CACHE_GRACE_DAYS = 7

# Built-in password hashes (RevitMcpRouter_KeyGen.py --hash "<password>").
# Used when the sheet is not configured or has never been fetched on this PC.
ALLOWED_PASSWORD_HASHES = {
    "REMOVED",
}

LICENSE_FILE = "license.json"
LICENSE_CACHE_FILE = "license_cache.json"


# ----------------------------------------------------------------------------
def license_dir():
    override = os.environ.get("RMR_LICENSE_DIR")            # tests only
    if override:
        return override
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RevitMcpRouter")


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
    """Signature over (hash, machine_id) so a hand-written or copied license.json is rejected."""
    msg = ("%s%s" % (act.get("hash", ""), act.get("machine_id", ""))).encode("utf-8")
    return hmac.new(_key_secret(), msg, hashlib.sha256).hexdigest()[:32]


def load_activations():
    try:
        with open(_license_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        acts = [a for a in data.get("activations", []) if a.get("hash") and a.get("machine_id")]
        out = []
        for a in acts:
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
        if len(compact) == 20 and compact.isalnum() and len(key) != 64:
            typ, key = "key", compact.upper()
        else:
            typ, key = "password", key.lower()
        rows[key] = {"type": typ, "status": norm.get("status", "").lower(),
                     "machine_id": norm.get("machine_id", ""), "note": norm.get("note", "")}
    return rows


def fetch_allow_list(timeout=LICENSE_SHEET_TIMEOUT_S):
    """(rows|None, source fetched|cache|none|disabled, error)"""
    if not LICENSE_SHEET_URL:
        return None, "disabled", None
    cache = os.path.join(license_dir(), LICENSE_CACHE_FILE)
    try:
        req = urllib.request.Request(LICENSE_SHEET_URL, headers={"User-Agent": PRODUCT_CODE + "/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8-sig", "replace")
        if "<html" in body[:400].lower():
            raise ValueError("sheet URL returned a web page, not CSV")
        rows = _parse_sheet(body)
        try:
            os.makedirs(license_dir(), exist_ok=True)
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
        age = (time.time() - fetched) / 86400.0
        if age <= LICENSE_CACHE_GRACE_DAYS:
            return data.get("rows", {}), "cache", err
        return None, "none", "%s (cached list is %.0f days old, past the %d-day grace)" % (err, age, LICENSE_CACHE_GRACE_DAYS)
    except Exception:
        return None, "none", err


def _cache_sig(fetched, rows):
    msg = ("%s|%.0f|%s" % (machine_id(), float(fetched), json.dumps(rows, sort_keys=True))).encode("utf-8")
    return hmac.new(_key_secret(), msg, hashlib.sha256).hexdigest()[:32]


def _row_for(rows, act, mid):
    if act["hash"].startswith("key:"):
        return rows.get(machine_key(mid).replace("-", ""))
    return rows.get(act["hash"])


# ----------------------------------------------------------------------------
# -- one-PC password lock (live, through the licence sheet's Apps Script) ----------------------
# POST {"action":"claim","product":CODE,"password":<plain>,"machine_id":MID}: the SCRIPT hashes the
# password itself (only someone who knows it can claim), finds this product's active password row
# and writes the Machine_ID if it is empty -> claimed | mine | other | revoked | unknown.
LICENCE_API_URL = ("https://script.google.com/macros/s/"
                   "REMOVED/exec")
CLAIM_PRODUCT_CODE = "RMR"
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


def license_state():
    """('ok', info) | ('unactivated', None) | ('locked', other) | ('revoked', info) | ('taken', info) | ('offline', info)"""
    mid = machine_id()
    acts = load_activations()
    mine = [a for a in acts if a["machine_id"] == mid]
    if not mine:
        return ("locked", acts[0]) if acts else ("unactivated", None)
    builtin_ok = any(a["hash"] in ALLOWED_PASSWORD_HASHES or a["hash"].startswith("key:") for a in mine)
    if not LICENSE_SHEET_URL:
        return ("ok", {"mode": "offline", "machine_id": mid}) if builtin_ok else ("revoked", {"machine_id": mid})
    rows, verdicts = None, []
    for _ in range(3):      # a just-edited published sheet can serve a stale copy for minutes
        rows, source, err = fetch_allow_list()
        if rows is None:
            break
        verdicts = [_verdict(rows, a, mid) for a in mine]
        if "ok" in verdicts:
            return "ok", {"mode": source, "machine_id": mid}
        time.sleep(1.5)
    if rows is None:
        return "offline", {"error": err or "licence server unreachable", "machine_id": mid}
    if "taken" in verdicts:
        return "taken", {"machine_id": mid}
    return "revoked", {"machine_id": mid}


def try_activate(secret):
    """Accept a per-machine key or a one-PC password -> (ok, message).
    A password is locked to the first PC that activates it (claimed live in the licence sheet)."""
    secret = (secret or "").strip()
    if not secret:
        return False, "Enter the password or key."
    mid = machine_id()
    acts = load_activations()
    is_key = _is_machine_key(secret, mid)
    if is_key:
        lookup = machine_key(mid).replace("-", "")
        rows, source, err = None, "disabled", None
        if LICENSE_SHEET_URL:
            for _ in range(3):
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
    if not save_activations(acts):
        return False, "Activated, but the licence file could not be written."
    return True, "Activated on this machine."


def status_text():
    state, info = license_state()
    mid = machine_id()
    if state == "ok":
        return "licensed (%s) · Machine ID %s" % ((info or {}).get("mode", "ok"), mid)
    if state == "unactivated":
        return "NOT ACTIVATED · Machine ID %s" % mid
    if state == "locked":
        return "licence file belongs to another machine (%s) · this Machine ID %s" % (info.get("machine_name", info.get("machine_id")), mid)
    if state == "revoked":
        return "licence REVOKED · Machine ID %s" % mid
    if state == "taken":
        return "password now activated on ANOTHER PC (one PC per password) · Machine ID %s" % mid
    return "licence server unreachable: %s · Machine ID %s" % ((info or {}).get("error"), mid)


def unlicensed_message():
    return ("%s is not activated on this PC (Machine ID %s). Run 'Revit MCP Router Setup' and enter your "
            "password or key, or email %s with the Machine ID." % (PRODUCT_DISPLAY, machine_id(), DEVELOPER_EMAIL))


# ----------------------------------------------------------------------------
def ensure_activated(parent=None):
    """tk gate. Returns True when licensed (after activation if needed), False to exit."""
    state, info = license_state()
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
    if own_root:
        root.withdraw()
        _rt().apply(root)
    rt = _rt()
    win = tk.Toplevel(root)
    rt.on_change(win, lambda p: win.configure(background=p["surface"]))
    win.title("%s - Licence" % PRODUCT_DISPLAY)
    win.resizable(False, False)
    result = {"ok": False}
    reason = {
        "ok": "This computer is licensed. Enter a new password or key to replace the current activation.",
        "unactivated": "This computer is not activated yet.",
        "locked": "The licence on this computer was activated for another machine.",
        "revoked": "The licence for this computer has been revoked.",
        "taken": "The password used here is now activated on another PC - each password works on one PC only.",
        "offline": "The licence server could not be reached and the offline grace period is over.",
    }.get(state, state)
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text=PRODUCT_DISPLAY, font=(rt.UI, 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, text=reason, wraplength=420).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 8))
    ttk.Label(frm, text="Machine ID:").grid(row=2, column=0, sticky="w")
    mid_var = tk.StringVar(value=mid)
    ttk.Entry(frm, textvariable=mid_var, width=24, state="readonly").grid(row=2, column=1, sticky="w")

    def copy_mid():
        win.clipboard_clear()
        win.clipboard_append(mid)
    ttk.Button(frm, text="Copy", command=copy_mid).grid(row=2, column=2, sticky="w", padx=4)
    ttk.Label(frm, text="Password or key:").grid(row=3, column=0, sticky="w", pady=(8, 0))
    key_var = tk.StringVar()
    ent = ttk.Entry(frm, textvariable=key_var, width=32, show="\u2022")
    ent.grid(row=3, column=1, columnspan=2, sticky="we", pady=(8, 0))
    msg = ttk.Label(frm, text="", style=rt.style_for("state-down"), wraplength=420)
    msg.grid(row=4, column=0, columnspan=3, sticky="w")

    def activate(*_):
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
        webbrowser.open("mailto:%s?subject=%s&body=%s" % (DEVELOPER_EMAIL, quote("%s licence - Machine ID %s" % (PRODUCT_DISPLAY, mid)),
                                                          quote("Product: %s\nMachine ID: %s\n" % (PRODUCT_DISPLAY, mid))))
    ttk.Button(btns, text="Email developer", command=mail).pack(side="right", padx=4)
    ttk.Button(btns, text="Close" if state == "ok" else "Quit", command=win.destroy).pack(side="right", padx=4)
    ttk.Label(frm, text="%s \u00b7 %s \u00b7 %s" % (PUBLISHER, DEVELOPER_NAME, DEVELOPER_EMAIL), style="Dim.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
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

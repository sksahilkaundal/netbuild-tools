# -*- coding: utf-8 -*-
"""Branding / licence-compatibility test for Revit MCP Router by Netbuild (any OS, no Revit needed).

    python router_branding_test.py        (or: python -m pytest router_branding_test.py)

* product name, version, owner, publisher, copyright, licence name and About / Licence content of the Setup app;
* setup_gui.LICENSE_TEXT == LICENSE.txt beside this file == the repository's root LICENSE
  (the Netbuild Software Licence Agreement);
* every value existing licences depend on is UNCHANGED (product code / name, file names and folders);
* the licence secrets (salt, key, password hashes, sheet / API URLs) are NOT in the source: they load
  from netbuild_secrets.py (written by the release build), and without it every check fails closed.
Needs tkinter (setup_gui imports it); run from source (the compiled module gives a decoy secret).
"""
import importlib
import inspect
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("RMR_LICENSE_DIR", None)

import nb_license as L  # noqa: E402
import setup_gui as G  # noqa: E402

MID = "0123-4567-89AB-CDEF"


def test_product_strings():
    assert L.PRODUCT_DISPLAY == "Revit MCP Router by Netbuild"
    assert G.APP == L.PRODUCT_DISPLAY
    assert G.VERSION == "1.3.7"
    assert L.OWNER == "Netbuild"
    assert L.PUBLISHER == "Netbuild"
    assert L.WEBSITE == "https://skaec.com"
    assert L.COPYRIGHT == u"© 2026 Netbuild. All rights reserved."
    assert L.LICENSE_NAME == "Netbuild Software Licence Agreement (proprietary)"
    assert L.DEVELOPER_EMAIL == "info@skaec.com"
    assert "Netbuild2026 ·" not in L.COPYRIGHT and "SKAEC" not in L.COPYRIGHT
    assert G.DESCRIPTION and len(G.REQUIREMENTS) >= 4
    assert any("Windows 10 or 11" in r for r in G.REQUIREMENTS)
    assert any("%d days" % L.LICENSE_CACHE_GRACE_DAYS in r for r in G.REQUIREMENTS)
    for name in ("_build_about", "_build_licence", "refresh_licence", "_change_key"):
        assert hasattr(G.SetupApp, name), name
    lic_src = inspect.getsource(G.SetupApp._build_licence)
    assert "Proprietary software -- owned by %s   |   Website: %s" in lic_src and "Copy licence" in lic_src
    assert "LICENSE_TEXT" in lic_src and "LICENSE_TEXT" not in inspect.getsource(G.SetupApp._build_about)
    assert "Licence: %s -- see the Licence tab" in inspect.getsource(G.SetupApp._build_about)


def test_license_text_equals_file():
    with open(os.path.join(HERE, "LICENSE.txt"), encoding="utf-8") as fh:
        text = fh.read()
    assert G.LICENSE_TEXT == text, "setup_gui.LICENSE_TEXT differs from LICENSE.txt"
    assert text.startswith("Netbuild Software Licence Agreement\n")
    assert "Copyright (c) 2026 Netbuild. All rights reserved." in text
    assert "Website: https://skaec.com" in text and "Revit MCP Router by Netbuild" in text
    with open(os.path.join(HERE, "..", "..", "LICENSE"), encoding="utf-8") as fh:
        assert fh.read() == text, "root LICENSE differs from LICENSE.txt"
    with open(os.path.join(HERE, "..", "RevitStatus_LICENSE.txt"), encoding="utf-8") as fh:
        assert fh.read() == text, "RevitStatus_LICENSE.txt differs from LICENSE.txt"


def test_licence_constants_unchanged():
    assert L.PRODUCT == "Revit MCP Router"                 # seed of _k2 and license.json "product"
    assert L.PRODUCT_CODE == "RMR"                         # Machine ID + sheet User-Agent
    assert L.CLAIM_PRODUCT_CODE == "RMR"
    assert L._ALLOWED_EXES == ("Revit Status.exe", "Revit Status KeyGen.exe", "RevitMcpBridge.exe", "Revit MCP Router Setup.exe")
    assert L.LICENSE_FILE == "license.json"
    assert L.LICENSE_CACHE_FILE == "license_cache.json"
    assert L.LICENSE_CACHE_GRACE_DAYS == 7
    assert L.FRESH_ACTIVATION_GRACE_S == 1800
    assert os.path.basename(L.license_dir()) == "RevitMcpRouter"

# The licence secrets (salt, key, password hashes, sheet / API URLs) are not in the repository: they come from
# netbuild_secrets.py, written by the release build. These tests swap in a fake netbuild_secrets module.
FAKE = {"RMR": {"pw_salt": "test-salt", "k1": "0f" * 32,
                 "password_hashes": ["ab" * 32], "sheet_url": "https://example.invalid/sheet.csv",
                 "api_url": "https://example.invalid/exec"}}


def _load(secrets):
    """Re-import nb_license with netbuild_secrets.SECRETS == secrets (None: no netbuild_secrets module)."""
    saved = sys.modules.get("netbuild_secrets")
    if secrets is None:
        sys.modules["netbuild_secrets"] = None          # import raises ImportError
    else:
        sys.modules["netbuild_secrets"] = types.SimpleNamespace(SECRETS=secrets)
    try:
        return importlib.reload(L)
    finally:
        if saved is None:
            sys.modules.pop("netbuild_secrets", None)
        else:
            sys.modules["netbuild_secrets"] = saved


def test_secrets_not_in_source():
    with open(L.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "from netbuild_secrets import SECRETS" in src
    assert re.search(r'_PW_SALT\s*=\s*"[^"]', src) is None, "salt literal in source"
    assert re.search(r'_K1\s*=\s*b["\']', src) is None, "key literal in source"
    assert re.search(r'"[0-9a-f]{64}"', src) is None, "hash literal in source"


def test_fails_closed_without_secrets():
    for secrets in (None, {}):
        M = _load(secrets)
        assert M._PW_SALT == "" and M._K1 == b""
        assert M.ALLOWED_PASSWORD_HASHES == set()
        assert M.LICENSE_SHEET_URL == "" and M.LICENCE_API_URL == ""
        assert M._key_secret() != M._key_secret(), "no secrets must give an unguessable, changing key"
    _load(FAKE)
    _load(None)


def test_keys_come_from_secrets():
    try:
        M = _load(FAKE)
        assert M._PW_SALT == "test-salt" and M._K1 == bytes.fromhex(FAKE["RMR"]["k1"])
        assert M.ALLOWED_PASSWORD_HASHES == {"ab" * 32}
        assert M.LICENSE_SHEET_URL == "https://example.invalid/sheet.csv"
        assert M.LICENCE_API_URL == "https://example.invalid/exec"
        assert M._key_secret() == M._key_secret()
        key = M.machine_key(MID)
        assert re.fullmatch(r"[0-9A-F]{5}(-[0-9A-F]{5}){3}", key) and key == M.machine_key(MID)
        assert M.password_hash("test") == M.password_hash("test") != M.password_hash("other")
        sig = M._sign({"hash": "key:" + MID, "machine_id": MID})
        assert sig == M._sign({"hash": "key:" + MID, "machine_id": MID})
        other = _load({"RMR": dict(FAKE["RMR"], k1="ff" * 32)})
        assert other.machine_key(MID) != key, "the key must depend on the secret"
    finally:
        _load(None)


def test_machine_id_derivation_unchanged():
    src = inspect.getsource(L.machine_id)
    assert '("machine\\x1f" + PRODUCT_CODE + "\\x1f" + guid + "\\x1f" + socket.gethostname().lower())' in src
    assert r'r"SOFTWARE\Microsoft\Cryptography"' in src and '"MachineGuid"' in src


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
        try:
            fn()
            print("ok    " + name)
        except AssertionError as e:
            failed += 1
            print("FAIL  %s: %s" % (name, e))
    print("ALL PASSED" if not failed else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)

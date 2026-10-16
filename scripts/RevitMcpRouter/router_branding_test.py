# -*- coding: utf-8 -*-
"""Branding / licence-compatibility test for Revit MCP Router by Netbuild (any OS, no Revit needed).

    python router_branding_test.py        (or: python -m pytest router_branding_test.py)

* product name, version, publisher, copyright and About content of the Setup app;
* setup_gui.LICENSE_TEXT == LICENSE.txt beside this file;
* every value existing licences depend on is UNCHANGED: salts, product names/codes used in the
  key derivation and the sheet, file names, the sheet / API URLs, the secret, and the outputs of
  password_hash / machine_key / _sign for fixed inputs (golden values from v1.3.6). If one of these
  fails, existing customers' keys, passwords or activations would stop working - fix the code,
  never the expected value.
Needs tkinter (setup_gui imports it); run from source (the compiled module gives a decoy secret).
"""
import hashlib
import inspect
import os
import sys

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
    assert L.PUBLISHER == "SKAEC.COM"
    assert L.WEBSITE == "https://skaec.com"
    assert L.COPYRIGHT == u"© 2026 SKAEC.COM. All rights reserved."
    assert L.DEVELOPER_EMAIL == "info@skaec.com"
    assert "Netbuild2026 ·" not in L.COPYRIGHT
    assert G.DESCRIPTION and len(G.REQUIREMENTS) >= 4
    assert any("Windows 10 or 11" in r for r in G.REQUIREMENTS)
    assert any("%d days" % L.LICENSE_CACHE_GRACE_DAYS in r for r in G.REQUIREMENTS)
    for name in ("_build_about", "_build_licence", "refresh_licence", "_change_key"):
        assert hasattr(G.SetupApp, name), name


def test_license_text_equals_file():
    with open(os.path.join(HERE, "LICENSE.txt"), encoding="utf-8") as fh:
        text = fh.read()
    assert G.LICENSE_TEXT == text, "setup_gui.LICENSE_TEXT differs from LICENSE.txt"
    assert text.startswith("Revit MCP Router by Netbuild -- Licence Agreement\n")
    assert "Copyright (c) 2026 SKAEC.COM. All rights reserved." in text


def test_licence_constants_unchanged():
    assert L.PRODUCT == "Revit MCP Router"                 # seed of _k2 and license.json "product"
    assert L.PRODUCT_CODE == "RMR"                         # Machine ID + sheet User-Agent
    assert L.CLAIM_PRODUCT_CODE == "RMR"                   # Apps Script claim
    assert L._PW_SALT == "REMOVED"
    assert L._ALLOWED_EXES == ("Revit Status.exe", "Revit Status KeyGen.exe", "RevitMcpBridge.exe", "Revit MCP Router Setup.exe")
    assert L.LICENSE_FILE == "license.json"
    assert L.LICENSE_CACHE_FILE == "license_cache.json"
    assert L.LICENSE_CACHE_GRACE_DAYS == 7
    assert L.FRESH_ACTIVATION_GRACE_S == 1800
    assert L.ALLOWED_PASSWORD_HASHES == {"REMOVED"}
    assert L.LICENSE_SHEET_URL == ("https://docs.google.com/spreadsheets/d/e/REMOVED"
                                   "REMOVED/pub?gid=1189617866&single=true&output=csv")
    assert L.LICENCE_API_URL == ("https://script.google.com/macros/s/"
                                 "REMOVED/exec")
    assert os.path.basename(L.license_dir()) == "RevitMcpRouter"


def test_key_outputs_unchanged():
    assert hashlib.sha256(L._K1).hexdigest() == "REMOVED"
    assert hashlib.sha256(L._k2()).hexdigest() == "REMOVED"
    assert hashlib.sha256(L._key_secret()).hexdigest() == "REMOVED"
    assert L.password_hash("test") == "REMOVED"
    assert L.machine_key(MID) == "A4140-32367-A1AF0-5FC70"
    assert L._sign({"hash": "key:" + MID, "machine_id": MID}) == "REMOVED"


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

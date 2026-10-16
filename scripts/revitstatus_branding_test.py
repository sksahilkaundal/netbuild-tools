# -*- coding: utf-8 -*-
"""Branding / licence-compatibility test for Revit Status by Netbuild (any OS, no Revit needed).

    python revitstatus_branding_test.py   (or: python -m pytest revitstatus_branding_test.py)

* product name, version, owner, publisher, copyright, licence name, window title, Licence / About tabs;
* revitstatus_core.LICENSE_TEXT == RevitStatus_LICENSE.txt beside this file == the repository's root LICENSE
  (the Netbuild Software Licence Agreement);
* every value existing licences depend on is UNCHANGED: salt, APP_TITLE (part of the key derivation),
  product code, file names and folders, the sheet / API URLs, the secret, and the outputs of
  password_hash / machine_key / _sign for fixed inputs (golden values from v1.2.3). If one of these
  fails, existing customers' keys, passwords or activations would stop working - fix the code,
  never the expected value.
Needs psutil (revitstatus_core imports it); run from source (the compiled module gives a decoy secret).
"""
import hashlib
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("REVITSTATUS_LICENSE_DIR", None)

import revitstatus_core as R  # noqa: E402

MID = "0123-4567-89AB-CDEF"


def test_product_strings():
    assert R.APP_DISPLAY == "Revit Status by Netbuild"
    assert R.VERSION == "1.2.4"
    assert R.WINDOW_TITLE == "Revit Status by Netbuild v1.2.4"
    assert R.OWNER == "Netbuild"
    assert R.PUBLISHER == "Netbuild"
    assert R.WEBSITE == "https://skaec.com"
    assert R.COPYRIGHT == u"© 2026 Netbuild. All rights reserved."
    assert R.LICENSE_NAME == "Netbuild Software Licence Agreement (proprietary)"
    assert R.DEVELOPER_EMAIL == "info@skaec.com"
    src = inspect.getsource(R.run_gui)
    assert "root.title(WINDOW_TITLE)" in src
    assert "Proprietary software -- owned by %s   |   Website: %s" in src and "Copy licence" in src
    assert "Licence: %s -- see the Licence tab" in src
    assert "FindWindowW(None, WINDOW_TITLE)" in inspect.getsource(R._single_instance_or_focus)


def test_license_text_equals_file():
    with open(os.path.join(HERE, "RevitStatus_LICENSE.txt"), encoding="utf-8") as fh:
        text = fh.read()
    assert R.LICENSE_TEXT == text, "revitstatus_core.LICENSE_TEXT differs from RevitStatus_LICENSE.txt"
    assert text.startswith("Netbuild Software Licence Agreement\n")
    assert "Copyright (c) 2026 Netbuild. All rights reserved." in text
    assert "Website: https://skaec.com" in text and "Revit Status by Netbuild" in text
    with open(os.path.join(HERE, "..", "LICENSE"), encoding="utf-8") as fh:
        assert fh.read() == text, "root LICENSE differs from RevitStatus_LICENSE.txt"
    with open(os.path.join(HERE, "RevitMcpRouter", "LICENSE.txt"), encoding="utf-8") as fh:
        assert fh.read() == text, "RevitMcpRouter/LICENSE.txt differs from RevitStatus_LICENSE.txt"


def test_licence_constants_unchanged():
    assert R.APP_TITLE == "Revit Status"                   # seed of _k2 and license.json "app"
    assert R._PW_SALT == "REMOVED"
    assert R.CLAIM_PRODUCT_CODE == "RS"
    assert R._ALLOWED_EXES == ("Revit Status.exe", "Revit Status KeyGen.exe", "RevitMcpBridge.exe", "Revit MCP Router Setup.exe")
    assert R.LICENSE_FILE == "license.json"
    assert R.LICENSE_CACHE_FILE == "license_cache.json"
    assert R.LICENSE_CACHE_GRACE_DAYS == 7
    assert R.FRESH_ACTIVATION_GRACE_S == 1800
    assert R.ALLOWED_PASSWORD_HASHES == {"REMOVED"}
    assert R.LICENSE_SHEET_URL == ("https://docs.google.com/spreadsheets/d/e/REMOVED"
                                   "REMOVED/pub?gid=1189617866&single=true&output=csv")
    assert R.LICENCE_API_URL == ("https://script.google.com/macros/s/"
                                 "REMOVED/exec")
    assert R.MUTEX_NAME == "Local\\RevitStatusApp.SingleInstance"
    assert R.SHOW_EVENT_NAME == "Local\\RevitStatusApp.Show"
    assert R.ROUTER_STATE_DIR.replace("\\", "/").endswith("RevitStatus/router")
    assert (R.BASE_PORT, R.SCAN_PORTS, R.STATUS_PATH) == (48884, 6, "/revit_mcp/status/")
    assert 'os.path.join(local, "RevitStatus", LICENSE_FILE)' in inspect.getsource(R._license_paths)


def test_key_outputs_unchanged():
    assert hashlib.sha256(R._K1).hexdigest() == "REMOVED"
    assert hashlib.sha256(R._k2()).hexdigest() == "REMOVED"
    assert hashlib.sha256(R._key_secret()).hexdigest() == "REMOVED"
    assert R.password_hash("test") == "REMOVED"
    assert R.machine_key(MID) == "89F07-E2A95-AD467-87EAF"
    assert R._sign({"hash": "key:" + MID, "machine_id": MID}) == "REMOVED"


def test_machine_id_derivation_unchanged():
    src = inspect.getsource(R.machine_id)
    assert '("machine\\x1f" + guid + "\\x1f" + socket.gethostname().lower())' in src
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

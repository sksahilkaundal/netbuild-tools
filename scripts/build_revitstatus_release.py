# -*- coding: utf-8 -*-
"""
Developer-only release build for Revit Status + its KeyGen (never shipped).

    py -3.14 build_revitstatus_release.py            # compile + freeze + self-test into the scratch folder
    py -3.14 build_revitstatus_release.py --deploy   # ... then mirror both apps into Portable\\ and restart the tray
    py -3.14 build_revitstatus_release.py --no-selftest   # CI (no licensed PC): compile + freeze + audit only

Steps
  1. Nuitka (zig backend) compiles revitstatus_core.py -> native .pyd (no source/bytecode ships).
     RevitStatus.pyw / RevitStatus_KeyGen_GUI.pyw stay tiny entry scripts.
  2. PyInstaller one-folder builds: "Revit Status" (tray app) and "Revit Status KeyGen" (developer only).
  3. Audit: no revitstatus_core.py/.pyc in either bundle, key secret literal absent from the .pyd.
  4. Self-test: "Revit Status.exe --selftest" must report licence=ok; KeyGen window must open.
  5. --deploy: close both apps (refuses to copy anything while one still runs - a half-copied folder
     would be synced by OneDrive), robocopy /MIR into Portable (keeping README, licence + cache, samples,
     sheet_api.json), re-sign the licence file beside the exe, restart the tray through Explorer.

Requires Python 3.14.7 (python.org, per-user install; the script refuses anything older) with:
    py -3.14 -m pip install nuitka ziglang pyinstaller psutil pystray pillow
Run it as:  py -3.14 build_revitstatus_release.py [--deploy]
"""
import os
import shutil
import subprocess
import sys
import time

PYTHON = (3, 14, 7)   # every release is built with this Python; an older one misses stdlib modules the .pyd needs
if sys.version_info[:3] < PYTHON:
    sys.exit("Build with Python %s or newer (this is %s): py -3.14 %s  -  https://www.python.org/downloads/"
             % (".".join(map(str, PYTHON)), sys.version.split()[0], os.path.basename(__file__)))

SRC = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(SRC)
SCRATCH = os.environ.get("RS_BUILD_DIR") or os.path.join(os.environ["LOCALAPPDATA"], "Temp", "rs_build")
STAGE = os.path.join(SCRATCH, "stage")
DIST = os.path.join(SCRATCH, "dist")
PORTABLE = os.path.join(PROJECT, "Portable")
APP = "Revit Status"
KEYGEN = "Revit Status KeyGen"
KEYGEN_DIR = "Revit Status KeyGen (developer only)"
CORE = "revitstatus_core"

HIDDEN = [CORE, "psutil", "pystray", "pystray._win32", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk", "PIL._tkinter_finder",
          "tkinter", "tkinter.ttk", "tkinter.messagebox", "urllib.request", "urllib.error", "csv", "hmac", "hashlib",
          "winreg", "socket", "uuid", "json", "ctypes", "threading", "queue", "datetime", "time", "webbrowser", "subprocess",
          "io", "string", "secrets", "revittools_theme"]


def run(cmd, **kw):
    print("> " + " ".join('"%s"' % c if " " in c else c for c in cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit("command failed (%d)" % r.returncode)
    return r


def compile_core():
    os.makedirs(STAGE, exist_ok=True)
    src = os.path.join(SRC, CORE + ".py")
    out = [f for f in os.listdir(STAGE) if f.startswith(CORE + ".") and f.endswith(".pyd")]
    if out and os.path.getmtime(os.path.join(STAGE, out[0])) > os.path.getmtime(src):
        print("   %s up to date" % out[0])
    else:
        # --zig: without it newer Nuitka falls back to a downloaded MinGW whose headers can be incomplete
        run([sys.executable, "-m", "nuitka", "--module", "--zig", "--assume-yes-for-downloads", "--remove-output", "--quiet",
             "--python-flag=no_docstrings", "--output-dir=" + STAGE, src])
    for f in os.listdir(STAGE):
        if f.endswith(".pyi"):
            os.remove(os.path.join(STAGE, f))
    for name in ("RevitStatus.pyw", "RevitStatus_KeyGen_GUI.pyw", "revitstatus_sheet_client.py"):
        shutil.copy2(os.path.join(SRC, name), os.path.join(STAGE, name))
    # shared Revit Tools design system (light / dark theme), imported lazily by the core
    shutil.copy2(os.path.join(PROJECT, "design", "revittools_theme.py"), os.path.join(STAGE, "revittools_theme.py"))


def freeze(name, entry, extra_hidden=()):
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--log-level", "WARN",
         "--name", name, "--distpath", DIST, "--workpath", os.path.join(SCRATCH, "work"), "--specpath", SCRATCH,
         "--paths", STAGE] + sum([["--hidden-import", h] for h in list(HIDDEN) + list(extra_hidden)], [])
        + [os.path.join(STAGE, entry)])
    app = os.path.join(DIST, name)
    for root, _, files in os.walk(app):
        for f in files:
            if f in (CORE + ".py", CORE + ".pyc", "RevitStatus.pyw"):
                sys.exit("source leaked into bundle: " + os.path.join(root, f))
    pyd = [os.path.join(root, f) for root, _, fs in os.walk(app) for f in fs if f.startswith(CORE + ".") and f.endswith(".pyd")]
    if not pyd:
        sys.exit("compiled core missing from " + app)
    data = open(pyd[0], "rb").read()
    if b"machine-key::a7c1e4" in data or b"_KEY_SECRET" in data:
        sys.exit("key secret literal visible in " + pyd[0])
    print("ok    %s: compiled core present, no source, secret literal absent" % name)
    return app


def selftest(app):
    exe = os.path.join(app, APP + ".exe")
    res = os.path.join(app, "selftest_result.txt")
    if os.path.exists(res):
        os.remove(res)
    subprocess.run([exe, "--selftest"], timeout=120)
    for _ in range(60):
        if os.path.exists(res):
            break
        time.sleep(0.5)
    txt = open(res, encoding="utf-8").read() if os.path.exists(res) else "(no selftest_result.txt)"
    head = "\n".join(txt.splitlines()[:4])
    print(head)
    if "licence=ok" not in txt or "pystray=ok" not in txt:
        sys.exit("Revit Status self-test FAILED")
    os.remove(res)


def window_opens(exe, title_part, wait=15):
    """Poll up to `wait` s: a first launch after a rebuild can be slow (antivirus scan of the new exe)."""
    import ctypes
    import ctypes.wintypes as w
    p = subprocess.Popen([exe])
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        n = u.GetWindowTextLengthW(h)
        if n and u.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            if title_part in b.value and " - File Explorer" not in b.value:   # a folder window can carry the name
                found.append(b.value)
        return True
    deadline = time.time() + wait
    while not found and time.time() < deadline:
        time.sleep(0.5)
        u.EnumWindows(cb, 0)
    subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
    if not found:
        sys.exit("no window for %s" % exe)
    print("ok    window: %s" % found[0])


def resign_license(path):
    """Existing licence files predate signed records: add the signature so they stay valid."""
    import json
    sys.path.insert(0, SRC)
    import revitstatus_core as rs
    if not os.path.isfile(path):
        return
    d = json.load(open(path, encoding="utf-8"))
    for a in d.get("activations", []):
        a["sig"] = rs._sign(a)
    json.dump(d, open(path, "w", encoding="utf-8"), indent=2)
    print("ok    re-signed %s" % path)


def _in_use(path):
    """True while a program runs from `path` (Windows refuses to open a running exe for writing)."""
    try:
        with open(path, "r+b"):
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return True


def close_apps(exes):
    """Close the apps, then refuse to deploy while any of them still runs: robocopy would stop half-way
    on its locked files. taskkill is denied for apps started outside a sandboxed host (the Claude app)."""
    for exe in exes:
        subprocess.run(["taskkill", "/F", "/IM", os.path.basename(exe)], capture_output=True)
    for _ in range(20):
        running = [os.path.basename(e) for e in exes if _in_use(e)]
        if not running:
            return
        time.sleep(0.5)
    sys.exit("%s still running and could not be closed from here - exit it (tray icon > Exit) and re-run with "
             "--deploy. Nothing was copied." % ", ".join(running))


def restart_tray(exe):
    """Through Explorer: a process started from a sandboxed (MSIX) host such as the Claude app would stay inside it.
    The Startup shortcut carries --tray; without it the app opens its window."""
    lnk = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", APP + ".lnk")
    subprocess.Popen(["explorer.exe", lnk if os.path.isfile(lnk) else exe])


def mirror(src, dst, excludes):
    r = subprocess.run(["robocopy", src, dst, "/MIR", "/XF"] + excludes + ["/NFL", "/NDL", "/NJH", "/NJS", "/R:3", "/W:2"],
                       capture_output=True, text=True)
    if r.returncode >= 8:
        sys.exit("robocopy failed: " + r.stdout[-800:] + r.stderr[-800:])
    print("ok    mirrored -> %s" % dst)


SOURCE_FILES = ["RevitStatus.pyw", "revitstatus_core.py", "revitstatus_sheet_client.py", "RevitStatus_KeyGen.py",
                "RevitStatus_KeyGen_GUI.pyw", "NetbuildLicensing_SheetApi.gs", "revitstatus_sheet_api.json",
                "build_revitstatus_release.py"]


def version():
    import re
    return re.search(r'^VERSION = "([^"]+)"', open(os.path.join(SRC, CORE + ".py"), encoding="utf-8").read(), re.M).group(1)


def archive_version(app_dst, note=""):
    """Keep this version for good: Releases\\Revit Status\\v<ver>_<date>\\ (source + both apps zipped, read-only)."""
    sys.path.insert(0, SRC)
    import release_archive
    release_archive.archive(APP, version(),
                            [(os.path.join(SRC, f), "scripts/" + f) for f in SOURCE_FILES]
                            + [(os.path.join(PROJECT, "design", "revittools_theme.py"), "design/revittools_theme.py")],
                            release=[app_dst, os.path.join(PORTABLE, KEYGEN_DIR)], note=note)


def main():
    print("== Revit Status release build -> %s" % SCRATCH)
    compile_core()
    app = freeze(APP, "RevitStatus.pyw")
    shutil.copy2(os.path.join(SRC, "RevitStatus_LICENSE.txt"), os.path.join(app, "LICENSE.txt"))   # Netbuild Software Licence Agreement
    kg = freeze(KEYGEN, "RevitStatus_KeyGen_GUI.pyw", extra_hidden=["revitstatus_sheet_client"])
    if "--no-selftest" in sys.argv:   # CI: the runner is not licensed; compile, freeze and the audit still ran
        print("   self-tests skipped (--no-selftest)")
    else:
        selftest(app)
        window_opens(os.path.join(kg, KEYGEN + ".exe"), KEYGEN)
    if "--deploy" in sys.argv:
        app_dst = os.path.join(PORTABLE, APP)
        close_apps([os.path.join(app_dst, APP + ".exe"), os.path.join(PORTABLE, KEYGEN_DIR, KEYGEN + ".exe")])
        mirror(app, app_dst, ["README.txt", "license.json", "license_cache.json"])
        resign_license(os.path.join(app_dst, "license.json"))
        resign_license(os.path.join(os.environ["LOCALAPPDATA"], "RevitStatus", "license.json"))
        mirror(kg, os.path.join(PORTABLE, KEYGEN_DIR), ["README.txt", "sheet_api.json", "license_cache.json"])
        restart_tray(os.path.join(app_dst, APP + ".exe"))
        print("ok    Revit Status restarted")
        archive_version(app_dst)
    print("== build OK")


if __name__ == "__main__":
    main()

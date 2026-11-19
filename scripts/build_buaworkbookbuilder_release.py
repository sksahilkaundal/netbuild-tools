# -*- coding: utf-8 -*-
"""
Developer-only build for BUA Workbook Builder (Portable\\BUA Workbook Builder.exe:
one file, no Python needed).

    py -3.14 build_buaworkbookbuilder_release.py            # compile + freeze + self-test into the scratch folder
    py -3.14 build_buaworkbookbuilder_release.py --deploy   # ... then replace Portable\\BUA Workbook Builder.exe

Steps
  1. Nuitka (zig backend) compiles buawb_core, BuaWorkbookBuilder_Engine and bua_license to
     native .pyd files (no source/bytecode ships; the licence check and its secret can't be
     read or simply edited out). BuaWorkbookBuilder_Launcher.pyw stays a 3-line stub.
  2. PyInstaller one-file, windowed build from the staging folder ONLY (never --paths scripts,
     or the plain .py modules would be bundled next to the .pyd).
  3. Audit: none of the three modules is in the bundle as .py/.pyc; each is present as .pyd.
  4. Self-test: "--selftest" must import everything, report all three modules compiled and a
     licence state; then the window (app, or its Licence dialog on an unlicensed PC) must open.
  5. --deploy: refuses to replace the exe while it runs; archives the new build + source in
     Releases\\BUA Workbook Builder\\; swaps the exe in one step.

Developer-only files that must NEVER ship: BuaLicenceAdmin.pyw, bua_license.py (source).
Requires Python 3.14.7 with:  py -3.14 -m pip install nuitka ziglang pyinstaller openpyxl
"""
import datetime as dt
import os
import shutil
import subprocess
import sys
import time

PYTHON = (3, 14, 7)   # every release is built with this Python; an older one misses stdlib modules the .pyd needs
if sys.version_info[:3] < PYTHON:
    sys.exit("Build with Python %s or newer (this is %s): py -3.14 %s"
             % (".".join(map(str, PYTHON)), sys.version.split()[0], os.path.basename(__file__)))

SRC = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(SRC)
SCRATCH = os.environ.get("BUAWB_BUILD_DIR") or os.path.join(os.environ["LOCALAPPDATA"], "Temp", "buawb_build")
STAGE = os.path.join(SCRATCH, "stage")
DIST = os.path.join(SCRATCH, "dist")
PORTABLE = os.path.join(PROJECT, "Portable")
APP = "BUA Workbook Builder"
ENTRY = "BuaWorkbookBuilder_Launcher.pyw"
COMPILED = ["buawb_core", "BuaWorkbookBuilder_Engine", "bua_license",
            "netbuild_secrets"]   # licence secrets: never committed; the build needs netbuild_secrets.py here
HIDDEN = COMPILED + ["revittools_theme", "openpyxl", "tkinter", "tkinter.ttk", "tkinter.filedialog",
                     "tkinter.messagebox", "tkinter.font", "queue", "threading", "subprocess", "json", "hashlib", "hmac",
                     "urllib.request", "urllib.error", "urllib.parse", "csv", "io", "socket", "uuid", "winreg",
                     "datetime", "time", "webbrowser", "re", "shutil", "tempfile", "collections", "copy", "ctypes"]
SOURCE_FILES = [ENTRY, "buawb_core.py", "BuaWorkbookBuilder_Engine.py", "bua_license.py",
                "build_buaworkbookbuilder_release.py", "BuaLicenceAdmin.pyw"]


def run(cmd, **kw):
    print("> " + " ".join('"%s"' % c if " " in c else c for c in cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit("command failed (%d)" % r.returncode)
    return r


def compile_modules():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)
    for mod in COMPILED:
        # --zig: without it newer Nuitka falls back to a downloaded MinGW whose headers can be incomplete
        run([sys.executable, "-m", "nuitka", "--module", "--zig", "--assume-yes-for-downloads", "--remove-output",
             "--quiet", "--python-flag=no_docstrings", "--output-dir=" + STAGE, os.path.join(SRC, mod + ".py")])
    for f in os.listdir(STAGE):
        if f.endswith(".pyi"):
            os.remove(os.path.join(STAGE, f))
    shutil.copy2(os.path.join(SRC, ENTRY), os.path.join(STAGE, ENTRY))
    shutil.copy2(os.path.join(PROJECT, "design", "revittools_theme.py"), os.path.join(STAGE, "revittools_theme.py"))
    for mod in COMPILED:
        if not any(f.startswith(mod + ".") and f.endswith(".pyd") for f in os.listdir(STAGE)):
            sys.exit("Nuitka produced no .pyd for " + mod)
    print("ok    compiled: %s" % ", ".join(COMPILED))


def freeze():
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--log-level", "WARN",
         "--name", APP, "--distpath", DIST, "--workpath", os.path.join(SCRATCH, "work"), "--specpath", SCRATCH,
         "--paths", STAGE, "--collect-submodules", "openpyxl"]
        + sum([["--hidden-import", h] for h in HIDDEN], []) + [os.path.join(STAGE, ENTRY)])
    exe = os.path.join(DIST, APP + ".exe")
    if not os.path.isfile(exe):
        sys.exit("no exe produced")
    return exe


def audit(exe):
    """List the one-file archive (recursively into the PYZ) - no plain module may ship."""
    r = subprocess.run([sys.executable, "-m", "PyInstaller.utils.cliutils.archive_viewer", "--list", "--recursive", "--brief", exe],
                       capture_output=True, text=True)
    listing = r.stdout
    if r.returncode != 0 or not listing.strip():
        sys.exit("archive listing failed: %s" % (r.stderr or r.stdout)[:400])
    names = [ln.strip() for ln in listing.splitlines()]
    for mod in COMPILED:
        leaked = [n for n in names if n in (mod, mod + ".py", mod + ".pyc") or n.endswith(" " + mod)]
        if leaked:
            sys.exit("source/bytecode of %s leaked into the bundle: %s" % (mod, leaked[:3]))
        if not any(mod in n and n.endswith(".pyd") for n in names):
            sys.exit("compiled %s .pyd missing from the bundle" % mod)
    for dev_only in ("BuaLicenceAdmin", "revitstatus_sheet_client"):
        if any(dev_only in n for n in names):
            sys.exit("developer-only module %s is in the bundle" % dev_only)
    print("ok    audit: %s shipped as .pyd only, no developer tools bundled" % ", ".join(COMPILED))


def window_opens(exe, title_part, wait=60):
    """Poll up to `wait` s: a one-file exe unpacks itself first, and antivirus scans a new build.
    An unlicensed PC shows the '<APP> - Licence' dialog instead of the app - both count."""
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
                found.append((h, b.value))
        return True
    deadline = time.time() + wait
    while not found and time.time() < deadline:
        time.sleep(0.5)
        u.EnumWindows(cb, 0)
    if found:
        time.sleep(2)
    hung = bool(found) and bool(u.IsHungAppWindow(found[0][0]))
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    if not found or hung:
        sys.exit("window of %s %s" % (exe, "not responding" if hung else "did not open"))
    print("ok    window: %s" % found[0][1])


def selftest(exe):
    res = os.path.join(DIST, "selftest_result.txt")
    if os.path.exists(res):
        os.remove(res)
    subprocess.run([exe, "--selftest"], timeout=240)
    txt = open(res, encoding="utf-8").read() if os.path.exists(res) else "(no selftest_result.txt)"
    print(txt)
    if "FAILED" in txt or "frozen=True" not in txt or "licence=" not in txt \
            or txt.count("compiled=True") != len(COMPILED):
        sys.exit("BUA Workbook Builder self-test FAILED")
    os.remove(res)
    window_opens(exe, APP)


def _in_use(path):
    try:
        with open(path, "r+b"):
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return True


def deploy(exe):
    sys.path.insert(0, SRC)
    import release_archive
    dst = os.path.join(PORTABLE, APP + ".exe")
    subprocess.run(["taskkill", "/F", "/IM", APP + ".exe"], capture_output=True)
    for _ in range(20):
        if not _in_use(dst):
            break
        time.sleep(0.5)
    else:
        sys.exit("%s is running and could not be closed from here - close it and re-run with --deploy. "
                 "Nothing was replaced." % dst)
    tmp = dst + ".new"
    shutil.copy2(exe, tmp)
    os.replace(tmp, dst)                         # one-step swap: never a half-written exe
    print("ok    deployed %s" % dst)
    time.sleep(1.1)                              # archive folder names carry the time: avoid a same-second clash
    release_archive.archive(APP, dt.date.today().strftime("%Y.%m.%d"),
                            [(os.path.join(SRC, f), "scripts/" + f) for f in SOURCE_FILES]
                            + [(os.path.join(PROJECT, "design", "revittools_theme.py"), "design/revittools_theme.py")],
                            release=[dst], note="built with Python %s" % sys.version.split()[0])


def main():
    print("== BUA Workbook Builder build (Python %s) -> %s" % (sys.version.split()[0], SCRATCH))
    compile_modules()
    exe = freeze()
    audit(exe)
    selftest(exe)
    if "--deploy" in sys.argv:
        deploy(exe)
    print("== build OK")


if __name__ == "__main__":
    main()

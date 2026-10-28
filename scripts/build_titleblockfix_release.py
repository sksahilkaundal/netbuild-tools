# -*- coding: utf-8 -*-
"""
Developer-only build for Title Block Fix (Portable\\Title Block Fix.exe: one file, no Python needed).

    py -3.14 build_titleblockfix_release.py            # freeze + self-test into the scratch folder
    py -3.14 build_titleblockfix_release.py --deploy   # ... then replace Portable\\Title Block Fix.exe

Steps
  1. PyInstaller one-file, windowed build of TitleBlockFix_Launcher.pyw (+ the step modules it imports
     inside functions, and the shared Revit Tools theme).
  2. Self-test: "Title Block Fix.exe --selftest" must load every step module, PyMuPDF, pywin32 and the
     profiles; then the window must open and respond.
  3. --deploy: refuses to replace the exe while it runs; archives the exe it replaces (once) and the new
     build with its source in Releases\\Title Block Fix\\; swaps the exe in one step.

Requires Python 3.14.7 (python.org, per-user install; the script refuses anything older) with:
    py -3.14 -m pip install pyinstaller pymupdf pywin32
"""
import datetime as dt
import os
import shutil
import subprocess
import sys
import time

PYTHON = (3, 14, 7)   # every release is built with this Python; an older one misses stdlib modules
if sys.version_info[:3] < PYTHON:
    sys.exit("Build with Python %s or newer (this is %s): py -3.14 %s  -  https://www.python.org/downloads/"
             % (".".join(map(str, PYTHON)), sys.version.split()[0], os.path.basename(__file__)))

SRC = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(SRC)
SCRATCH = os.environ.get("TBF_BUILD_DIR") or os.path.join(os.environ["LOCALAPPDATA"], "Temp", "tbf_build")
DIST = os.path.join(SCRATCH, "dist")
PORTABLE = os.path.join(PROJECT, "Portable")
APP = "Title Block Fix"
ENTRY = "TitleBlockFix_Launcher.pyw"
STEPS = ["TitleBlockFix_Config", "TitleBlockFix_PDF", "TitleBlockFix_DWG", "TitleBlockFix_Plot",
         "TitleBlockFix_Verify", "TitleBlockFix_VerifyGeometry"]
SOURCE_FILES = [ENTRY, "TitleBlockFix_Pipeline.py", "build_titleblockfix_release.py"] + [s + ".py" for s in STEPS]


def run(cmd, **kw):
    print("> " + " ".join('"%s"' % c if " " in c else c for c in cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit("command failed (%d)" % r.returncode)
    return r


def freeze():
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--log-level", "WARN",
         "--name", APP, "--distpath", DIST, "--workpath", os.path.join(SCRATCH, "work"), "--specpath", SCRATCH,
         "--paths", SRC, "--paths", os.path.join(PROJECT, "design"), "--hidden-import", "revittools_theme"]
        + sum([["--hidden-import", s] for s in STEPS], []) + [os.path.join(SRC, ENTRY)])
    exe = os.path.join(DIST, APP + ".exe")
    if not os.path.isfile(exe):
        sys.exit("no exe produced")
    return exe


def window_opens(exe, title, wait=40):
    """Poll up to `wait` s: a one-file exe unpacks itself first, and antivirus scans a new build."""
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
            if b.value == title:
                found.append(h)
        return True
    deadline = time.time() + wait
    while not found and time.time() < deadline:
        time.sleep(0.5)
        u.EnumWindows(cb, 0)
    if found:
        time.sleep(2)
    hung = bool(found) and bool(u.IsHungAppWindow(found[0]))
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    if not found or hung:
        sys.exit("window of %s %s" % (exe, "not responding" if hung else "did not open"))
    print("ok    window: %s" % title)


def selftest(exe):
    res = os.path.join(DIST, "selftest_result.txt")
    if os.path.exists(res):
        os.remove(res)
    subprocess.run([exe, "--selftest"], timeout=180)
    txt = open(res, encoding="utf-8").read() if os.path.exists(res) else "(no selftest_result.txt)"
    print(txt)
    if "FAILED" in txt or "frozen=True" not in txt:
        sys.exit("Title Block Fix self-test FAILED")
    os.remove(res)
    window_opens(exe, APP)


def _in_use(path):
    """True while a program runs from `path` (Windows refuses to open a running exe for writing)."""
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
    if os.path.isfile(dst):                      # the exe being replaced, kept once (no-op when already archived)
        was = dt.datetime.fromtimestamp(os.path.getmtime(dst))
        release_archive.archive(APP, was.strftime("%Y.%m.%d"), [], release=[dst], when=was,
                                note="exe as deployed before the %s rebuild (source not captured)" % dt.date.today())
    tmp = dst + ".new"
    shutil.copy2(exe, tmp)
    os.replace(tmp, dst)                         # one-step swap: never a half-written exe
    print("ok    deployed %s" % dst)
    release_archive.archive(APP, dt.date.today().strftime("%Y.%m.%d"),
                            [(os.path.join(SRC, f), "scripts/" + f) for f in SOURCE_FILES]
                            + [(os.path.join(PROJECT, "design", "revittools_theme.py"), "design/revittools_theme.py")],
                            release=[dst], note="built with Python %s" % sys.version.split()[0])


def main():
    print("== Title Block Fix build (Python %s) -> %s" % (sys.version.split()[0], SCRATCH))
    exe = freeze()
    selftest(exe)
    if "--deploy" in sys.argv:
        deploy(exe)
    print("== build OK")


if __name__ == "__main__":
    main()

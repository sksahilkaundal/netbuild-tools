# -*- coding: utf-8 -*-
"""
Developer-only release build for Revit MCP Router (never shipped).

    py -3.14 build_release.py            # compile + freeze + self-test into the scratch folder
    py -3.14 build_release.py --deploy   # ... then robocopy /MIR to Portable\\Revit MCP Router and zip
    py -3.14 build_release.py --no-selftest   # CI (no licensed PC): compile + freeze + bundle audit only

Steps
  1. Nuitka (zig backend, no MSVC needed) compiles the protected modules to native .pyd:
       revit_mcp_router, nb_license, bridge_core, install_revit_mcp_router
     -> no Python source or bytecode of these ships. Entry scripts stay tiny stubs.
  2. PyInstaller one-folder build with TWO executables sharing one _internal:
       RevitMcpBridge.exe          (console: MCP stdio server Claude launches)
       Revit MCP Router Setup.exe  (windowed: licence gate + install GUI)
  3. Self-tests: Setup --selftest, RevitMcpBridge --check, router_test.py over the exe.
  4. --deploy: mirror to Portable and zip as "Revit MCP Router v<version>.zip".

Requires Python 3.14.7 (python.org, per-user install; the script refuses anything older) with:
    py -3.14 -m pip install nuitka ziglang pyinstaller "mcp[cli]<2" httpx
Run it as:  py -3.14 build_release.py [--deploy]. Any of your PCs: the source is in OneDrive, the
scratch/build folders are per PC (%LOCALAPPDATA%).
Self-tests need this PC to be licensed (RevitMcpRouter_KeyGen.py --this-machine + a sheet row) and use the
installed pyRevit MCP extension, or extension_snapshot\\ when it is not installed.
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile

PYTHON = (3, 14, 7)   # every release is built with this Python; an older one misses stdlib modules the .pyd needs
if sys.version_info[:3] < PYTHON:
    sys.exit("Build with Python %s or newer (this is %s): py -3.14 %s  -  https://www.python.org/downloads/"
             % (".".join(map(str, PYTHON)), sys.version.split()[0], os.path.basename(__file__)))

SRC = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SRC))
SCRATCH = os.environ.get("RMR_BUILD_DIR") or os.path.join(os.environ["LOCALAPPDATA"], "Temp", "rmr_build")
STAGE = os.path.join(SCRATCH, "stage")
DIST = os.path.join(SCRATCH, "dist")
PORTABLE = os.path.join(PROJECT, "Portable")
APP_NAME = "Revit MCP Router"
COMPILED = ["revit_mcp_router", "nb_license", "multimodel_core", "bridge_core", "install_revit_mcp_router", "setup_gui",
            "netbuild_secrets"]   # licence secrets: never committed; the build needs netbuild_secrets.py here
NO_DOCSTRINGS = {"revit_mcp_router", "nb_license", "multimodel_core", "install_revit_mcp_router", "setup_gui"}   # bridge_core keeps tool docstrings

HIDDEN = [
    # what the compiled modules import (PyInstaller cannot look inside a .pyd)
    "httpx", "anyio", "anyio._backends._asyncio", "mcp", "mcp.server.fastmcp", "mcp.server.fastmcp.utilities.types",
    "urllib.request", "csv", "hmac", "hashlib", "winreg", "socket", "uuid", "json", "pickle", "copyreg",
    "ctypes", "concurrent.futures", "threading", "glob", "re", "atexit", "datetime", "shutil", "subprocess",
    "argparse", "queue", "traceback", "webbrowser", "functools", "base64", "typing",
    # stdlib used by the extension's tools/*.py (imported from disk at run time)
    "time", "os", "asyncio",
] + COMPILED          # the .pyd modules import each other; PyInstaller cannot see that
HIDDEN_GUI = ["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox", "revittools_theme"]


def run(cmd, **kw):
    print("> " + " ".join('"%s"' % c if " " in c else c for c in cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit("command failed (%d)" % r.returncode)
    return r


def version():
    src = open(os.path.join(SRC, "setup_gui.py"), encoding="utf-8").read()
    return re.search(r'VERSION = "([^"]+)"', src).group(1)


def compile_modules():
    os.makedirs(STAGE, exist_ok=True)
    for name in COMPILED:
        out = [f for f in os.listdir(STAGE) if f.startswith(name + ".") and f.endswith(".pyd")]
        src = os.path.join(SRC, name + ".py")
        if out and os.path.getmtime(os.path.join(STAGE, out[0])) > os.path.getmtime(src):
            print("   %s up to date" % out[0])
            continue
        # --zig: without it newer Nuitka falls back to a downloaded MinGW whose headers can be incomplete
        cmd = [sys.executable, "-m", "nuitka", "--module", "--zig", "--assume-yes-for-downloads", "--remove-output",
               "--quiet", "--output-dir=" + STAGE, src]
        if name in NO_DOCSTRINGS:
            cmd.insert(-1, "--python-flag=no_docstrings")
        run(cmd)
        for f in os.listdir(STAGE):          # drop the generated .pyi stubs
            if f.endswith(".pyi"):
                os.remove(os.path.join(STAGE, f))
    missing = [n for n in COMPILED if not _pyd(STAGE, n)]
    if missing:   # 2026-10-02: five .pyd vanished from the stage and v1.3.6 shipped them as bytecode
        sys.exit("compiled module(s) missing from %s after compile: %s" % (STAGE, ", ".join(missing)))


def _pyd(folder, name):
    return [f for f in os.listdir(folder) if f.startswith(name + ".") and f.endswith(".pyd")]


def stage_entries():
    shutil.copy2(os.path.join(SRC, "revit_mcp_bridge.py"), os.path.join(STAGE, "RevitMcpBridge.py"))
    shutil.copy2(os.path.join(SRC, "RevitMcpRouterSetup.pyw"), os.path.join(STAGE, "RevitMcpRouterSetup.pyw"))
    # shared Revit Tools design system (light / dark theme) for the Setup GUI
    shutil.copy2(os.path.join(PROJECT, "design", "revittools_theme.py"), os.path.join(STAGE, "revittools_theme.py"))


def write_spec():
    spec = os.path.join(STAGE, "rmr.spec")
    with open(spec, "w", encoding="utf-8") as fh:
        fh.write('''# -*- mode: python -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
hidden = %r + collect_submodules("mcp") + collect_submodules("httpx") + collect_submodules("anyio") + collect_submodules("pydantic")
hidden_gui = %r
datas = collect_data_files("mcp") + collect_data_files("certifi")
stage = %r

a_bridge = Analysis([stage + "/RevitMcpBridge.py"], pathex=[stage], hiddenimports=hidden, datas=datas, excludes=["tkinter"])
a_setup = Analysis([stage + "/RevitMcpRouterSetup.pyw"], pathex=[stage], hiddenimports=hidden + hidden_gui, datas=datas)
MERGE((a_bridge, "RevitMcpBridge", "RevitMcpBridge"), (a_setup, "RevitMcpRouterSetup", "Revit MCP Router Setup"))

pyz_b = PYZ(a_bridge.pure)
exe_b = EXE(pyz_b, a_bridge.scripts, [], exclude_binaries=True, name="RevitMcpBridge", console=True, upx=False)
pyz_s = PYZ(a_setup.pure)
exe_s = EXE(pyz_s, a_setup.scripts, [], exclude_binaries=True, name="Revit MCP Router Setup", console=False, upx=False)
coll = COLLECT(exe_b, a_bridge.binaries, a_bridge.datas, exe_s, a_setup.binaries, a_setup.datas, name=%r, upx=False)
''' % (HIDDEN, HIDDEN_GUI, STAGE.replace("\\", "/"), APP_NAME))
    return spec


def freeze(spec):
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    # cwd = SCRATCH: `-m` puts the cwd on sys.path, and from SRC PyInstaller silently packs the .py
    # source of a module whose .pyd is missing (as bytecode inside PYZ.pyz)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
         "--distpath", DIST, "--workpath", os.path.join(SCRATCH, "work"), spec], cwd=SCRATCH)
    app = os.path.join(DIST, APP_NAME)
    for leftover in ("RevitMcpBridge.py", "RevitMcpRouterSetup.pyw"):
        p = os.path.join(app, "_internal", leftover)
        if os.path.exists(p):
            os.remove(p)
    # no source of the protected modules may be in the bundle
    for root, _, files in os.walk(app):
        for f in files:
            if f in [c + ".py" for c in COMPILED] or f in [c + ".pyc" for c in COMPILED]:
                sys.exit("source leaked into bundle: " + os.path.join(root, f))
    missing = [n for n in COMPILED if not _pyd(os.path.join(app, "_internal"), n)]
    if missing:
        sys.exit("compiled module(s) missing from the bundle: " + ", ".join(missing))
    from PyInstaller.archive.readers import CArchiveReader
    for exe in ("RevitMcpBridge.exe", "Revit MCP Router Setup.exe"):
        pyz = CArchiveReader(os.path.join(app, exe)).open_embedded_archive("PYZ.pyz")
        leaked = sorted(set(COMPILED) & set(pyz.toc))
        if leaked:
            sys.exit("bytecode of protected module(s) inside %s PYZ: %s" % (exe, ", ".join(leaked)))
    print("   bundle audit: %d compiled modules as .pyd, none as source or bytecode" % len(COMPILED))
    return app


def write_readme(app, ver):
    shutil.copy2(os.path.join(SRC, "LICENSE.txt"), os.path.join(app, "LICENSE.txt"))   # Netbuild Software Licence Agreement
    with open(os.path.join(app, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("""Revit MCP Router by Netbuild  v%s                        (c) 2026 Netbuild
==============================================================================
Lets Claude Code drive ANY of several open Revit sessions (2023-2026 side by
side), chosen per chat session, reconnecting automatically after a Revit restart
and never running a command on the wrong model.

Requires on this PC: Claude Code and the Revit MCP connector add-in installed in Revit.
No admin rights needed. Licensed per computer (see the Licence tab for your Machine ID).

1. Double-click "Revit MCP Router Setup.exe".
   First run: enter the password or key you received. The Licence tab shows your
   Machine ID, the developer's contact details and the licence terms.
2. Click "Install / Reset". The app is installed under %%LOCALAPPDATA%%\\RevitMcpRouter\\app-%s
   and Claude Code is connected to it (your Claude config is backed up first).
   This folder can be deleted afterwards.
3. Start a NEW Claude Code session. In it:
      revit_list_sessions                     -> which Revit is on which port
      revit_select_session doc:<model name>   -> route this session (or version:2026 / port:48885)
   With only one Revit open nothing needs selecting.

"Restore default connection" puts Claude back on the stock connector.
"Find Revit sessions" is discovery only. Add a project folder in the box if that
project is not yet connected to Revit.

Support / licence keys: %s  (include your Machine ID from the Licence tab)
Proprietary software owned by Netbuild - https://skaec.com
(c) 2026 Netbuild. All rights reserved. Licensed per computer; not transferable; no redistribution.
Licence agreement: Netbuild Software Licence Agreement - LICENSE.txt in this folder
(also on the Setup app's Licence tab).
""" % (ver, ver, "info@skaec.com"))


def selftests(app):
    installed = os.path.join(os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mcp-server-for-revit-python.extension")
    if not os.environ.get("REVIT_MCP_EXTENSION_DIR") and not os.path.isfile(os.path.join(installed, "tools", "__init__.py")):
        os.environ["REVIT_MCP_EXTENSION_DIR"] = os.path.join(SRC, "extension_snapshot")   # PC without the extension
        print("   extension not installed here - self-tests use extension_snapshot")
    exe_setup = os.path.join(app, "Revit MCP Router Setup.exe")
    exe_bridge = os.path.join(app, "RevitMcpBridge.exe")
    res = os.path.join(app, "selftest_result.txt")
    if os.path.exists(res):
        os.remove(res)
    run([exe_setup, "--selftest"])
    import time
    for _ in range(60):
        if os.path.exists(res):
            break
        time.sleep(0.5)
    txt = open(res, encoding="utf-8").read() if os.path.exists(res) else "(no selftest_result.txt)"
    print(txt[-1500:])
    if "SELFTEST OK" not in txt:
        sys.exit("Setup self-test FAILED")
    os.remove(res)
    r = run([exe_bridge, "--check"], capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines() if l.startswith(("bridge:", "licence:", "tools (", "router:", "  port "))))
    env = dict(os.environ, ROUTER_TEST_BRIDGE=exe_bridge)
    r = subprocess.run([sys.executable, "-u", os.path.join(SRC, "router_test.py")], env=env, capture_output=True, text=True, timeout=300)
    tail = "\n".join(r.stdout.splitlines()[-3:])
    print(tail)
    if "ALL PASSED" not in r.stdout:
        print(r.stdout[-3000:]); print(r.stderr[-2000:])
        sys.exit("router_test over the exe FAILED")
    for f in ("bridge_stderr.log",):
        if os.path.exists(f):
            os.remove(f)


def _in_use(path):
    """True while a program runs from `path` (Windows refuses to open a running exe for writing)."""
    try:
        with open(path, "r+b"):
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return True


def deploy(app, ver):
    import time
    dest = os.path.join(PORTABLE, APP_NAME)
    subprocess.run(["taskkill", "/F", "/IM", "Revit MCP Router Setup.exe"], capture_output=True)
    # robocopy would stop half-way on a running exe's locked files, leaving a mixed folder that OneDrive syncs
    for _ in range(20):
        running = [e for e in ("Revit MCP Router Setup.exe", "RevitMcpBridge.exe") if _in_use(os.path.join(dest, e))]
        if not running:
            break
        time.sleep(0.5)
    else:
        sys.exit("%s is running from %s - close it and re-run with --deploy. Nothing was copied." % (", ".join(running), dest))
    r = subprocess.run(["robocopy", app, dest, "/MIR", "/NFL", "/NDL", "/NJH", "/NJS", "/R:3", "/W:2"], capture_output=True, text=True)
    if r.returncode >= 8:
        sys.exit("robocopy failed: " + r.stdout[-800:] + r.stderr[-800:])
    zpath = os.path.join(PORTABLE, "%s v%s.zip" % (APP_NAME, ver))
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(dest):
            for f in files:
                p = os.path.join(root, f)
                zf.write(p, os.path.join(APP_NAME, os.path.relpath(p, dest)))
    print("deployed: %s\nzip:      %s (%.1f MB)" % (dest, zpath, os.path.getsize(zpath) / 1e6))
    # keep this version for good: Releases\Revit MCP Router\v<ver>_<date>\ (source + zip, read-only)
    sys.path.insert(0, os.path.dirname(SRC))
    import release_archive
    installer = "Install Revit MCP Router on this PC"
    release_archive.archive(APP_NAME, ver, [
        (SRC, "RevitMcpRouter"),
        (os.path.join(PROJECT, "design", "revittools_theme.py"), "design/revittools_theme.py"),
        (os.path.join(PORTABLE, installer + ".ps1"), "Portable/" + installer + ".ps1"),
        (os.path.join(PORTABLE, installer + ".cmd"), "Portable/" + installer + ".cmd"),
    ], release=[zpath])


def main():
    ver = version()
    print("== Revit MCP Router release build v%s -> %s" % (ver, SCRATCH))
    compile_modules()
    stage_entries()
    app = freeze(write_spec())
    write_readme(app, ver)
    if "--no-selftest" in sys.argv:   # CI: the runner is not licensed; compile, freeze and the bundle audit still ran
        print("   self-tests skipped (--no-selftest)")
    else:
        selftests(app)
    if "--deploy" in sys.argv:
        deploy(app, ver)
    print("== build OK: " + app)


if __name__ == "__main__":
    main()

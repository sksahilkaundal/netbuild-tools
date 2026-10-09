# -*- coding: utf-8 -*-
r"""
ProjectA Tools per-user installer -- run by Install.bat / Uninstall.bat with the bundled Python.
No admin rights: everything goes to %LOCALAPPDATA%\ProjectA_Tools and the user's own shortcuts.

    python projecta_install.py install            copy the package, unblock it, add shortcuts
    python projecta_install.py remove-shortcuts   (Uninstall.bat deletes the folders afterwards)

install: runtime\ and app\ are replaced; Netbuild\ files are only copied where the installed copy
is missing or older (your edits there survive a reinstall); user\ (settings, logs) is never touched.
"""
import os
import shutil
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ProjectA_Tools")
TOP_FILES = ("ProjectA Issue Report.bat", "Uninstall.bat", "README.md", "VERSION.txt")
LINK = "ProjectA Issue Report.lnk"


def unblock(root):
    """Drop the 'Mark of the Web' (Zone.Identifier stream) a downloaded zip puts on every file."""
    if os.name != "nt":
        return 0
    n = 0
    for d, _, files in os.walk(root):
        for f in files:
            try:
                os.remove(os.path.join(d, f) + ":Zone.Identifier")
                n += 1
            except OSError:
                pass
    return n


def replace_tree(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))


def merge_newer(src, dst):
    """Copy files missing in dst or older there; keep anything newer in dst (user edits)."""
    kept = []
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        out = os.path.join(dst, os.path.relpath(d, src))
        os.makedirs(out, exist_ok=True)
        for f in files:
            s, t = os.path.join(d, f), os.path.join(out, f)
            if os.path.exists(t) and os.path.getmtime(t) > os.path.getmtime(s) + 2:
                kept.append(os.path.relpath(t, dst))
                continue
            shutil.copy2(s, t)
    return kept


def shortcut_dirs():
    try:
        import win32com.client                   # pywin32, bundled
        sh = win32com.client.Dispatch("WScript.Shell")
        return sh, [sh.SpecialFolders("Programs"), sh.SpecialFolders("Desktop")]   # follows OneDrive-redirected Desktop
    except Exception as exc:                     # noqa: BLE001
        print("  (shortcuts skipped: %s)" % exc)
        return None, []


def make_shortcuts():
    sh, dirs = shortcut_dirs()
    if sh is None and os.name == "nt":           # COM unavailable: same shortcuts through PowerShell
        import subprocess
        bat = os.path.join(DEST, "ProjectA Issue Report.bat").replace("'", "''")
        ps = ("$w = New-Object -ComObject WScript.Shell; foreach ($d in @([Environment]::GetFolderPath('Programs'),"
              " [Environment]::GetFolderPath('Desktop'))) { $s = $w.CreateShortcut((Join-Path $d '%s'));"
              " $s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; $s.Save(); $s.FullName }"
              % (LINK, bat, DEST.replace("'", "''")))
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                               capture_output=True, text=True, timeout=60)
            return [l for l in r.stdout.splitlines() if l.strip()]
        except (OSError, subprocess.SubprocessError) as exc:
            print("  (shortcuts not created: %s -- start ProjectA Issue Report.bat directly)" % exc)
        return []
    made = []
    for d in dirs:
        try:
            lnk = sh.CreateShortcut(os.path.join(d, LINK))
            lnk.TargetPath = os.path.join(DEST, "ProjectA Issue Report.bat")
            lnk.WorkingDirectory = DEST
            lnk.IconLocation = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "imageres.dll") + ",112"
            lnk.Description = "ProjectA ACC Issue Report pipeline"
            lnk.Save()
            made.append(os.path.join(d, LINK))
        except Exception as exc:                 # noqa: BLE001
            print("  (shortcut in %s not created: %s)" % (d, exc))
    return made


def remove_shortcuts():
    _, dirs = shortcut_dirs()
    for d in dirs:
        try:
            os.remove(os.path.join(d, LINK))
            print("  removed %s" % os.path.join(d, LINK))
        except OSError:
            pass


def install():
    print("Installing ProjectA Tools to %s  (current user, no admin rights)" % DEST)
    if os.path.normcase(os.path.abspath(PKG)) == os.path.normcase(os.path.abspath(DEST)):
        print("  already running from the install folder -- nothing to copy")
    else:
        os.makedirs(DEST, exist_ok=True)
        try:
            for sub in ("runtime", "app"):
                print("  copying %s ..." % sub)
                replace_tree(os.path.join(PKG, sub), os.path.join(DEST, sub))
        except OSError as exc:
            sys.exit("!!! copy failed (%s)\n    Close every 'ProjectA Issue Report' window, then run Install.bat again." % exc)
        print("  copying Netbuild (your newer edits are kept) ...")
        kept = merge_newer(os.path.join(PKG, "Netbuild"), os.path.join(DEST, "Netbuild"))
        for k in kept:
            print("    kept your newer %s" % k)
        for f in TOP_FILES:
            if os.path.isfile(os.path.join(PKG, f)):
                shutil.copy2(os.path.join(PKG, f), os.path.join(DEST, f))
    n = unblock(DEST)
    if n:
        print("  unblocked %d downloaded files" % n)
    for p in make_shortcuts():
        print("  shortcut: %s" % p)
    print("Installed.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "install":
        install()
    elif cmd == "remove-shortcuts":
        remove_shortcuts()
    else:
        print(__doc__)

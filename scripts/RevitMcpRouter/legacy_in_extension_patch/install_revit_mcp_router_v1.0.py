# -*- coding: utf-8 -*-
"""
Revit MCP Router - one-shot install / verify / uninstall pipeline.

    python install_revit_mcp_router.py            # DRY RUN: shows what would change
    python install_revit_mcp_router.py --apply    # does it (backs up ~/.claude.json first)
    python install_revit_mcp_router.py --verify   # launcher --check + list of routed entries
    python install_revit_mcp_router.py --uninstall --apply   # points entries back at the extension's main.py

What --apply does
-----------------
1. Locates the pyRevit MCP extension and its venv python
   (%APPDATA%\\pyRevit\\Extensions\\mcp-server-for-revit-python.extension, or REVIT_MCP_EXTENSION_DIR).
2. Runs the launcher's self-check (`revit_mcp_bridge.py --check`): tools load, Revits discovered.
   Missing mcp/httpx in the venv are installed by the launcher itself.
3. Rewrites ~/.claude.json: every `mcpServers.revit` entry (per project, and the global block
   if present) gets command = venv python, args = [this folder's revit_mcp_bridge.py].
   Projects without a revit entry are NOT touched (use --add-project <path> to add one).
4. Re-reads the file to prove it is valid JSON and prints the result.

Nothing inside the extension folder is modified. Backup: ~/.claude.json.bak-<timestamp>.
Takes effect in the next new Claude Code session.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(HERE, "revit_mcp_bridge.py")
ROUTER = os.path.join(HERE, "revit_mcp_router.py")
CLAUDE_JSON = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".claude.json")
EXT_DIR = os.environ.get("REVIT_MCP_EXTENSION_DIR") or os.path.join(
    os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mcp-server-for-revit-python.extension")
VENV_PY = os.path.join(EXT_DIR, ".venv", "Scripts", "python.exe")
MAIN_PY = os.path.join(EXT_DIR, "main.py")


class InstallError(Exception):
    """A step failed; message is user-facing."""


LOG = print   # GUI front-ends replace this with their own logger


def say(msg):
    LOG(msg)


def fail(msg):
    say("FAIL  " + msg)
    raise InstallError(msg)


def use_launcher_dir(folder):
    """Point the installer at a copy of the bridge living in `folder` (exe/product mode)."""
    global LAUNCHER, ROUTER
    LAUNCHER = os.path.join(folder, "revit_mcp_bridge.py")
    ROUTER = os.path.join(folder, "revit_mcp_router.py")


def install_files(src_dir, dest_dir):
    """Copy the bridge + router into dest_dir (e.g. LOCALAPPDATA/RevitMcpRouter) and use them.

    The launcher must never run from inside a PyInstaller bundle: the child
    venv python puts the script's folder first on sys.path and would import the
    bundle's python314 .pyd files ("Module use of python314.dll conflicts").
    """
    os.makedirs(dest_dir, exist_ok=True)
    for name in ("revit_mcp_bridge.py", "revit_mcp_router.py"):
        src, dst = os.path.join(src_dir, name), os.path.join(dest_dir, name)
        same = os.path.isfile(dst) and open(src, "rb").read() == open(dst, "rb").read()
        if not same:
            shutil.copy2(src, dst)
            say("ok    copied %s -> %s" % (name, dest_dir))
    use_launcher_dir(dest_dir)


def child_env():
    """Environment for spawning the venv python / uv from a PyInstaller-frozen GUI.

    The frozen bootloader prepends its _internal folder to PATH and may set
    PYTHONHOME/PYTHONPATH; a child CPython 3.13 then picks up python314.dll
    ("Module use of python314.dll conflicts with this version of Python").
    Strip anything that points into the bundle.
    """
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR"):
        env.pop(k, None)
    bundle = getattr(sys, "_MEIPASS", None)
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None
    bad = [os.path.normcase(b) for b in (bundle, exe_dir) if b]
    if bad:
        keep = [p for p in env.get("PATH", "").split(os.pathsep)
                if p and not any(os.path.normcase(p).startswith(b) for b in bad)]
        env["PATH"] = os.pathsep.join(keep)
    return env


def find_uv():
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    for c in (shutil.which("uv"), os.path.join(home, "uv-portable", "uv.exe"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "uv", "uv.exe"),
              os.path.join(home, ".local", "bin", "uv.exe")):
        if c and os.path.isfile(c):
            return c
    return None


def ensure_venv():
    """Create the extension's .venv with uv if the extension was installed without one."""
    if os.path.isfile(VENV_PY):
        return
    uv = find_uv()
    if not uv:
        fail("the extension has no .venv and uv was not found - install uv (https://docs.astral.sh/uv/) or run "
             "'uv sync' inside %s" % EXT_DIR)
    say("--    creating the extension venv with uv ...")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([uv, "venv", "--python", "3.13", os.path.join(EXT_DIR, ".venv")],
                       capture_output=True, text=True, timeout=600, creationflags=flags, env=child_env())
    if r.returncode != 0 or not os.path.isfile(VENV_PY):
        fail("uv venv failed: %s" % (r.stderr or r.stdout)[-800:])
    say("ok    venv created (the launcher installs mcp/httpx on first start)")


# ----------------------------------------------------------------------------
def check_files():
    ensure_venv()
    for label, path in (("launcher", LAUNCHER), ("router", ROUTER), ("extension tools", os.path.join(EXT_DIR, "tools", "__init__.py")),
                        ("venv python", VENV_PY), ("~/.claude.json", CLAUDE_JSON)):
        if not os.path.isfile(path):
            fail("%s not found: %s" % (label, path))
        say("ok    %-16s %s" % (label, path))


def launcher_check():
    say("--    running launcher self-check (%s --check) ..." % os.path.basename(LAUNCHER))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([VENV_PY, LAUNCHER, "--check"], capture_output=True, text=True, timeout=180,
                       creationflags=flags, env=child_env())
    out = r.stdout or ""
    fatal = [l for l in (r.stderr or "").splitlines() if "FATAL" in l]
    if r.returncode != 0 or fatal or "tools (" not in out:
        say(out[-1500:]); say((r.stderr or "")[-1500:])
        fail("launcher self-check failed")
    tools_line = next((l for l in out.splitlines() if l.startswith("tools (")), "")
    say("ok    " + tools_line[:100] + ("..." if len(tools_line) > 100 else ""))
    for l in out.splitlines():
        if l.startswith("  port ") or l.startswith("router:"):
            say("      " + l.strip())
    return out


def load_config():
    try:
        with open(CLAUDE_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        fail("cannot parse %s: %s" % (CLAUDE_JSON, e))


def revit_entries(cfg):
    """Yield (label, dict) for every mcpServers.revit block: per project + global."""
    if "revit" in cfg.get("mcpServers", {}):
        yield "<global>", cfg["mcpServers"]["revit"]
    for key, proj in cfg.get("projects", {}).items():
        r = proj.get("mcpServers", {}).get("revit")
        if r:
            yield key, r


def desired(uninstall=False):
    return {"type": "stdio", "command": VENV_PY, "args": [MAIN_PY if uninstall else LAUNCHER]}


def plan(cfg, uninstall, add_projects):
    changes = []
    for label, entry in revit_entries(cfg):
        want = desired(uninstall)
        cur = {"command": entry.get("command"), "args": entry.get("args")}
        if cur["command"] != want["command"] or cur["args"] != want["args"]:
            changes.append((label, entry, want))
    for p in add_projects:
        key = os.path.abspath(p)
        proj = cfg.setdefault("projects", {}).setdefault(key, {})
        if "revit" not in proj.get("mcpServers", {}):
            changes.append((key + "  (new entry)", proj.setdefault("mcpServers", {}).setdefault("revit", {}), desired(uninstall)))
    return changes


def apply(cfg, changes):
    for label, entry, want in changes:
        entry.update(want)
        entry.setdefault("env", {})
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = CLAUDE_JSON + ".bak-" + stamp
    shutil.copy2(CLAUDE_JSON, backup)
    tmp = CLAUDE_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    with open(tmp, encoding="utf-8") as fh:
        json.load(fh)   # prove it parses before it replaces the real file
    os.replace(tmp, CLAUDE_JSON)
    say("ok    backup %s" % backup)


def report(cfg):
    say("--    revit MCP entries now:")
    for label, entry in revit_entries(cfg):
        a = (entry.get("args") or [""])[0]
        base = os.path.basename(a).lower()
        state = "ROUTER" if base == "revit_mcp_bridge.py" else ("main.py" if base == "main.py" else "other")
        say("      [%-7s] %s" % (state, label))
        if state == "ROUTER" and os.path.normcase(a) != os.path.normcase(LAUNCHER):
            say("               bridge at: %s" % a)
        if entry.get("env"):
            say("               env: %s" % json.dumps(entry["env"]))


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    ap.add_argument("--verify", action="store_true", help="self-check + report only")
    ap.add_argument("--uninstall", action="store_true", help="point entries back at the extension's main.py")
    ap.add_argument("--add-project", action="append", default=[], metavar="DIR", help="also add a revit entry for this project folder")
    ap.add_argument("--skip-check", action="store_true", help="do not run the launcher self-check")
    a = ap.parse_args()

    say("Revit MCP Router installer  (%s)" % ("APPLY" if a.apply else "DRY RUN"))
    check_files()
    if not a.skip_check and not a.uninstall:
        launcher_check()
    cfg = load_config()
    if a.verify:
        report(cfg)
        return
    changes = plan(cfg, a.uninstall, a.add_project)
    if not changes:
        say("ok    nothing to change")
        report(cfg)
        return
    say("--    %d entr%s to %s:" % (len(changes), "y" if len(changes) == 1 else "ies", "restore" if a.uninstall else "route through the launcher"))
    for label, entry, want in changes:
        say("      %s" % label)
        say("         args: %s  ->  %s" % ((entry.get("args") or ["<none>"])[0], want["args"][0]))
    if not a.apply:
        say("--    dry run - re-run with --apply to write ~/.claude.json")
        return
    apply(cfg, changes)
    report(load_config())
    say("done  start a NEW Claude Code session for it to take effect")


if __name__ == "__main__":
    try:
        main()
    except InstallError:
        sys.exit(1)

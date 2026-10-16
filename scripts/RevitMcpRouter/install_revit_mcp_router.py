# -*- coding: utf-8 -*-
"""
Revit MCP Router - install / verify / uninstall pipeline (compiled to a .pyd for release).

CLI (developer / source mode, bridge = extension venv python + revit_mcp_bridge.py):
    python install_revit_mcp_router.py            # DRY RUN: shows what would change
    python install_revit_mcp_router.py --apply    # does it (backs up ~/.claude.json first)
    python install_revit_mcp_router.py --verify   # bridge --check + list of routed entries
    python install_revit_mcp_router.py --uninstall --apply   # entries back to the extension's main.py
    add --codex to any of the above to also (un)register it in ~/.codex/config.toml

Product mode (Setup exe): the whole app folder is copied to
%LOCALAPPDATA%\\RevitMcpRouter\\app-<version>\\ and every mcpServers.revit entry
in ~/.claude.json becomes  command = <that folder>\\RevitMcpBridge.exe, args = [].
The extension's own venv is not needed at all in product mode.

Claude Code reads a project's entry only under a forward-slash key ("C:/SK/proj"). A revit entry under a
backslash key ("C:\\SK\\proj") is ignored, so it is copied to the forward-slash key (report: IGNORED).

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
CLAUDE_JSON = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".claude.json")
INSTALL_ROOT = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RevitMcpRouter")
CONFIG_FILE = os.path.join(INSTALL_ROOT, "config.json")
EXT_DIR = os.environ.get("REVIT_MCP_EXTENSION_DIR") or os.path.join(
    os.environ.get("APPDATA", ""), "pyRevit", "Extensions", "mcp-server-for-revit-python.extension")

# the bridge command Claude should launch: [command, *args]
BRIDGE_CMD = None


class InstallError(Exception):
    """A step failed; message is user-facing."""


LOG = print   # GUI front-ends replace this


def say(msg):
    LOG(msg)


def fail(msg):
    say("FAIL  " + msg)
    raise InstallError(msg)


def venv_python():
    return os.path.join(EXT_DIR, ".venv", "Scripts", "python.exe")


def main_py():
    return os.path.join(EXT_DIR, "main.py")


def use_source_bridge(folder=HERE):
    """Developer mode: extension venv python + the .py stub in `folder`."""
    global BRIDGE_CMD
    BRIDGE_CMD = [venv_python(), os.path.join(folder, "revit_mcp_bridge.py")]


def use_exe_bridge(app_dir):
    """Product mode: RevitMcpBridge.exe inside app_dir."""
    global BRIDGE_CMD
    BRIDGE_CMD = [os.path.join(app_dir, "RevitMcpBridge.exe")]


def child_env():
    """Env for children spawned from a PyInstaller-frozen app: drop the bundle from PATH/PYTHON* vars."""
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR"):
        env.pop(k, None)
    bundle = getattr(sys, "_MEIPASS", None)
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None
    bad = [os.path.normcase(b) for b in (bundle, exe_dir) if b]
    if bad:
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if p and not any(os.path.normcase(p).startswith(b) for b in bad))
    return env


# ----------------------------------------------------------------------------
def install_app(src_app_dir, version):
    """Copy the frozen app folder (exe + _internal) to a versioned folder under INSTALL_ROOT.

    A versioned folder is used because a bridge from the previous version may
    still be running inside an open Claude session and would lock its files.
    """
    dest = os.path.join(INSTALL_ROOT, "app-" + version)
    os.makedirs(INSTALL_ROOT, exist_ok=True)
    say("--    copying app to %s ..." % dest)
    try:
        shutil.copytree(src_app_dir, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("selftest_result.txt", "*.zip"))
    except PermissionError as e:
        fail("cannot overwrite %s (a bridge of this version is probably running - close Claude sessions and retry): %s" % (dest, e))
    if not os.path.isfile(os.path.join(dest, "RevitMcpBridge.exe")):
        fail("RevitMcpBridge.exe missing in %s" % dest)
    verify_copy(src_app_dir, dest)
    say("ok    app installed")
    use_exe_bridge(dest)
    return dest


def verify_copy(src, dest):
    """Every file in dest must match its source size. A source in OneDrive can be an online-only
    placeholder that copies as 0 bytes (seen 2026-09-24: base_library.zip -> bridge could not start);
    reading it in full makes OneDrive download it, so re-copy by read/write before giving up."""
    bad = []
    for root, _, files in os.walk(src):
        for f in files:
            if f in ("selftest_result.txt",) or f.endswith(".zip") and root == src:
                continue
            s = os.path.join(root, f)
            d = os.path.join(dest, os.path.relpath(s, src))
            want = os.path.getsize(s)
            if os.path.isfile(d) and os.path.getsize(d) == want:
                continue
            try:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                with open(s, "rb") as fi:
                    data = fi.read()
                with open(d, "wb") as fo:
                    fo.write(data)
            except Exception as e:
                say("--    re-copy failed %s: %s" % (s, e))
            if not (os.path.isfile(d) and os.path.getsize(d) == want):
                bad.append(os.path.relpath(s, src))
    if bad:
        fail("%d file(s) did not copy completely (first: %s). If the app folder is in OneDrive, right-click it -> "
             "'Always keep on this device', wait for the sync, then retry." % (len(bad), bad[0]))


def write_config():
    os.makedirs(INSTALL_ROOT, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump({"extension_dir": EXT_DIR, "bridge": BRIDGE_CMD, "updated": dt.datetime.now().isoformat(timespec="seconds")}, fh, indent=2)
    say("ok    config %s" % CONFIG_FILE)


def cleanup_old_apps(keep_dir):
    """Delete older app-* folders that are not locked (best effort)."""
    try:
        for name in os.listdir(INSTALL_ROOT):
            p = os.path.join(INSTALL_ROOT, name)
            if name.startswith("app-") and os.path.isdir(p) and os.path.normcase(p) != os.path.normcase(keep_dir):
                try:
                    shutil.rmtree(p)
                    say("ok    removed old %s" % name)
                except Exception:
                    say("--    old %s still in use, left in place" % name)
    except Exception:
        pass


# ----------------------------------------------------------------------------
def check_files():
    if BRIDGE_CMD is None:
        use_source_bridge()
    if not os.path.isfile(os.path.join(EXT_DIR, "tools", "__init__.py")):
        fail("Revit connector not found. Install the Revit MCP connector add-in in Revit first, or pick its folder above.")
    say("ok    %-16s found" % "Revit connector")
    if not os.path.isfile(CLAUDE_JSON):
        fail("Claude config file not found: %s (start Claude Code once, then retry)" % CLAUDE_JSON)
    say("ok    %-16s %s" % ("Claude config", CLAUDE_JSON))
    for p in BRIDGE_CMD:
        if not os.path.isfile(p):
            fail("Claude bridge not found: %s" % p)
    say("ok    %-16s %s" % ("Claude bridge", BRIDGE_CMD[0]))


def bridge_check():
    say("--    checking the Claude bridge and looking for Revit sessions ...")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(BRIDGE_CMD + ["--check"], capture_output=True, text=True, timeout=180,
                       creationflags=flags, env=child_env())
    out = r.stdout or ""
    fatal = [l for l in (r.stderr or "").splitlines() if "FATAL" in l]
    if r.returncode != 0 or fatal or "tools (" not in out:
        say(out[-1500:]); say((r.stderr or "")[-1500:])
        fail("the Claude bridge did not start correctly")
    for l in out.splitlines():
        if l.startswith("tools ("):
            say("ok    " + l[:100] + ("..." if len(l) > 100 else ""))
        elif l.startswith("licence:"):
            say("ok    " + l)
        elif l.startswith("  port ") or l.startswith("router:"):
            say("      " + l.strip())
    return out


launcher_check = bridge_check   # old name


def load_config():
    try:
        with open(CLAUDE_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        fail("cannot parse %s: %s" % (CLAUDE_JSON, e))


def revit_entries(cfg):
    """Yield (label, dict) for every mcpServers.revit block: global + per project."""
    if "revit" in cfg.get("mcpServers", {}):
        yield "<global>", cfg["mcpServers"]["revit"]
    for key, proj in cfg.get("projects", {}).items():
        r = proj.get("mcpServers", {}).get("revit")
        if r:
            yield key, r


def project_key(folder):
    """The key Claude Code files a project folder under in ~/.claude.json: absolute, forward slashes (C:/SK/proj)."""
    return os.path.normpath(os.path.abspath(folder)).replace("\\", "/")


def ignored_key(key):
    """Claude Code never looks a project up under a backslash key (C:\\SK\\proj): an entry there does nothing."""
    return "\\" in key


def project_block(cfg, folder, create=False):
    """(key, block) of the project entry Claude Code reads for `folder`, matched ignoring case and slash
    direction as Windows does; (None, None) when there is none and create is False."""
    want = os.path.normcase(project_key(folder))
    for key, proj in cfg.get("projects", {}).items():
        if not ignored_key(key) and os.path.normcase(os.path.normpath(key)) == want:
            return key, proj
    if not create:
        return None, None
    key = project_key(folder)
    return key, cfg.setdefault("projects", {}).setdefault(key, {})


def desired(uninstall=False):
    if uninstall:
        return {"type": "stdio", "command": venv_python(), "args": [main_py()]}
    return {"type": "stdio", "command": BRIDGE_CMD[0], "args": list(BRIDGE_CMD[1:])}


def plan(cfg, uninstall, add_projects):
    changes = []
    want = desired(uninstall)
    for label, entry in revit_entries(cfg):
        if entry.get("command") != want["command"] or (entry.get("args") or []) != want["args"]:
            changes.append((label, entry, want))
    for key, proj in list(cfg.get("projects", {}).items()):
        old = proj.get("mcpServers", {}).get("revit")
        if old and ignored_key(key):
            new_key, new_proj = project_block(cfg, key, create=True)
            servers = new_proj.setdefault("mcpServers", {})
            if "revit" not in servers:
                servers["revit"] = json.loads(json.dumps(old))   # copied, not moved: the old key is left in place
                changes.append(("%s  (copy of %s, which Claude Code ignores)" % (new_key, key), servers["revit"], want))
    for p in add_projects:
        key, proj = project_block(cfg, p, create=True)
        servers = proj.setdefault("mcpServers", {})
        if "revit" not in servers:
            changes.append((key + "  (new entry)", servers.setdefault("revit", {}), want))
    return changes


def apply(cfg, changes):
    for label, entry, want in changes:
        entry.update(want)
        entry.setdefault("env", {})
    backup = CLAUDE_JSON + ".bak-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(CLAUDE_JSON, backup)
    tmp = CLAUDE_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    with open(tmp, encoding="utf-8") as fh:
        json.load(fh)   # prove it parses before it replaces the real file
    os.replace(tmp, CLAUDE_JSON)
    say("ok    backup %s" % backup)


def report(cfg):
    say("--    Claude projects connected to Revit:")
    for label, entry in revit_entries(cfg):
        if ignored_key(label):
            key, proj = project_block(cfg, label)
            used = proj is not None and "revit" in proj.get("mcpServers", {})
            say("      [IGNORED] %s" % label)
            say("               Claude Code does not read keys with backslashes - %s" % (
                "it uses the entry under %s" % key if used else
                "run Install / Reset (source mode: --apply) to copy it to %s" % project_key(label)))
            continue
        cmd = entry.get("command") or ""
        a = (entry.get("args") or [""])[0]
        base = os.path.basename(cmd).lower(), os.path.basename(a).lower()
        if base[0] == "revitmcpbridge.exe" or base[1] == "revit_mcp_bridge.py":
            state = "ROUTER"
        elif base[1] == "main.py":
            state = "default"
        else:
            state = "other"
        say("      [%-7s] %s" % (state, label))
        if state == "ROUTER":
            say("               -> %s" % (cmd if base[0] == "revitmcpbridge.exe" else a))
        if entry.get("env"):
            say("               env: %s" % json.dumps(entry["env"]))


# ---------------------------------------------------------------- Codex ---
CODEX_TOML = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".codex", "config.toml")
CODEX_HEADER = "[mcp_servers.revit]"


def codex_present():
    return os.path.isdir(os.path.dirname(CODEX_TOML))


def _toml_str(s):
    return "'%s'" % s if "'" not in s else json.dumps(s)   # literal string keeps backslashes as-is


def codex_block(uninstall=False):
    want = desired(uninstall)
    return "\n".join([
        CODEX_HEADER,
        "command = %s" % _toml_str(want["command"]),
        "args = [%s]" % ", ".join(_toml_str(a) for a in want["args"]),
        "startup_timeout_sec = 60",
        "tool_timeout_sec = 1800   # multi-model runs take up to 10 min per model",
    ]) + "\n"


def codex_plan(uninstall=False):
    """Return (old_text, new_text); equal when nothing changes. Only the [mcp_servers.revit] table is touched."""
    try:
        with open(CODEX_TOML, encoding="utf-8") as fh:
            old = fh.read()
    except FileNotFoundError:
        old = ""
    lines = old.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.strip() == CODEX_HEADER), None)
    block = codex_block(uninstall)
    if start is None and uninstall:
        return old, old   # restore never adds a Codex entry the user did not have
    if start is None:
        sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
        return old, old + sep + block
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    tail = "\n" if end < len(lines) else ""
    return old, "".join(lines[:start]) + block + tail + "".join(lines[end:])


def codex_apply(uninstall=False):
    old, new = codex_plan(uninstall)
    if old == new:
        say("ok    Codex config already routed")
        return
    os.makedirs(os.path.dirname(CODEX_TOML), exist_ok=True)
    if old:
        backup = CODEX_TOML + ".bak-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(CODEX_TOML, backup)
        say("ok    backup %s" % backup)
    tmp = CODEX_TOML + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new)
    try:
        import tomllib
        with open(tmp, "rb") as fh:
            tomllib.load(fh)   # prove it parses before it replaces the real file
    except ImportError:
        pass
    except Exception as e:
        os.remove(tmp)
        fail("Codex config would not parse after the edit (left unchanged): %s" % e)
    os.replace(tmp, CODEX_TOML)
    say("ok    Codex %s -> %s" % (CODEX_TOML, "default connector" if uninstall else "Revit MCP Router"))


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    ap.add_argument("--verify", action="store_true", help="self-check + report only")
    ap.add_argument("--uninstall", action="store_true", help="point entries back at the extension's main.py")
    ap.add_argument("--add-project", action="append", default=[], metavar="DIR", help="also add a revit entry for this project folder")
    ap.add_argument("--skip-check", action="store_true", help="do not run the bridge self-check")
    ap.add_argument("--codex", action="store_true", help="also register the bridge in ~/.codex/config.toml")
    a = ap.parse_args()

    say("Revit MCP Router installer  (%s, source mode)" % ("APPLY" if a.apply else "DRY RUN"))
    use_source_bridge()
    check_files()
    if not a.skip_check and not a.uninstall:
        bridge_check()
    if a.codex:
        old, new = codex_plan(a.uninstall)
        if a.apply:
            codex_apply(a.uninstall)
        elif old != new:
            say("--    Codex: would write to %s:\n%s" % (CODEX_TOML, codex_block(a.uninstall)))
    cfg = load_config()
    if a.verify:
        report(cfg)
        return
    changes = plan(cfg, a.uninstall, a.add_project)
    if not changes:
        say("ok    nothing to change")
        report(cfg)
        return
    say("--    %d entr%s to %s:" % (len(changes), "y" if len(changes) == 1 else "ies", "restore" if a.uninstall else "route through Revit MCP Router"))
    for label, entry, want in changes:
        say("      %s" % label)
        say("         %s %s  ->  %s %s" % (entry.get("command", "<none>"), (entry.get("args") or [""])[0], want["command"], want["args"][0] if want["args"] else ""))
    if not a.apply:
        say("--    dry run - re-run with --apply to write ~/.claude.json")
        return
    apply(cfg, changes)
    write_config()
    report(load_config())
    say("done  start a NEW Claude Code session for it to take effect")


if __name__ == "__main__":
    try:
        main()
    except InstallError:
        sys.exit(1)

"""Script folder for the Netbuild pyRevit buttons (IronPython 2.7 under pyRevit, and CPython 3 for the tests).

Point the buttons at a folder -- a network share, a synced OneDrive / ACC / BIM 360 folder -- that holds the
current button folders ("Level Shift.pushbutton", ...) at any depth, in any sub-folders:

- live: every button runs its script from that folder (run_live, the first lines of every button script).
  The copy bundled in the extension runs when no folder is set, live is off, the folder is offline or the
  button is not in it;
- update: Netbuild > Update Scripts copies the changed files of every matching button -- and the lib folder of a
  same-named .extension found there -- into the installed extensions, after a backup (plan_update, apply_update).

Which folder: your own choice (Netbuild > Script Folder, saved in %APPDATA%\\Netbuild\\pyRevit\\script_source.json),
else the NETBUILD_SCRIPT_SOURCE environment variable (several folders separated by ;), else the default shipped
in the extension's own script_source.json. %VARIABLES% and ~ are expanded.
"""

import io
import json
import os
import re
import shutil
import sys
import time

SETTINGS_NAME = "script_source.json"
INDEX_NAME = "script_index.json"
ENV = "NETBUILD_SCRIPT_SOURCE"
RESCAN_SECONDS = 300            # a button missing from the index looks again at most this often
BUNDLES = (".pushbutton", ".smartbutton", ".invokebutton", ".urlbutton", ".linkbutton", ".contentbutton",
           ".panelbutton", ".nobutton")
SKIP_DIRS = (".git", ".svn", "__pycache__", "node_modules")
SKIP_EXT = (".pyc", ".pyo")
LIVE_KEY = "__netbuild_live__"  # set in the scope of a script run from the script folder
INDEX_VERSION = 2               # 2: the index also holds the .py files (script_path)


# ------------------------------------------------------------------ settings
def user_dir(env=None):
    env = os.environ if env is None else env
    return os.path.join(env.get("APPDATA") or os.path.expanduser("~"), "Netbuild", "pyRevit")


def _read_json(path):
    try:
        with io.open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def _write_json(path, data):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    text = json.dumps(data, indent=2, sort_keys=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(u"%s\n" % text)


def split_folders(value, env=None):
    """Folders from a list or a ';'-separated string; %VARS% and ~ expanded, blanks dropped."""
    if not value:
        return []
    env = os.environ if env is None else env
    items = value if isinstance(value, (list, tuple)) else value.split(";")
    return [os.path.normpath(os.path.expanduser(re.sub(r"%([^%]+)%", lambda m: env.get(m.group(1), m.group(0)),
                                                       p.strip()))) for p in items if p and p.strip()]


def extension_root(path):
    """The *.extension folder that holds path, or None."""
    d = os.path.abspath(path)
    while True:
        if d.lower().endswith(".extension"):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def settings(ext_dir=None, env=None):
    """{"folders": [...], "live": bool, "from": where the folders came from}."""
    env = os.environ if env is None else env
    user = _read_json(os.path.join(user_dir(env), SETTINGS_NAME))
    default = _read_json(os.path.join(ext_dir, SETTINGS_NAME)) if ext_dir else {}
    source, folders = "none", []
    for name, value in (("your setting", user.get("folders")), (ENV, env.get(ENV)),
                        ("extension default", default.get("folders"))):
        folders = split_folders(value, env)
        if folders:
            source = name
            break
    return {"folders": folders, "live": bool(user.get("live", default.get("live", True))), "from": source}


def save_settings(folders=None, live=None, env=None):
    """Save your own folders / live switch (None keeps the saved value); the button index is rebuilt next time."""
    path = os.path.join(user_dir(env), SETTINGS_NAME)
    data = _read_json(path)
    if folders is not None:
        data["folders"] = list(folders)
    if live is not None:
        data["live"] = bool(live)
    _write_json(path, data)
    try:
        os.remove(os.path.join(user_dir(env), INDEX_NAME))
    except OSError:
        pass
    return path


# ------------------------------------------------------------------ finding button folders
def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _inside(path, root):
    p, r = _key(path), _key(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _newest(folder):
    if os.path.isfile(folder):
        return os.path.getmtime(folder)
    times = [os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder)
             if os.path.isfile(os.path.join(folder, n))]
    return max(times) if times else 0


def scan(folders):
    """{lower-case name: [paths, newest first]} for every button folder, .extension folder and .py file below
    folders (not the files inside button folders)."""
    found, seen = {}, set()
    for root in folders:
        if not os.path.isdir(root):
            continue
        for d, dirs, files in os.walk(root):
            dirs[:] = sorted(n for n in dirs if n not in SKIP_DIRS)
            name = os.path.basename(d).lower()
            if (name.endswith(BUNDLES) or name.endswith(".extension")) and _key(d) not in seen:
                seen.add(_key(d))               # a folder inside another script folder is found once
                found.setdefault(name, []).append(d)
            if name.endswith(BUNDLES):
                dirs[:] = []                    # a button folder holds no buttons
                continue
            for n in files:
                if n.lower().endswith(".py") and _key(os.path.join(d, n)) not in seen:
                    seen.add(_key(os.path.join(d, n)))
                    found.setdefault(n.lower(), []).append(os.path.join(d, n))
    for name in found:
        found[name].sort(key=_newest, reverse=True)
    return found


def rescan(folders, env=None):
    """Scan folders now and save the index the buttons look in."""
    data = {"folders": folders, "scanned": time.time(), "bundles": scan(folders), "version": INDEX_VERSION}
    try:
        _write_json(os.path.join(user_dir(env), INDEX_NAME), data)
    except (IOError, OSError):
        pass
    return data["bundles"]


def find_bundle(name, folders, exclude=(), env=None):
    """The newest folder (or .py file) called name below folders and outside exclude, or None. Uses the saved index;
    scans again when the folders changed, or when name is missing and the index is older than RESCAN_SECONDS."""
    data = _read_json(os.path.join(user_dir(env), INDEX_NAME))
    fresh = data.get("folders") == folders and data.get("version") == INDEX_VERSION
    for attempt in (0, 1):
        if fresh:
            for d in (data.get("bundles") or {}).get(name.lower(), []):
                if os.path.exists(d) and not [x for x in exclude if _inside(d, x)]:
                    return d
            if attempt or time.time() - data.get("scanned", 0) < RESCAN_SECONDS:
                return None
        data, fresh = {"bundles": rescan(folders, env)}, True
    return None


# ------------------------------------------------------------------ scripts the buttons run by name
def script_path(name, fallback=None, env=None):
    """The newest file called name (e.g. "CutFloorsAtColumns_MCP.py") anywhere below the script folders; else
    fallback when that file exists; else None. A name not in the index makes the folders be scanned again."""
    try:
        folders = settings(extension_root(__file__), env)["folders"]
        if folders:
            found = find_bundle(name, folders, env=env)
            if found is None:
                rescan(folders, env)            # added since the last scan?
                found = find_bundle(name, folders, env=env)
            if found and os.path.isfile(found):
                return found
    except Exception:           # an offline share or a bad setting: try the fallback
        pass
    return fallback if fallback and os.path.isfile(fallback) else None


def missing_text(name, fallback=None, env=None):
    """Why script_path(name) found nothing, for an alert."""
    folders = settings(extension_root(__file__), env)["folders"]
    lines = ["%s was not found." % name, "", "Looked in every sub-folder of:"]
    lines += ["    %s%s" % (f, "" if os.path.isdir(f) else "   -- not reachable") for f in folders] or \
        ["    (no script folder set)"]
    if fallback:
        lines.append("and at:\n    %s" % fallback)
    lines += ["", "Put the script in one of those folders, or set the folder with Netbuild > Script Folder."]
    return "\n".join(lines)


# ------------------------------------------------------------------ live
def live_source(script_file, env=None):
    """The script-folder copy of script_file (same button folder name, same file name), or None."""
    try:
        here = os.path.abspath(script_file)
        bundle = os.path.dirname(here)
        ext = extension_root(bundle)
        s = settings(ext, env)
        if not s["live"] or not s["folders"]:
            return None
        found = find_bundle(os.path.basename(bundle), s["folders"], [ext or bundle], env)
        src = os.path.join(found, os.path.basename(here)) if found else None
        if not src or not os.path.isfile(src) or _key(os.path.realpath(src)) == _key(os.path.realpath(here)):
            return None
        return src
    except Exception:           # an offline share or a bad setting never stops the bundled button
        return None


def _run_file(path, scope):
    try:
        runner = execfile       # noqa: F821 -- IronPython 2.7 (pyRevit)
    except NameError:
        runner = None
    if runner is not None:
        runner(path, scope)
        return
    with io.open(path, "rb") as f:
        code = compile(f.read(), path, "exec")
    exec(code, scope)


def run_live(scope, env=None):
    """First lines of every Netbuild button script:

        import netbuild_scripts
        netbuild_scripts.run_live(globals())

    Runs this button's script from the script folder in this script's scope, then ends this script (SystemExit,
    a normal end for pyRevit). Returns -- the bundled script carries on -- when there is no script-folder copy."""
    if scope.get(LIVE_KEY) or not scope.get("__file__"):
        return None
    src = live_source(scope["__file__"], env)
    if src is None:
        return None
    folder = os.path.dirname(src)
    ext = extension_root(folder)
    for p in ([os.path.join(ext, "lib")] if ext else []) + [folder]:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    scope[LIVE_KEY] = src
    scope["__file__"] = src
    _run_file(src, scope)
    raise SystemExit(0)


# ------------------------------------------------------------------ update
def installed_extensions(this_ext, roots=()):
    """this_ext plus every *.extension folder directly in roots and next to this_ext."""
    out, seen = [], set()
    for d in [this_ext] + [os.path.join(r, n) for r in [os.path.dirname(this_ext)] + list(roots)
                            if os.path.isdir(r) for n in sorted(os.listdir(r))]:
        if d.lower().endswith(".extension") and os.path.isdir(d) and _key(d) not in seen:
            seen.add(_key(d))
            out.append(d)
    return out


def _files(folder):
    for d, dirs, files in os.walk(folder):
        dirs[:] = sorted(n for n in dirs if n not in SKIP_DIRS)
        for n in sorted(files):
            if not n.lower().endswith(SKIP_EXT):
                p = os.path.join(d, n)
                yield p, os.path.relpath(p, folder)


def _differs(a, b):
    if not os.path.isfile(b) or os.path.getsize(a) != os.path.getsize(b):
        return True
    with io.open(a, "rb") as fa:
        with io.open(b, "rb") as fb:
            return fa.read() != fb.read()


def plan_update(folders, extensions, env=None):
    """[(source file, installed file)] that differ: the files of every installed button whose folder name is found
    below folders, and the lib of a same-named .extension found there. Copies inside the installed extensions are
    never a source."""
    found = rescan(folders, env)

    def source(name):
        for d in found.get(name.lower(), []):
            if not [x for x in extensions if _inside(d, x)]:
                return d
        return None

    plan = []
    for ext in extensions:
        pairs = []
        src_ext = source(os.path.basename(ext))
        if src_ext and os.path.isdir(os.path.join(src_ext, "lib")):
            pairs.append((os.path.join(src_ext, "lib"), os.path.join(ext, "lib")))
        for d, dirs, files in os.walk(ext):
            dirs[:] = sorted(n for n in dirs if n not in SKIP_DIRS)
            if os.path.basename(d).lower().endswith(BUNDLES):
                dirs[:] = []
                src = source(os.path.basename(d))
                if src:
                    pairs.append((src, d))
        for src_dir, dst_dir in pairs:
            for path, rel in _files(src_dir):
                dst = os.path.join(dst_dir, rel)
                if _differs(path, dst):
                    plan.append((path, dst))
    return plan


def _backup_dir(env=None):
    return os.path.join(user_dir(env), "backups", time.strftime("%Y%m%d_%H%M%S"))


def _back_up(path, backup):
    """Copy path into backup, under its extension's folder name (nothing when path does not exist)."""
    if not os.path.isfile(path):
        return
    ext = extension_root(path)
    keep = os.path.join(backup, os.path.relpath(path, os.path.dirname(ext) if ext else os.path.dirname(path)))
    if not os.path.isdir(os.path.dirname(keep)):
        os.makedirs(os.path.dirname(keep))
    shutil.copy2(path, keep)


def apply_update(plan, env=None):
    """Copy every (source, installed) pair; the replaced files go to %APPDATA%\\Netbuild\\pyRevit\\backups\\<time>.
    Returns (files copied, [error lines], backup folder)."""
    backup = _backup_dir(env)
    copied, errors = 0, []
    for src, dst in plan:
        try:
            _back_up(dst, backup)
            if not os.path.isdir(os.path.dirname(dst)):
                os.makedirs(os.path.dirname(dst))
            shutil.copy2(src, dst)
            copied += 1
        except (IOError, OSError) as e:
            errors.append("%s: %s" % (dst, e))
    return copied, errors, backup


# ------------------------------------------------------------------ header for other extensions
HEADER = ("import netbuild_scripts\n"
          "netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one\n")
HEADER_BUNDLES = (".pushbutton", ".panelbutton")    # not .smartbutton: pyRevit runs those while loading the ribbon
HEADER_FILES = ("script.py", "config.py")
_TRIPLE = re.compile(r"""^[rRuUbB]{0,2}(\"\"\"|\'\'\')""")
_META = re.compile(r"^(__\w+__\s*=|from\s+__future__\s+import\b)")


def _statement_end(lines, i):
    """Index after the statement starting at lines[i] (follows open brackets and triple-quoted strings)."""
    depth, quote = 0, None
    while i < len(lines):
        text = lines[i]
        j = 0
        while j < len(text):
            if quote:
                if text.startswith(quote, j):
                    j, quote = j + len(quote), None
                    continue
            elif text.startswith('"""', j) or text.startswith("'''", j):
                quote = text[j:j + 3]
                j += 3
                continue
            elif text[j] in "\"'":
                k = text.find(text[j], j + 1)
                j = len(text) if k < 0 else k + 1
                continue
            elif text[j] == "#":
                break
            elif text[j] in "([{":
                depth += 1
            elif text[j] in ")]}":
                depth -= 1
            j += 1
        i += 1
        if not quote and depth <= 0 and not text.rstrip().endswith("\\"):
            return i
    return i


def header_position(lines):
    """Where the header goes: after the leading comments, the docstring, `from __future__` imports and the
    __title__ / __author__ / ... lines at the top of the script."""
    i, at = 0, 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        if lines[i].strip():
            at = i + 1                  # keep #! and # -*- coding -*- lines first
        i += 1
    if i < len(lines) and (_TRIPLE.match(lines[i].strip()) or lines[i].strip()[:1] in "\"'"):
        i = at = _statement_end(lines, i)
    while i < len(lines):
        text = lines[i].strip()
        if not text or text.startswith("#"):
            i += 1
        elif _META.match(text):
            i = at = _statement_end(lines, i)
        else:
            break
    return at


def with_header(source):
    """source (text) with the run_live header added, or None when it already has it."""
    if "netbuild_scripts.run_live(" in source:
        return None
    nl = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines(True)
    at = header_position(lines)
    before = lines[:at]
    if before and not before[-1].endswith(("\n", "\r")):
        before[-1] += nl
    block = ([nl] if before else []) + [l + nl for l in HEADER.splitlines()]
    after = lines[at:]
    if after and after[0].strip():
        block.append(nl)
    return "".join(before + block + after)


def extensions_in(folder):
    """folder itself when it is a *.extension, else the *.extension folders directly in it."""
    if not os.path.isdir(folder):
        return []
    if folder.lower().rstrip("\\/").endswith(".extension"):
        return [folder]
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
            if n.lower().endswith(".extension") and os.path.isdir(os.path.join(folder, n))]


def add_header(extensions, lib_file, apply=False, env=None):
    """Add the run_live header to every button script.py / config.py in extensions and copy lib_file
    (netbuild_scripts.py) into each extension's lib, so the import works there too. With apply=False only report.
    Returns ([files changed or to change], [(file, reason) skipped], backup folder or None)."""
    changed, skipped = [], []
    backup = _backup_dir(env) if apply else None
    for ext in extensions:
        for d, dirs, files in os.walk(ext):
            dirs[:] = sorted(n for n in dirs if n not in SKIP_DIRS)
            if not os.path.basename(d).lower().endswith(BUNDLES):
                continue
            dirs[:] = []
            for name in sorted(files):
                if name.lower() not in HEADER_FILES:
                    continue
                path = os.path.join(d, name)
                if not d.lower().endswith(HEADER_BUNDLES):
                    skipped.append((path, "a %s runs while pyRevit loads" % os.path.splitext(d)[1]))
                    continue
                with io.open(path, "rb") as f:
                    raw = f.read()
                bom = raw.startswith(b"\xef\xbb\xbf")
                try:
                    text = raw[3 if bom else 0:].decode("utf-8")
                except UnicodeDecodeError:
                    skipped.append((path, "not UTF-8 text"))
                    continue
                new = with_header(text)
                if new is None:
                    skipped.append((path, "already has the header"))
                    continue
                changed.append(path)
                if apply:
                    _back_up(path, backup)
                    with io.open(path, "wb") as f:
                        f.write((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
        lib = os.path.join(ext, "lib", os.path.basename(lib_file))
        if _key(lib) != _key(lib_file) and _differs(lib_file, lib):
            changed.append(lib)
            if apply:
                _back_up(lib, backup)
                if not os.path.isdir(os.path.dirname(lib)):
                    os.makedirs(os.path.dirname(lib))
                shutil.copy2(lib_file, lib)
    return changed, skipped, backup


# ------------------------------------------------------------------ text
def summary(s):
    """One short line for the Script Folder menu (its message area shows one line)."""
    if not s["folders"]:
        return "No script folder -- buttons run their bundled scripts"
    off = len([f for f in s["folders"] if not os.path.isdir(f)])
    return "%d script folder%s (%s)%s -- live scripts %s" % (
        len(s["folders"]), "" if len(s["folders"]) == 1 else "s", s["from"],
        (", %d not reachable" % off) if off else "", "on" if s["live"] else "off")


def describe(s, bundles=None):
    """The settings (and, given a scan, what was found) as text for the Script Folder button."""
    lines = []
    if s["folders"]:
        lines.append("Script folder%s (%s):" % ("s" if len(s["folders"]) > 1 else "", s["from"]))
        for f in s["folders"]:
            lines.append("    %s%s" % (f, "" if os.path.isdir(f) else "   -- not reachable"))
    else:
        lines.append("No script folder set -- every button runs the script bundled with it.")
    lines.append("Live scripts: %s" % ("on -- buttons run their script from the folder" if s["live"] else
                                       "off -- use Update Scripts to copy changes in"))
    if bundles is not None:
        names = sorted(k for k in bundles if k.endswith(BUNDLES))
        lines.append("%d button folder%s found, in any sub-folder." % (len(names), "" if len(names) == 1 else "s"))
        for k in names:
            if len(bundles[k]) > 1:
                lines.append("    %s is there %d times -- the newest is used: %s" % (
                    os.path.basename(bundles[k][0]), len(bundles[k]), bundles[k][0]))
    return "\n".join(lines)

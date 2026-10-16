# -*- coding: utf-8 -*-
"""
Version archive for the products we sell (Revit MCP Router, Revit Status) - developer only, never shipped.

Every released version is kept for good, source + release, in OneDrive (so on every PC):

    Releases\\<product>\\v<version>_<YYYY-MM-DD>\\
        source\\...                       the files that built it (no __pycache__, venvs or licence files)
        <product> v<version> SOURCE.zip   the same source as one file (easy to find / download from OneDrive online)
        release\\*.zip                    what was deployed
        MANIFEST.json                    version, date, note, SHA-256 of every source file
    Releases\\_Project source snapshots\\Netbuild source <date>.zip   every code/text file of the whole project

Rules
  * Never overwritten: archived files are made read-only, and a version is never archived twice
    with the same source. Same version with CHANGED source (rebuilt without a version bump) gets a
    second folder v<version>_<date>_<HHMMSS> - bump VERSION instead so the history stays readable.
  * build_release.py --deploy (Router), build_revitstatus_release.py --deploy (Revit Status) and
    build_titleblockfix_release.py --deploy (Title Block Fix) call archive() after deploying, so nothing
    needs remembering.

    python release_archive.py --list          # everything archived, per product
    python release_archive.py --snapshot      # zip every code/text file of the project (dated, never overwritten)
"""
import datetime as dt
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import sys
import zipfile

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(PROJECT, "Releases")
SKIP_DIRS = {"__pycache__", ".venv", ".git"}
SKIP_FILES = ["*.pyc", "license.json", "license_cache.json", "selftest_result.txt", "bridge_stderr.log"]


def _walk(path, base):
    """Yield (abs_path, rel_name) for a file or a directory tree, skipping caches and licence files."""
    if os.path.isfile(path):
        yield path, base
        return
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if not any(fnmatch.fnmatch(f, p) for p in SKIP_FILES):
                p = os.path.join(root, f)
                yield p, os.path.join(base, os.path.relpath(p, path))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:   # a full read also makes OneDrive download an online-only file
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _retry(fn, *args, tries=60, wait=1.0):
    """OneDrive holds a folder it is still uploading for a few seconds (WinError 5/32 on rename or delete):
    retry for up to a minute instead of failing after the files are already written."""
    import time
    for i in range(tries):
        try:
            return fn(*args)
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(wait)


def _read_only(folder):
    for root, _, files in os.walk(folder):
        for f in files:
            os.chmod(os.path.join(root, f), stat.S_IREAD)


def writable(folder):
    """Undo _read_only - only for correcting an archive that was provably wrong (say why in its MANIFEST note)."""
    for root, _, files in os.walk(folder):
        for f in files:
            os.chmod(os.path.join(root, f), stat.S_IREAD | stat.S_IWRITE)


def write_source_zip(folder, product, version):
    """<product> v<version> SOURCE.zip beside source\\ (+ source-unverified\\ when present)."""
    zpath = os.path.join(folder, "%s v%s SOURCE.zip" % (product, version))
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ("source", "source-unverified"):
            base = os.path.join(folder, sub)
            for root, _, files in os.walk(base):
                for f in sorted(files):
                    p = os.path.join(root, f)
                    zf.write(p, os.path.join(sub, os.path.relpath(p, base)))
    return zpath


# whole-project source snapshot: code and text only, no binaries, data dumps, caches or licence/secret stores
SNAP_EXT = {".py", ".pyw", ".ps1", ".psm1", ".cmd", ".bat", ".md", ".txt", ".json", ".gs", ".css", ".toml", ".spec",
            ".ini", ".yml", ".yaml", ".html", ".js", ".ts", ".csv", ".xml", ".diff", ".cfg"}
SNAP_SKIP_DIRS = {"__pycache__", ".venv", ".git", ".claude", "Releases", "Portable", "exports", "DimensionCaptures",
                  "node_modules"}
SNAP_MAX_BYTES = 5 * 1024 * 1024


def snapshot_project(note="", log=print):
    """Zip every code/text file of the project into Releases\\_Project source snapshots\\ (never overwritten)."""
    out_dir = os.path.join(ROOT, "_Project source snapshots")
    os.makedirs(out_dir, exist_ok=True)
    now = dt.datetime.now()
    zpath = os.path.join(out_dir, "Netbuild source %s.zip" % now.strftime("%Y-%m-%d"))
    if os.path.exists(zpath):
        zpath = zpath[:-4] + now.strftime(" %H%M%S") + ".zip"
    listed = []
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT):
            dirs[:] = sorted(d for d in dirs if d not in SNAP_SKIP_DIRS and not d.startswith("node-v"))
            for f in sorted(files):
                p = os.path.join(root, f)
                ext = os.path.splitext(f)[1].lower()
                if ext not in SNAP_EXT and not f.startswith(".mcp.json"):
                    continue
                if any(fnmatch.fnmatch(f, pat) for pat in SKIP_FILES) or os.path.getsize(p) > SNAP_MAX_BYTES:
                    continue
                rel = os.path.relpath(p, PROJECT)
                zf.write(p, rel)
                listed.append({"file": rel.replace("\\", "/"), "sha256": _sha(p)})
        zf.writestr("SNAPSHOT.json", json.dumps({"taken": now.isoformat(timespec="seconds"), "note": note,
                                                "files": listed}, indent=1))
    os.chmod(zpath, stat.S_IREAD)
    log("ok    project source snapshot: %s (%d files, %.1f MB)" % (zpath, len(listed), os.path.getsize(zpath) / 1e6))
    return zpath


def archive(product, version, sources, release=(), note="", when=None, log=print):
    """sources: [(path, name inside source\\)]; release: .zip files (copied) or folders (zipped).
    Returns the archive folder (the existing one when this version + source is already archived)."""
    files = [(p, n.replace("\\", "/")) for src, base in sources for p, n in _walk(src, base)]
    manifest = {n: _sha(p) for p, n in files}
    pdir = os.path.join(ROOT, product)
    os.makedirs(pdir, exist_ok=True)
    for name in sorted(os.listdir(pdir)):
        mf = os.path.join(pdir, name, "MANIFEST.json")
        if name.startswith("v%s_" % version) and os.path.isfile(mf):
            with open(mf, encoding="utf-8") as fh:
                if json.load(fh).get("source") == manifest:
                    log("ok    %s v%s already archived: %s" % (product, version, os.path.join(pdir, name)))
                    return os.path.join(pdir, name)
    when = when or dt.datetime.now()
    name = "v%s_%s" % (version, when.strftime("%Y-%m-%d"))
    if os.path.exists(os.path.join(pdir, name)):
        name += dt.datetime.now().strftime("_%H%M%S")
    dest = os.path.join(pdir, name)
    tmp = dest + ".partial"
    if os.path.exists(tmp):
        _retry(shutil.rmtree, tmp)
    for p, n in files:
        d = os.path.join(tmp, "source", n)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(p, d)
        if _sha(d) != manifest[n]:
            raise RuntimeError("archive copy differs from source: %s" % p)
    released = []
    for r in release:
        rdir = os.path.join(tmp, "release")
        os.makedirs(rdir, exist_ok=True)
        if os.path.isfile(r):
            shutil.copy2(r, rdir)
            released.append(os.path.basename(r))
        else:
            zname = "%s v%s.zip" % (os.path.basename(r.rstrip("\\/")), version)
            with zipfile.ZipFile(os.path.join(rdir, zname), "w", zipfile.ZIP_DEFLATED) as zf:
                for p, n in _walk(r, os.path.basename(r.rstrip("\\/"))):
                    zf.write(p, n)
            released.append(zname)
    with open(os.path.join(tmp, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump({"product": product, "version": version, "archived": dt.datetime.now().isoformat(timespec="seconds"),
                   "dated": when.strftime("%Y-%m-%d"), "note": note, "release": released,
                   "source": manifest}, fh, indent=2)
    if files:
        write_source_zip(tmp, product, version)
    _retry(os.replace, tmp, dest)
    _read_only(dest)
    log("ok    archived %s v%s -> %s (%d source files, %s)" % (product, version, dest, len(files),
                                                            ", ".join(released) or "no release"))
    return dest


def listing():
    if not os.path.isdir(ROOT):
        print("nothing archived yet (%s)" % ROOT)
        return
    for product in sorted(os.listdir(ROOT)):
        if not os.path.isdir(os.path.join(ROOT, product)):
            continue
        print(product)
        if product.startswith("_"):
            for name in sorted(os.listdir(os.path.join(ROOT, product))):
                print("  %s" % name)
            continue
        for name in sorted(os.listdir(os.path.join(ROOT, product))):
            mf = os.path.join(ROOT, product, name, "MANIFEST.json")
            if os.path.isfile(mf):
                with open(mf, encoding="utf-8") as fh:
                    m = json.load(fh)
                latest = (m.get("history") or [{}])[-1].get("change") or m.get("note", "")
                print("  %-28s %4d source files  %-40s %s" % (name, len(m.get("source", {})),
                                                             ", ".join(m.get("release", [])) or "-", latest[:70]))


if __name__ == "__main__":
    if "--list" in sys.argv:
        listing()
    elif "--snapshot" in sys.argv:
        snapshot_project()
    else:
        print(__doc__)

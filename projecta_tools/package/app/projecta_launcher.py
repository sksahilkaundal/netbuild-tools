# -*- coding: utf-8 -*-
r"""
ProjectA Tools launcher -- runs the ProjectA ACC Issue Report pipeline (prompt Ver. 05) on a local PC
with the portable Python bundled next to it: no admin rights, no system Python needed.

    "ProjectA Issue Report.bat"                       interactive menu
    "ProjectA Issue Report.bat" check                 environment check (Python, packages, scripts, BASE)
    "ProjectA Issue Report.bat" <step> [options]      one step, for scripting / Claude Code on the PC

    steps   : extract | pending | build | verify | spotcheck | all | walk <argv...>
    options : --base "<BASE>"  --export YYYYMMDD  --pdf "<Issue detail-....pdf>"
              --bcf "<a.bcf>" [--bcf "<b.bcf>" ...]  --cap all|NNNN  --prev YYYYMMDD|none
              --folder "<output folder>" (verify)  --note "<supersede note>"  --yes (all: build
              even when issues have no Studio note = "leave blank")
    Options are remembered in %LOCALAPPDATA%\ProjectA_Tools\user\settings.json.

Every step runs the user's own scripts UNCHANGED in a fresh Python process and sets their
CONFIG globals from here, exactly like the prompt's "Commands behind the prompt":
    <Netbuild>\scripts\ProjectA_IssueReport_Pipeline.py   step 1 extract (RUN_BUILD=False), step 2 build
    <Netbuild>\scripts\ProjectA_IssueWalkthrough.py       pending / log / next / show / goto / bulk
    <Netbuild>\scripts\ProjectA_IssueReport_Verify.py     step 3 verify
    <Netbuild>\ProjectA_IssueExport_Extract.py, <Netbuild>\ProjectA_IssueDetailReport_Build.py
It never writes a Studio note by itself, never closes a PDF viewer and never edits the scripts.
Each run is logged to %LOCALAPPDATA%\ProjectA_Tools\user\logs (full output + the exact code that ran).
"""
import csv
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time

VERSION = "1.0 (pipeline prompt Ver. 05)"
APP = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(APP)
BUNDLED_NETBUILD = os.path.join(PKG, "Netbuild")
LIVE_NETBUILD = r"C:\SK\OneDrive\Netbuild"
USER = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ProjectA_Tools", "user")
SETTINGS = os.path.join(USER, "settings.json")
LOGS, RUNS = os.path.join(USER, "logs"), os.path.join(USER, "runs")
SESSION_LOG = os.path.join(USER, "session_log.csv")

SCRIPTS = {
    "pipeline": os.path.join("scripts", "ProjectA_IssueReport_Pipeline.py"),
    "walkthrough": os.path.join("scripts", "ProjectA_IssueWalkthrough.py"),
    "verify": os.path.join("scripts", "ProjectA_IssueReport_Verify.py"),
    "extract": "ProjectA_IssueExport_Extract.py",
    "build": "ProjectA_IssueDetailReport_Build.py",
}
PACKAGES = ["reportlab", "pymupdf", "win32com", "PIL", "openpyxl"]
DEFAULTS = {"netbuild_root": "", "base": r"C:\SK\Projects\ProjectA\Issues\260914", "export_subdir": "",
            "acc_pdf": "", "bcf": [], "max_issue_id": None, "previous_export_subdir": "",
            "by_model": True, "out_date": "", "supersede_note": "", "last_output": "", "last_output_export": ""}
DATED = re.compile(r"^\d{8}$")
OUT_RE = re.compile(r"^\d{8}_ProjectA_ACC Issue detail \(Issues \d+-\d+\)$")


# ------------------------------------------------------------------ settings
def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    os.makedirs(USER, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def netbuild_root(s):
    """settings value, else the live OneDrive copy when it has the pipeline, else the bundled copy."""
    if s.get("netbuild_root"):
        return s["netbuild_root"]
    if os.path.isfile(os.path.join(LIVE_NETBUILD, SCRIPTS["pipeline"])):
        return LIVE_NETBUILD
    return BUNDLED_NETBUILD


def missing_scripts(s):
    root = netbuild_root(s)
    return [rel for rel in SCRIPTS.values() if not os.path.isfile(os.path.join(root, rel))]


# ------------------------------------------------------------------ console
def say(msg=""):
    print(msg, flush=True)


def banner(msg):
    say("\n" + "=" * 78 + "\n" + msg + "\n" + "=" * 78)


_EOF = []


def ask(prompt, default=None):
    tip = " [%s]" % default if default not in (None, "") else ""
    try:
        v = input("%s%s: " % (prompt, tip)).strip().strip('"')
    except EOFError:                             # input closed: take defaults, and let the menu end
        _EOF.append(1)
        v = ""
    return v if v else ("" if default is None else str(default))


def yes(prompt, default=True):
    v = ask(prompt + (" (Y/n)" if default else " (y/N)")).lower()
    return default if not v else v.startswith("y")


def choose(title, items, default=0, allow_other=True):
    """Pick one of items by number (1-based); Enter = default; free text if allow_other."""
    say(title)
    for i, it in enumerate(items, 1):
        say("  %2d  %s" % (i, it))
    v = ask("Number%s" % (" or name" if allow_other else ""), default + 1 if items else None)
    if v.isdigit() and 1 <= int(v) <= len(items):
        return items[int(v) - 1]
    return v if allow_other else (items[default] if items else "")


def open_in_explorer(path):
    if os.name == "nt" and os.path.exists(path):
        try:
            os.startfile(path)                   # noqa: S606 - opens Explorer on the user's own folder
        except OSError:
            pass


# ------------------------------------------------------------------ child runs
PRE = '''# generated by ProjectA Tools launcher %(version)s -- %(when)s
import os, sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
ROOT = %(root)r
sys.path[:0] = [os.path.join(ROOT, "scripts"), ROOT, %(app)r]
BASE = %(base)r
'''

PIPELINE = '''import ProjectA_IssueReport_Pipeline as p
p.BASE = BASE
p.EXPORT_SUBDIR = %(export)r
p.ACC_PDF = %(pdf)r
p.BCF_FILE = %(bcf)r
p.MAX_ISSUE_ID = %(cap)r
p.PREVIOUS_EXPORT_SUBDIR = %(prev)r
p.BY_MODEL = %(by_model)r
p.OUT_DATE = %(out_date)r
p.SUPERSEDE_NOTE = %(note)r
p.RUN_EXTRACT = %(run_extract)r
p.RUN_BUILD = %(run_build)r
p.main()
'''

PUBLISH = '''import ProjectA_IssueReport_Pipeline as p
p.BASE = BASE
p.SUPERSEDE_NOTE = %(note)r
p.publish(%(staging)r, %(folder)r)
'''

WALK = '''import ProjectA_IssueWalkthrough as w
w.BASE = BASE
w.TAG_CSV = os.path.join(BASE, "core_tagging_completed.csv")
w.NOTES_CSV = os.path.join(BASE, "studio_notes_clean.csv")
w.SNAP_DIR = os.path.join(BASE, "snapshots_full")
w.EXPORT_SUBDIR = %(export)r
if %(bcf)r:
    w.BCF_FILE = %(bcf)r
'''

VERIFY = '''import ProjectA_IssueReport_Verify as v
b = v.b
v.BASE = b.BASE = BASE
b.OURS_CSV = os.path.join(BASE, "core_tagging_completed.csv")
b.Studio_NOTES_CSV = os.path.join(BASE, "studio_notes_clean.csv")
b.BEFORE_DIR = os.path.join(BASE, "snapshots_full")
b.AFTER_DIR = os.path.join(BASE, "snapshots_after_photos")
sys.exit(v.main(%(argv)r))
'''

CHECK = '''import importlib, platform
print("python  %%s  %%s" %% (platform.python_version(), sys.executable))
for name in %(packages)r:
    try:
        m = importlib.import_module(name)
        print("  ok       %%-10s %%s" %% (name, getattr(m, "__version__", getattr(m, "VersionBundle", ""))))
    except Exception as exc:
        print("  MISSING  %%-10s %%s" %% (name, exc))
'''


def run_child(s, action, body, **kw):
    """Run PRE + body in a fresh Python; stream + log the output. Returns (exit code, output text)."""
    os.makedirs(LOGS, exist_ok=True)
    os.makedirs(RUNS, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    code = (PRE % dict(version=VERSION, when=time.strftime("%Y-%m-%d %H:%M"), root=netbuild_root(s), app=APP,
                       base=s["base"])) + (body % kw if kw else body)
    run_file = os.path.join(RUNS, "%s_%s.py" % (stamp, action))
    with open(run_file, "w", encoding="utf-8") as f:
        f.write(code)
    log_file = os.path.join(LOGS, "%s_%s.log" % (stamp, action))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    out, t0 = [], time.time()
    with open(log_file, "w", encoding="utf-8") as log:
        log.write("# code: %s\n# netbuild: %s\n\n" % (run_file, netbuild_root(s)))
        proc = subprocess.Popen([sys.executable, "-u", run_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=env, cwd=netbuild_root(s))
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                say(line)
                log.write(line + "\n")
                out.append(line)
            rc = proc.wait()
        except KeyboardInterrupt:
            proc.wait()
            rc = -1
            say("\n*** interrupted ***")
    text = "\n".join(out)
    session_log(s, action, rc, time.time() - t0, log_file)
    say("\n(log: %s)" % log_file)
    return rc, text


def session_log(s, action, rc, secs, log_file):
    new = not os.path.exists(SESSION_LOG)
    try:
        with open(SESSION_LOG, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["when", "action", "export", "issues cap", "exit code", "minutes", "log"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M"), action, s.get("export_subdir"), s.get("max_issue_id") or "all",
                        rc, round(secs / 60.0, 1), log_file])
    except OSError:
        pass


# ------------------------------------------------------------------ export set-up
def dated_folders(base):
    try:
        return sorted((n for n in os.listdir(base) if DATED.match(n) and os.path.isdir(os.path.join(base, n))),
                      reverse=True)
    except OSError:
        return []


def has_export_csv(base, sub):
    d = os.path.join(base, sub)
    return os.path.isdir(d) and any(re.match(r"ProjectA_issue_detail_report_\d+_\d+\.csv$", f) for f in os.listdir(d))


def setup_export(s):
    banner("Export set-up  (the prompt's blanks)")
    base = ask("BASE", s["base"])
    if "onedrive" in base.lower():
        say("  note: the prompt uses the C:\\SK\\Projects\\... junction, not the OneDrive path")
    if not os.path.isdir(base):
        say("  !!! BASE not found: %s" % base)
        return False
    s["base"] = base
    subs = dated_folders(base)
    export = choose("\nNew export folder (a NEW dated folder under BASE, holding the ACC PDF + BCFs):",
                    subs[:12], 0 if s.get("export_subdir") not in subs[:12] else subs.index(s["export_subdir"]))
    d = os.path.join(base, export)
    if not os.path.isdir(d):
        say("  !!! not found: %s" % d)
        return False
    s["export_subdir"] = export
    pdfs = sorted(n for n in os.listdir(d) if n.lower().endswith(".pdf"))
    pdfs = sorted(pdfs, key=lambda n: not n.lower().startswith("issue detail"))
    if not pdfs:
        say("  !!! no PDF in %s" % d)
        return False
    s["acc_pdf"] = pdfs[0] if len(pdfs) == 1 else choose("\nACC PDF:", pdfs, 0)
    bcfs = sorted(n for n in os.listdir(d) if n.lower().endswith(".bcf"))
    if not bcfs:
        say("  !!! no .bcf in %s" % d)
        return False
    say("\nBCF(s) in the folder (ACC caps a BCF at 250 issues -- list every BCF of this export):")
    for i, n in enumerate(bcfs, 1):
        say("  %2d  %s" % (i, n))
    v = ask("Numbers to use, e.g. 1,2  (Enter = all)", "")
    pick = [bcfs[int(x) - 1] for x in re.findall(r"\d+", v) if 1 <= int(x) <= len(bcfs)] if v else bcfs
    s["bcf"] = pick or bcfs
    cap = ask("\nIssues: all, or the last ACC id to include (#NNNN)", s.get("max_issue_id") or "all")
    s["max_issue_id"] = int(re.sub(r"\D", "", cap)) if re.search(r"\d", cap) else None
    older = [x for x in subs if x < export and has_export_csv(base, x)]
    prev_default = s.get("previous_export_subdir") if s.get("previous_export_subdir") in older else (older[0] if older else "none")
    while True:
        prev = ask("\nPrevious EXPORT FOLDER for the 'movement since' table (YYYYMMDD | none)", prev_default)
        prev = "" if prev.lower() in ("none", "-", "") else prev
        if not prev or has_export_csv(base, prev) or _EOF:
            break
        say("  !!! %s has no ProjectA_issue_detail_report_*.csv -- give the previous EXPORT folder (not the report's"
            " build date), or none. With an extracted CSV: %s" % (prev, ", ".join(older[:6]) or "none"))
    s["previous_export_subdir"] = prev
    save_settings(s)
    show_export(s)
    return True


def show_export(s):
    say("  BASE     : %s" % s["base"])
    say("  Export   : %s" % (s.get("export_subdir") or "(not set -- choose 1)"))
    say("  ACC PDF  : %s" % (s.get("acc_pdf") or "-"))
    say("  BCF(s)   : %s" % (" ; ".join(s.get("bcf") or []) or "-"))
    say("  Issues   : %s" % ("up to #%s" % s["max_issue_id"] if s.get("max_issue_id") else "all"))
    say("  Previous : %s" % (s.get("previous_export_subdir") or "none"))


def export_ready(s):
    if not (s.get("export_subdir") and s.get("acc_pdf") and s.get("bcf")):
        say("Set the export up first (menu 1, or --export / --pdf / --bcf).")
        return False
    miss = missing_scripts(s)
    if miss:
        say("!!! scripts missing in %s:\n    %s\n    Copy them there, or point Settings (menu 9) at your Netbuild folder."
            % (netbuild_root(s), "\n    ".join(miss)))
        return False
    return True


def pipe_kw(s, run_extract, run_build):
    return dict(export=s["export_subdir"], pdf=s["acc_pdf"], bcf=list(s["bcf"]), cap=s.get("max_issue_id"),
                prev=s.get("previous_export_subdir") or "", by_model=bool(s.get("by_model", True)),
                out_date=s.get("out_date") or None, note=s.get("supersede_note") or "",
                run_extract=run_extract, run_build=run_build)


# ------------------------------------------------------------------ steps
def step_extract(s):
    if not export_ready(s):
        return False
    banner("STEP 1  extract only (RUN_BUILD=False)  --  export %s" % s["export_subdir"])
    rc, out = run_child(s, "extract", PIPELINE, **pipe_kw(s, True, False))
    ok = rc == 0
    m = re.search(r"pin snapshots:\s*(\d+)\s*from BCF,\s*(\d+)\s*from PDF(?:\D+(\d+)\s*missing)?", out)
    a = re.search(r"ACC links:\s*(\d+)\s*of\s*(\d+)", out)
    say("\nChecks:")
    if m:
        good = m.group(2) == "0" and (m.group(3) or "0") == "0"
        say("  pin snapshots: %s from BCF, %s from PDF, %s missing  %s" % (
            m.group(1), m.group(2), m.group(3) or "0",
            "OK" if good else "!!! expected 0 from PDF and 0 missing (a BCF not listed? the report would bloat)"))
        ok &= good
    else:
        say("  !!! no 'pin snapshots: N from BCF, 0 from PDF' line in the log")
        ok = False
    if a:
        good = a.group(1) == a.group(2)
        say("  ACC links: %s of %s issues  %s" % (a.group(1), a.group(2), "OK" if good else "!!! some issues have no ACC link"))
        ok &= good
    else:
        say("  !!! no 'ACC links: N of N issues' line in the log")
        ok = False
    say("  exit code %d -> %s" % (rc, "extract OK" if ok else "CHECK THE OUTPUT ABOVE"))
    return ok


def step_pending(s):
    if not export_ready(s):
        return None
    banner("Missing Studio notes (ProjectA_IssueWalkthrough.py pending, no level range) by tier / model")
    body = WALK + "import projecta_helpers\nprojecta_helpers.pending_grouped(BASE, %(export)r, %(prev)r, w)\n"
    rc, out = run_child(s, "pending", body, export=s["export_subdir"], bcf=(s.get("bcf") or [""])[0],
                        prev=s.get("previous_export_subdir") or "")
    m = re.search(r"PENDING_TOTAL=(\d+)", out)
    return int(m.group(1)) if rc == 0 and m else None


def step_log_notes(s):
    if not export_ready(s):
        return
    banner("Log Studio notes (ProjectA_IssueWalkthrough.py log)  --  your notes only; Enter on an empty line to finish")
    say("Format per line:  <acc id>|<L##>|<note>      e.g.  1041|L26|Open. Pending design decision.")
    specs = []
    while True:
        v = ask("note")
        if not v:
            break
        if v.count("|") < 2:
            say("  needs two '|' -- <acc id>|<L##>|<note>")
            continue
        specs.append(v)
    if specs and yes("Log %d note(s)?" % len(specs)):
        run_child(s, "log", WALK + "w.main(%(argv)r)\n", export=s["export_subdir"], bcf=(s.get("bcf") or [""])[0],
                  argv=["log"] + specs)


def step_walk(s, argv=None):
    if not export_ready(s):
        return
    bcf = (s.get("bcf") or [""])[0]
    if argv is None:
        banner("Walkthrough command (ProjectA_IssueWalkthrough.py) -- Revit must be open for next / goto")
        say(" next --lo 41 --hi 58 | next --bldg B001 | show 1041 | goto 47 pump|tank")
        say(" pending --lo 24 --hi 40 | bulk --lo 26 --hi 40 --title \"common path\" \"<note>\"")
        if len(s.get("bcf") or []) > 1:
            bcf = choose("The walkthrough reads ONE BCF -- the one holding these issues:", s["bcf"], 0, False)
        line = ask("command")
        if not line:
            return
        argv = shlex.split(line)
    run_child(s, "walk", WALK + "w.main(%(argv)r)\n", export=s["export_subdir"], bcf=bcf, argv=argv)


def step_build(s):
    if not export_ready(s):
        return None
    banner("STEP 2  build both reports (RUN_EXTRACT=False)  --  export %s" % s["export_subdir"])
    rc, out = run_child(s, "build", PIPELINE, **pipe_kw(s, False, True))
    folder = None
    m = re.search(r"^Output\s*:\s*(.+?)\s*$", out, re.M)
    if m:
        folder = m.group(1)
    elif "NOT PUBLISHED" in out:
        folder = retry_publish(s, out)
    if folder:
        s["last_output"], s["last_output_export"] = folder, s["export_subdir"]
        save_settings(s)
        say("\nOutput folder: %s" % folder)
    else:
        say("\n*** build did not publish an output folder (exit code %d) -- see the output above ***" % rc)
    return folder


def retry_publish(s, out):
    lines = out.splitlines()
    i = next((k for k, l in enumerate(lines) if "NOT PUBLISHED" in l), None)
    try:
        staging, folder = lines[i + 1].strip(), lines[i + 3].strip()
    except (TypeError, IndexError):
        return None
    say("\n!!! The build is done but could not be published: a PDF in the old output folder is open in your viewer.")
    say("    Close that PDF yourself (this tool never closes the viewer), then press Enter to publish again.")
    while True:
        if not yes("Retry the publish now?"):
            say("    Left as staging folder: %s\n    Rename it to: %s" % (staging, folder))
            return None
        rc, out2 = run_child(s, "publish", PUBLISH, note=s.get("supersede_note") or "", staging=staging, folder=folder)
        if re.search(r"^Output\s*:", out2, re.M):
            return folder


def output_folders(base):
    try:
        names = [n for n in os.listdir(base) if OUT_RE.match(n)]
    except OSError:
        return []
    return [os.path.join(base, n) for n in sorted(names, reverse=True)]


def step_verify(s, folder=None, interactive=True):
    if missing_scripts(s):
        export_ready(s)
        return False
    if folder is None:
        found = output_folders(s["base"])
        default = s.get("last_output") if s.get("last_output") in found else (found[0] if found else "")
        if interactive:
            items = [default] + [f for f in found if f != default] if default else found
            folder = choose("Output folder to verify:", items[:12], 0)
        else:
            folder = default
    if not folder or not os.path.isdir(folder):
        say("!!! output folder not found: %s" % folder)
        return False
    banner("STEP 3  verify  --  %s" % folder)
    argv = [folder]
    if folder == s.get("last_output") and s.get("last_output_export"):
        argv.append(s["last_output_export"])         # the export it was built from (needed when capped)
    rc, out = run_child(s, "verify", VERIFY, argv=argv)
    ok = rc == 0 and "ALL CHECKS PASSED" in out
    say("\n" + ("ALL CHECKS PASSED" if ok else "*** VERIFY FAILED -- see FAIL lines above ***"))
    reports = re.findall(r"^(\d{8}_ProjectA_ACC Issue detail.*?\.pdf)\s*\n\s+(\d+) pages, ([\d.]+) MB, (\d+) issue pages",
                         out, re.M)
    if reports:
        say("\nReports:")
        for name, pages, mb, issues in reports:
            say("  %-80s %4s pages  %4s issues  %6s MB" % (name, pages, issues, mb))
    say("Folder: %s" % folder)
    return ok


def step_spotcheck(s):
    if not s.get("export_subdir"):
        say("Set the export up first (menu 1).")
        return
    run_child(s, "spotcheck", "import projecta_helpers\nprojecta_helpers.photo_spot_check(BASE, %(export)r, %(cap)r)\n",
              export=s["export_subdir"], cap=s.get("max_issue_id"))


def run_all(s, interactive=True, leave_blank=False):
    if not step_extract(s):
        if not (interactive and yes("\nExtract checks did not pass. Continue anyway?", False)):
            return
    n = step_pending(s)
    if n is None:
        say("pending list failed -- stopping")
        return
    if n:
        if interactive:
            while True:
                v = ask("\n%d issue(s) have no Studio note. [L]og notes now / [B]uild and leave them blank / [S]top" % n, "S").lower()
                if v.startswith("l"):
                    step_log_notes(s)
                    n = step_pending(s) or 0
                    if not n:
                        break
                elif v.startswith("b"):
                    break
                else:
                    return
        elif not leave_blank:
            say("\n%d issue(s) have no Studio note -- stopping before the build (pass --yes to leave them blank)." % n)
            return
    folder = step_build(s)
    if not folder:
        return
    step_verify(s, folder, interactive=False)
    say("")
    step_spotcheck(s)
    if interactive:
        open_in_explorer(folder)


def check(s):
    banner("Environment check  --  ProjectA Tools %s" % VERSION)
    root = netbuild_root(s)
    say("launcher : %s" % APP)
    say("Netbuild : %s%s" % (root, "  (bundled copy)" if root == BUNDLED_NETBUILD else ""))
    for key, rel in SCRIPTS.items():
        say("  %-8s %-45s %s" % ("ok" if os.path.isfile(os.path.join(root, rel)) else "MISSING", rel, ""))
    say("BASE     : %s  %s" % (s["base"], "ok" if os.path.isdir(s["base"]) else "NOT FOUND"))
    for n in ("core_tagging_completed.csv", "studio_notes_clean.csv"):
        say("  %-8s %s" % ("ok" if os.path.isfile(os.path.join(s["base"], n)) else "MISSING", n))
    rc, out = run_child(s, "check", CHECK, packages=PACKAGES)
    good = rc == 0 and "MISSING" not in out and not missing_scripts(s)
    say("\n" + ("READY" if good else "NOT READY -- fix the MISSING items above"))
    return good


def settings_menu(s):
    banner("Settings")
    say("Scripts folder (Netbuild root, holds ProjectA_IssueExport_Extract.py + scripts\\...).")
    say("  blank = %s if it has the pipeline, else the bundled copy %s" % (LIVE_NETBUILD, BUNDLED_NETBUILD))
    v = ask("Netbuild root", s.get("netbuild_root") or "blank")
    s["netbuild_root"] = "" if v.lower() == "blank" else v
    s["base"] = ask("BASE", s["base"])
    s["by_model"] = yes("Also build the 'by Tier-Model' report (BY_MODEL)?", bool(s.get("by_model", True)))
    v = ask("OUT_DATE (YYYYMMDD to force the report date; blank = today)", s.get("out_date") or "blank")
    s["out_date"] = "" if v.lower() == "blank" else v
    v = ask("SUPERSEDE_NOTE (suffix for a replaced folder in _superseded; blank = 'replaced HHMM')",
            s.get("supersede_note") or "blank")
    s["supersede_note"] = "" if v.lower() == "blank" else v
    save_settings(s)
    check(s)


# ------------------------------------------------------------------ menu / CLI
MENU = """
 1  Set up export (folder, ACC PDF, BCFs, issue cap, previous export)
 2  STEP 1  Extract only  + checks + missing notes by tier / model
 3  Missing Studio notes (walkthrough pending) by tier / model
 4  Log Studio notes (walkthrough log)
 5  STEP 2  Build both reports  (+ publish, retry if a PDF is open)
 6  STEP 3  Verify an output folder
 7  RUN ALL: extract -> notes -> build -> verify -> spot-check list
 8  Walkthrough command (next / show / goto / bulk ...)
 9  Settings + environment check
10  After-photo spot-check list (issues with 2-3 photos)
11  Open BASE / logs folder
 0  Exit"""


def menu(s):
    while True:
        banner("ProjectA Issue Report  --  ProjectF Sports Boulevard ProjectA TOWER    (ProjectA Tools %s)" % VERSION)
        say("  Scripts  : %s%s" % (netbuild_root(s), "  !!! missing: " + ", ".join(missing_scripts(s)) if missing_scripts(s) else ""))
        show_export(s)
        say(MENU)
        c = ask("\nChoose")
        if _EOF:
            return
        try:
            if c == "1":
                setup_export(s)
            elif c == "2":
                if step_extract(s):
                    step_pending(s)
            elif c == "3":
                step_pending(s)
            elif c == "4":
                step_log_notes(s)
            elif c == "5":
                folder = step_build(s)
                if folder and yes("Verify it now?"):
                    step_verify(s, folder, interactive=False)
            elif c == "6":
                step_verify(s)
            elif c == "7":
                run_all(s)
            elif c == "8":
                step_walk(s)
            elif c == "9":
                settings_menu(s)
            elif c == "10":
                step_spotcheck(s)
            elif c == "11":
                open_in_explorer(s["base"])
                open_in_explorer(USER)
            elif c in ("0", "q", "exit"):
                return
        except KeyboardInterrupt:
            say("\n(cancelled)")
        ask("\nPress Enter for the menu")
        if _EOF:
            return


def parse_cli(argv, s):
    opts, rest, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--base", "--export", "--pdf", "--cap", "--prev", "--folder", "--note") and i + 1 < len(argv):
            opts[a] = argv[i + 1]
            i += 2
        elif a == "--bcf" and i + 1 < len(argv):
            opts.setdefault("--bcf", []).append(argv[i + 1])
            i += 2
        elif a == "--yes":
            opts["--yes"] = True
            i += 1
        else:
            rest.append(a)
            i += 1
    if "--base" in opts:
        s["base"] = opts["--base"]
    if "--export" in opts:
        s["export_subdir"] = opts["--export"]
    if "--pdf" in opts:
        s["acc_pdf"] = opts["--pdf"]
    if "--bcf" in opts:
        s["bcf"] = opts["--bcf"]
    if "--cap" in opts:
        c = opts["--cap"]
        s["max_issue_id"] = int(re.sub(r"\D", "", c)) if re.search(r"\d", c) else None
    if "--prev" in opts:
        s["previous_export_subdir"] = "" if opts["--prev"].lower() == "none" else opts["--prev"]
    if "--note" in opts:
        s["supersede_note"] = opts["--note"]
    return opts, rest


def main(argv):
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    s = load_settings()
    if not argv:
        menu(s)
        return 0
    if argv[0] in ("-h", "--help", "help"):
        say(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "walk":                                # pass the rest through verbatim
        step_walk(s, argv[1:])
        return 0
    opts, _ = parse_cli(argv[1:], s)
    save_settings(s)
    if cmd == "check":
        return 0 if check(s) else 1
    if cmd == "extract":
        return 0 if step_extract(s) else 1
    if cmd == "pending":
        return 0 if step_pending(s) is not None else 1
    if cmd == "build":
        return 0 if step_build(s) else 1
    if cmd == "verify":
        return 0 if step_verify(s, opts.get("--folder"), interactive=False) else 1
    if cmd == "spotcheck":
        step_spotcheck(s)
        return 0
    if cmd == "all":
        run_all(s, interactive=False, leave_blank=bool(opts.get("--yes")))
        return 0
    say("unknown command: %s\n%s" % (cmd, __doc__))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

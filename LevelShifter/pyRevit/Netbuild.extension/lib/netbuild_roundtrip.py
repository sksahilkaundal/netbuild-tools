# -*- coding: utf-8 -*-
"""Shared logic for the Netbuild 01 > Schedules and Excel buttons (Export Schedule / Import Excel).

Revit side runs the same scripts the Revit MCP uses (exec with doc/uidoc/DB/System),
Excel side runs CPython 3.14 + openpyxl in a child process. Source scripts live in
C:\\SK\\OneDrive\\Netbuild\\scripts (skill: schedule-roundtrip-excel) - edit them there,
not here. IronPython 2.7 compatible (Revit 2023+).
"""
import datetime
import json
import os
import re

import System
from System.Diagnostics import Process, ProcessStartInfo
from Autodesk.Revit import DB

NETBUILD = r"C:\SK\OneDrive\Netbuild"
SCRIPTS = os.path.join(NETBUILD, "scripts")
DUMP = os.path.join(SCRIPTS, "schedule_roundtrip_dump.py")
BUILD = os.path.join(SCRIPTS, "schedule_roundtrip_build_grouped_xlsx.py")
TOOLS = os.path.join(SCRIPTS, "schedule_roundtrip_plugin_tools.py")
DIFF = os.path.join(SCRIPTS, "schedule_roundtrip_import_diff.py")
IMPORT = os.path.join(SCRIPTS, "schedule_roundtrip_import.py")
AREA_REF = os.path.join(SCRIPTS, "templates", "schedule_roundtrip_area_reference.xlsx")
EXPORT_ROOT = r"C:\SK\Projects\ProjectA\Exports"
DEFAULT_PARAMS = ["Studio_Function Code", "Studio_Sub-Function Code", "Studio_Area_Department"]


class RoundTripError(Exception):
    pass


# ---- helpers -------------------------------------------------------------------------
def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]', "-", s).strip()


def stamp():
    return datetime.datetime.now().strftime("%H%M%S")


def default_dir(create=True):
    if os.path.isdir(EXPORT_ROOT):
        d = os.path.join(EXPORT_ROOT, datetime.date.today().strftime("%Y-%m-%d"))
        if create and not os.path.isdir(d):
            os.makedirs(d)
        return d if os.path.isdir(d) else EXPORT_ROOT
    return os.path.join(os.environ.get("USERPROFILE", ""), "Documents")


def is_locked(path):
    """True when another program (Excel) holds the file open."""
    if not os.path.isfile(path):
        return False
    try:
        fs = System.IO.File.Open(path, System.IO.FileMode.Open, System.IO.FileAccess.ReadWrite,
                                 System.IO.FileShare.None)
        fs.Close()
        return False
    except System.IO.IOException:
        return True


def python_cmd():
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python314", "python.exe")
    return [exe] if os.path.isfile(exe) else ["py", "-3.14"]


def _q(a):
    """Quote one argument for a Windows command line (CommandLineToArgvW rules)."""
    a = u"%s" % a
    if a and not re.search(r'[\s"]', a):
        return a
    out, bs = u'"', 0
    for ch in a:
        if ch == "\\":
            bs += 1
        elif ch == '"':
            out += "\\" * (bs * 2 + 1) + '"'
            bs = 0
        else:
            out += "\\" * bs + ch
            bs = 0
    return out + "\\" * (bs * 2) + '"'


def run_py(args):
    """Run CPython with args; returns (exit code, stdout, stderr)."""
    cmd = python_cmd()
    psi = ProcessStartInfo(cmd[0], u" ".join(_q(x) for x in cmd[1:] + list(args)))
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    psi.RedirectStandardOutput = True
    psi.RedirectStandardError = True
    psi.StandardOutputEncoding = System.Text.Encoding.UTF8
    psi.StandardErrorEncoding = System.Text.Encoding.UTF8
    psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
    psi.EnvironmentVariables["PYTHONWARNINGS"] = "ignore"
    p = Process.Start(psi)
    err = p.StandardError.ReadToEndAsync()
    out = p.StandardOutput.ReadToEnd()
    p.WaitForExit()
    return p.ExitCode, out, err.Result


def last_json(text):
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RoundTripError("No result from helper:\n" + (text or "")[-1500:])


def py_checked(args, what):
    code, out, err = run_py(args)
    if code != 0:
        raise RoundTripError("%s failed (exit %s):\n%s" % (what, code, (err or out)[-1500:]))
    return out


def run_revit_script(path, doc, uidoc, extra):
    """exec a Revit script with the same context execute_revit_code gives it; returns its namespace."""
    from pyrevit import revit
    ns = {"doc": doc, "uidoc": uidoc, "DB": DB, "System": System, "revit": revit,
          "__file__": path, "__name__": "__main__"}
    ns.update(extra)
    with open(path, "r") as f:
        code = f.read()
    exec(compile(code, path, "exec"), ns)
    return ns


def worker_crash(app):
    """Crash dump / captureTryCrash for THIS Revit session's worker (a bulk commit would hang Revit)."""
    try:
        jf = app.RecordingJournalFilename
    except Exception:
        return []
    if not jf or not os.path.isfile(jf):
        return []
    folder, prefix = os.path.dirname(jf), os.path.splitext(os.path.basename(jf))[0]
    hits = [f for f in os.listdir(folder) if f.startswith(prefix + ".worker") and f.lower().endswith(".dmp")]
    log = os.path.join(folder, prefix + ".worker1.log")
    try:
        if os.path.isfile(log) and "captureTryCrash" in open(log).read():
            hits.append(os.path.basename(log) + " (captureTryCrash)")
    except Exception:
        pass
    return hits


# ---- export --------------------------------------------------------------------------
def active_schedule(doc, uidoc):
    """The active view as a ViewSchedule, looked up by Id so the type never depends on how
    the script engine wrapped ActiveView; None when the active view is not a schedule."""
    view = None
    for src in (uidoc, doc):
        try:
            view = src.ActiveView
        except Exception:
            view = None
        if view is not None:
            break
    if view is None:
        return None, "(no active view)"
    label = "%s  [%s]" % (getattr(view, "Name", "?"), getattr(view, "ViewType", "?"))
    for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        if vs.Id == view.Id:
            return vs, label
    return None, label


def check_schedule(view, label=""):
    if view is None:
        import sys
        return ("Open the schedule you want to export first - the active view is not a schedule.\n\n"
                "Active view seen: %s\nEngine: %s" % (label or "-", sys.version.split()[0]))
    if view.IsTemplate:
        return "The active view is a schedule template - open a normal schedule."
    if view.Definition.IsKeySchedule:
        return "Key schedules can't be exported this way - open a normal schedule."
    if view.Definition.GetFieldCount() < 3:
        return "The schedule needs at least 3 columns."
    return None


def work_dir(xlsx):
    """Working files (dump, template, change list) go in a _roundtrip subfolder next to the workbook."""
    d = os.path.join(os.path.dirname(xlsx), "_roundtrip")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def loaded_links(doc):
    """Titles of the loaded Revit links in doc."""
    out = []
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is not None and ld.Title not in out:
            out.append(ld.Title)
    return out


def export_schedule(doc, uidoc, view, out_xlsx, include_links=False):
    folder = work_dir(out_xlsx)
    st = stamp()
    dump = os.path.join(folder, "_schedule_dump_%s_%s.json" % (safe_name(doc.Title), st))
    ns = run_revit_script(DUMP, doc, uidoc, {"SCHEDULE_NAME": view.Name, "OUT_JSON": dump,
                                             "INCLUDE_LINKS": bool(include_links)})
    recs = ns["elem_recs"]
    res = {"dump": dump, "host": len([e for e in recs if e.get("model") == doc.Title]),
           "linked": len([e for e in recs if e.get("model") != doc.Title]),
           "link_models": sorted(set(e.get("model") for e in recs if e.get("model") != doc.Title)),
           "matched": ns["matched"], "excluded": len(ns["foreign"]),
           "owned": len([e for e in recs if e.get("owner") and e.get("owner") != doc.Application.Username])}
    if not recs:
        raise RoundTripError("The schedule shows no elements from this model%s." %
                             (" or its loaded links" if include_links else ""))
    tpl_out = os.path.join(folder, "_template_%s_%s.xlsx" % (safe_name(doc.Title), st))
    t = last_json(py_checked([TOOLS, "template", dump, AREA_REF, tpl_out], "Template"))
    res["layout"] = "Area reference layout" if t["mode"] == "reference" else "all schedule columns"
    res["build_log"] = py_checked([BUILD, dump, t["template"], out_xlsx, "--id-first", "--itemize",
                                   "--level-order", "building", "--band", t["band"],
                                   "--component", t["component"] or "(none)"], "Workbook build")
    if t["mode"] == "generated" and os.path.isfile(tpl_out):
        os.remove(tpl_out)
    res["tie"] = last_json(py_checked([TOOLS, "tieout", dump, out_xlsx], "Total check"))
    res["component"] = t["component"]
    return res


# ---- import --------------------------------------------------------------------------
def workbook_info(xlsx):
    return last_json(py_checked([TOOLS, "info", xlsx], "Reading the workbook"))


def diff(xlsx, params, doc):
    changes = os.path.join(work_dir(xlsx), "_import_changes_%s_%s.json" % (safe_name(doc.Title), stamp()))
    out = py_checked([DIFF, xlsx, changes, "--params", ",".join(params)], "Diff")
    return changes, out


def run_import(doc, uidoc, changes, dry_run):
    return run_revit_script(IMPORT, doc, uidoc, {"CHANGES_JSON": changes, "DRY_RUN": bool(dry_run)})

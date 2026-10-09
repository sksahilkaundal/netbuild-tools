# -*- coding: utf-8 -*-
"""
ProjectA ACC issue walkthrough -- scroll issues, navigate Revit, log the note.

The loop the user wants (see the acc-issue-walkthrough-working-style memory):
    show the next issue  ->  put Revit on that level with the pinned rooms
    selected  ->  take the user's note  ->  log it  ->  next.
No measuring, no analysis, unless asked. The note is the user's judgement.

Usage (from a shell, with the target model OPEN in Revit):
    python ProjectA_IssueWalkthrough.py next  [--lo 41 --hi 58] [--bldg B001]   next un-noted issue in a level range
    python ProjectA_IssueWalkthrough.py show  <acc_id>              one issue's full text + precedents
    python ProjectA_IssueWalkthrough.py goto  <level_no> [regex]    Revit -> that level's plan (VIEW_ORDER), rooms matching regex selected
    python ProjectA_IssueWalkthrough.py log   "<acc_id>|<L##>|<note>" [...]   log one or more notes
    python ProjectA_IssueWalkthrough.py pending [--lo 24 --hi 40] [--bldg B001]   what is still un-noted
    python ProjectA_IssueWalkthrough.py bulk  --lo 26 --hi 40 [--bldg B001] --title "common path" "<note>"   one note for every match

Tier level ranges (projecta-model-reference-by-tier): Podium GF-06, Tier01 07-23,
Tier02 24-40, Tier03 41-58, Tier04 59-75, Tier05 76+. A model owns its range
but CONTAINS every level, so "which model" must come from the range, not
from what levels exist in the open document.

--bldg filters on the code in the placement sheet name
(ProjectC-Studio-DWG-<B001>-L05-...): one export mixes B001, B003, B004, B2B5,
T00O and SW00 sheets on the same level numbers, so a podium-building walk
needs it. goto opens the first view matching CONFIG VIEW_ORDER: in the B1-B5
podium models "<level>_Part Plan_Linked View" (e.g. "Ground Floor_Part Plan_
Linked View"), elsewhere "<level> GA Plan_Linked View"; then any GA plan. It
reads the B00x level names ("B1-05th Floor"). goto works on the ACTIVE model
only: open the building's own model (B2B5 sheets cover B2-B5) before walking.

Revit access: the pyRevit MCP listener's HTTP route on port 48884 -- the
identical call the MCP `execute_revit_code` tool makes, so this works even
in a session where the MCP tools are not loaded. IronPython 2.7 inside
Revit: print ONE formatted string, use DB.Element.Name.__get__(e) for .Name,
and DB.ElementId(Int64(n)) in Revit 2026.

Data files (BASE): the ACC export CSV under EXPORT_SUBDIR (from
ProjectA_IssueExport_Extract.py), the BCF (untruncated descriptions + comments),
core_tagging_completed.csv (one row per ACC id; new ids appended) and
studio_notes_clean.csv (index -> note). ProjectA_IssueDetailReport_Build.py reads
the same two CSVs.
"""
import csv
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
import zipfile

# ----------------------------- CONFIG ---------------------------------
BASE = r"C:\SK\Projects\ProjectA\Issues\260914"
EXPORT_SUBDIR = "20261009"                     # ACC export CSV to read issue rows from
BCF_FILE = "2026-10-08 16_06 245 Issues-260916 to 261008.bcf"   # inside EXPORT_SUBDIR; full descriptions + comments
REVIT_URL = "http://127.0.0.1:48884/revit_mcp/execute_code/"
# goto opens the first view whose name matches, in this order; then any GA plan, then any floor plan.
# B1-B5 podium models: "<level>_Part Plan_Linked View" (not the "... Part Plan_Linked View_SK" copies);
# otherwise "<level> GA Plan_Linked View" (B001's L01 GA one has a double space).
VIEW_ORDER = [r"_Part Plan_Linked\s+View$", r"GA Plan_Linked\s+View$"]
# ------------------------------------------------------------------------

TAG_CSV = os.path.join(BASE, "core_tagging_completed.csv")
NOTES_CSV = os.path.join(BASE, "studio_notes_clean.csv")
SNAP_DIR = os.path.join(BASE, "snapshots_full")


# --------------------------------------------------------------- Revit
REVIT_GOTO = r'''
import re
from System.Collections.Generic import List
nm = lambda e: DB.Element.Name.__get__(e)
LEVEL_NO = %(level)d
KEY = re.compile(r"%(regex)s", re.I) if r"%(regex)s" else None
ORD = r"0*%%d(st|nd|rd|th)\b" %% LEVEL_NO
def is_level(n):
    # "24th Floor"; the podium B00x models prefix the building: "B1-05th Floor"
    return re.match(r"^(B\d+-)?" + ORD, n) is not None or n.strip() == "%(name)s"
def is_view(v):
    # B001's "06th Floor GA Plan" / "06th Floor_Part Plan_Linked View" sit on "B1-Roof Level", so the view name counts too
    return is_level(nm(v.GenLevel)) or (LEVEL_NO > 0 and re.match("^" + ORD + " Floor[ _]", nm(v)) is not None)
views = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan)
         if not v.IsTemplate and v.ViewType == DB.ViewType.FloorPlan
         and v.GenLevel is not None and is_view(v)]
ORDER = %(order)s
def rank(v):
    # the user's views first (VIEW_ORDER), then any GA plan, then the rest
    for i, p in enumerate(ORDER):
        if re.search(p, nm(v)):
            return i
    return len(ORDER) + (0 if "GA" in nm(v) else 1)
views.sort(key=lambda v: (rank(v), len(nm(v))))
if not views:
    print("no floor plan view for level %%d in %%s" %% (LEVEL_NO, doc.Title))
else:
    ids = List[DB.ElementId]()
    lvl_id = views[0].GenLevel.Id
    if KEY is not None:
        for r in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
            if r.Area > 0 and r.Level is not None and (r.LevelId == lvl_id or is_level(nm(r.Level))):
                name = r.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString() or ""
                if KEY.search(name):
                    ids.Add(r.Id)
                    print("  %%s %%s" %% (r.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER).AsString(), name))
    uidoc.ActiveView = views[0]
    uidoc.Selection.SetElementIds(ids)
    if ids.Count: uidoc.ShowElements(ids)
    print("Revit (%%s) -> %%s, %%d selected" %% (doc.Title, nm(views[0]), ids.Count))
'''


def revit(code, description="ProjectA_IssueWalkthrough", use_transaction=False):
    """Run IronPython inside Revit via the pyRevit listener; returns its printed output."""
    payload = {"code": code, "description": description, "use_transaction": use_transaction}
    req = urllib.request.Request(REVIT_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        body = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return "HTTP %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:800])
    except Exception as exc:
        return "Revit unreachable (%s) -- is Revit open with the pyRevit MCP listener running?" % exc
    try:
        d = json.loads(body)
        return d.get("output") or d.get("error") or body
    except Exception:
        return body


def level_name(level_no):
    """Revit level name for the non-ordinal levels: 0 -> Ground Floor, -N -> Basement 0N."""
    n = int(level_no)
    return "Ground Floor" if n == 0 else ("Basement %02d" % -n if n < 0 else "")


def level_label(level_no):
    """Report label: L26, GF, B02 (basements are negative level numbers, see level_of)."""
    if level_no is None: return "?"
    n = int(level_no)
    return "B%02d" % -n if n < 0 else ("GF" if n == 0 else "L%02d" % n)


def goto(level_no, regex=""):
    """Activate the level's plan (first VIEW_ORDER match, else a GA plan) and select rooms whose name matches regex."""
    name = level_name(level_no)
    return revit(REVIT_GOTO % {"level": int(level_no), "regex": regex.replace('"', ''), "name": name,
                               "order": repr(list(VIEW_ORDER))})


# ---------------------------------------------------------------- data
def level_of(sheet):
    """Level number from the placement sheet code: -L26- -> 26, -GFL- -> 0, -B02- -> -2 (basements negative)."""
    m = re.search(r"-L(\d{2})-", sheet or "")
    if m: return int(m.group(1))
    m = re.search(r"-B(\d{2})-", sheet or "")
    if m: return -int(m.group(1))
    return 0 if "-GFL-" in (sheet or "") else None


def bldg_of(sheet):
    """Building / zone code of the placement sheet: ProjectC-Studio-DWG-B001-L02-... -> B001 (None for a 3D-model pin)."""
    m = re.search(r"-DWG-([A-Z0-9]{4})-", sheet or "")
    return m.group(1) if m else None


def read_csv(path):
    """(column names, rows) of a UTF-8 (BOM) CSV."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return rd.fieldnames, list(rd)


def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def export_rows():
    """The export CSV's issue rows (from ProjectA_IssueExport_Extract.py), sorted by ACC id."""
    d = os.path.join(BASE, EXPORT_SUBDIR)
    hits = sorted(f for f in os.listdir(d) if re.match(r"ProjectA_issue_detail_report_\d+_\d+\.csv$", f))
    if not hits:
        raise SystemExit("no ProjectA_issue_detail_report_*.csv in %s -- run ProjectA_IssueExport_Extract.py first" % d)
    return sorted(read_csv(os.path.join(d, hits[0]))[1], key=lambda r: int(r["issue_id"]))


def tag_index():
    """{ACC id: tagging index}."""
    return {r["acc_issue_id"]: r["index"] for r in read_csv(TAG_CSV)[1]}


def notes():
    """{tagging index: Studio note}."""
    return {r["index"]: r["studio_note"] for r in read_csv(NOTES_CSV)[1]}


def note_for(issue_id, tag=None, nts=None):
    tag = tag or tag_index(); nts = nts or notes()
    return (nts.get(tag.get(issue_id, ""), "") or "").strip()


_bcf_cache = None


def bcf_text():
    """{issue_id: (description, [(author, text), ...])} from the BCF -- the CSV
    export truncates descriptions and the CSV 'comments' can lag the BCF."""
    global _bcf_cache
    if _bcf_cache is not None:
        return _bcf_cache
    out = {}
    path = os.path.join(BASE, EXPORT_SUBDIR, BCF_FILE)
    if os.path.exists(path):
        z = zipfile.ZipFile(path)
        clean = lambda t: re.sub(r"[^\x20-\x7e\n]", "", (t or "").replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")).strip()
        for m in [n for n in z.namelist() if n.endswith("markup.bcf")]:
            x = z.read(m).decode("utf-8", "replace")
            i = re.search(r"<Index>(\d+)</Index>", x)
            if not i:
                continue
            d = re.search(r"<Description>(.*?)</Description>", x, re.S)
            cm = []
            for c in re.findall(r"<Comment Guid=.*?</Comment>\s*\n", x, re.S):
                a = re.search(r"<Author>([^<]+)", c); t = re.search(r"<Comment>(.*?)</Comment>", c, re.S)
                if t and clean(t.group(1)):
                    cm.append((a.group(1).split("@")[0] if a else "?", clean(t.group(1))))
            out[i.group(1)] = (clean(d.group(1) if d else ""), cm)
    _bcf_cache = out
    return out


def show(issue_id, rows=None):
    rows = rows or export_rows()
    r = next((r for r in rows if r["issue_id"] == str(issue_id)), None)
    if r is None:
        print("#%s is not in the %s export" % (issue_id, EXPORT_SUBDIR)); return None
    lvl = level_of(r["placement_sheet"])
    desc, comments = bcf_text().get(r["issue_id"], (r["description"], []))
    print("#%s  %s  [%s]  %s  -> %s  by %s  photos=%s" % (
        r["issue_id"], r["title"], r["status"], level_label(lvl),
        r["assigned_to"][:26], r["created_by"][:24], r["photo_count"]))
    print(textwrap.fill(desc or "(no description)", 100, initial_indent="   ", subsequent_indent="   "))
    for a, t in comments:
        print(textwrap.fill("COMMENT (%s): %s" % (a, t), 100, initial_indent="   ", subsequent_indent="      "))
    snap = os.path.join(SNAP_DIR, "%s.png" % r["issue_id"])
    print("   snapshot: %s" % (snap if os.path.exists(snap) else "(none)"))
    tag, nts = tag_index(), notes()
    cur = note_for(r["issue_id"], tag, nts)
    print("   Studio note: %s" % (cur or "(none yet)"))
    same = [(o["issue_id"], level_of(o["placement_sheet"]), note_for(o["issue_id"], tag, nts)) for o in rows
            if o["title"].strip().lower() == r["title"].strip().lower() and o["issue_id"] != r["issue_id"]
            and note_for(o["issue_id"], tag, nts)]
    for i, l, n in same[:4]:
        print("   precedent #%s %s: %s" % (i, level_label(l), n[:110]))
    return r, lvl


def pending(lo=None, hi=None, title=None, rows=None, bldg=None):
    rows = rows or export_rows(); tag, nts = tag_index(), notes()
    out = []
    for r in rows:
        lvl = level_of(r["placement_sheet"])
        if lo is not None and (lvl is None or lvl < lo or lvl > hi):
            continue
        if bldg and (bldg_of(r["placement_sheet"]) or "").upper() != bldg.upper():
            continue
        if title and title.lower() not in r["title"].lower():
            continue
        if not note_for(r["issue_id"], tag, nts):
            out.append(r)
    return out


def log(issue_id, level, note):
    """Append/refresh the note; add a tagging row (next index) for a new ACC id."""
    issue_id = str(issue_id)
    cols, rows = read_csv(TAG_CSV)
    idx = next((r["index"] for r in rows if r["acc_issue_id"] == issue_id), None)
    if idx is None:
        a = next((r for r in export_rows() if r["issue_id"] == issue_id), None)
        if a is None:
            raise SystemExit("#%s is not in the %s export" % (issue_id, EXPORT_SUBDIR))
        idx = str(max(int(r["index"]) for r in rows) + 1)
        row = dict.fromkeys(cols, "")
        row.update({"index": idx, "title": a["title"], "status": a["status"], "assignee": a["assigned_to"],
                    "snapshot_file": issue_id + ".png", "level": level, "placement_sheet": a["placement_sheet"],
                    "acc_issue_id": issue_id, "acc_report_status": a["status"]})
        write_csv(TAG_CSV, cols, rows + [row])
    nr = [r for r in read_csv(NOTES_CSV)[1] if r["index"] != idx] + [{"index": idx, "studio_note": note}]
    write_csv(NOTES_CSV, ["index", "studio_note"], nr)
    print("logged #%s (index %s, %s): %s" % (issue_id, idx, level, note))


# ----------------------------------------------------------------- CLI
def _range(argv):
    lo = hi = None
    if "--lo" in argv:
        lo = int(argv[argv.index("--lo") + 1]); hi = int(argv[argv.index("--hi") + 1])
    return lo, hi


def _bldg(argv):
    return argv[argv.index("--bldg") + 1] if "--bldg" in argv else None


def _warn_3d_pins(lo, bldg=None):
    """A level range or building filter skips issues pinned in a 3D model (no -L##- sheet) -- say how many."""
    if lo is None and not bldg:
        return
    n = len([r for r in pending() if level_of(r["placement_sheet"]) is None])
    if n:
        print("  (+%d un-noted issue(s) pinned in a 3D model, no sheet level -- not in any range; "
              "ProjectA_BcfViewpointLevels.py estimates their level from the BCF viewpoint)" % n)


def main(argv):
    if not argv:
        print(__doc__); return
    cmd, rest = argv[0], argv[1:]
    if cmd == "next":
        lo, hi = _range(rest); bldg = _bldg(rest); todo = pending(lo, hi, bldg=bldg)
        print("pending in range: %d" % len(todo))
        _warn_3d_pins(lo, bldg)
        if todo:
            r, lvl = show(todo[0]["issue_id"])
            if lvl is not None:
                print(goto(lvl))
    elif cmd == "show":
        show(rest[0])
    elif cmd == "goto":
        print(goto(int(rest[0]), rest[1] if len(rest) > 1 else ""))
    elif cmd == "log":
        for spec in rest:
            i, lvl, note = spec.split("|", 2); log(i, lvl, note)
    elif cmd == "pending":
        lo, hi = _range(rest); bldg = _bldg(rest)
        for r in pending(lo, hi, bldg=bldg):
            print("  #%s  %s  %s  [%s]" % (r["issue_id"], level_label(level_of(r["placement_sheet"])), r["title"][:50], r["status"]))
        _warn_3d_pins(lo, bldg)
    elif cmd == "bulk":
        lo, hi = _range(rest); title = rest[rest.index("--title") + 1]; note = rest[-1]
        for r in pending(lo, hi, title, bldg=_bldg(rest)):
            log(r["issue_id"], level_label(level_of(r["placement_sheet"])), note)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

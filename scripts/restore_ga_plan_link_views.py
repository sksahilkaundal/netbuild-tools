# -*- coding: utf-8 -*-
"""
Restore "By Linked View" link display on every GA Plan view placed on the
`10_GA Plans` sheets, for two links, on the LINK TYPE row (instance-row
overrides are removed so the type row governs):

  1. CORE link  (3505-ProjectG-Studio-ARC-RVT-00003) -> the linked view named
     "<link level> GA Plan_Linked View" whose level sits at the SAME ELEVATION
     as the host view's level (host/link level names differ, e.g.
     "Podium 03" vs "Level 01 (Podium 3 as per DCR)", so names are not used).
  2. GRID link  (3505-ProjectG-Studio-ARC-BIM-00001) -> one of three banded views,
     picked by the host level elevation (see GRID_BANDS).

Why this exists: these overrides were lost three times on 2026-09-23..25
(unsaved / unsynced edits, possibly Undo). Run it, then SAVE and SYNC.

Runs from the pyRevit button "Restore GA Link Views" (Studio-Claude.extension,
Netbuild 01 tab) or through the Revit MCP `execute_revit_code` tool.
A link that is missing or not loaded in the active model is reported and
skipped, so the same script is safe on the Tower and Podium models.

DRY_RUN = True  -> report + trial apply inside a TransactionGroup, rolled back.
DRY_RUN = False -> commit. The button injects DRY_RUN = False after its
                   Yes/No confirmation; the MCP default is a dry run.
"""
from Autodesk.Revit.DB import (FilteredElementCollector, ViewSheet, ViewPlan,
                               ViewType, View, Level, RevitLinkInstance,
                               RevitLinkGraphicsSettings, LinkVisibility,
                               Transaction, TransactionGroup, ElementId,
                               BuiltInParameter)

try:
    doc  # injected by the pyRevit wrapper / MCP execute_revit_code
except NameError:
    doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
try:
    DRY_RUN  # the button injects False after its confirmation
except NameError:
    DRY_RUN = True
SHEET_SERIES_PARAM = "Studio_02 - Drawing Series"
SHEET_SERIES_VALUE = "10_GA Plans"
ELEV_TOL_MM = 5.0

CORE_LINK_KEY = "3505-ProjectG-Studio-ARC-RVT-00003"
CORE_VIEW_SUFFIX = "GA Plan_Linked View"      # linked views are "<level> GA Plan_Linked View"

GRID_LINK_KEY = "3505-ProjectG-Studio-ARC-BIM-00001"
# (upper bound of host level elevation in mm, linked view name) - first match wins.
GRID_BANDS = [
    (-0.001,  "00_BIM - Grid Setting -Out (L00)_B_Linked View"),               # basements
    (8951.0,  "00_BIM - Grid Setting -Out (L00)_GF-P1, L4-Roof_Linked View"),  # GF, P1
    (27851.0, "00_BIM - Grid Setting -Out (L00)_P2-L3_Linked View"),           # P2 .. Level 03
    (1.0e9,   "00_BIM - Grid Setting -Out (L00)_GF-P1, L4-Roof_Linked View"),  # Level 04 .. Roof and above
]
# ----------------------------------------------------------------------

MM = 304.8
TOL = ELEV_TOL_MM / MM


def ga_views():
    out = []
    for s in FilteredElementCollector(doc).OfClass(ViewSheet):
        p = s.LookupParameter(SHEET_SERIES_PARAM)
        if not p or (p.AsString() or "") != SHEET_SERIES_VALUE:
            continue
        for vid in s.GetAllPlacedViews():
            v = doc.GetElement(vid)
            if isinstance(v, ViewPlan) and v.ViewType == ViewType.FloorPlan and v.GenLevel:
                out.append((v, s.SheetNumber))
    return sorted(out, key=lambda r: (r[0].GenLevel.Elevation, r[1]))


def find_link(key):
    for i in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        if key in i.Name:
            return i
    return None


def plan_core(views, inst):
    ld = inst.GetLinkDocument()
    levels = list(FilteredElementCollector(ld).OfClass(Level))
    lviews = [v for v in FilteredElementCollector(ld).OfClass(ViewPlan)
              if not v.IsTemplate and v.GenLevel and v.Name.endswith(CORE_VIEW_SUFFIX)]
    rows, skipped = [], []
    for v, sn in views:
        ll = [l for l in levels if abs(l.Elevation - v.GenLevel.Elevation) <= TOL]
        tv = [x for x in lviews if len(ll) == 1 and x.GenLevel.Id == ll[0].Id]
        if len(tv) == 1:
            rows.append((v, sn, tv[0]))
        else:
            skipped.append((sn, v.Name, "link levels at elevation: %d, linked views: %d" % (len(ll), len(tv))))
    return rows, skipped


def plan_grid(views, inst):
    ld = inst.GetLinkDocument()
    lv = dict((v.Name, v) for v in FilteredElementCollector(ld).OfClass(View) if not v.IsTemplate)
    missing = sorted(set(n for _, n in GRID_BANDS if n not in lv))
    if missing:
        return [], [("-", "-", "linked view not found in grid link: %s" % ", ".join(missing))]
    rows = []
    for v, sn in views:
        mm = v.GenLevel.Elevation * MM
        name = next(n for top, n in GRID_BANDS if mm <= top)
        rows.append((v, sn, lv[name]))
    return rows, []


def is_ok(v, sn, tv, inst):
    ot = v.GetLinkOverrides(inst.GetTypeId())
    return (ot is not None and ot.LinkVisibilityType == LinkVisibility.ByLinkView
            and ot.LinkedViewId == tv.Id and v.GetLinkOverrides(inst.Id) is None)


def apply(rows, inst):
    tid = inst.GetTypeId()
    fails = []
    for v, sn, tv in rows:
        try:
            st = RevitLinkGraphicsSettings()
            st.LinkVisibilityType = LinkVisibility.ByLinkView
            st.LinkedViewId = tv.Id
            v.SetLinkOverrides(tid, st)
            if v.GetLinkOverrides(inst.Id):
                v.RemoveLinkOverrides(inst.Id)
        except Exception as ex:
            fails.append((sn, v.Name, str(ex)[:100]))
    return fails


views = ga_views()
print("=" * 70)
print("Model: %s | GA Plan views on '%s' sheets: %d | DRY_RUN: %s" % (doc.Title, SHEET_SERIES_VALUE, len(views), DRY_RUN))

jobs = []
for label, key, planner in (("Core link", CORE_LINK_KEY, plan_core), ("Grid link", GRID_LINK_KEY, plan_grid)):
    inst = find_link(key)
    if inst is None:
        print("%s %s: NOT IN THIS MODEL - skipped" % (label, key))
        continue
    if inst.GetLinkDocument() is None:
        ws = doc.GetWorksetTable().GetWorkset(inst.WorksetId).Name if doc.IsWorkshared else "-"
        print("%s %s: NOT LOADED - skipped. Open workset '%s' (Collaborate > Worksets) or reload the link, then run again."
              % (label, key, ws))
        continue
    rows, skipped = planner(views, inst)
    need = [r for r in rows if not is_ok(r[0], r[1], r[2], inst)]
    print("%s %s: %d views paired, %d already correct, %d to restore, %d skipped"
          % (label, key, len(rows), len(rows) - len(need), len(need), len(skipped)))
    for s in skipped:
        print("   SKIP %s | %s | %s" % s)
    jobs.append((label, inst, rows))

if not views or not jobs:
    print("Nothing to do.")
else:
    tg = TransactionGroup(doc, "Restore GA Plan link views")
    tg.Start()
    t = Transaction(doc, "Restore GA Plan link views")
    t.Start()
    all_fails = []
    for label, inst, rows in jobs:
        all_fails += [(label,) + f for f in apply(rows, inst)]
    status = t.Commit()
    for label, inst, rows in jobs:
        bad = [(sn, v.Name) for v, sn, tv in rows if not is_ok(v, sn, tv, inst)]
        print("%s: verified %d/%d%s" % (label, len(rows) - len(bad), len(rows), (" | NOT OK: %s" % bad) if bad else ""))
    if all_fails:
        print("FAILURES:")
        for f in all_fails:
            print("   %s | %s | %s | %s" % f)
    if DRY_RUN:
        tg.RollBack()
        print("DRY RUN - rolled back, nothing changed.")
    else:
        tg.Assimilate()
        print("APPLIED (%s). Now SAVE and SYNC WITH CENTRAL so it is not lost again." % status)
print("=" * 70)

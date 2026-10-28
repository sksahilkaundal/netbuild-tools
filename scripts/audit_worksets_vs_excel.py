# -*- coding: utf-8 -*-
"""
Audit a model's user worksets against the authoritative Excel register,
create any missing worksets, and consolidate exact-spelling duplicates
(Excel name supersedes) WITHOUT ever deleting a workset that has no
Excel counterpart.

STEP 02 of a 3-step process (Step 01 = link_consumed_discipline_models.py).
REUSABLE TEMPLATE for other building models (B001-B005) and other projects
that follow the same "<Project> - Worksets.xlsx" register convention --
edit only the CONFIG block below (WORKSET_NAMES) for a new run.

============================== WORKFLOW ====================================
The Excel file itself cannot be read from inside Revit/IronPython (no xlsx
library in the pyRevit env) -- read it OUTSIDE Revit first (e.g. openpyxl
via a normal Python interpreter; the file may be locked/open in Excel, in
which case copy it to a scratch path first and read the copy), extract the
exact workset name list from the correct sheet, and paste that list into
WORKSET_NAMES below before running this script inside Revit.

For this project the correct sheet was "Sheet Model " (note trailing space
in the tab name) -- NOT "Sheet1" (an older/different naming draft) and NOT
"Archive" (superseded). Confirm which sheet matches the model's actual
naming convention before trusting it -- compare a handful of live workset
names against each candidate sheet first.

============================ WHAT THIS SCRIPT DOES =========================
1. AUDIT: exact string diff between WORKSET_NAMES and the model's current
   user worksets. Reports MATCHED / MISSING (in Excel, not model) / EXTRA
   (in model, not Excel).
2. CREATE: for every MISSING name, creates a new empty Workset with that
   exact name (Workset.Create).
3. CONSOLIDATE (optional, CONSOLIDATE_PAIRS): for near-duplicate worksets
   that are really the same thing under two different spellings (e.g. model
   had "Link-EL" while Excel says "Link-ELE"), the Excel-named workset is
   ALWAYS the one that survives. Because Workset.Create makes an EMPTY
   workset, consolidation is done as: delete the (empty, just-created)
   Excel-named workset, then WorksetTable.RenameWorkset the OLD
   element-holding workset to the Excel name. This means every element
   keeps its original workset assignment -- nothing is moved, only the
   container is renamed. Verify the Excel-named workset has 0 elements
   (ElementWorksetFilter count) before deleting it -- if it is NOT empty,
   STOP and investigate rather than deleting live content.
4. NEVER deletes a workset that has no Excel counterpart at all (e.g. this
   project's "ID Placeholder" / "LAN Placeholder" -- pre-existing, no Excel
   row, left alone every run per explicit user instruction).

DeleteWorksetSettings requires BOTH constructor args even for
DeleteAllElements -- pass DB.WorksetId.InvalidWorksetId as the second arg
when not moving elements elsewhere.

DRY_RUN = True  -> report only, no worksets created/renamed/deleted.
DRY_RUN = False -> creates MISSING worksets and applies CONSOLIDATE_PAIRS.
"""
from Autodesk.Revit.DB import (
    FilteredWorksetCollector, WorksetKind, Workset, Transaction,
    FilteredElementCollector, ElementWorksetFilter,
    DeleteWorksetSettings, DeleteWorksetOption, WorksetId
)

doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
DRY_RUN = True

# Exact workset names from the authoritative Excel sheet, in the order
# they appear in that sheet. Paste the full list here per project/run --
# read it OUTSIDE Revit first (openpyxl), copy-paste exactly (preserve
# trailing spaces -- some real workset names in this convention DO end
# with a space, e.g. "Studio_AR-Ceiling ").
WORKSET_NAMES = [
    "Studio_AR-00 Link-AV", "Studio_AR-00 Link-Basement", "Studio_AR-00 Link-CAD Host model",
    "Studio_AR-00 Link-Core", "Studio_AR-00 Link-ELE", "Studio_AR-00 Link-Facade",
    "Studio_AR-00 Link-INT", "Studio_AR-00 Link-FF", "Studio_AR-00 Link-LAN",
    "Studio_AR-00 Link-Levels ", "Studio_AR-00 Link-LGT", "Studio_AR-00 Link-MEC",
    "Studio_AR-00 Link-PLB", "Studio_AR-00 Link-Podium Buildings", "Studio_AR-00 Link-STR",
    "Studio_AR-00 Link-TC", "Studio_AR-00 Link-WS", "Studio_AR-00 Link-Tower (PO)",
    "Studio_AR-00 Link-Tower (T1)", "Studio_AR-00 Link-Tower (T2)", "Studio_AR-00 Link-Tower (T3)",
    "Studio_AR-00 Link-Tower (T4)", "Studio_AR-00 Link-Tower (T5)", "Studio_AR-01 Datum Grids (BA)",
    "Studio_AR-01 Datum Grids (PO)", "Studio_AR-01 Datum Grids (TO)",
    "Studio_AR-01 Datum Part Plan Scope Box", "Studio_AR-01 Datum Levels",
    "Studio_AR-01 Datum Ref. Planes", "Studio_AR-Ceiling ", "Studio_AR-Ceiling Fixtures",
    "Studio_AR-Doors (BOH)", "Studio_AR-Doors (FOH)", "Studio_AR-Entourage", "Studio_AR-Facade ",
    "Studio_AR-Facade Cladding", "Studio_AR-Facade Fins", "Studio_AR-Facade Glazing",
    "Studio_AR-Facade Screens", "Studio_AR-Fixtures", "Studio_AR-Floors (BOH)",
    "Studio_AR-Floors (FOH)", "Studio_AR-Furniture ", "Studio_AR-Lifts", "Studio_AR-Parking",
    "Studio_AR-Plot Boundary", "Studio_AR-Railings", "Studio_AR-Ramps",
    "Studio_AR-Room Separation Lines", "Studio_AR-Rooms ", "Studio_AR-Shafts", "Studio_AR-Stairs",
    "Studio_AR-STR Placeholder", "Studio_AR-Walls ", "Studio_AR-Windows", "Studio_AR-Walls Fixtures",
]

# (old_model_name, new_excel_name) pairs already known to be the same
# workset under two spellings. Leave empty on a fresh model where the
# audit hasn't surfaced any duplicates yet -- fill in only after reviewing
# the EXTRA list from a DRY_RUN pass and confirming each pair really is a
# duplicate (never guess; an EXTRA with no plausible Excel match should
# stay an EXTRA, not get force-paired).
CONSOLIDATE_PAIRS = [
    # ("Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE"),
]

# ----------------------------- AUDIT -----------------------------
current = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
current_by_name = {w.Name: w for w in current}
current_names = set(current_by_name.keys())

missing = [n for n in WORKSET_NAMES if n not in current_names]
extra = [n for n in sorted(current_names) if n not in WORKSET_NAMES]
matched = [n for n in WORKSET_NAMES if n in current_names]

print("=" * 70)
print("DRY_RUN = {0}".format(DRY_RUN))
print("Excel rows: {0}  |  Model worksets: {1}".format(len(WORKSET_NAMES), len(current_names)))
print("Matched: {0}  |  Missing: {1}  |  Extra: {2}".format(len(matched), len(missing), len(extra)))
print("-" * 70)
if missing:
    print("MISSING (will be created):")
    for n in missing:
        print("   ", repr(n))
if extra:
    print("EXTRA (in model, no Excel row -- left alone unless in CONSOLIDATE_PAIRS):")
    for n in extra:
        print("   ", repr(n))
print("=" * 70)

# ----------------------------- CREATE MISSING -----------------------------
created = []
if missing and not DRY_RUN:
    t = Transaction(doc, "Create missing worksets from Excel register")
    t.Start()
    for name in missing:
        Workset.Create(doc, name)
        created.append(name)
    t.Commit()
    print("CREATED {0} workset(s).".format(len(created)))

# ----------------------------- CONSOLIDATE -----------------------------
if CONSOLIDATE_PAIRS and not DRY_RUN:
    wt = doc.GetWorksetTable()
    # refresh workset lookup (includes ones just created above)
    current = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
    by_name = {w.Name: w for w in current}

    t = Transaction(doc, "Consolidate duplicate worksets (Excel name supersedes)")
    t.Start()
    done = []
    try:
        for old_name, new_name in CONSOLIDATE_PAIRS:
            old_ws = by_name.get(old_name)
            new_ws = by_name.get(new_name)
            if old_ws is None or new_ws is None:
                print("SKIP (not found): {0} -> {1}".format(old_name, new_name))
                continue
            count = FilteredElementCollector(doc).WherePasses(ElementWorksetFilter(new_ws.Id)).GetElementCount()
            if count != 0:
                raise Exception(
                    "Refusing to delete '{0}' -- it has {1} element(s) on it, "
                    "expected 0 (empty, just-created).".format(new_name, count)
                )
            settings = DeleteWorksetSettings(DeleteWorksetOption.DeleteAllElements, WorksetId.InvalidWorksetId)
            wt.DeleteWorkset(doc, new_ws.Id, settings)
            wt.RenameWorkset(doc, old_ws.Id, new_name)
            done.append((old_name, new_name))
        t.Commit()
        print("CONSOLIDATED {0} pair(s):".format(len(done)))
        for old_name, new_name in done:
            print("   '{0}' -> '{1}'".format(old_name, new_name))
    except Exception as ex:
        t.RollBack()
        print("ROLLED BACK consolidation:", str(ex))

if DRY_RUN:
    print("DRY RUN: no changes made. Set DRY_RUN = False to create/consolidate.")

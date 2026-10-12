# -*- coding: utf-8 -*-
"""
Duplicate a set of source-zone sheets into one or more target zones:
copies sheet metadata (all writable instance parameters except Sheet
Number/Sheet Name identity), renames the sheet number's zone suffix,
and sets the Location/Zone + Browser Filter params on each new sheet.

REUSABLE TEMPLATE — edit only the CONFIG block below for a new run.
See [[duplicate-sheets-by-zone-prompt-template]] for the matching
fill-in-the-blanks chat prompt.

Matches sheets whose SheetNumber starts with SHEET_NUMBER_PREFIX and
ends with "-" + SOURCE_ZONE (e.g. "10G01-B1"). For each match and each
code in TARGET_ZONES, creates a new sheet with the same titleblock,
same Sheet Name, SheetNumber with the zone suffix swapped
(e.g. "10G01-B3"), then sets:
  - LOCATION_ZONE_PARAM  = target zone code (e.g. "B3")
  - BROWSER_FILTER_PARAM = target zone code + BROWSER_FILTER_SUFFIX (e.g. "B3_1-200")

Skips (prints SKIP) any target sheet number that already exists —
never overwrites an existing sheet.

Assumes source sheets have no placed viewports (metadata-only sheets).
If a source sheet does have viewports, this script will NOT copy them —
check GetAllViewports() counts first if that's a possibility for a new
building/run.
"""
from Autodesk.Revit.DB import ViewSheet, Viewport, FilteredElementCollector, StorageType, Transaction

doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
SHEET_NUMBER_PREFIX = "10"          # only sheets whose number starts with this
SOURCE_ZONE = "B1"                  # zone suffix to duplicate FROM, e.g. sheets ending "-B1"
TARGET_ZONES = ["B3", "B4"]         # zone codes to duplicate TO

LOCATION_ZONE_PARAM = "SBFX_SHEET_04_Location/Zone"
BROWSER_FILTER_PARAM = "Studio_03 - Browser Filter"
BROWSER_FILTER_SUFFIX = "_1-200"    # appended to target zone code, e.g. "B3" -> "B3_1-200"

DRY_RUN = True   # True = print the planned creations only, no transaction committed
# ------------------------------------------------------------------------

sheets = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()
source_sheets = [
    s for s in sheets
    if s.SheetNumber.startswith(SHEET_NUMBER_PREFIX) and s.SheetNumber.endswith("-" + SOURCE_ZONE)
]
print("Source sheets found: %d" % len(source_sheets))
for s in source_sheets:
    print("  ", s.SheetNumber, "|", s.Name)

if not source_sheets:
    print("Nothing to do — check SHEET_NUMBER_PREFIX / SOURCE_ZONE against real sheet numbers.")

all_viewports = FilteredElementCollector(doc).OfClass(Viewport).ToElements()
for s in source_sheets:
    vp_count = len([vp for vp in all_viewports if vp.SheetId == s.Id])
    if vp_count:
        print("WARNING: %s has %d placed viewport(s) — this script copies metadata only, "
              "not view placements." % (s.SheetNumber, vp_count))

titleblock_type_id = None
for s in source_sheets:
    tb = FilteredElementCollector(doc, s.Id).OfCategory(
        __import__("Autodesk.Revit.DB", fromlist=["BuiltInCategory"]).BuiltInCategory.OST_TitleBlocks
    ).ToElements()
    if tb:
        titleblock_type_id = tb[0].GetTypeId()
        break
print("Titleblock type id:", titleblock_type_id)

existing_numbers = set(s.SheetNumber for s in sheets)

plan = []
for b1 in source_sheets:
    for zone in TARGET_ZONES:
        new_num = b1.SheetNumber[: -len(SOURCE_ZONE)] + zone
        if new_num in existing_numbers:
            print("SKIP (already exists):", new_num)
            continue
        plan.append((b1, zone, new_num))

print("Planned creations: %d" % len(plan))

if DRY_RUN:
    for b1, zone, new_num in plan:
        print("  DRY RUN:", b1.SheetNumber, "->", new_num, "| zone param ->", zone)
else:
    t = Transaction(doc, "Duplicate sheets by zone")
    t.Start()
    created = []
    for b1, zone, new_num in plan:
        new_sheet = ViewSheet.Create(doc, titleblock_type_id)
        new_sheet.SheetNumber = new_num
        new_sheet.Name = b1.Name

        for p in b1.Parameters:
            try:
                pname = p.Definition.Name
            except Exception:
                continue
            if pname in ("Sheet Number", "Sheet Name"):
                continue
            np = new_sheet.LookupParameter(pname)
            if np is None or np.IsReadOnly:
                continue
            try:
                if p.StorageType == StorageType.String:
                    np.Set(p.AsString() or "")
                elif p.StorageType == StorageType.Integer:
                    np.Set(p.AsInteger())
                elif p.StorageType == StorageType.Double:
                    np.Set(p.AsDouble())
                elif p.StorageType == StorageType.ElementId:
                    eid = p.AsElementId()
                    if eid and eid.value > 0:
                        np.Set(eid)
            except Exception:
                pass

        lz = new_sheet.LookupParameter(LOCATION_ZONE_PARAM)
        if lz:
            lz.Set(zone)

        bf = new_sheet.LookupParameter(BROWSER_FILTER_PARAM)
        if bf:
            bf.Set(zone + BROWSER_FILTER_SUFFIX)

        created.append(new_num)
    t.Commit()

    print("Created: %d" % len(created))
    for c in created:
        print("  ", c)

"""
DoorTypeSwapByRoughWidth.py -- audit doors by rough opening width, then swap
one door TYPE for another across the open Revit model.

Two steps, each independent, both driven by the CONFIG block below:

  Step 1  AUDIT   list every door instance whose type's rough width equals
                  ROUGH_WIDTH_MM (per level, per type, with ids and marks)
  Step 2  SWAP    change every instance of SRC_TYPE to TGT_TYPE (only when
                  APPLY = True -- the standing rule is dry run first)

Grouped instances are reported and skipped: ChangeTypeId on a group member
silently rolls the whole transaction back through the API (see the
group-member-door-type-swap-procedure memory); those must be done by hand
via Edit Group. The commit status is printed -- read it, a "RolledBack" is
not an error message.

Revit access: POSTs IronPython to the pyRevit MCP listener's HTTP route
(http://127.0.0.1:48884/revit_mcp/execute_code/) -- the identical call the
execute_revit_code MCP tool makes -- so it works whether or not the MCP
tools loaded in the session. IronPython 2.7 rules apply inside the code
string: DB.Element.Name.__get__(e) for .Name, str(e.Id) for the id (Revit
2026 ElementId has no .IntegerValue and .value is not exposed to IronPython),
one formatted string per print.

First use 2026-09-18 on ProjectC-Studio-BIM-BA00-ZZZ-AR-900001: 50 doors at
1600 mm (38 DS-121 + 12 DS-42 across B01-B03); 38 DS-121 -> DS-42, none in
groups, Committed, 0 left.

Usage:
    python DoorTypeSwapByRoughWidth.py            # runs the steps enabled in CONFIG
"""
import json
import urllib.request

# ============================== CONFIG ======================================
ROUGH_WIDTH_MM = 1600          # Step 1: doors whose type rough width == this (+-1 mm)
SRC_TYPE = "DS-121 (F00)_Cabinet/Garbage (small room) (1600xVaries)"   # Step 2: from
TGT_TYPE = "DS-42 (F00)_BOH Circulation (1600x2200)"                    # Step 2: to
LEVELS = []                    # e.g. ["Basement 01", "Basement 02"]; [] = every level
RUN_AUDIT = True
RUN_SWAP = True
APPLY = False                  # False = dry run (select + report only); True = commit the swap
REVIT_URL = "http://127.0.0.1:48884/revit_mcp/execute_code/"
# ============================================================================


def revit(code, description="DoorTypeSwapByRoughWidth"):
    payload = {"code": code, "description": description, "use_transaction": False}
    req = urllib.request.Request(REVIT_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        body = urllib.request.urlopen(req, timeout=300).read().decode("utf-8", "replace")
    except Exception as exc:
        return "Revit unreachable (%s) -- is Revit open with the pyRevit MCP listener running?" % exc
    try:
        d = json.loads(body)
        return d.get("output") or d.get("error") or body
    except Exception:
        return body


COMMON = r'''
nm = lambda e: DB.Element.Name.__get__(e)
LEVELS = %(levels)r
def lvl(d):
    return nm(doc.GetElement(d.LevelId)) if d.LevelId != DB.ElementId.InvalidElementId else "?"
def in_scope(d):
    return (not LEVELS) or lvl(d) in LEVELS
def rough_width_mm(t, d):
    for e, key in ((t, DB.BuiltInParameter.FAMILY_ROUGH_WIDTH_PARAM),):
        q = e.get_Parameter(key)
        if q and q.HasValue: return q.AsDouble() * 304.8
    for e, name in ((t, "Rough Width"), (t, "Rough Opening Width"), (d, "Rough Width")):
        q = e.LookupParameter(name)
        if q and q.HasValue and q.StorageType == DB.StorageType.Double: return q.AsDouble() * 304.8
    return None
doors = [d for d in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Doors).WhereElementIsNotElementType() if in_scope(d)]
'''

AUDIT = COMMON + r'''
W = %(w)r
hits = []
for d in doors:
    t = doc.GetElement(d.GetTypeId())
    ro = rough_width_mm(t, d)
    if ro is not None and abs(ro - W) < 1.0:
        mk = d.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK).AsString() or ""
        hits.append((lvl(d), nm(t.Family) + " : " + nm(t), str(d.Id), mk))
print("doors with rough width %%d mm: %%d" %% (W, len(hits)))
summary = {}
for l, ty, i, m in hits: summary[(l, ty)] = summary.get((l, ty), 0) + 1
for (l, ty), n in sorted(summary.items()): print("  %%-16s %%3d  %%s" %% (l, n, ty))
for h in sorted(hits): print("    %%s | id %%s | %%s | mark %%s" %% h)
'''

SWAP = COMMON + r'''
from System.Collections.Generic import List
SRC, TGT, APPLY = %(src)r, %(tgt)r, %(apply)r
types = [t for t in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Doors).WhereElementIsElementType() if nm(t) == TGT]
if len(types) != 1:
    print("target type %%r: found %%d (need exactly 1) -- stop" %% (TGT, len(types)))
else:
    tgt = types[0]
    src_doors = [d for d in doors if nm(doc.GetElement(d.GetTypeId())) == SRC]
    ids = List[DB.ElementId]()
    grouped, free = [], []
    for d in src_doors:
        ids.Add(d.Id)
        (grouped if d.GroupId != DB.ElementId.InvalidElementId else free).append(d)
    uidoc.Selection.SetElementIds(ids)
    per_level = {}
    for d in src_doors: per_level[lvl(d)] = per_level.get(lvl(d), 0) + 1
    print("%%r instances: %%d  (ungrouped %%d, in groups %%d)  by level: %%s" %% (SRC, len(src_doors), len(free), len(grouped), sorted(per_level.items())))
    for d in grouped:
        print("  GROUPED (skipped, do via Edit Group): id %%s | %%s | group %%s" %% (d.Id, lvl(d), nm(doc.GetElement(d.GroupId))))
    if not APPLY:
        print("DRY RUN -- nothing changed; %%d would be swapped to %%r" %% (len(free), TGT))
    elif free:
        t = DB.Transaction(doc, "Door type swap %%s -> %%s" %% (SRC, TGT))
        t.Start()
        ok = 0
        for d in free:
            try:
                d.ChangeTypeId(tgt.Id); ok += 1
            except Exception as ex:
                print("  FAIL id %%s: %%s" %% (d.Id, ex))
        st = t.Commit()
        left = sum(1 for d in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Doors).WhereElementIsNotElementType() if in_scope(d) and nm(doc.GetElement(d.GetTypeId())) == SRC)
        print("changed %%d | commit status: %%s | %%r remaining: %%d" %% (ok, st, SRC, left))
'''


def main():
    if RUN_AUDIT:
        print("=" * 70 + "\nStep 1  audit doors with rough width %d mm\n" % ROUGH_WIDTH_MM + "=" * 70)
        print(revit(AUDIT % {"levels": LEVELS, "w": ROUGH_WIDTH_MM}))
    if RUN_SWAP:
        print("=" * 70 + "\nStep 2  swap %s -> %s  (%s)\n" % (SRC_TYPE, TGT_TYPE, "APPLY" if APPLY else "DRY RUN") + "=" * 70)
        print(revit(SWAP % {"levels": LEVELS, "src": SRC_TYPE, "tgt": TGT_TYPE, "apply": APPLY}))


if __name__ == "__main__":
    main()

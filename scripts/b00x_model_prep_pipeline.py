# -*- coding: utf-8 -*-
"""
Master 3-step B00x model-prep pipeline: audits/cleans discipline links,
creates+consolidates worksets against the Excel register, and places every
link (type AND instance) on its correct workset -- in one script, one
CONFIG block, one run.

REUSABLE TEMPLATE across B001-B005 (and future ProjectA buildings) -- edit only
the CONFIG block for a new run. This consolidates the three step scripts
that were built and run individually for B001 on 2026-09-08:
    scripts\\link_consumed_discipline_models.py   (Step 01)
    scripts\\audit_worksets_vs_excel.py            (Step 02)
    scripts\\assign_link_worksets.py               (Step 03)
Those three remain as standalone references; this file is the single
combined entry point for running all three checks/fixes together on a new
building model. See memory [[b00x-model-prep-pipeline-script]].

============================== WHAT STAYS MANUAL ============================
STEP 01's actual link CREATION cannot be scripted -- the Revit API has no
way to browse ACC/Autodesk Docs folders or build a cloud RevitLinkType from
just a filename (it needs the item's cloud GUID, which this project could
not reliably obtain from ACC web URLs since the ACC site itself was blocked
by browser site permissions in this environment). New links must still be
added by hand: Insert > Link Revit > External Resources > Autodesk Docs >
<project> > A.WIP > 01.Architecture > Consumed > <discipline folder>,
selecting the HOST_BUILDING-specific file (NEVER a T00O/SW00/PO00/BA00
substitute -- see [[revit-link-scope-building-specific]]), Positioning =
"Auto - By Shared Coordinates". This script's STEP01_AUDIT section only
reports what's missing/wrong-scope/present -- it does not create links.

Everything else (creating/consolidating worksets, deleting wrong-scope
links, assigning link type+instance worksets) IS scripted and applied here
when DRY_RUN = False.

============================== RUN ORDER ====================================
1. STEP01_AUDIT   -- report + optionally remove wrong-scope (Tower/SW00/etc)
                      links for REQUIRED_DISCIPLINES. Never adds a link.
2. STEP02_WORKSETS -- create WORKSET_NAMES entries missing from the model;
                      consolidate CONSOLIDATE_PAIRS (Excel name supersedes,
                      renames the element-holding workset in place).
3. STEP03_ASSIGN  -- place every RevitLinkType + its RevitLinkInstance onto
                      its DISC_TO_WORKSET / BUILDING_TO_WORKSET / MANUAL_
                      OVERRIDES workset. Anything with no confident rule is
                      printed under AMBIGUOUS and left untouched -- resolve
                      with the user first, then add to MANUAL_OVERRIDES and
                      re-run.

DRY_RUN = True  -> reports everything, changes nothing. ALWAYS run this
                   first on a new building and read the full report before
                   flipping to False.
DRY_RUN = False -> creates missing worksets, consolidates duplicates,
                   removes wrong-scope links, assigns link worksets.

============================ ROLLOUT STATUS (2026-09-08) ====================
Run for real (DRY_RUN=False) on all of B001-B005 -- see memory
[[b00x-model-prep-pipeline-rollout-history]] for full per-building detail.
Key things a future run should know:

- Interiors (ID) and Telecommunication (TC) have NO building-specific model
  yet for ANY of B001-B005 -- only site-wide/Tower-wide files exist in their
  Consumed folders, correctly left unlinked every time. This is a content
  gap upstream, not a linking bug -- don't try to "fix" it by relaxing the
  building-specific-only rule.
- Near-duplicate worksets (model uses a short/wrong spelling of an Excel
  workset name, e.g. "Link-EL" vs Excel's "Link-ELE", "Link-PL" vs
  "Link-PLB") have shown up on MULTIPLE buildings (B001, B003, B004) --
  expect this on a new building too. A DRY_RUN's Step 02 EXTRA list is where
  these surface; consolidate via CONSOLIDATE_PAIRS, Excel name always wins.
- A link for one building's AR model sometimes appears cross-referenced
  inside a DIFFERENT building's model (seen: B005-ZZZ-AR inside B002,
  B002-ZZZ-AR inside B005) usually landed on the unassigned default Walls
  workset. Precedent target: "Studio_AR-00 Link-Podium Buildings" (used for
  both cross-building AR cases so far) -- but confirm with the user rather
  than auto-applying, since there's no discipline/building code that
  distinguishes "this is a genuine cross-reference" from "this looks wrong."
- KNOWN INCONSISTENCY NOT YET FIXED: B002's own PO00-ZZZ-AR link is still on
  "Link-Podium Buildings", left over from before the PO00->Link-Tower (PO)
  rule was made permanent (during the B004 run). Correct it if B002 is
  revisited.
- CONFIRMED WORKS ON NON-AR HOSTS TOO: after B001-B005 (AR hosts), the
  pipeline was run a second full pass against every building's BM host model
  (ProjectC-Studio-BIM-B00x-ZZZ-BM-950001) -- B001-BM through B005-BM, all
  DRY_RUN=False and verified. Worked unchanged: same Excel worksets, same
  Consumed source, same discipline rules. ROLLOUT NOW COMPLETE across all 10
  host models (5 buildings x AR+BM).
- AR-IN-NON-AR-HOST IS NOW A PERMANENT RULE (AR_IN_NON_AR_HOST_WORKSET,
  currently "Studio_AR-00 Link-Podium Buildings"): every BM host links its own
  building's AR model, and this discipline/building combo has no
  DISC_TO_WORKSET or BUILDING_TO_WORKSET entry. Confirmed 3x by the user
  (B001-BM, B002-BM, B003-BM all answered "Link-Podium Buildings") before
  being promoted from a per-building AskUserQuestion into this standing rule
  -- B004-BM and B005-BM both resolved it automatically with 0 ambiguous.
  Do not re-ask for this case on a future building; only re-ask if a BM host
  ever shows a DIFFERENT target being requested (would mean the rule needs
  qualifying, e.g. by building).
  Watch for "Differing Coordinate Systems" / "Import Geometry Not Visible"
  Revit dialogs appearing mid-link and blocking the MCP API (60s timeout) --
  just close them and retry the same call. Also watch Revit's Home/Recent-
  Files screen: clicking a recent-file thumbnail there is an Open action, not
  a focus action, and on a cloud-central model can trigger a "create local
  copy" prompt -- confirm via screenshot which screen is showing before any
  click during a multi-step computer-use sequence.
"""
import re
from Autodesk.Revit.DB import (
    FilteredElementCollector, FilteredWorksetCollector, WorksetKind,
    RevitLinkType, RevitLinkInstance, Workset, BuiltInParameter,
    Transaction, ElementWorksetFilter,
    DeleteWorksetSettings, DeleteWorksetOption, WorksetId
)

doc = __revit__.ActiveUIDocument.Document

# =========================== CONFIG (edit per run) ==========================
DRY_RUN = True

# The building this host model belongs to (e.g. "B001".."B005").
HOST_BUILDING = "B001"

# --- Step 01: required disciplines, building-specific only -----------------
# code -> ACC Consumed subfolder name (for the manual-link instructions if
# something is reported MISSING).
REQUIRED_DISCIPLINES = {
    "ST": "04_ST_STRUCTURE", "HV": "05_ME_MECHANICAL-HVAC", "PL": "06_PL_PLUMBING",
    "FF": "07_FF_FIRE FIGHTING", "EL": "09_EL_ELECTRICAL", "ID": "02_ID_INTERIORS",
    "LA": "03_LA_LANDSCAPE", "WS": "08_WS_WAYFINDING & SIGNAGE",
    "TC": "10_TC_TELECOMMUNICATION", "AV": "19_AV_Audio Visual",
}
BROAD_SCOPE_CODES = ["T00O", "SW00", "PO00", "BA00"]
REMOVE_WRONG_SCOPE = True  # only takes effect when DRY_RUN = False

# --- Step 02: Excel workset register (paste exact names, read via openpyxl
# OUTSIDE Revit first -- the "3470 ProjectA Wadi High Rise - Worksets.xlsx" file
# is usually locked/open; copy it to a scratch path before reading a copy).
# Confirm the correct tab by comparing a few names against the model's live
# worksets first -- this project's tab is "Sheet Model " (trailing space).
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
# Fill in only after a DRY_RUN pass shows genuine exact-spelling duplicates
# in the EXTRA list -- never guess-pair. (old_model_name, new_excel_name).
CONSOLIDATE_PAIRS = [
    # ("Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE"),
]

# --- Step 03: link workset assignment ---------------------------------------
DISC_TO_WORKSET = {
    "ST": "Studio_AR-00 Link-STR", "EL": "Studio_AR-00 Link-ELE", "FF": "Studio_AR-00 Link-FF",
    "PL": "Studio_AR-00 Link-PLB", "HV": "Studio_AR-00 Link-MEC", "WS": "Studio_AR-00 Link-WS",
    "AV": "Studio_AR-00 Link-AV", "ID": "Studio_AR-00 Link-INT", "LA": "Studio_AR-00 Link-LAN",
    "TC": "Studio_AR-00 Link-TC", "LGT": "Studio_AR-00 Link-LGT",
}
BUILDING_TO_WORKSET = {
    "BA00": "Studio_AR-00 Link-Basement",
    # Standing rules confirmed by user (2026-09-08, on B004): T00O always ->
    # Link-Core; PO00 always -> Link-Tower (PO) (settles earlier per-building
    # inconsistency between B001 and B002).
    "T00O": "Studio_AR-00 Link-Core",
    "PO00": "Studio_AR-00 Link-Tower (PO)",
}
# Standing rule confirmed 3/3 times (B001-BM, B002-BM, B003-BM, 2026-09-08):
# when the HOST is a non-AR model (e.g. a BM/base-model host) and it links
# that same building's own AR model, the AR link always -> Link-Podium
# Buildings. Not covered by DISC_TO_WORKSET (no "AR" entry) or
# BUILDING_TO_WORKSET (B00x codes aren't in there) -- handled as a special
# case in the classify loop below via HOST_BUILDING + disc == "AR".
AR_IN_NON_AR_HOST_WORKSET = "Studio_AR-00 Link-Podium Buildings"
# EXACT FILENAME rules (not discipline-code rules -- "BM" is not a reliable
# discipline signal across the project per user correction 2026-09-08).
MANUAL_OVERRIDES = {
    # "ProjectC-Studio-BIM-PO00-ZZZ-AR-900001.rvt": "Studio_AR-00 Link-Tower (PO)",
    "ProjectC-Studio-BIM-SW00-ZZZ-BM-925001.rvt": "Studio_AR-00 Link-Levels ",
}

# Standing rule confirmed by user (2026-09-08): a link named
# "...-TO-ZZZ-AR-90000X.rvt" (building code literally "TO", not "T00O") is a
# TOWER TIER model -- the trailing digit X in the sequence number gives the
# tier number, target workset "Studio_AR-00 Link-Tower (TX)". Distinct from
# "T00O-ZZZ-AR" (genuine overall/all-towers link -- stays ambiguous, resolve
# per building, usually Link-Core).
TOWER_TIER_RE = re.compile(r"^ProjectC-[A-Z]+-BIM-TO-ZZZ-AR-\d{5}(\d)$", re.IGNORECASE)

NAME_RE = re.compile(r"^ProjectC-[A-Z]+-BIM-([A-Z0-9]+)-ZZZ-([A-Z]+)-\d+", re.IGNORECASE)


def ws_int(ws):
    wid = ws.Id
    return wid.IntegerValue if hasattr(wid, 'IntegerValue') else wid.Value


def get_ws_name(elem, ws_by_id):
    wid = elem.WorksetId
    key = wid.IntegerValue if hasattr(wid, 'IntegerValue') else wid.Value
    return ws_by_id.get(key, "UNKNOWN(%s)" % key)


def link_type_name(lt):
    p = lt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
    return p.AsString() if p else ""


print("#" * 70)
print("B00x MODEL PREP PIPELINE -- host building: {0} -- DRY_RUN = {1}".format(HOST_BUILDING, DRY_RUN))
print("#" * 70)

# ============================ STEP 01: LINK AUDIT ============================
print("\n--- STEP 01: discipline link audit (never creates links) ---")
link_types = list(FilteredElementCollector(doc).OfClass(RevitLinkType))
parsed = []
for lt in link_types:
    name = link_type_name(lt)
    m = NAME_RE.match(name)
    parsed.append((lt, name, m.group(1).upper() if m else None, m.group(2).upper() if m else None))

linked_ok, wrong_scope, missing = [], [], []
for disc, folder in REQUIRED_DISCIPLINES.items():
    matches = [row for row in parsed if row[3] == disc]
    host_match = next((row for row in matches if row[2] == HOST_BUILDING), None)
    broad_match = next((row for row in matches if row[2] in BROAD_SCOPE_CODES), None)
    if host_match:
        linked_ok.append((disc, host_match[1]))
    elif broad_match:
        wrong_scope.append((disc, broad_match[0], broad_match[1]))
    else:
        missing.append((disc, folder))

print("OK ({0}), WRONG SCOPE ({1}), MISSING ({2})".format(len(linked_ok), len(wrong_scope), len(missing)))
for disc, lt, name in wrong_scope:
    print("   WRONG SCOPE [{0}] {1}{2}".format(disc, name, " -> WILL REMOVE" if (REMOVE_WRONG_SCOPE and not DRY_RUN) else ""))
for disc, folder in missing:
    print("   MISSING [{0}] -- manual link needed from Consumed/{1}, {2}-specific file only".format(disc, folder, HOST_BUILDING))

if wrong_scope and REMOVE_WRONG_SCOPE and not DRY_RUN:
    t = Transaction(doc, "Step01: remove wrong-scope discipline links")
    t.Start()
    for disc, lt, name in wrong_scope:
        doc.Delete(lt.Id)
    t.Commit()
    print("   Removed {0} wrong-scope link(s).".format(len(wrong_scope)))

# ============================ STEP 02: WORKSETS ============================
print("\n--- STEP 02: worksets vs Excel register ---")
current = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
current_by_name = {w.Name: w for w in current}
current_names = set(current_by_name.keys())
ws_missing = [n for n in WORKSET_NAMES if n not in current_names]
ws_extra = [n for n in sorted(current_names) if n not in WORKSET_NAMES]

print("Excel {0} | Model {1} | Missing {2} | Extra {3}".format(
    len(WORKSET_NAMES), len(current_names), len(ws_missing), len(ws_extra)))
for n in ws_missing:
    print("   MISSING (will create):", repr(n))
for n in ws_extra:
    print("   EXTRA (left alone unless in CONSOLIDATE_PAIRS):", repr(n))

if not DRY_RUN:
    if ws_missing:
        t = Transaction(doc, "Step02: create missing worksets")
        t.Start()
        for name in ws_missing:
            Workset.Create(doc, name)
        t.Commit()
        print("   Created {0} workset(s).".format(len(ws_missing)))

    if CONSOLIDATE_PAIRS:
        wt = doc.GetWorksetTable()
        current = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
        by_name = {w.Name: w for w in current}
        t = Transaction(doc, "Step02: consolidate duplicate worksets")
        t.Start()
        try:
            for old_name, new_name in CONSOLIDATE_PAIRS:
                old_ws, new_ws = by_name.get(old_name), by_name.get(new_name)
                if old_ws is None or new_ws is None:
                    print("   SKIP (not found):", old_name, "->", new_name)
                    continue
                count = FilteredElementCollector(doc).WherePasses(ElementWorksetFilter(new_ws.Id)).GetElementCount()
                if count != 0:
                    raise Exception("Refusing to delete '{0}' -- {1} element(s) on it".format(new_name, count))
                settings = DeleteWorksetSettings(DeleteWorksetOption.DeleteAllElements, WorksetId.InvalidWorksetId)
                wt.DeleteWorkset(doc, new_ws.Id, settings)
                wt.RenameWorkset(doc, old_ws.Id, new_name)
                print("   Consolidated '{0}' -> '{1}'".format(old_name, new_name))
            t.Commit()
        except Exception as ex:
            t.RollBack()
            print("   ROLLED BACK consolidation:", str(ex))

# ============================ STEP 03: ASSIGN LINK WORKSETS =================
print("\n--- STEP 03: assign link type+instance worksets ---")
worksets = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
ws_by_name = {w.Name: w for w in worksets}
ws_by_id = {ws_int(w): w.Name for w in worksets}
link_types = list(FilteredElementCollector(doc).OfClass(RevitLinkType))
link_instances = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))

confident, ambiguous = [], []
for lt in link_types:
    name = link_type_name(lt)
    m = NAME_RE.match(name)
    if not m:
        ambiguous.append((name, "filename doesn't match naming convention"))
        continue
    building, disc = m.group(1).upper(), m.group(2).upper()
    tier_m = TOWER_TIER_RE.match(name)
    if name in MANUAL_OVERRIDES:
        confident.append((lt, name, MANUAL_OVERRIDES[name]))
    elif disc == "AR" and building == HOST_BUILDING and AR_IN_NON_AR_HOST_WORKSET in ws_by_name:
        confident.append((lt, name, AR_IN_NON_AR_HOST_WORKSET))
    elif tier_m:
        target = "Studio_AR-00 Link-Tower (T{0})".format(tier_m.group(1))
        if target in ws_by_name:
            confident.append((lt, name, target))
        else:
            ambiguous.append((name, "Tower Tier T{0} workset doesn't exist yet -- run Step 02 first".format(tier_m.group(1))))
    elif disc in DISC_TO_WORKSET and DISC_TO_WORKSET[disc] in ws_by_name:
        confident.append((lt, name, DISC_TO_WORKSET[disc]))
    elif building in BUILDING_TO_WORKSET and BUILDING_TO_WORKSET[building] in ws_by_name:
        confident.append((lt, name, BUILDING_TO_WORKSET[building]))
    else:
        ambiguous.append((name, "no confident rule (building={0} disc={1}) -- resolve with user, add to MANUAL_OVERRIDES".format(building, disc)))

for lt, name, target in confident:
    current_ws = get_ws_name(lt, ws_by_id)
    print("   {0}: {1} -> {2}{3}".format(name, current_ws, target, " (no change)" if current_ws == target else ""))
for name, reason in ambiguous:
    print("   AMBIGUOUS:", name, "--", reason)

if not DRY_RUN and confident:
    t = Transaction(doc, "Step03: assign link type+instance worksets")
    t.Start()
    applied = 0
    for lt, name, target_name in confident:
        target_ws = ws_by_name[target_name]
        lt.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM).Set(ws_int(target_ws))
        applied += 1
        inst = next((li for li in link_instances if li.GetTypeId() == lt.Id), None)
        if inst is not None:
            inst.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM).Set(ws_int(target_ws))
            applied += 1
    t.Commit()
    print("   Applied {0} assignment(s).".format(applied))

print("\n" + "#" * 70)
if DRY_RUN:
    print("DRY RUN complete -- nothing changed. Review AMBIGUOUS items with the user, fill in overrides, then set DRY_RUN = False.")
else:
    print("PIPELINE APPLIED for {0}.".format(HOST_BUILDING))
print("#" * 70)

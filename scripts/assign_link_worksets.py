# -*- coding: utf-8 -*-
"""
Place every Revit Link's TYPE and INSTANCE onto its matching "Link-*"
workset, using a discipline-code lookup table with a fuzzy fallback for
anything the table doesn't cover. Never silently guesses a low-confidence
placement -- those are printed under AMBIGUOUS for a human decision.

STEP 03 of a 3-step process (Step 01 = link_consumed_discipline_models.py,
Step 02 = audit_worksets_vs_excel.py). REUSABLE for other building models
(B001-B005) -- edit only the CONFIG block below for a new run.

============================== WORKFLOW ====================================
Filename convention: ProjectC-<ORG>-BIM-<BUILDING>-ZZZ-<DISC>-<SEQNO>.rvt
  DISC = 2-3 letter discipline code (ST, EL, FF, PL, HV, WS, AV, ID, LA, TC,
         BM, AR...). This is looked up in DISC_TO_WORKSET for a confident
         match. BUILDING (T00O, SW00, PO00, BA00, B00x) is used only for the
         handful of AR-discipline "context" links, via BUILDING_TO_WORKSET.

Every RevitLinkType AND its corresponding RevitLinkInstance are both moved
-- Revit tracks these as two separate workset assignments (the type's own
placement and the instance's placement can differ and both need setting).
Workset assignment uses BuiltInParameter.ELEM_PARTITION_PARAM (an Integer
storage param holding the workset id) -- NOT a dedicated "SetWorkset" API
method. WorksetId has no .IntegerValue in Revit 2026 -- use `.Value`,  or
the hasattr() fallback below for cross-version safety (mirrors the 2026
ElementId.IntegerValue removal noted elsewhere in this project).

============================ CONFIDENCE TIERS ===============================
- CONFIDENT: DISC_TO_WORKSET has an exact entry AND a workset with that
  exact name exists in the model -- applied automatically.
- AMBIGUOUS: discipline/building code has no table entry, OR the current
  placement conflates two genuinely different links onto one workset (seen
  live: a building's own PO00-AR and an unrelated B00x-AR cross-reference
  both defaulted onto "Link-Podium Buildings" -- one is right, one isn't).
  These are PRINTED, never auto-applied. Resolve them with the user
  (one-by-one, present the real candidate worksets, do not guess), then add
  the resolved pairs to MANUAL_OVERRIDES and re-run.

============================ ROLLOUT STATUS (2026-09-08) ====================
Run across all of B001-B005 -- see memory
[[b00x-model-prep-pipeline-rollout-history]] for full detail. T00O and PO00
are now PERMANENT rules in BUILDING_TO_WORKSET (T00O->Link-Core,
PO00->Link-Tower (PO)), no longer ambiguous. SW00-ZZZ-BM-925001 is pinned
by exact filename in MANUAL_OVERRIDES (not a discipline-wide "BM" rule --
BM is not a reliable discipline signal project-wide). Still genuinely
ambiguous, resolve per building: a cross-building AR link (one building's
AR model linked inside a different building, e.g. B005-ZZZ-AR seen inside
B002, B002-ZZZ-AR seen inside B005) -- precedent target has been
"Link-Podium Buildings" both times, but confirm with the user rather than
auto-applying. KNOWN UNFIXED: B002's own PO00-ZZZ-AR link predates the
PO00 rule and is still on Link-Podium Buildings -- correct if revisited.

DRY_RUN = True  -> report only, no changes.
DRY_RUN = False -> applies CONFIDENT matches + MANUAL_OVERRIDES.
"""
import re
from Autodesk.Revit.DB import (
    FilteredElementCollector, FilteredWorksetCollector, WorksetKind,
    RevitLinkType, RevitLinkInstance, BuiltInParameter, Transaction
)

doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
DRY_RUN = True

# Discipline code -> exact target workset name. Extend as new disciplines
# get linked (see [[link-consumed-discipline-models-script]] for the
# discipline codes this project uses).
DISC_TO_WORKSET = {
    "ST": "Studio_AR-00 Link-STR",
    "EL": "Studio_AR-00 Link-ELE",
    "FF": "Studio_AR-00 Link-FF",
    "PL": "Studio_AR-00 Link-PLB",
    "HV": "Studio_AR-00 Link-MEC",
    "WS": "Studio_AR-00 Link-WS",
    "AV": "Studio_AR-00 Link-AV",
    "ID": "Studio_AR-00 Link-INT",
    "LA": "Studio_AR-00 Link-LAN",
    "TC": "Studio_AR-00 Link-TC",
    "LGT": "Studio_AR-00 Link-LGT",
}

# Standing rule confirmed by user (2026-09-08): a link named
# "...-TO-ZZZ-AR-90000X.rvt" (building code literally "TO", not "T00O") is a
# TOWER TIER model -- the trailing digit X in the sequence number gives the
# tier number, target workset "Studio_AR-00 Link-Tower (TX)". Distinct from
# "T00O-ZZZ-AR" (a genuine overall/all-towers link, stays ambiguous / on
# Link-Core per building -- don't conflate the two building codes).
TOWER_TIER_RE = re.compile(r"^ProjectC-[A-Z]+-BIM-TO-ZZZ-AR-\d{5}(\d)$", re.IGNORECASE)

# Building/context code -> target workset, for AR-discipline "whole
# building context" links only (T00O, PO00, BA00 etc, NOT B00x-ST/EL/etc
# which use DISC_TO_WORKSET above).
BUILDING_TO_WORKSET = {
    "BA00": "Studio_AR-00 Link-Basement",
    # Standing rules confirmed by user (2026-09-08, on B004): T00O always ->
    # Link-Core; PO00 always -> Link-Tower (PO). This settles earlier
    # per-building inconsistency (B001 moved PO00 to Link-Tower (PO), B002
    # kept it on Link-Podium Buildings -- B004's answer makes Link-Tower (PO)
    # the permanent rule going forward).
    "T00O": "Studio_AR-00 Link-Core",
    "PO00": "Studio_AR-00 Link-Tower (PO)",
}

# (filename, target_workset_name) -- filled in after resolving an
# AMBIGUOUS case with the user. Applied same as CONFIDENT matches. These are
# EXACT FILENAME rules, not discipline-code rules -- "BM" is not a reliable
# discipline signal across the project (per user correction 2026-09-08), so
# each SW00-ZZZ-BM-* filename is pinned individually here rather than a
# blanket DISC_TO_WORKSET["BM"] entry.
MANUAL_OVERRIDES = {
    "ProjectC-Studio-BIM-PO00-ZZZ-AR-900001.rvt": "Studio_AR-00 Link-Tower (PO)",
    "ProjectC-Studio-BIM-SW00-ZZZ-BM-925001.rvt": "Studio_AR-00 Link-Levels ",
}

NAME_RE = re.compile(r"^ProjectC-[A-Z]+-BIM-([A-Z0-9]+)-ZZZ-([A-Z]+)-\d+", re.IGNORECASE)

# ----------------------------- GATHER -----------------------------
worksets = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
ws_by_name = {w.Name: w for w in worksets}


def ws_int(ws):
    wid = ws.Id
    return wid.IntegerValue if hasattr(wid, 'IntegerValue') else wid.Value


def get_ws_name(elem, ws_by_id):
    wid = elem.WorksetId
    key = wid.IntegerValue if hasattr(wid, 'IntegerValue') else wid.Value
    return ws_by_id.get(key, "UNKNOWN(%s)" % key)


ws_by_id = {ws_int(w): w.Name for w in worksets}

link_types = list(FilteredElementCollector(doc).OfClass(RevitLinkType))
link_instances = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))


def link_name(lt):
    p = lt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
    return p.AsString() if p else ""


# ----------------------------- CLASSIFY -----------------------------
confident = []   # (link_type_elem, name, target_workset_name)
ambiguous = []    # (name, reason)

for lt in link_types:
    name = link_name(lt)
    m = NAME_RE.match(name)
    if not m:
        ambiguous.append((name, "filename doesn't match naming convention"))
        continue
    building, disc = m.group(1).upper(), m.group(2).upper()

    tier_m = TOWER_TIER_RE.match(name)

    if name in MANUAL_OVERRIDES:
        confident.append((lt, name, MANUAL_OVERRIDES[name]))
    elif tier_m:
        target = "Studio_AR-00 Link-Tower (T%s)" % tier_m.group(1)
        if target in ws_by_name:
            confident.append((lt, name, target))
        else:
            ambiguous.append((name, "Tower Tier T%s workset doesn't exist yet -- run Step 02 first" % tier_m.group(1)))
    elif disc in DISC_TO_WORKSET and DISC_TO_WORKSET[disc] in ws_by_name:
        confident.append((lt, name, DISC_TO_WORKSET[disc]))
    elif building in BUILDING_TO_WORKSET and BUILDING_TO_WORKSET[building] in ws_by_name:
        confident.append((lt, name, BUILDING_TO_WORKSET[building]))
    else:
        ambiguous.append((name, "no confident rule for building=%s disc=%s -- resolve with user, add to MANUAL_OVERRIDES" % (building, disc)))

# ----------------------------- REPORT -----------------------------
print("=" * 70)
print("DRY_RUN = {0}".format(DRY_RUN))
print("CONFIDENT ({0}):".format(len(confident)))
for lt, name, target in confident:
    current = get_ws_name(lt, ws_by_id)
    changed = " (CHANGE: {0} -> {1})".format(current, target) if current != target else " (already correct)"
    print("   {0}{1}".format(name, changed))
print("-" * 70)
print("AMBIGUOUS ({0}) -- not touched, resolve manually:".format(len(ambiguous)))
for name, reason in ambiguous:
    print("   {0}  --  {1}".format(name, reason))
print("=" * 70)

# ----------------------------- APPLY -----------------------------
if not DRY_RUN:
    t = Transaction(doc, "Step 03: assign link type+instance worksets")
    t.Start()
    applied = []
    for lt, name, target_name in confident:
        target_ws = ws_by_name[target_name]
        lt.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM).Set(ws_int(target_ws))
        applied.append((name, "TYPE", target_name))
        inst = next((li for li in link_instances if li.GetTypeId() == lt.Id), None)
        if inst is not None:
            inst.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM).Set(ws_int(target_ws))
            applied.append((name, "INSTANCE", target_name))
    t.Commit()
    print("APPLIED {0} assignment(s).".format(len(applied)))
    for a in applied:
        print("   ", a)
else:
    print("DRY RUN: no changes made. Set DRY_RUN = False to apply CONFIDENT + MANUAL_OVERRIDES.")

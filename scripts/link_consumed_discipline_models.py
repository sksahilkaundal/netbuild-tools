# -*- coding: utf-8 -*-
"""
Audit + clean up a building's Revit Links against the set of discipline
models that SHOULD be linked in from ACC, per the project's "Consumed"
folder convention.

STEP 1 of a 3-step process (later steps not yet defined as of this run).
This script is REUSABLE for other building models (B001-B005) — edit only
the CONFIG block below for a new run.

============================== BACKGROUND =================================
Source location in ACC (Autodesk Construction Cloud / Autodesk Docs), browsed
via Revit's own Insert > Link Revit > External Resources > Autodesk Docs
dialog (NOT the ACC web site — that was blocked by browser site permissions
in this environment; Revit's native cloud connector is a separate, working
path):

    <Project Root> \ A.WIP \ 01.Architecture \ Consumed \ <NN>_<CODE>_<NAME>\

Each host discipline (here: Architecture, since the open doc is the B00x AR
model) has its own "Consumed" folder containing subfolders for every OTHER
discipline it references, using the SAME numbering/codes as the ACC web
folder structure (02_ID_INTERIORS, 03_LA_LANDSCAPE, 04_ST_STRUCTURE,
05_ME_MECHANICAL-HVAC, 06_PL_PLUMBING, 07_FF_FIRE FIGHTING,
08_WS_WAYFINDING & SIGNAGE, 09_EL_ELECTRICAL, 10_TC_TELECOMMUNICATION,
19_AV_Audio Visual). AVOID the "_Archive" subfolder inside 01.Architecture
itself, and any "Archive" subfolder inside a discipline's own folder.

File naming convention: ProjectC-<ORG>-BIM-<BUILDING>-ZZZ-<DISC>-<SEQNO>.rvt
  ORG      = originating company (e.g. Studio, DEC)
  BUILDING = B001-B005 (asset/building code) -- MUST match the host building
  DISC     = 2-letter discipline code (ST, EL, FF, PL, HV, WS, AV, ID, LA, TC...)

=========================== CRITICAL RULE ==================================
ONLY link files scoped to the HOST BUILDING code (e.g. B001). Do NOT
substitute a Tower-wide (T00O) or Site-Wide (SW00) scoped file even if it is
the ONLY file present in that discipline's Consumed subfolder. This was
tried once (Interiors and Landscape only had SW00 files, Telecommunication
only had a T00O file) and the user explicitly rejected it and had those
three links removed afterward — see memory
[[revit-link-scope-building-specific]]. If no building-specific file exists
for a discipline, this script reports it as MISSING and does NOT link
anything for it — flag to the user instead of guessing.

======================== WHAT THIS SCRIPT DOES / DOESN'T ===================
The Revit API has NO way to browse ACC/Autodesk Docs folder contents or
create a cloud RevitLinkType purely from a file name (cloud linking needs
either the item's GUID via ModelPathUtils.ConvertCloudGUIDsToCloudPath, which
this project could not reliably obtain from ACC web URLs, or the native
Insert > Link Revit UI browse-and-select flow). So:

  - AUDIT (this script): fully automatable. Lists current RevitLinkType
    links, classifies each by parsed BUILDING/DISC code, reports which
    REQUIRED_DISCIPLINES are linked / missing / present-but-wrong-scope.
  - CLEANUP (this script, REMOVE_WRONG_SCOPE=True): fully automatable.
    Deletes any link whose BUILDING code is T00O/SW00/PO00/BA00 etc. for a
    discipline that is in REQUIRED_DISCIPLINES (i.e. should have been
    building-specific) -- but ONLY ones this script itself would have
    reason to flag; it never touches a pre-existing link for a discipline
    NOT in REQUIRED_DISCIPLINES (e.g. don't touch the model's own AR
    Tower/Podium/BA00/B00x context links -- those are a different, accepted
    pattern, confirmed by the user: "keeping all the existing links").
  - LINKING ITSELF stays manual/UI: for each MISSING discipline, this
    script prints the exact Consumed subfolder to browse to in Revit's
    Link Revit dialog. Select the BUILDING-specific file there, set
    Positioning = "Auto - By Shared Coordinates", click Open.

DRY_RUN = True  -> report only, no changes (recommended first run).
DRY_RUN = False -> also deletes any wrong-scope links found (if
                   REMOVE_WRONG_SCOPE is True).
"""
import re
from Autodesk.Revit.DB import FilteredElementCollector, RevitLinkType, BuiltInParameter, Transaction

doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
DRY_RUN = True
REMOVE_WRONG_SCOPE = True   # only takes effect when DRY_RUN = False

# The building this host model belongs to. Change per run/model.
HOST_BUILDING = "B001"

# Discipline codes that MUST be linked, building-specific, for this host.
# Extend/edit this list per project. Codes are the <DISC> token in the
# ProjectC-<ORG>-BIM-<BUILDING>-ZZZ-<DISC>-<SEQNO>.rvt naming convention.
# Comment: value is the ACC "Consumed" subfolder name for that discipline,
# for printing the manual browse path when a link is missing.
REQUIRED_DISCIPLINES = {
    "ST": "04_ST_STRUCTURE",
    "HV": "05_ME_MECHANICAL-HVAC",
    "PL": "06_PL_PLUMBING",
    "FF": "07_FF_FIRE FIGHTING",
    "EL": "09_EL_ELECTRICAL",
    "ID": "02_ID_INTERIORS",
    "LA": "03_LA_LANDSCAPE",
    "WS": "08_WS_WAYFINDING & SIGNAGE",
    "TC": "10_TC_TELECOMMUNICATION",
    "AV": "19_AV_Audio Visual",
}

# Non-building-specific codes that must NEVER substitute for a
# building-specific REQUIRED_DISCIPLINES link.
BROAD_SCOPE_CODES = ["T00O", "SW00", "PO00", "BA00"]

CONSUMED_FOLDER_PATH = (
    "External Resources > Autodesk Docs > <Project> > A.WIP > "
    "01.Architecture > Consumed > {folder}"
)

# ----------------------------- PARSE -----------------------------
NAME_RE = re.compile(r"^ProjectC-[A-Z]+-BIM-([A-Z0-9]+)-ZZZ-([A-Z]+)-\d+", re.IGNORECASE)

links = list(FilteredElementCollector(doc).OfClass(RevitLinkType))
parsed = []  # (link, name, building_code, disc_code)
for lt in links:
    p = lt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
    name = p.AsString() if p else ""
    m = NAME_RE.match(name)
    if m:
        parsed.append((lt, name, m.group(1).upper(), m.group(2).upper()))
    else:
        parsed.append((lt, name, None, None))

# ----------------------------- CLASSIFY -----------------------------
linked_ok = []       # discipline correctly linked as HOST_BUILDING
wrong_scope = []     # discipline linked but with a broad-scope building code
missing = []         # discipline not linked at all

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

# ----------------------------- REPORT -----------------------------
print("=" * 70)
print("Host building: {0}   DRY_RUN = {1}".format(HOST_BUILDING, DRY_RUN))
print("Total link types in model: {0}".format(len(links)))
print("-" * 70)
print("OK - linked, building-specific ({0}):".format(len(linked_ok)))
for disc, name in linked_ok:
    print("   [{0}] {1}".format(disc, name))

print("-" * 70)
print("WRONG SCOPE - linked but Tower/SW00/etc, not building-specific ({0}):".format(len(wrong_scope)))
for disc, lt, name in wrong_scope:
    flag = " -> WILL REMOVE" if (REMOVE_WRONG_SCOPE and not DRY_RUN) else " -> would remove (dry run)" if REMOVE_WRONG_SCOPE else ""
    print("   [{0}] {1}{2}".format(disc, name, flag))

print("-" * 70)
print("MISSING - not linked at all ({0}):".format(len(missing)))
for disc, folder in missing:
    print("   [{0}] browse: {1}".format(disc, CONSUMED_FOLDER_PATH.format(folder=folder)))
    print("        -> select the {0}-specific file only. NEVER substitute a T00O/SW00/PO00/BA00 file.".format(HOST_BUILDING))
    print("        -> Positioning = 'Auto - By Shared Coordinates'")
print("=" * 70)

# ----------------------------- CLEANUP -----------------------------
if wrong_scope and REMOVE_WRONG_SCOPE and not DRY_RUN:
    t = Transaction(doc, "Remove wrong-scope discipline links")
    t.Start()
    removed = 0
    for disc, lt, name in wrong_scope:
        doc.Delete(lt.Id)
        removed += 1
    t.Commit()
    print("REMOVED {0} wrong-scope link(s).".format(removed))
elif wrong_scope and DRY_RUN:
    print("DRY RUN: no links removed. Set DRY_RUN = False to remove wrong-scope links above.")

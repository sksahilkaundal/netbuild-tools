# -*- coding: utf-8 -*-
"""
Set each building-specific Master GA Plan view's Revit Link display to
"By Linked View", pairing each view 1:1 with its OWN building's link
(not with every link in MODEL_CODES) — pointing at the matching floor's
linked view inside that link.

REUSABLE TEMPLATE — edit only the CONFIG block below for a new run/building set.
See [[set-linked-view-per-floor-by-building-prompt-template]] for the matching
fill-in-the-blanks chat prompt.

This is a SIBLING of scripts\\set_linked_view_per_floor.py, not a replacement.
Use THIS script when master views are already split per-building
(e.g. "B1 - <LEVEL> GA Plan-1-200", one set of views per building) and each
view must only ever point at its own building's link. Use the other script
when a single generic view (e.g. "Overall - <LEVEL> GA Plan") must fan out
across multiple building links simultaneously.

IMPORTANT BUG THIS FIXES: an earlier attempt reused the generic script's
single MASTER_VIEW_RE + "any MODEL_CODES link matches" logic for a
per-building view set, and it silently cross-wired e.g. a "B1 - ..." view
to the B003 and B004 links too (all three links matched the same regex
group), producing "does not support link graphical overrides" failures
and wrong pairings. This script instead extracts the building code from
the view name and looks up ONLY that building's link via
BUILDING_TO_LINK_CODE.

DRY_RUN = True  -> only processes the Ground floor view(s), prints the plan,
                   and rolls back (no changes committed). Use this first.
DRY_RUN = False -> processes all allowed floors and commits.
"""
import re
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, RevitLinkInstance,
    RevitLinkGraphicsSettings, LinkVisibility, Transaction, TransactionGroup,
    ViewPlan, ViewType, Level, ElementId
)

doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
# Edit these placeholders per run. Confirm actual view/link names live in
# the model first — naming conventions vary between buildings/exports,
# don't assume a prior run's values still apply.
DRY_RUN = True

# Maps the building code captured from the view name to a substring that
# identifies that SAME building's RevitLinkInstance by file name. One
# view-prefix code per building actually in scope for this run.
BUILDING_TO_LINK_CODE = {
    "B1": "B001",
    "B3": "B003",
    "B4": "B004",
}

# Only these floors are ever touched, regardless of DRY_RUN.
ALLOWED_FLOOR_KEYWORDS = [
    "GROUND",
    "01ST", "1ST",
    "02ND", "2ND",
    "03RD", "3RD",
    "04TH", "4TH",
    "05TH", "5TH",
    "06TH", "6TH",
]

# <MASTER_VIEW_PATTERN> placeholder — regex matching the host-view naming
# convention. Group 1 = building code (must be one of BUILDING_TO_LINK_CODE
# keys), group 2 = <LEVEL>. Keep the suffix REQUIRED (not optional) so this
# never accidentally matches an unrelated same-prefix view elsewhere in the
# model (seen live: a same-named "B1 - Ground Floor GA Plan" WITHOUT the
# "-1-200" suffix existed under a different, unrelated view template).
MASTER_VIEW_NAME_REGEX = r"^(B1|B3|B4)\s*-\s*(.+?)\s+GA Plan-1-200\s*$"
MASTER_VIEW_RE = re.compile(MASTER_VIEW_NAME_REGEX, re.IGNORECASE)

# <TARGET_LINKED_VIEW_PATTERN> placeholder — format string for the target
# view name inside the linked document. {level} is substituted with the
# captured <LEVEL> text. find_view_in_linked_doc() also fuzzy-matches on
# whitespace/underscore/plural differences (confirmed live: one linked doc
# had "01st Floor GA Plan_Linked  View_1-200" with a double space and still
# matched correctly).
TARGET_LINKED_VIEW_FORMAT = "{level} GA Plan_Linked View_1-200"

# --- MATCH_MODE (added 2026-09-21 for Tower 00002 <- 00003) ---
# 'regex'           -> original: building code + <LEVEL> captured from the
#                      host view NAME, link picked via BUILDING_TO_LINK_CODE.
# 'level_elevation' -> host views picked by VIEW TEMPLATE name prefix (or
#                      the Studio_02 Drawing Series value), ONE link picked by
#                      SINGLE_LINK_CODE, and the floor paired by the host
#                      view's GenLevel ELEVATION against the link doc's
#                      Levels (host/link level NAMES differed on the Tower:
#                      "Level 21" vs "Level 21 - MEP", "Level 38 GA Plan"
#                      vs "Level 38"). Target = TARGET_LINKED_VIEW_FORMAT
#                      with {level} = the LINK's level name.
MATCH_MODE = "regex"
HOST_VIEW_TEMPLATE_PREFIX = "10 _ GA Plans"     # level_elevation mode only; str or tuple of str, e.g. ("10 _ GA Plans", "11 _ Part Plans")
HOST_VIEW_SERIES_VALUE = None                   # e.g. "10_GA Plans"; None = ignore
SINGLE_LINK_CODE = None                         # e.g. "3505-ProjectG-Studio-ARC-RVT-00003"
LEVEL_ELEVATION_TOL_MM = 5.0
DRY_RUN_ALL_ROWS = False   # level_elevation mode: True = dry-run every row (rolled back), False = lowest level only


def level_is_allowed(level_text):
    upper = level_text.upper()
    return any(kw in upper for kw in ALLOWED_FLOOR_KEYWORDS)


def normalize_name(name):
    n = re.sub(r"[\s_]+", "", name.lower())
    n = n.replace("plans", "plan")
    return n


def find_view_in_linked_doc(linked_doc, target_name):
    if linked_doc is None:
        return None
    target_norm = normalize_name(target_name)
    collector = FilteredElementCollector(linked_doc).OfCategory(BuiltInCategory.OST_Views)
    exact_match = None
    fuzzy_match = None
    for v in collector:
        try:
            if v.IsTemplate:
                continue
            if v.Name == target_name:
                exact_match = v
                break
            if normalize_name(v.Name) == target_norm and fuzzy_match is None:
                fuzzy_match = v
        except Exception:
            continue
    return exact_match if exact_match is not None else fuzzy_match


# ----------------------------- GATHER -----------------------------
all_links = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))
plan_rows = []   # (view, level_text, link_instance, target_view)
skipped_rows = []
master_views = []

if MATCH_MODE == "level_elevation":
    link = next((l for l in all_links if SINGLE_LINK_CODE and SINGLE_LINK_CODE in l.Name), None)
    linked_doc = link.GetLinkDocument() if link is not None else None
    if link is None or linked_doc is None:
        skipped_rows.append((None, SINGLE_LINK_CODE, None, "link not found or not loaded"))
        link_levels = []
    else:
        link_levels = sorted(FilteredElementCollector(linked_doc).OfClass(Level).ToElements(), key=lambda l: l.Elevation)
    tol_ft = LEVEL_ELEVATION_TOL_MM / 304.8
    cands = []
    for v in FilteredElementCollector(doc).OfClass(ViewPlan).ToElements():
        try:
            if v.IsTemplate or v.ViewType != ViewType.FloorPlan:
                continue
            tmpl = doc.GetElement(v.ViewTemplateId) if v.ViewTemplateId != ElementId.InvalidElementId else None
            if not (tmpl and tmpl.Name.startswith(HOST_VIEW_TEMPLATE_PREFIX)):
                continue
            if HOST_VIEW_SERIES_VALUE:
                p = v.LookupParameter("Studio_02 - Drawing Series")
                if not p or (p.AsString() or "") != HOST_VIEW_SERIES_VALUE:
                    continue
            if v.GenLevel is None:
                continue
            cands.append(v)
        except Exception:
            continue
    cands.sort(key=lambda v: v.GenLevel.Elevation)
    master_views = [(v, None, v.GenLevel.Name) for v in cands]
    if DRY_RUN and not DRY_RUN_ALL_ROWS and cands:
        lowest = cands[0].GenLevel.Elevation
        cands = [v for v in cands if abs(v.GenLevel.Elevation - lowest) < tol_ft]
    for v in cands:
        if link is None or linked_doc is None:
            break
        hl = v.GenLevel
        ll = next((l for l in link_levels if abs(l.Elevation - hl.Elevation) <= tol_ft), None)
        if ll is None:
            skipped_rows.append((v.Name, link.Name, None, "no link level within %.0fmm of host level '%s'" % (LEVEL_ELEVATION_TOL_MM, hl.Name)))
            continue
        target_name = TARGET_LINKED_VIEW_FORMAT.format(level=ll.Name)
        target_view = find_view_in_linked_doc(linked_doc, target_name)
        if target_view is None:
            # Fallback: the link's level may have been RENAMED after its
            # views were created (Podium run: level "Lift Pit" vs view
            # "ST-01 TYPICAL (BASEMENT LIFT PIT) GA Plan_Linked View") —
            # take the unique linked view whose GenLevel sits at this
            # elevation and whose name ends like the format's suffix.
            suffix = TARGET_LINKED_VIEW_FORMAT.split("{level}")[-1]
            hits = []
            for lv in FilteredElementCollector(linked_doc).OfClass(ViewPlan).ToElements():
                try:
                    if lv.IsTemplate or lv.GenLevel is None or not lv.Name.endswith(suffix):
                        continue
                    if abs(lv.GenLevel.Elevation - hl.Elevation) <= tol_ft:
                        hits.append(lv)
                except Exception:
                    continue
            if len(hits) == 1:
                target_view = hits[0]
            elif len(hits) > 1:
                skipped_rows.append((v.Name, link.Name, target_name, "ambiguous: %d linked views at that elevation" % len(hits)))
                continue
        if target_view is None:
            skipped_rows.append((v.Name, link.Name, target_name, "linked view not found"))
            continue
        plan_rows.append((v, "%s -> %s" % (hl.Name, ll.Name), link, target_view))
else:
    all_views = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Views).WhereElementIsNotElementType()
    for v in all_views:
        try:
            if v.IsTemplate:
                continue
            m = MASTER_VIEW_RE.match(v.Name)
            if m:
                master_views.append((v, m.group(1).upper(), m.group(2).strip()))
        except Exception:
            continue

    for view, bcode, level_text in master_views:
        if not level_is_allowed(level_text):
            continue
        is_ground = "GROUND" in level_text.upper()
        if DRY_RUN and not is_ground:
            continue

        link_code = BUILDING_TO_LINK_CODE.get(bcode)
        link = next((l for l in all_links if link_code and link_code in l.Name), None)
        if link is None:
            skipped_rows.append((view.Name, None, None, "no link found for code %s" % link_code))
            continue

        target_name = TARGET_LINKED_VIEW_FORMAT.format(level=level_text)
        linked_doc = link.GetLinkDocument()
        target_view = find_view_in_linked_doc(linked_doc, target_name)

        if target_view is None:
            skipped_rows.append((view.Name, link.Name, target_name, "linked view not found (link not loaded, or name mismatch)"))
            continue

        plan_rows.append((view, level_text, link, target_view))

# ----------------------------- REPORT -----------------------------
print("=" * 70)
print("MATCH_MODE = {0}".format(MATCH_MODE))
print("Master views matched: {0}".format(len(master_views)))
print("DRY_RUN = {0}".format(DRY_RUN))
print("Rows to apply: {0}".format(len(plan_rows)))
print("-" * 70)
for view, level_text, link, target_view in plan_rows:
    tmpl = doc.GetElement(view.ViewTemplateId) if view.ViewTemplateId != ElementId.InvalidElementId else None
    print("VIEW '{0}' [{1}] tmpl='{4}'  |  LINK '{2}'  ->  linked view '{3}'".format(
        view.Name, level_text, link.Name, target_view.Name, tmpl.Name if tmpl else None))

if skipped_rows:
    print("-" * 70)
    print("SKIPPED:")
    for row in skipped_rows:
        print("  ", row)
print("=" * 70)

# ----------------------------- APPLY -----------------------------
tg = TransactionGroup(doc, "Set linked view per floor by building (dry run)" if DRY_RUN else "Set linked view per floor by building")
tg.Start()

t = Transaction(doc, "Set linked view per floor by building")
t.Start()
applied = 0
failed = []
for view, level_text, link, target_view in plan_rows:
    try:
        settings = RevitLinkGraphicsSettings()
        settings.LinkVisibilityType = LinkVisibility.ByLinkView
        settings.LinkedViewId = target_view.Id
        view.SetLinkOverrides(link.Id, settings)
        applied += 1
    except Exception as ex:
        failed.append((view.Name, link.Name, str(ex)))
t.Commit()

if DRY_RUN:
    tg.RollBack()
    print("DRY RUN: {0} change(s) computed, transaction rolled back. Nothing was saved.".format(applied))
else:
    tg.Assimilate()
    print("APPLIED: {0} view/link overrides committed.".format(applied))

if failed:
    print("FAILURES:")
    for f in failed:
        print("  ", f)

# -*- coding: utf-8 -*-
"""
Set each Master GA Plan view's Revit Link display to "By Linked View",
pointing at the matching floor's linked view, for the target BIM models.

REUSABLE TEMPLATE — edit only the CONFIG block below for a new run/building.
See [[linked-view-per-floor-prompt-template]] for the matching fill-in-the-blanks
chat prompt; the placeholders there map 1:1 to the CONFIG values here.

Master view name pattern   : configurable via MASTER_VIEW_NAME_REGEX (placeholder: <LEVEL>)
Target linked view pattern : configurable via TARGET_LINKED_VIEW_FORMAT (placeholder: {level})
                              (inside the link's document)

Only touches RevitLinkInstances whose link type name contains one of MODEL_CODES.
Only touches views whose <LEVEL> matches ALLOWED_FLOOR_KEYWORDS.

DRY_RUN = True  -> only processes the Ground floor view(s), prints the plan,
                   and rolls back (no changes committed). Use this first.
DRY_RUN = False -> processes all allowed floors and commits.
"""
import re
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, RevitLinkInstance,
    RevitLinkGraphicsSettings, LinkVisibility, Transaction, TransactionGroup
)

doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
# Edit these placeholders per run. Confirm actual view names live in the model
# first (list views matching "GA Plan") — naming conventions have varied
# between buildings/exports, don't assume a prior run's values still apply.
DRY_RUN = True

# <MODEL_FULL_NAME_n> placeholders — substrings that identify target
# RevitLinkInstances by link/file name. Only include models actually in
# scope for this run.
MODEL_CODES = [
    "B001", "B003", "B004",
]

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
# convention, with a single capture group for <LEVEL>. Known variants seen
# so far: "Overall - <LEVEL> GA Plan", "B2 B5 - <LEVEL> GA Plan",
# "B1/B3/B4 - <LEVEL> GA Plan-1-200".
# Add new prefixes to the (?:...) alternation as new conventions are found,
# rather than replacing the pattern outright, so old runs stay reproducible.
MASTER_VIEW_NAME_REGEX = r"^(?:Overall|B2\s*B5|B1|B3|B4)\s*-\s*(.+?)\s+GA Plan(?:-1-200)?\s*$"
MASTER_VIEW_RE = re.compile(MASTER_VIEW_NAME_REGEX, re.IGNORECASE)

# <TARGET_LINKED_VIEW_PATTERN> placeholder — format string for the target
# view name inside the linked document. {level} is substituted with the
# captured <LEVEL> text. Watch for suffix variants that can coexist in the
# same linked doc (e.g. plain "_Linked View" vs. scale-suffixed
# "_Linked View_1-200") — confirm which one is the intended target live,
# don't assume.
TARGET_LINKED_VIEW_FORMAT = "{level} GA Plan_Linked View_1-200"


def level_is_allowed(level_text):
    upper = level_text.upper()
    return any(kw in upper for kw in ALLOWED_FLOOR_KEYWORDS)


def linked_view_name_for(level_text):
    return TARGET_LINKED_VIEW_FORMAT.format(level=level_text)


def normalize_name(name):
    # Collapse whitespace/underscores and singularize "Plans" -> "Plan" so minor
    # naming inconsistencies between buildings (spacing, underscore placement,
    # plural "Plans") don't block a match.
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


def link_type_name(link_instance):
    try:
        return link_instance.Name
    except Exception:
        return ""


def matches_target_model(link_instance):
    name = link_type_name(link_instance)
    return any(code in name for code in MODEL_CODES)


# ----------------------------- GATHER -----------------------------
all_views = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Views).WhereElementIsNotElementType()
master_views = []
for v in all_views:
    try:
        if v.IsTemplate:
            continue
        m = MASTER_VIEW_RE.match(v.Name)
        if m:
            master_views.append((v, m.group(1).strip()))
    except Exception:
        continue

all_links = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))

plan_rows = []   # (view, level_text, link_instance, target_view_or_None)
skipped_rows = []

for view, level_text in master_views:
    if not level_is_allowed(level_text):
        continue
    is_ground = "GROUND" in level_text.upper()
    if DRY_RUN and not is_ground:
        continue

    for link in all_links:
        if not matches_target_model(link):
            continue
        target_name = linked_view_name_for(level_text)
        linked_doc = link.GetLinkDocument()
        target_view = find_view_in_linked_doc(linked_doc, target_name)

        if target_view is None:
            skipped_rows.append((view.Name, link_type_name(link), target_name, "linked view not found (link not loaded, or name mismatch)"))
            continue

        plan_rows.append((view, level_text, link, target_view))

# ----------------------------- REPORT -----------------------------
print("=" * 70)
print("Master views matched: {0}".format(len(master_views)))
print("DRY_RUN = {0}".format(DRY_RUN))
print("-" * 70)
for view, level_text, link, target_view in plan_rows:
    print("VIEW '{0}'  |  LINK '{1}'  ->  linked view '{2}' (id {3})".format(
        view.Name, link_type_name(link), target_view.Name, target_view.Id))

if skipped_rows:
    print("-" * 70)
    print("SKIPPED (no matching linked view found):")
    for view_name, link_name, target_name, reason in skipped_rows:
        print("  VIEW '{0}' | LINK '{1}' | wanted '{2}' | {3}".format(view_name, link_name, target_name, reason))
print("=" * 70)

# ----------------------------- APPLY -----------------------------
tg = TransactionGroup(doc, "Set linked view per floor (dry run)" if DRY_RUN else "Set linked view per floor")
tg.Start()

t = Transaction(doc, "Set linked view per floor")
t.Start()
applied = 0
for view, level_text, link, target_view in plan_rows:
    try:
        settings = RevitLinkGraphicsSettings()
        settings.LinkVisibilityType = LinkVisibility.ByLinkView
        settings.LinkedViewId = target_view.Id
        view.SetLinkOverrides(link.Id, settings)
        applied += 1
    except Exception as ex:
        print("FAILED: view '{0}' link '{1}' -> {2}".format(view.Name, link_type_name(link), ex))
t.Commit()

if DRY_RUN:
    tg.RollBack()
    print("DRY RUN: {0} change(s) computed, transaction rolled back. Nothing was saved.".format(applied))
else:
    tg.Assimilate()
    print("APPLIED: {0} view/link overrides committed.".format(applied))

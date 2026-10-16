# -*- coding: UTF-8 -*-
"""
clear_model_warnings.py

For the Revit MCP `execute_revit_code` tool (uses the pre-supplied `doc`,
`DB`/`Autodesk.Revit.DB` namespace; no extra imports needed).

Reusable end-to-end warning-cleanup pipeline, developed live against
ProjectC-Studio-BIM-B001-ZZZ-BM-950001 (2,120 warnings -> 0). Runs six steps in
order, each individually toggleable via CONFIG:

  1. Delete all Area Plan views + Area-related schedules (views whose
     ViewType == AreaPlan, plus ViewSchedules whose category is Areas).
  2. Delete all Area elements (OST_Areas).
  3. Delete all Area Separation Lines (OST_AreaSchemeLines).
  4. Delete orphaned Matchlines (OwnerViewId == InvalidElementId). Revit's
     API refuses to edit a Matchline's sketch programmatically
     (SketchEditScope raises "Sketch does not support editing"), so
     straightening a live, in-use matchline is NOT possible via script -
     this step only removes dead ones with no owner view, which is what
     was actually causing the "off axis" warnings in every model tested
     so far. A matchline WITH a valid owner view that is genuinely
     off-axis will be skipped and must be fixed by hand (Edit Sketch in
     the UI).
  5. Delete orphaned Room Tags - i.e. tags where `tag.Room` is None and
     `tag.TaggedLocalRoomId` raises (dangling room reference, nothing to
     move the tag into). A tag whose room reference IS valid but is
     merely positioned outside the room boundary is left alone (that one
     genuinely needs repositioning, not deletion) - this step only
     touches tags with a broken/missing room reference.
  6. Run the duplicate "Type Mark" fixer (same logic as the standalone
     FixDuplicateTypeMarks_MCP.py) - three passes per duplicate group:
     keyword-prefix rule, thickness-suffix rule (Walls/Floors), then a
     letter-suffix fallback that always succeeds.

Steps 1-3 clear the vast majority of warnings on these models (the
"Highlighted lines overlap" / "off axis" / "not properly enclosed"
warnings are almost all Area/Area-separation-line side effects). Steps
4-5 are narrow, defensive cleanups for the specific dead-reference cases
seen on B001 - they will not touch anything with a live, valid reference.
Step 6 is the one already-proven reusable fixer, run last since it only
targets whatever duplicate-Type-Mark warnings remain.

CONFIG block below controls which steps run and whether it's a dry run.
Adjust KEYWORD_PREFIX_RULES / THICKNESS_SUFFIX_CATEGORIES per project the
same way as the standalone Type Mark script.
"""

from Autodesk.Revit.DB import *
from System.Collections.Generic import List
import re

# ---------------------------------------------------------------- CONFIG --
DRY_RUN = False  # True = report counts/plans only, no transactions committed

RUN_STEP_1_DELETE_AREA_PLANS = True
RUN_STEP_2_DELETE_AREAS = True
RUN_STEP_3_DELETE_AREA_SEP_LINES = True
RUN_STEP_4_DELETE_ORPHANED_MATCHLINES = True
RUN_STEP_5_DELETE_ORPHANED_ROOM_TAGS = True
RUN_STEP_6_FIX_DUPLICATE_TYPE_MARKS = True

# --- Step 6 (Type Mark fixer) config - same as FixDuplicateTypeMarks_MCP.py ---
TARGET_CATEGORIES = None  # None = every category Revit flags
KEYWORD_PREFIX_RULES = [
    ("ritz", "RITZ-"),
    ("dormakaba", "DK-"),
]
THICKNESS_SUFFIX_CATEGORIES = ["Walls", "Floors"]
# ----------------------------------------------------------------------- #


def warning_count():
    return len(doc.GetWarnings())


def step1_delete_area_plans():
    view_ids = []
    names = []
    plan_views = FilteredElementCollector(doc).OfClass(ViewPlan).WhereElementIsNotElementType().ToElements()
    for v in plan_views:
        if v.ViewType == ViewType.AreaPlan:
            view_ids.append(v.Id)
            names.append(v.Name)
    schedules = FilteredElementCollector(doc).OfClass(ViewSchedule).ToElements()
    for s in schedules:
        try:
            if s.Definition.CategoryId == ElementId(BuiltInCategory.OST_Areas):
                view_ids.append(s.Id)
                names.append(s.Name)
        except Exception:
            pass

    print("[Step 1] Area Plan / Area-related views targeted: {}".format(len(view_ids)))
    if DRY_RUN or not view_ids:
        return
    t = Transaction(doc, "Delete Area Plans, Area Views")
    t.Start()
    deleted = list(doc.Delete(List[ElementId](view_ids)))
    t.Commit()
    print("[Step 1] Deleted (incl. dependents): {}".format(len(deleted)))


def step2_delete_areas():
    areas = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements()
    ids = [a.Id for a in areas]
    print("[Step 2] Areas targeted: {}".format(len(ids)))
    if DRY_RUN or not ids:
        return
    t = Transaction(doc, "Delete all Areas")
    t.Start()
    deleted = list(doc.Delete(List[ElementId](ids)))
    t.Commit()
    print("[Step 2] Deleted (incl. dependents): {}".format(len(deleted)))


def step3_delete_area_sep_lines():
    lines = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_AreaSchemeLines).WhereElementIsNotElementType().ToElements()
    ids = [l.Id for l in lines]
    print("[Step 3] Area Separation Lines targeted: {}".format(len(ids)))
    if DRY_RUN or not ids:
        return
    t = Transaction(doc, "Delete Area Separation Lines")
    t.Start()
    deleted = list(doc.Delete(List[ElementId](ids)))
    t.Commit()
    print("[Step 3] Deleted (incl. dependents): {}".format(len(deleted)))


def step4_delete_orphaned_matchlines():
    matchlines = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Matchline).WhereElementIsNotElementType().ToElements()
    orphaned = [m.Id for m in matchlines if m.OwnerViewId == ElementId.InvalidElementId]
    live = len(list(matchlines)) - len(orphaned)
    print("[Step 4] Orphaned matchlines targeted: {} (live matchlines left untouched: {})".format(len(orphaned), live))
    if DRY_RUN or not orphaned:
        return
    t = Transaction(doc, "Delete orphaned Matchlines")
    t.Start()
    deleted = list(doc.Delete(List[ElementId](orphaned)))
    t.Commit()
    print("[Step 4] Deleted (incl. dependents): {}".format(len(deleted)))


def step5_delete_orphaned_room_tags():
    warnings = doc.GetWarnings()
    candidate_ids = []
    for w in warnings:
        if "Room Tag is outside" in w.GetDescriptionText():
            candidate_ids.extend(list(w.GetFailingElements()))

    orphaned_ids = []
    for tid in candidate_ids:
        tag = doc.GetElement(tid)
        if tag is None:
            continue
        if tag.Room is not None:
            continue  # valid room reference - a genuine positioning issue, leave for manual fix
        try:
            tag.TaggedLocalRoomId  # raises if the room reference is dangling
            continue  # didn't raise -> has some valid local room id, leave alone
        except Exception:
            orphaned_ids.append(tid)

    print("[Step 5] Orphaned Room Tags targeted: {} (of {} flagged)".format(len(orphaned_ids), len(candidate_ids)))
    if DRY_RUN or not orphaned_ids:
        return
    t = Transaction(doc, "Delete orphaned Room Tags")
    t.Start()
    deleted = list(doc.Delete(List[ElementId](orphaned_ids)))
    t.Commit()
    print("[Step 5] Deleted (incl. dependents): {}".format(len(deleted)))


# ---------------------------------------------------- Step 6 helpers -----
def _get_type_name(et):
    p = et.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
    if p:
        name = p.AsString()
        if name:
            return name
    return getattr(et, "Name", "") or ""


def _get_type_mark(et):
    p = et.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK)
    return p.AsString() if p else None


def _set_type_mark(et, value):
    p = et.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK)
    p.Set(value)


def _numeric_token(name):
    m = re.search(r'(\d+)\s*mm', name, re.IGNORECASE)
    if not m:
        m = re.search(r'(\d+)', name)
    if not m:
        return None
    token = m.group(1)
    if re.search(r'\bred\b', name, re.IGNORECASE):
        token += "R"
    return token


def _letters():
    i = 0
    while True:
        n = i
        s = ""
        while True:
            s = chr(ord('a') + n % 26) + s
            n = n // 26 - 1
            if n < 0:
                break
        yield s
        i += 1


def _plan_group(types_info):
    plan = {}
    used = set(t[3] for t in types_info)

    remaining = []
    for eid, cat, tname, mark in types_info:
        handled = False
        for kw, prefix in KEYWORD_PREFIX_RULES:
            if kw not in tname.lower():
                continue
            base_mark = prefix + (mark or "").replace(" ", "")
            new_mark = base_mark
            if new_mark in used:
                token = _numeric_token(tname)
                candidate = base_mark + "-" + token if token else None
                if candidate and candidate not in used:
                    new_mark = candidate
                else:
                    break
            plan[eid.Value] = new_mark
            used.add(new_mark)
            handled = True
            break
        if not handled:
            remaining.append((eid, cat, tname, mark))

    still_remaining = []
    for eid, cat, tname, mark in remaining:
        if cat in THICKNESS_SUFFIX_CATEGORIES:
            token = _numeric_token(tname)
            if token:
                new_mark = "{}-{}".format(mark, token)
                if new_mark not in used:
                    plan[eid.Value] = new_mark
                    used.add(new_mark)
                    continue
        still_remaining.append((eid, cat, tname, mark))

    still_remaining.sort(key=lambda t: t[2])
    letgen = _letters()
    for eid, cat, tname, mark in still_remaining:
        for suffix in letgen:
            new_mark = "{}{}".format(mark, suffix)
            if new_mark not in used:
                plan[eid.Value] = new_mark
                used.add(new_mark)
                break

    return plan


def step6_fix_duplicate_type_marks():
    warnings = doc.GetWarnings()
    dup_warnings = [
        w for w in warnings
        if "duplicate" in w.GetDescriptionText().lower() and "type mark" in w.GetDescriptionText().lower()
    ]
    print("[Step 6] Duplicate Type Mark warnings found: {}".format(len(dup_warnings)))

    all_plan = {}
    skipped_groups = 0
    id_lookup = {}

    for w in dup_warnings:
        ids = list(w.GetFailingElements())
        types_info = []
        for eid in ids:
            et = doc.GetElement(eid)
            if et is None:
                continue
            cat = et.Category.Name if et.Category else "N/A"
            tname = _get_type_name(et)
            mark = _get_type_mark(et)
            types_info.append((eid, cat, tname, mark))
            id_lookup[eid.Value] = eid

        if not types_info:
            continue

        if TARGET_CATEGORIES is not None:
            if any(cat not in TARGET_CATEGORIES for _, cat, _, _ in types_info):
                skipped_groups += 1
                continue

        all_plan.update(_plan_group(types_info))

    print("[Step 6] Duplicate groups skipped (category not in scope): {}".format(skipped_groups))
    print("[Step 6] Type Mark changes planned: {}".format(len(all_plan)))
    for tid, new_mark in sorted(all_plan.items()):
        et = doc.GetElement(id_lookup[tid])
        old_mark = _get_type_mark(et)
        tname = _get_type_name(et)
        cat = et.Category.Name if et.Category else "N/A"
        print("  [{}] {} | '{}' -> '{}'  ({})".format(cat, tname, old_mark, new_mark, tid))

    if DRY_RUN or not all_plan:
        return
    t = Transaction(doc, "Assign unique Type Marks to duplicate groups")
    t.Start()
    applied = 0
    for tid, new_mark in all_plan.items():
        et = doc.GetElement(id_lookup[tid])
        _set_type_mark(et, new_mark)
        applied += 1
    status = t.Commit()
    print("[Step 6] Commit status: {}  Type Marks updated: {}".format(status, applied))


# --------------------------------------------------------------- MAIN ----
print("Document: {}".format(doc.Title))
print("DRY_RUN: {}".format(DRY_RUN))
before = warning_count()
print("Warnings before: {}".format(before))

if RUN_STEP_1_DELETE_AREA_PLANS:
    step1_delete_area_plans()
if RUN_STEP_2_DELETE_AREAS:
    step2_delete_areas()
if RUN_STEP_3_DELETE_AREA_SEP_LINES:
    step3_delete_area_sep_lines()
if RUN_STEP_4_DELETE_ORPHANED_MATCHLINES:
    step4_delete_orphaned_matchlines()
if RUN_STEP_5_DELETE_ORPHANED_ROOM_TAGS:
    step5_delete_orphaned_room_tags()
if RUN_STEP_6_FIX_DUPLICATE_TYPE_MARKS:
    step6_fix_duplicate_type_marks()

after = warning_count()
print("Warnings after: {}".format(after))
print("DONE")

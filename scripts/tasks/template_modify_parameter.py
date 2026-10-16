# TEMPLATE task for MultiModelBatch.py -- MODIFIES the model. Copy this file,
# edit the SETTINGS block, point MultiModelBatch at it (--task), dry-run first.
#
# What it does: sets instance parameter PARAM_NAME = VALUE on every element of
# CATEGORY (optionally only on LEVELS). Elements inside model groups are
# bucketed and listed, never edited -- group members with two or more
# placements roll back through the API without an error (see the
# multi-building-level-parameter-rollout memory); do those via Edit Group.
#
# In dry run the transaction really runs and MultiModelBatch rolls the whole
# model back afterwards, so the counts you see are the counts you would get.
# ------------------------------ SETTINGS ------------------------------------
CATEGORY = DB.BuiltInCategory.OST_Doors
PARAM_NAME = "Comments"
VALUE = "checked 2026-09"          # str for text params; float (internal units) for numbers
LEVELS = []                        # e.g. ["Basement 01", "Basement 02"]; [] = every level
ONLY_IF_BLANK = True               # don't overwrite a value that is already set
# ----------------------------------------------------------------------------
nm = lambda e: DB.Element.Name.__get__(e)

def level_name(e):
    lid = getattr(e, "LevelId", DB.ElementId.InvalidElementId)
    if lid == DB.ElementId.InvalidElementId:
        return "?"
    lv = doc.GetElement(lid)
    return nm(lv) if lv is not None else "?"

todo, grouped, no_param, already = [], [], [], []
for e in DB.FilteredElementCollector(doc).OfCategory(CATEGORY).WhereElementIsNotElementType():
    if LEVELS and level_name(e) not in LEVELS:
        continue
    p = e.LookupParameter(PARAM_NAME)
    if p is None or p.IsReadOnly:
        no_param.append(str(e.Id))
        continue
    if e.GroupId != DB.ElementId.InvalidElementId:
        grouped.append((str(e.Id), nm(doc.GetElement(e.GroupId))))
        continue
    if ONLY_IF_BLANK and p.HasValue and (p.AsString() or p.AsValueString()):
        already.append(str(e.Id))
        continue
    todo.append(e)

set_ok, set_fail = 0, []
if todo:
    with ctx.transaction("Set %s on %d elements" % (PARAM_NAME, len(todo))) as t:
        for e in todo:
            try:
                if e.LookupParameter(PARAM_NAME).Set(VALUE):
                    set_ok += 1
                else:
                    set_fail.append(str(e.Id))
            except Exception as ex:
                set_fail.append("%s (%s)" % (str(e.Id), ex))

group_types = {}
for eid, gname in grouped:
    group_types.setdefault(gname, []).append(eid)

result = {
    "set": set_ok,
    "set_failed": set_fail,
    "already_set_skipped": len(already),
    "no_param_or_readonly": len(no_param),
    "in_groups_skipped": len(grouped),
    "group_types_to_edit_by_hand": sorted(group_types.keys()),
}
ctx.log("%s: set %d, failed %d, already %d, no-param %d, grouped %d across %d group types" % (
    ctx.title, set_ok, len(set_fail), len(already), len(no_param), len(grouped), len(group_types)))
for gname in sorted(group_types):
    ctx.log("   group type %r: %d member(s) -> Edit Group once, change propagates" % (gname, len(group_types[gname])))

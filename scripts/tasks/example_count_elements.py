# Example task for MultiModelBatch.py -- READ-ONLY. Counts a few categories in
# the TARGET model. Safe to run on any model in dry run or apply mode.
#
# Names available here (IronPython 2.7):
#   doc     the TARGET model (NOT necessarily the active window)
#   uidoc   the active UIDocument when the target IS the active model, else None
#   DB      Autodesk.Revit.DB        revit   pyRevit module
#   ctx     ctx.title, ctx.dry_run, ctx.is_active, ctx.log(msg),
#           `with ctx.transaction("name") as t:` for model changes
#   result  assign a JSON-serialisable dict -> shown in the summary table
def count(bic):
    return DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().GetElementCount()

result = {
    "levels": count(DB.BuiltInCategory.OST_Levels),
    "walls": count(DB.BuiltInCategory.OST_Walls),
    "doors": count(DB.BuiltInCategory.OST_Doors),
    "rooms": count(DB.BuiltInCategory.OST_Rooms),
    "warnings": len(list(doc.GetWarnings())),
    "active_window": ctx.is_active,
}
ctx.log("%s: %d levels, %d walls, %d doors, %d rooms, %d warnings" % (
    ctx.title, result["levels"], result["walls"], result["doors"], result["rooms"], result["warnings"]))

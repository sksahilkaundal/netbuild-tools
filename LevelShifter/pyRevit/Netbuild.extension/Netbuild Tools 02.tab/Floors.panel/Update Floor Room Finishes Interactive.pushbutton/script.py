# -*- coding: utf-8 -*-
"""Update Floor Boundary to Room Finish Faces  (pyRevit, Revit 2022+)

Workflow:
  1. Draw ONE floor (any rough shape) on the level that has your rooms.
  2. Select it (or pick it when prompted) and run this script.

The script collects every placed room on the floor's level, extracts each
room boundary at the WALL FINISH face, and rewrites the floor's sketch so
it contains one closed loop per room. You end up with a single floor whose
edges follow the internal (finish) faces of the walls around every room.
"""

from System.Collections.Generic import List

from pyrevit import revit, forms, script
from Autodesk.Revit import DB
from Autodesk.Revit.DB import (
    BuiltInCategory, FilteredElementCollector, SpatialElementBoundaryOptions,
    SpatialElementBoundaryLocation, SketchEditScope, ElementId, Line, XYZ,
    CurveElement, Transform,
)
from Autodesk.Revit.DB.Architecture import Room
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

MIN_SEGMENT = 0.01  # ft - skip degenerate segments


# --------------------------------------------------------------- selection
class FloorFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, DB.Floor)

    def AllowReference(self, ref, point):
        return False


def get_selected_floor():
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, DB.Floor):
            return el
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, FloorFilter(), "Pick the floor to update")
        return doc.GetElement(ref.ElementId)
    except Exception:
        return None


# --------------------------------------------------------------- room loops
def room_finish_loops(level_id):
    """Yield (room, [closed lists of curves]) at wall FINISH faces."""
    opts = SpatialElementBoundaryOptions()
    opts.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish

    rooms = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .ToElements())

    for room in rooms:
        if not isinstance(room, Room) or room.Area <= 0:
            continue
        if room.LevelId != level_id:
            continue
        loops = room.GetBoundarySegments(opts)
        if not loops:
            continue
        curve_loops = []
        for seg_list in loops:
            curves = [s.GetCurve() for s in seg_list
                      if s.GetCurve() and s.GetCurve().Length > MIN_SEGMENT]
            if len(curves) >= 3:
                curve_loops.append(curves)
        if curve_loops:
            yield room, curve_loops


# --------------------------------------------------------------- main
floor = get_selected_floor()
if not floor:
    forms.alert("No floor selected. Select or pick a floor and run again.",
                exitscript=True)

level = doc.GetElement(floor.LevelId)
room_data = list(room_finish_loops(floor.LevelId))
if not room_data:
    forms.alert("No placed rooms found on level '{}'.".format(level.Name),
                exitscript=True)

sketch = doc.GetElement(floor.SketchId)
if sketch is None:
    forms.alert("Cannot access the floor sketch (requires Revit 2022+).",
                exitscript=True)

sketch_plane = sketch.SketchPlane
z = sketch_plane.GetPlane().Origin.Z


def flatten(curve):
    """Project a boundary curve onto the sketch plane elevation."""
    p0 = curve.GetEndPoint(0)
    if abs(p0.Z - z) < 1e-9:
        return curve
    if isinstance(curve, Line):
        p1 = curve.GetEndPoint(1)
        return Line.CreateBound(XYZ(p0.X, p0.Y, z), XYZ(p1.X, p1.Y, z))
    return curve.CreateTransformed(
        Transform.CreateTranslation(XYZ(0, 0, z - p0.Z)))


# Edit the existing floor's sketch in place - the floor element (and its
# id, type, parameters, hosted elements) is preserved.
scope = SketchEditScope(doc, "Update floor to room finish faces")
scope.Start(sketch.Id)

try:
    with revit.Transaction("Rebuild floor sketch from rooms", doc=doc):
        # 1. delete the existing sketch curves
        old_ids = [ce.Id for ce in
                   FilteredElementCollector(doc, sketch.Id)
                   .OfClass(CurveElement)]
        if old_ids:
            doc.Delete(List[ElementId](old_ids))

        # 2. draw one loop per room boundary at the finish faces
        n_loops = 0
        for room, loops in room_data:
            for loop in loops:
                for c in loop:
                    doc.Create.NewModelCurve(flatten(c), sketch_plane)
                n_loops += 1

    scope.Commit(revit.failure.FailureSwallower())
except Exception as ex:
    scope.Cancel()
    forms.alert("Sketch update failed and was cancelled:\n{}".format(ex),
                exitscript=True)

output.print_md(
    "**Done.** Floor `{}` updated on level **{}**: "
    "{} room(s), {} boundary loop(s) now follow the wall finish faces."
    .format(floor.Id, level.Name, len(room_data), n_loops))

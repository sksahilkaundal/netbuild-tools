"""A stand-in Revit model for Stair Path by Netbuild (no Revit needed).

Just the Revit API the engine touches, with Revit's behaviour where it matters:

* ``StairsPath.Create`` raises "the stairsId is not visible in planViewId" unless the flight is visible in the
  view -- a view sees the flights touching its level (base, top or passing through) minus ``hidden`` (a
  shallow View Range) and anything outside its crop;
* a Fixed Up Direction stair path has no Show Down Text: setting it raises, as in Revit;
* every change outside a Transaction raises; Transaction / TransactionGroup roll back to a snapshot.

Units are feet, as in the Revit API.
"""

import copy
import sys
import types


def mm(v):
    return v / 304.8


class _Enum(object):
    """Every name exists and maps to a stable negative int, like Revit's BuiltIn enums."""

    def __init__(self, base):
        self.__dict__["_ids"], self.__dict__["_base"] = {}, base

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._ids.setdefault(name, self._base - len(self._ids))


BuiltInParameter = _Enum(-1000000)
BuiltInCategory = _Enum(-2000000)
ViewType = types.SimpleNamespace(FloorPlan="FloorPlan", CeilingPlan="CeilingPlan")
TransactionStatus = types.SimpleNamespace(Committed="Committed", RolledBack="RolledBack")
FailureSeverity = types.SimpleNamespace(Warning="Warning", Error="Error")
FailureProcessingResult = types.SimpleNamespace(Continue="Continue", ProceedWithRollBack="ProceedWithRollBack")


class IFailuresPreprocessor(object):
    pass


class ElementId(object):
    def __init__(self, n):
        self.Value = int(n)

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.Value == self.Value

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.Value)

    def __repr__(self):
        return "ElementId(%d)" % self.Value


class LinkElementId(object):
    def __init__(self, host):
        self.HostElementId = host


class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def __repr__(self):
        return "XYZ(%g, %g, %g)" % (self.X * 304.8, self.Y * 304.8, self.Z * 304.8)


class Transform(object):
    def OfPoint(self, p):
        return XYZ(p.X, p.Y, p.Z)


class BoundingBoxXYZ(object):
    def __init__(self, x0, y0, z0, x1, y1, z1):
        self.Min, self.Max, self.Transform = XYZ(x0, y0, z0), XYZ(x1, y1, z1), Transform()


class Param(object):
    def __init__(self, value):
        self.value = value

    def AsElementId(self):
        return self.value

    def AsDouble(self):
        return self.value

    def AsString(self):
        return self.value


class Element(object):
    category = None
    is_type = False

    def __init__(self, doc, name=""):
        self.Id = ElementId(doc.next_id())
        self.Name = name
        self.params = {}
        self.owner_view = None
        doc.add(self)

    def get_Parameter(self, bip):
        v = self.params.get(bip)
        return Param(v) if v is not None else None

    @property
    def OwnerViewId(self):
        return self.owner_view if self.owner_view is not None else ElementId(-1)


class Level(Element):
    def __init__(self, doc, name, elev_mm):
        Element.__init__(self, doc, name)
        self.Elevation = mm(elev_mm)


class Line(object):
    def __init__(self, p0, p1):
        self.p = (p0, p1)

    def GetEndPoint(self, i):
        return self.p[i]


class StairsRun(Element):
    def __init__(self, doc, base_elev, p0, p1):
        Element.__init__(self, doc)
        self.BaseElevation, self.line = base_elev, Line(p0, p1)

    def GetStairsPath(self):
        return [self.line]


class Stairs(Element):
    category = BuiltInCategory.OST_Stairs

    def __init__(self, doc, base, top, box_mm, run_mm, base_off=0.0, top_off=0.0, run_id=None):
        Element.__init__(self, doc)
        if run_id is not None:                              # keep the scenario's ids readable
            doc.by_id.pop(self.Id.Value)
            self.Id = ElementId(run_id)
            doc.by_id[run_id] = self
        x0, y0, x1, y1 = [mm(v) for v in box_mm]
        self.box = (x0, y0, x1, y1)
        self.params[BuiltInParameter.STAIRS_BASE_LEVEL_PARAM] = base.Id
        self.params[BuiltInParameter.STAIRS_TOP_LEVEL_PARAM] = top.Id
        self.params[BuiltInParameter.STAIRS_BASE_OFFSET] = mm(base_off)
        self.params[BuiltInParameter.STAIRS_TOP_OFFSET] = mm(top_off)
        self.base_elev = base.Elevation + mm(base_off)
        self.top_elev = top.Elevation + mm(top_off)
        self.Height = self.top_elev - self.base_elev
        (ax, ay), (bx, by) = run_mm
        # a second run first in the list, at a higher BaseElevation: the engine must not take list order
        self.runs = [StairsRun(doc, mm(1500), XYZ(0, 0, 0), XYZ(mm(-1), mm(-1), 0)).Id,
                     StairsRun(doc, 0.0, XYZ(mm(ax), mm(ay), 0), XYZ(mm(bx), mm(by), 0)).Id]

    def GetStairsRuns(self):
        return list(self.runs)

    def get_BoundingBox(self, view):
        x0, y0, x1, y1 = self.box
        return BoundingBoxXYZ(x0, y0, self.base_elev - mm(200), x1, y1, self.top_elev)


class LegacyStairs(Element):
    """A sketch-based stair: in OST_Stairs but not a Stairs element (Revit cannot path it)."""
    category = BuiltInCategory.OST_Stairs

    def get_BoundingBox(self, view):
        return BoundingBoxXYZ(0, 0, 0, 1, 1, 1)


class StairsPathType(Element):
    category = BuiltInCategory.OST_StairsPaths
    is_type = True

    def __init__(self, doc, family, name):
        Element.__init__(self, doc, name)
        self.family = family
        self.params[BuiltInParameter.ALL_MODEL_FAMILY_NAME] = family
        self.params[BuiltInParameter.ALL_MODEL_TYPE_NAME] = name

    def Duplicate(self, name):
        doc = self.doc_ref
        doc.check_tx("Duplicate")
        t = StairsPathType(doc, self.family, name)
        t.doc_ref = doc
        return t


class StairsPath(Element):
    category = BuiltInCategory.OST_StairsPaths

    def __init__(self, doc, stair_id, type_id, view_id):
        Element.__init__(self, doc)
        self.StairsId, self.type_id, self.owner_view = LinkElementId(stair_id), type_id, view_id
        self.fixed = doc.by_id[type_id.Value].family == "Fixed Up Direction"
        self._show_down = not self.fixed
        self.ShowUpText = True
        self.UpTextOffset = self.DownTextOffset = XYZ()
        self.doc_ref = doc

    @staticmethod
    def Create(doc, link_id, type_id, view_id):
        doc.check_tx("StairsPath.Create")
        view = doc.by_id[view_id.Value]
        sid = link_id.HostElementId.Value
        if sid not in view.visible_ids(doc):
            raise ValueError("the stairsId is not visible in planViewId.")
        return StairsPath(doc, link_id.HostElementId, type_id, view_id)

    @property
    def ShowDownText(self):
        if self.fixed:
            raise ValueError("the type of this stairs path is not automatic up/down direction.")
        return self._show_down

    @ShowDownText.setter
    def ShowDownText(self, v):
        if self.fixed:
            raise ValueError("the type of this stairs path is not automatic up/down direction.")
        self._show_down = v

    def GetTypeId(self):
        return self.type_id

    def get_BoundingBox(self, view):
        st = self.doc_ref.by_id[self.StairsId.HostElementId.Value]
        x0, y0, x1, y1 = st.box
        return BoundingBoxXYZ(x0, y0, 0, x1, y1, 0)


class ViewPlan(Element):
    def __init__(self, doc, name, level, scale, crop_mm=None, template=None, hidden=()):
        Element.__init__(self, doc, name)
        self.GenLevel, self.Scale, self.IsTemplate, self.ViewType = level, scale, False, ViewType.FloorPlan
        self.CropBoxActive = crop_mm is not None
        if crop_mm:
            x0, y0, x1, y1 = [mm(v) for v in crop_mm]
            self.CropBox = BoundingBoxXYZ(x0, y0, -10, x1, y1, 10)
        self.ViewTemplateId = template.Id if template is not None else ElementId(-1)
        self.hidden = set(hidden)

    def visible_ids(self, doc):
        out = set()
        lv = self.GenLevel.Elevation
        for el in doc.by_id.values():
            if not isinstance(el, Stairs) or el.Id.Value in self.hidden:
                continue
            if not (el.base_elev - mm(10) <= lv <= el.top_elev + mm(10)):
                continue
            if self.CropBoxActive:
                c = self.CropBox
                x0, y0, x1, y1 = el.box
                if x1 < c.Min.X or x0 > c.Max.X or y1 < c.Min.Y or y0 > c.Max.Y:
                    continue
            out.add(el.Id.Value)
        return out


class ViewTemplate(Element):
    def __init__(self, doc, name, controls_range=True):
        Element.__init__(self, doc, name)
        self.free = [] if controls_range else [ElementId(BuiltInParameter.PLAN_VIEW_RANGE)]

    def GetNonControlledTemplateParameterIds(self):
        return list(self.free)


class LocationPoint(object):
    def __init__(self, doc, p):
        self.doc, self._p = doc, p

    @property
    def Point(self):
        return self._p

    @Point.setter
    def Point(self, p):
        self.doc.check_tx("move a tag")
        self._p = p


class Room(Element):
    def __init__(self, doc, name, rect_mm, level):
        Element.__init__(self, doc, name)
        self.params[BuiltInParameter.ROOM_NAME] = name
        self.rect = [mm(v) for v in rect_mm]
        x0, y0, x1, y1 = self.rect
        self.Location = types.SimpleNamespace(Point=XYZ((x0 + x1) / 2, (y0 + y1) / 2, level.Elevation))
        self.z = (level.Elevation, level.Elevation + mm(3000))

    def IsPointInRoom(self, p):
        x0, y0, x1, y1 = self.rect
        return x0 <= p.X <= x1 and y0 <= p.Y <= y1 and self.z[0] <= p.Z <= self.z[1]


class RoomTag(Element):
    category = BuiltInCategory.OST_RoomTags

    def __init__(self, doc, room, view, at_mm):
        Element.__init__(self, doc)
        self.Room, self.owner_view = room, view.Id
        self.Location = LocationPoint(doc, XYZ(mm(at_mm[0]), mm(at_mm[1]), 0))

    def get_BoundingBox(self, view):
        p, h = self.Location.Point, mm(300)
        return BoundingBoxXYZ(p.X - h, p.Y - h, 0, p.X + h, p.Y + h, 0)


class Dimension(Element):
    category = BuiltInCategory.OST_Dimensions

    def __init__(self, doc, view, box_mm):
        Element.__init__(self, doc)
        self.owner_view, self.box = view.Id, [mm(v) for v in box_mm]

    def get_BoundingBox(self, view):
        x0, y0, x1, y1 = self.box
        return BoundingBoxXYZ(x0, y0, 0, x1, y1, 0)


class Collector(object):
    def __init__(self, doc, view_id=None):
        self.doc, self.view_id = doc, view_id
        self.items = list(doc.by_id.values())

    def OfCategory(self, cat):
        self.items = [e for e in self.items if e.category == cat]
        return self

    def OfClass(self, cls):
        self.items = [e for e in self.items if isinstance(e, cls)]
        return self

    def WhereElementIsElementType(self):
        self.items = [e for e in self.items if e.is_type]
        return self

    def WhereElementIsNotElementType(self):
        self.items = [e for e in self.items if not e.is_type]
        return self

    def ToElements(self):
        if self.view_id is None:
            return list(self.items)
        view = self.doc.by_id[self.view_id.Value]
        seen = view.visible_ids(self.doc)
        return [e for e in self.items if (e.Id.Value in seen if isinstance(e, Stairs) else
                                          e.owner_view == self.view_id)]


class _Options(object):
    def SetFailuresPreprocessor(self, p):
        self.pre = p


class Transaction(object):
    def __init__(self, doc, name):
        self.doc, self.name = doc, name

    def GetFailureHandlingOptions(self):
        return _Options()

    def SetFailureHandlingOptions(self, o):
        pass

    def Start(self):
        self.snap = self.doc.snapshot()
        self.doc.tx += 1
        self.doc.names.append(self.name)

    def Commit(self):
        self.doc.tx -= 1
        return TransactionStatus.Committed

    def RollBack(self):
        self.doc.tx -= 1
        self.doc.restore(self.snap)


class TransactionGroup(object):
    def __init__(self, doc, name):
        self.doc, self.name, self.started = doc, name, False

    def Start(self):
        self.snap, self.started = self.doc.snapshot(), True
        self.doc.groups.append(self.name)

    def HasStarted(self):
        return self.started

    def RollBack(self):
        self.doc.restore(self.snap)
        self.started = False
        self.doc.group_result = "rolled back"

    def Assimilate(self):
        self.started = False
        self.doc.group_result = "assimilated"


class Doc(object):
    def __init__(self, title):
        self.Title = title
        self.IsFamilyDocument = self.IsReadOnly = False
        self.by_id, self._next, self.tx = {}, 1000, 0
        self.names, self.groups, self.group_result = [], [], None

    def next_id(self):
        self._next += 1
        return self._next

    def add(self, el):
        self.by_id[el.Id.Value] = el

    def GetElement(self, eid):
        return self.by_id.get(eid.Value) if eid is not None else None

    def check_tx(self, what):
        if not self.tx:
            raise RuntimeError("%s outside a transaction" % what)

    def Delete(self, ids):
        self.check_tx("Delete")
        for i in ids:
            self.by_id.pop(i.Value, None)

    def snapshot(self):
        keep = {}
        for k, e in self.by_id.items():
            keep[k] = (e, dict(e.__dict__))
            if isinstance(e, RoomTag):
                keep[k] = (e, dict(e.__dict__), e.Location._p)
        return keep

    def restore(self, snap):
        self.by_id = {}
        for k, item in snap.items():
            e = item[0]
            e.__dict__.clear()
            e.__dict__.update(item[1])
            if len(item) == 3:
                e.Location._p = item[2]
            self.by_id[k] = e

    def paths(self):
        return sorted([e for e in self.by_id.values() if isinstance(e, StairsPath)], key=lambda e: e.Id.Value)


def install_stubs():
    db = types.ModuleType("Autodesk.Revit.DB")
    for name in ("BuiltInCategory", "BuiltInParameter", "ElementId", "FailureProcessingResult", "FailureSeverity",
                 "IFailuresPreprocessor", "Level", "LinkElementId", "Transaction", "TransactionGroup",
                 "TransactionStatus", "ViewPlan", "ViewType", "XYZ"):
        setattr(db, name, globals()[name])
    db.FilteredElementCollector = Collector
    arch = types.ModuleType("Autodesk.Revit.DB.Architecture")
    arch.StairsPath = StairsPath
    db.Architecture = arch
    revit_mod = types.ModuleType("Autodesk.Revit")
    revit_mod.DB = db
    autodesk = types.ModuleType("Autodesk")
    autodesk.Revit = revit_mod
    generic = types.ModuleType("System.Collections.Generic")
    generic.List = {ElementId: list}
    sys.modules.update({"Autodesk": autodesk, "Autodesk.Revit": revit_mod, "Autodesk.Revit.DB": db,
                        "Autodesk.Revit.DB.Architecture": arch, "System.Collections.Generic": generic})
    sys.modules.pop("stair_path.engine", None)       # re-bind the engine to these stubs
    pkg = sys.modules.get("stair_path")
    if pkg is not None and hasattr(pkg, "engine"):
        delattr(pkg, "engine")


class Model(object):
    """The test building: five levels, two stair cores (one messy), a stub stair, five views.

    Core A (x 0-2.5 m, width > length -> text along Y): 101 GF->L01, 102 L01->L02 (Base Level says GF, offset
    +3500), 103 L02->L03, plus 150 GF->L03 -- a legacy duplicate overlapping the whole core.
    Core B (x 20-26 m, length > width -> text along X): 201 GF->L02 (run +X), 202 L02->L03 (run -X).
    300: a stub at L01 (base = top), 400: a sketch stair Revit cannot path.
    """

    def __init__(self, drop_types=()):
        d = self.doc = Doc("Tower_B001")
        lv = self.lv = dict((n, Level(d, n, e)) for n, e in (("GF", 0), ("L01", 3500), ("L02", 7000),
                                                             ("L03", 10500), ("Roof", 14000)))
        a_box, b_box = (0, 0, 2500, 6000), (20000, 0, 26000, 2500)
        up_y, down_y = ((1000, 500), (1000, 5500)), ((1500, 5500), (1500, 500))
        up_x, down_x = ((20500, 1000), (25500, 1000)), ((25500, 1500), (20500, 1500))
        self.s = {}
        for sid, b, t, box, run, off in ((101, "GF", "L01", a_box, up_y, 0), (102, "GF", "L02", a_box, down_y, 3500),
                                         (103, "L02", "L03", a_box, up_y, 0), (150, "GF", "L03", a_box, up_y, 0),
                                         (201, "GF", "L02", b_box, up_x, 0), (202, "L02", "L03", b_box, down_x, 0),
                                         (300, "L01", "L01", (40000, 0, 41000, 3000), up_y, 0)):
            self.s[sid] = Stairs(d, lv[b], lv[t], box, run, base_off=off, run_id=sid)
        self.legacy = LegacyStairs(d)
        self.types = {}
        for fam, name in (("Fixed Up Direction", "Standard"), ("Fixed Up Direction", "Standard 1-200"),
                          ("Fixed Up Direction", "Standard 1:100"), ("Automatic Up/Down Direction", "Standard"),
                          ("Automatic Up/Down Direction", "Standard 1-500"),
                          ("Automatic Up/Down Direction", "Standard 1-200"),
                          ("Automatic Up/Down Direction", "Standard 1-100 (Studio)"),
                          ("Automatic Up/Down Direction", "Standard 1-100")):
            if (fam, name) in drop_types:
                continue
            t = StairsPathType(d, fam, name)
            t.doc_ref = d
            self.types[(fam, name)] = t
        self.tpl = ViewTemplate(d, "GA 1-100")
        self.v = {
            "GF": ViewPlan(d, "GF GA Plan", lv["GF"], 500),
            "L01": ViewPlan(d, "L01 GA Plan", lv["L01"], 200),
            "L02": ViewPlan(d, "L02 GA Plan", lv["L02"], 100, template=self.tpl, hidden=(102, 201)),
            "L03": ViewPlan(d, "L03 Part Plan 01", lv["L03"], 200, crop_mm=(-1000, -1000, 5000, 7000)),
            "L01D": ViewPlan(d, "L01 Stair Detail", lv["L01"], 50),
            "Roof": ViewPlan(d, "Roof GA Plan", lv["Roof"], 200),
        }
        self.open = [self.v[k] for k in ("GF", "L01", "L02", "L03", "L01D")]
        self.uidoc = types.SimpleNamespace(GetOpenUIViews=lambda: [types.SimpleNamespace(ViewId=v.Id)
                                                                   for v in self.open])
        # existing annotations: one in a target view (cleared), one in the stair detail view (kept)
        d.tx += 1
        self.old = StairsPath(d, self.s[101].Id, self.types[("Automatic Up/Down Direction", "Standard 1-200")].Id,
                              self.v["L01"].Id)
        self.kept = StairsPath(d, self.s[101].Id, self.types[("Automatic Up/Down Direction", "Standard")].Id,
                               self.v["L01D"].Id)
        d.tx -= 1
        # rooms / tags at L01: an office tag sitting on core A, a Staircase tag left outside its room
        office = Room(d, "Office", (3000, 0, 9000, 6000), lv["L01"])
        stair_room = Room(d, "Staircase 01", (0, 0, 2500, 6000), lv["L01"])
        self.office_tag = RoomTag(d, office, self.v["L01"], (2400, 3000))
        self.stair_tag = RoomTag(d, stair_room, self.v["L01"], (2700, 9000))
        self.free_tag = RoomTag(d, office, self.v["L01"], (8000, 5000))
        self.dim = Dimension(d, self.v["L02"], (21000, 2000, 24000, 2200))

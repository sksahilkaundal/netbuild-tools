"""A stand-in Revit model for Clear Warnings by Netbuild (no Revit needed).

``DB`` is the slice of the Revit API the engine uses; ``b001_model()`` builds a document shaped like
ProjectC-Studio-BIM-B001 (Area Plans, Areas, Area Separation Lines, dead Matchlines and Room Tags, duplicate Type
Marks). ``doc.GetWarnings()`` is worked out from the model's current state, the way Revit re-checks it, so
deleting an Area removes its warning. As in Revit, every change outside a Transaction raises, and a
Transaction / TransactionGroup rolled back restores the model.
"""

import copy
import types


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


ElementId.InvalidElementId = ElementId(-1)


class OldElementId(object):
    """Revit 2023 and older: IntegerValue only."""

    def __init__(self, n):
        self.IntegerValue = int(n)


BIC = dict(OST_Areas=-2003200, OST_AreaSchemeLines=-2000079, OST_Matchline=-2000198, OST_RoomTags=-2000480,
           OST_Views=-2000279, OST_Schedules=-2000573, OST_Walls=-2000011, OST_Floors=-2000032,
           OST_Doors=-2000023, OST_Rooms=-2000160)
CAT_NAMES = dict(OST_Areas="Areas", OST_AreaSchemeLines="Area Boundary", OST_Matchline="Matchline",
                 OST_RoomTags="Room Tags", OST_Views="Views", OST_Schedules="Schedules", OST_Walls="Walls",
                 OST_Floors="Floors", OST_Doors="Doors", OST_Rooms="Rooms")
BuiltInCategory = types.SimpleNamespace(**BIC)
BuiltInParameter = types.SimpleNamespace(ALL_MODEL_TYPE_MARK="ALL_MODEL_TYPE_MARK",
                                         ALL_MODEL_TYPE_NAME="ALL_MODEL_TYPE_NAME")
ViewType = types.SimpleNamespace(AreaPlan="AreaPlan", FloorPlan="FloorPlan", Schedule="Schedule")


class Category(object):
    def __init__(self, key):
        self.Id, self.Name = ElementId(BIC[key]), CAT_NAMES[key]


class Parameter(object):
    def __init__(self, el, key, read_only=False):
        self.el, self.key, self.IsReadOnly = el, key, read_only

    def AsString(self):
        return self.el.params.get(self.key)

    def Set(self, value):
        self.el.doc.must_be_in_transaction("Parameter.Set")
        self.el.params[self.key] = value
        return True


class Element(object):
    is_type = False

    def __init__(self, doc, n, cat=None, name=""):
        self.doc, self.Id, self.Name = doc, ElementId(n), name
        self.Category = Category(cat) if cat else None
        self.params, self.dependents = {}, []

    def get_Parameter(self, key):
        return Parameter(self, key) if key in self.params else None


class ViewPlan(Element):
    def __init__(self, doc, n, name, view_type="AreaPlan", template=False):
        Element.__init__(self, doc, n, "OST_Views", name)
        self.ViewType, self.IsTemplate = view_type, template


class ViewSchedule(Element):
    def __init__(self, doc, n, name, cat="OST_Areas", template=False):
        Element.__init__(self, doc, n, "OST_Schedules", name)
        self.ViewType, self.IsTemplate = "Schedule", template
        self.Definition = types.SimpleNamespace(CategoryId=ElementId(BIC[cat])) if cat else None

    def __getattribute__(self, name):
        if name == "Definition" and object.__getattribute__(self, "__dict__")["Definition"] is None:
            raise AttributeError("a revision schedule has no Definition")
        return object.__getattribute__(self, name)


class ElementType(Element):
    is_type = True

    def __init__(self, doc, n, cat, name, mark):
        Element.__init__(self, doc, n, cat, name)
        self.params = {"ALL_MODEL_TYPE_NAME": name, "ALL_MODEL_TYPE_MARK": mark}


class Matchline(Element):
    def __init__(self, doc, n, owner, off_axis=True):
        Element.__init__(self, doc, n, "OST_Matchline", "Matchline")
        self.OwnerViewId, self.off_axis = owner, off_axis


class RoomTag(Element):
    def __init__(self, doc, n, owner, room=None, dangling=False, outside=True):
        Element.__init__(self, doc, n, "OST_RoomTags", "Room Tag")
        self.OwnerViewId, self.Room, self.dangling, self.outside = owner, room, dangling, outside

    @property
    def TaggedLocalRoomId(self):
        if self.dangling:
            raise Exception("The room reference is invalid")
        return self.Room.Id if self.Room is not None else ElementId.InvalidElementId


class Warning(object):
    def __init__(self, text, ids):
        self.text, self.ids = text, ids

    def GetDescriptionText(self):
        return self.text

    def GetFailingElements(self):
        return list(self.ids)


AREA_TEXT = "Area is not in a properly enclosed region"
OVERLAP_TEXT = "Highlighted lines overlap. Lines may not form closed loops."
OFF_AXIS_TEXT = "Matchline is slightly off axis and may cause inaccuracies."
TAG_TEXT = "Room Tag is outside of its Room. Enable Leader or move Room Tag within its Room."
TYPE_MARK_TEXT = "Elements have duplicate 'Type Mark' values."
WALLS_TEXT = "Highlighted walls overlap. One of them may be ignored when Revit finds room boundaries."


class Document(object):
    def __init__(self, title):
        self.Title, self.IsReadOnly, self.IsFamilyDocument = title, False, False
        self.elements, self.ActiveView = {}, None
        self.in_transaction, self.log, self._snapshots = 0, [], []
        self._next = 1000
        self.fixed_warnings = []                         # warnings nothing here touches (walls overlap, ...)

    # -- building the model
    def add(self, cls, *args, **kw):
        self._next += 1
        el = cls(self, self._next, *args, **kw)
        self.elements[el.Id.Value] = el
        return el

    def must_be_in_transaction(self, what):
        if not self.in_transaction:
            raise Exception("%s: Modifying is forbidden because the document has no open transaction." % what)

    # -- the API
    def GetElement(self, eid):
        n = eid.Value if hasattr(eid, "Value") else eid.IntegerValue
        return self.elements.get(n)

    def Delete(self, ids):
        self.must_be_in_transaction("Document.Delete")
        gone = []
        stack = list(ids)
        while stack:
            eid = stack.pop()
            el = self.elements.pop(eid.Value, None)
            if el is None:
                continue
            gone.append(eid)
            stack.extend(el.dependents)
        return gone

    def GetWarnings(self):
        out = [Warning(text, ids) for text, ids in self.fixed_warnings]
        for el in self.of(lambda e: e.Category and e.Category.Name == "Areas"):
            out.append(Warning(AREA_TEXT, [el.Id]))
        lines = self.of(lambda e: e.Category and e.Category.Name == "Area Boundary")
        for a, b in zip(lines[0::2], lines[1::2]):
            out.append(Warning(OVERLAP_TEXT, [a.Id, b.Id]))
        for m in self.of(lambda e: isinstance(e, Matchline) and e.off_axis):
            out.append(Warning(OFF_AXIS_TEXT, [m.Id]))
        for t in self.of(lambda e: isinstance(e, RoomTag) and e.outside):
            out.append(Warning(TAG_TEXT, [t.Id]))
        marks = {}
        for t in self.of(lambda e: e.is_type and e.params.get("ALL_MODEL_TYPE_MARK")):
            marks.setdefault((t.Category.Name, t.params["ALL_MODEL_TYPE_MARK"]), []).append(t.Id)
        for key in sorted(marks):
            if len(marks[key]) > 1:
                out.append(Warning(TYPE_MARK_TEXT, marks[key]))
        return out

    def of(self, test):
        return [self.elements[k] for k in sorted(self.elements) if test(self.elements[k])]

    # -- transactions
    def snapshot(self):
        return dict((k, (v, copy.deepcopy(v.params))) for k, v in self.elements.items())

    def restore(self, snap):
        self.elements = {}
        for k, (el, params) in snap.items():
            el.params = params
            self.elements[k] = el

    def state(self):
        return sorted((k, sorted(v.params.items())) for k, v in self.elements.items())


class Transaction(object):
    def __init__(self, doc, name):
        self.doc, self.name = doc, name

    def Start(self):
        self.snap = self.doc.snapshot()
        self.doc.in_transaction += 1
        self.doc.log.append(("start", self.name))

    def Commit(self):
        self.doc.in_transaction -= 1
        self.doc.log.append(("commit", self.name))
        if getattr(self.doc, "fail_on_commit", None) == self.name:
            raise Exception("Revit refused: an element is borrowed by another user")
        return "Committed"

    def RollBack(self):
        if self.doc.log[-1] != ("commit", self.name):
            self.doc.in_transaction -= 1
        self.doc.restore(self.snap)
        self.doc.log.append(("rollback", self.name))


class TransactionGroup(object):
    def __init__(self, doc, name):
        self.doc, self.name = doc, name

    def Start(self):
        self.snap = self.doc.snapshot()
        self.doc.log.append(("group", self.name))

    def Assimilate(self):
        self.doc.log.append(("assimilate", self.name))

    def RollBack(self):
        self.doc.restore(self.snap)
        self.doc.log.append(("group rollback", self.name))


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.doc, self.tests = doc, []

    def OfClass(self, cls):
        self.tests.append(lambda e: isinstance(e, cls))
        return self

    def OfCategory(self, bic):
        self.tests.append(lambda e: e.Category is not None and e.Category.Id.Value == bic)
        return self

    def WhereElementIsNotElementType(self):
        self.tests.append(lambda e: not e.is_type)
        return self

    def WhereElementIsElementType(self):
        self.tests.append(lambda e: e.is_type)
        return self

    def ToElements(self):
        return self.doc.of(lambda e: all(t(e) for t in self.tests))


DB = types.ModuleType("Autodesk.Revit.DB")
for _name in ("ElementId", "BuiltInCategory", "BuiltInParameter", "ViewType", "ViewPlan", "ViewSchedule",
              "Transaction", "TransactionGroup", "FilteredElementCollector"):
    setattr(DB, _name, globals()[_name])


def b001_model(title="ProjectC-Studio-BIM-B001-ZZZ-BM-950001"):
    """A small B001: most warnings on Areas / Area Separation Lines, plus every case steps 4 - 6 handle."""
    doc = Document(title)
    floor = doc.add(ViewPlan, "L01 GA Plan", "FloorPlan")
    doc.ActiveView = floor
    plans = [doc.add(ViewPlan, "L%02d Area Plan GFA" % i) for i in range(1, 3)]
    doc.add(ViewPlan, "Area Plan template", template=True)                  # kept: a template, not a view
    doc.add(ViewSchedule, "GFA Area Schedule")
    doc.add(ViewSchedule, "Door Schedule", "OST_Doors")                       # not an Area schedule
    doc.add(ViewSchedule, "Revision Schedule", None)                          # no Definition
    for plan in plans:
        for _ in range(3):
            area = doc.add(Element, "OST_Areas", "Area")
            plan.dependents.append(area.Id)                                   # deleting the plan takes its areas
    for _ in range(8):
        doc.add(Element, "OST_AreaSchemeLines", "Area Separation")
    doc.add(Matchline, ElementId.InvalidElementId)                            # orphaned: step 4 deletes it
    doc.live_matchline = doc.add(Matchline, floor.Id)                         # live + off axis: manual review
    doc.add(Matchline, floor.Id, off_axis=False)                              # live, fine
    room = doc.add(Element, "OST_Rooms", "Lobby")
    room.Number = "L01-001"
    doc.dangling_tag = doc.add(RoomTag, floor.Id, dangling=True)              # orphaned: step 5 deletes it
    doc.placed_tag = doc.add(RoomTag, floor.Id, room=room)                    # valid room, out of place: review
    doc.add(ElementType, "OST_Walls", "Wall 200mm", "W1")
    doc.add(ElementType, "OST_Walls", "Wall 100mm", "W1")
    doc.add(ElementType, "OST_Doors", "Ritz Door 900", "D1")
    doc.add(ElementType, "OST_Doors", "Single Door", "D1")
    doc.add(ElementType, "OST_Doors", "Double Door", "D1")
    doc.add(ElementType, "OST_Doors", "Existing", "D1a")                      # a letter already in use
    doc.fixed_warnings = [(WALLS_TEXT, [floor.Id])]
    return doc

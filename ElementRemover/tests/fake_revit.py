"""A stand-in for Revit + the pyRevit MCP listener, for tests (no Revit needed).

Serves POST /revit_mcp/execute_code/ like the real route and runs the posted payload with
``doc`` bound to the active document. The Revit API pieces the payload imports are stubbed
with Revit's behaviour where it matters:

* worksets (one closed: its elements are not loaded, so collectors do not return them), rule-based
  view filters (categories + a rule on Comments) and saved selection filters;
* model groups: a member cannot be deleted while it is grouped (Revit keeps the instances of a type
  identical), a pinned group cannot be ungrouped, group types need unique names, a type still in
  use cannot be deleted, nested groups;
* Delete takes the dependents with it -- a door with its host wall, a tag with what it tags, a
  group instance with its members -- and refuses pinned elements;
* every change outside a Transaction raises, as in Revit; Transaction / TransactionGroup roll back
  to a snapshot; commit runs the failures preprocessor (warnings, errors) and refuses elements
  borrowed by another user.
"""

import builtins
import copy
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ------------------------------------------------------------ Revit API stubs

class ElementId(object):
    def __init__(self, n):
        self.IntegerValue = self.Value = int(n)

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


ElementId.InvalidElementId = ElementId(-1)
INVALID = ElementId.InvalidElementId


class WorksetId(object):
    def __init__(self, n):
        self.IntegerValue = int(n)

    def __eq__(self, other):
        return isinstance(other, WorksetId) and other.IntegerValue == self.IntegerValue

    def __hash__(self):
        return hash(self.IntegerValue)


class _Categories(object):
    """BuiltInCategory: every name maps to a stable negative int, like the real enum."""

    def __init__(self):
        self.__dict__["_ids"] = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._ids.setdefault(name, -2000000 - len(self._ids))


BuiltInCategory = _Categories()


class _Enum(object):
    def __init__(self, *names):
        for n in names:
            setattr(self, n, n)


CategoryType = _Enum("Model", "Annotation", "AnalyticalModel")
FailureSeverity = _Enum("Warning", "Error")
FailureProcessingResult = _Enum("Continue", "ProceedWithRollBack")
TransactionStatus = _Enum("Committed", "RolledBack")
CheckoutStatus = _Enum("OwnedByOtherUser", "OwnedByCurrentUser", "NotOwned")
WorksetKind = _Enum("UserWorkset", "ViewWorkset", "StandardWorkset")

NAMES = {"OST_Walls": "Walls", "OST_Doors": "Doors", "OST_Floors": "Floors", "OST_Furniture": "Furniture",
         "OST_PlumbingFixtures": "Plumbing Fixtures", "OST_Levels": "Levels", "OST_Grids": "Grids",
         "OST_IOSModelGroups": "Model Groups", "OST_WallTags": "Wall Tags", "OST_Views": "Views",
         "OST_Topography": "Topography", "OST_GenericModel": "Generic Models", "OST_TextNotes": "Text Notes"}


class Category(object):
    def __init__(self, bic, name, kind="Model"):
        self.Id = ElementId(getattr(BuiltInCategory, bic))
        self.Name, self.CategoryType = name, kind

    @staticmethod
    def GetCategory(doc, cid):
        return [c for c in doc._cats.values() if c.Id == cid][0]


class Element(object):
    def __init__(self, doc, cat, name, ws=None, comments="", view_specific=False):
        self.doc = doc
        self.Id = ElementId(doc.new_id())
        self.Category = doc.category(cat) if cat else None
        self.Name = name
        self.WorksetId = WorksetId(ws if ws is not None else 0)
        self.comments = comments
        self.GroupId = INVALID
        self._pinned = False
        self.ViewSpecific = view_specific
        self.IsValidObject = True
        doc.add(self)

    @property
    def Pinned(self):
        return self._pinned

    @Pinned.setter
    def Pinned(self, value):
        self.doc.touch(self)
        self._pinned = bool(value)

    def GetTypeId(self):
        return INVALID


class ElementType(Element):
    pass


class View(Element):
    pass


class Level(Element):
    pass


class FamilyInstance(Element):
    def __init__(self, doc, cat, name, ws=None, comments="", host=None):
        super().__init__(doc, cat, name, ws, comments)
        self.Host = host
        self.SuperComponent = None


class Tag(Element):
    def __init__(self, doc, tagged):
        super().__init__(doc, "OST_WallTags", "Wall Tag", ws=100, view_specific=True)
        self.tagged = tagged


class GroupType(ElementType):
    def __init__(self, doc, name):
        super().__init__(doc, None, name)

    def __setattr__(self, key, value):
        if key == "Name" and "Name" in self.__dict__:
            if [t for t in self.doc.by_id.values() if isinstance(t, GroupType) and t is not self
                    and t.Name == value]:
                raise Exception("The name '%s' is already in use" % value)
            self.doc.touch(self)
        object.__setattr__(self, key, value)


class Group(Element):
    """A model group instance: its members carry its id in GroupId."""

    def __init__(self, doc, gtype, members, ws=None):
        super().__init__(doc, "OST_IOSModelGroups", gtype.Name, ws)
        self.type_id = gtype.Id
        self.members = [m.Id for m in members]
        for m in members:
            m.GroupId = self.Id

    @property
    def Name(self):
        """As in Revit: a group instance is named by its type."""
        t = self.doc.by_id.get(self.__dict__["type_id"].Value) if "type_id" in self.__dict__ else None
        return t.Name if t is not None else self.__dict__.get("_name", "")

    @Name.setter
    def Name(self, value):
        self.__dict__["_name"] = value

    def member_els(self):
        return [self.doc.by_id[i.Value] for i in self.members if i.Value in self.doc.by_id]

    def GetTypeId(self):
        return self.type_id

    @property
    def GroupType(self):
        return self.doc.by_id[self.type_id.Value]

    def GetMemberIds(self):
        return list(self.members)

    def GetAvailableAttachedDetailGroupTypeIds(self):
        return []

    def UngroupMembers(self):
        if self.Pinned:
            raise Exception("The group is pinned")
        self.doc.touch(self)
        for m in self.member_els():
            m.GroupId = INVALID
        self.doc.remove(self)
        return list(self.members)


class Workset(object):
    def __init__(self, n, name, is_open=True, kind=WorksetKind.UserWorkset):
        self.Id, self.Name, self.IsOpen, self.Kind = WorksetId(n), name, is_open, kind


class ElementWorksetFilter(object):
    def __init__(self, wsid, inverted=False):
        self.wsid, self.inverted = wsid, inverted

    def passes(self, el):
        return (el.WorksetId == self.wsid) != self.inverted


class ElementMulticategoryFilter(object):
    def __init__(self, cats):
        self.cats = set(c.Value for c in cats)

    def passes(self, el):
        return el.Category is not None and el.Category.Id.Value in self.cats


class CommentsRule(object):
    """Stands for the ElementFilter a rule-based view filter holds (here: Comments equals a value)."""

    def __init__(self, value):
        self.value = value

    def passes(self, el):
        return el.comments == self.value


class ParameterFilterElement(Element):
    def __init__(self, doc, name, cats, rule=None):
        super().__init__(doc, None, name)
        self.cats, self.rule = [doc.category(c).Id for c in cats], rule

    def GetCategories(self):
        return list(self.cats)

    def GetElementFilter(self):
        return self.rule


class SelectionFilterElement(Element):
    def __init__(self, doc, name, els):
        super().__init__(doc, None, name)
        self.ids = [e.Id for e in els]

    def GetElementIds(self):
        return list(self.ids)


class Collector(object):
    def __init__(self, doc):
        closed = set(w.Id for w in doc.worksets if not w.IsOpen)
        self.items = [e for e in doc.by_id.values() if e.WorksetId not in closed]

    def OfClass(self, cls):
        self.items = [e for e in self.items if isinstance(e, cls)]
        return self

    def WhereElementIsNotElementType(self):
        self.items = [e for e in self.items if not isinstance(e, ElementType)]
        return self

    def WherePasses(self, f):
        self.items = [e for e in self.items if f.passes(e)]
        return self

    def GetElementCount(self):
        return len(self.items)

    def ToElements(self):
        return list(self.items)

    def __iter__(self):
        return iter(list(self.items))


class WorksetCollector(object):
    def __init__(self, doc):
        self.doc = doc

    def OfKind(self, kind):
        return [w for w in self.doc.worksets if w.Kind == kind]


class IFailuresPreprocessor(object):
    pass


class _Failure(object):
    def __init__(self, severity, text, ids=()):
        self.severity, self.text, self.ids = severity, text, list(ids)

    def GetFailingElementIds(self):
        return list(self.ids)

    def GetSeverity(self):
        return self.severity

    def GetDescriptionText(self):
        return self.text


class _Accessor(object):
    def __init__(self, failures):
        self.failures = list(failures)

    def GetFailureMessages(self):
        return list(self.failures)

    def DeleteWarning(self, f):
        self.failures.remove(f)


class _Options(object):
    def __init__(self):
        self.pre = None

    def SetFailuresPreprocessor(self, pre):
        self.pre = pre
        return self


class Transaction(object):
    def __init__(self, doc, name):
        self.doc, self.name, self.opts, self.snap = doc, name, _Options(), None

    def GetFailureHandlingOptions(self):
        return self.opts

    def SetFailureHandlingOptions(self, opts):
        self.opts = opts

    def Start(self):
        if self.doc.tx is not None:
            raise Exception("a transaction is already open")
        self.snap = self.doc.snapshot()
        self.doc.tx = self
        self.doc.touched = set()

    def RollBack(self):
        self.doc.restore(self.snap)
        self.doc.tx = None
        return TransactionStatus.RolledBack

    def Commit(self):
        doc = self.doc
        doc.log.append(self.name)
        fails = [_Failure(FailureSeverity.Warning, t) for t in doc.commit_warnings]
        fails += [_Failure(FailureSeverity.Error, t) for t in doc.commit_errors]
        for i in sorted(doc.touched):
            if i in doc.owners:
                fails.append(_Failure(FailureSeverity.Error, "Can't edit the element until '%s' saves changes "
                                      "to central and relinquishes it" % doc.owners[i], [ElementId(i)]))
        if fails:
            acc = _Accessor(fails)
            res = self.opts.pre.PreprocessFailures(acc) if self.opts.pre else FailureProcessingResult.Continue
            left = [f for f in acc.failures if f.severity == FailureSeverity.Error]
            if res == FailureProcessingResult.ProceedWithRollBack or left:
                return self.RollBack()
        doc.tx = None
        return TransactionStatus.Committed


class TransactionGroup(object):
    def __init__(self, doc, name):
        self.doc, self.name, self.snap, self.started = doc, name, None, False

    def Start(self):
        self.snap = self.doc.snapshot()
        self.started = True

    def HasStarted(self):
        return self.started

    def RollBack(self):
        self.doc.restore(self.snap)
        self.started = False
        self.doc.groups.append((self.name, "rolled back"))

    def Assimilate(self):
        self.started = False
        self.doc.groups.append((self.name, "assimilated"))


class WorksharingUtils(object):
    @staticmethod
    def GetCheckoutStatus(doc, eid):
        return CheckoutStatus.OwnedByOtherUser if eid.Value in doc.owners else CheckoutStatus.OwnedByCurrentUser

    @staticmethod
    def GetWorksharingTooltipInfo(doc, eid):
        return types.SimpleNamespace(Owner=doc.owners.get(eid.Value, ""))


def install_stubs():
    db = types.ModuleType("Autodesk.Revit.DB")
    for name in ("BuiltInCategory", "Category", "CategoryType", "ElementId", "ElementMulticategoryFilter",
                 "ElementType", "ElementWorksetFilter", "FailureProcessingResult", "FailureSeverity", "Group",
                 "IFailuresPreprocessor", "ParameterFilterElement", "SelectionFilterElement", "Transaction",
                 "TransactionGroup", "TransactionStatus", "View", "WorksetKind", "WorksharingUtils",
                 "CheckoutStatus"):
        setattr(db, name, globals()[name])
    db.FilteredElementCollector = Collector
    db.FilteredWorksetCollector = WorksetCollector
    revit_mod = types.ModuleType("Autodesk.Revit")
    revit_mod.DB = db
    autodesk = types.ModuleType("Autodesk")
    autodesk.Revit = revit_mod
    generic = types.ModuleType("System.Collections.Generic")
    generic.List = {ElementId: list}
    sys.modules.update({"Autodesk": autodesk, "Autodesk.Revit": revit_mod, "Autodesk.Revit.DB": db,
                        "System.Collections.Generic": generic})
    return db


# ------------------------------------------------------------ the model

class Doc(object):
    def __init__(self, title, app):
        self.Title, self.Application = title, app
        self.PathName = r"C:\Revit_Local\%s.rvt" % title
        self.IsLinked = self.IsFamilyDocument = self.IsReadOnly = False
        self.IsWorkshared = True
        self.worksets = []
        self.by_id = {}
        self._next = 500000
        self._cats = {}
        self.tx = None
        self.touched = set()
        self.owners = {}            # element id -> user who borrowed it
        self.commit_warnings, self.commit_errors = [], []
        self.log, self.groups = [], []
        self.Create = types.SimpleNamespace(NewGroup=self.new_group)
        self.Settings = types.SimpleNamespace(Categories=self)   # iterating it yields the categories
        app.Documents.append(self)

    def __iter__(self):
        for bic in NAMES:
            self.category(bic)
        return iter(list(self._cats.values()))

    def new_id(self):
        self._next += 1
        return self._next

    def category(self, bic):
        if bic not in self._cats:
            kind = "Annotation" if bic in ("OST_WallTags", "OST_TextNotes") else "Model"
            self._cats[bic] = Category(bic, NAMES.get(bic, bic[4:]), kind)
        return self._cats[bic]

    def GetWorksetTable(self):
        return types.SimpleNamespace(GetWorkset=lambda wid: ([w for w in self.worksets if w.Id == wid] or
                                                             [Workset(wid.IntegerValue, "?")])[0])

    def add(self, el):
        self.by_id[el.Id.Value] = el

    def GetElement(self, eid):
        return self.by_id.get(eid.Value)

    def touch(self, el):
        if self.tx is None:
            raise Exception("Attempt to modify the model outside of transaction.")
        self.touched.add(el.Id.Value)

    STATE = ("GroupId", "Name", "_pinned", "IsValidObject", "members", "type_id")

    def snapshot(self):
        return dict((i, (e, dict((k, copy.deepcopy(e.__dict__[k])) for k in self.STATE if k in e.__dict__)))
                    for i, e in self.by_id.items())

    def restore(self, snap):
        for e in self.by_id.values():
            if e.Id.Value not in snap:
                e.IsValidObject = False     # created after the snapshot
        self.by_id = dict((i, e) for i, (e, _) in snap.items())
        for e, state in snap.values():
            for k, v in state.items():
                e.__dict__[k] = copy.deepcopy(v)

    def remove(self, el):
        el.IsValidObject = False
        del self.by_id[el.Id.Value]

    def dependents(self, el):
        """What Revit deletes with an element: hosted instances, tags, a group's members."""
        out = [e for e in self.by_id.values() if getattr(e, "Host", None) is el or getattr(e, "tagged", None) is el]
        if isinstance(el, Group):
            out += el.member_els()
        return out

    def Delete(self, ids):
        ids = ids if isinstance(ids, list) else [ids]
        going, order = set(), []

        def take(el, cascade):
            if el.Id.Value in going:
                return
            if isinstance(el, GroupType) and [g for g in self.by_id.values()
                                              if isinstance(g, Group) and g.type_id == el.Id]:
                raise Exception("group type '%s' is in use" % el.Name)
            if el.Pinned and not cascade:
                raise Exception("Element %d is pinned" % el.Id.Value)
            if not cascade and el.GroupId.Value > 0 and el.GroupId.Value not in going:
                raise Exception("Can't delete element %d: it is a member of a group -- Revit keeps the "
                                "instances of a group type identical" % el.Id.Value)
            going.add(el.Id.Value)
            order.append(el)
            for dep in self.dependents(el):
                take(dep, True)

        for i in ids:
            el = self.by_id.get(i.Value)
            if el is None:
                raise Exception("element %d does not exist" % i.Value)
            take(el, False)
        for el in order:
            self.touch(el)
        for el in order:
            self.remove(el)
        return [el.Id for el in order]

    def new_group(self, ids):
        members = [self.by_id[i.Value] for i in ids]
        for m in members:
            if m.GroupId.Value > 0:
                raise Exception("element %d is already in a group" % m.Id.Value)
            self.touch(m)
        gt = GroupType(self, "Group %d" % self._next)
        self.touch(gt)
        g = Group(self, gt, members, ws=members[0].WorksetId.IntegerValue)
        self.touch(g)
        return g

    # ---- for the tests
    def alive(self, el):
        return el.Id.Value in self.by_id

    def group_of(self, el):
        g = self.by_id.get(el.GroupId.Value)
        return g

    def type_names(self):
        return sorted(t.Name for t in self.by_id.values() if isinstance(t, GroupType))


class FakeRevit(object):
    def __init__(self):
        install_stubs()
        self.app = types.SimpleNamespace(Documents=[])
        self.paused = False
        self.calls = 0
        self.lock = threading.Lock()
        d = self.doc = Doc("B003-Studio-ARC-ZZ-M3-A-0001_user", self.app)
        LG, ARC, DEMO, INT, SITE = 1, 2, 3, 4, 5
        d.worksets = [Workset(LG, "Shared Levels and Grids"), Workset(ARC, "Architecture"),
                      Workset(DEMO, "Demolition"), Workset(INT, "Interiors"), Workset(SITE, "Site", is_open=False),
                      Workset(100, "Views", kind=WorksetKind.ViewWorkset)]
        e = self.el = {}
        e["L01"] = Level(d, "OST_Levels", "L01", LG)
        e["L02"] = Level(d, "OST_Levels", "L02", LG)
        e["grid A"] = Element(d, "OST_Grids", "A", LG)
        e["plan"] = View(d, "OST_Views", "L01 - Floor Plan", 100)
        # Demolition: two walls (one hosting a door that is on Architecture, and tagged), a pinned slab,
        # a grid (protected), and a wall inside the 'Store' group instance G3
        e["demo wall 1"] = Element(d, "OST_Walls", "Existing Wall 200", DEMO)
        e["demo door"] = FamilyInstance(d, "OST_Doors", "Single Flush 900x2100", ARC, host=e["demo wall 1"])
        e["demo tag"] = Tag(d, e["demo wall 1"])
        e["demo wall 2"] = Element(d, "OST_Walls", "Existing Wall 100", DEMO)
        e["demo slab"] = Element(d, "OST_Floors", "Existing Slab 250", DEMO)
        e["demo slab"]._pinned = True
        e["grid B"] = Element(d, "OST_Grids", "B", DEMO)
        # Architecture: walls kept / marked REMOVE
        e["wall keep"] = Element(d, "OST_Walls", "Basic Wall 200", ARC)
        e["wall remove"] = Element(d, "OST_Walls", "Basic Wall 200", ARC, comments="REMOVE")
        e["sofa"] = Element(d, "OST_Furniture", "Sofa 3 seat", INT)
        e["topo"] = Element(d, "OST_Topography", "Site", SITE)

        # group type 'Toilet Core' placed twice: partition, door marked REMOVE (hosted on it), WC
        core_t = e["Toilet Core"] = GroupType(d, "Toilet Core")
        for k in ("1", "2"):
            p = e["core wall " + k] = Element(d, "OST_Walls", "Partition 100", ARC)
            dr = e["core door " + k] = FamilyInstance(d, "OST_Doors", "Single Flush 800x2100", ARC, "REMOVE", host=p)
            wc = e["core wc " + k] = FamilyInstance(d, "OST_PlumbingFixtures", "WC", INT)
            e["core " + k] = Group(d, core_t, [p, dr, wc], ARC)
        # group type 'Store' placed twice; only G3's wall is on Demolition
        store_t = e["Store"] = GroupType(d, "Store")
        e["store wall 3"] = Element(d, "OST_Walls", "Store partition", DEMO)
        e["store shelf 3"] = FamilyInstance(d, "OST_Furniture", "Shelf", INT)
        e["store 3"] = Group(d, store_t, [e["store wall 3"], e["store shelf 3"]], ARC)
        e["store wall 4"] = Element(d, "OST_Walls", "Store partition", ARC)
        e["store shelf 4"] = FamilyInstance(d, "OST_Furniture", "Shelf", INT)
        e["store 4"] = Group(d, store_t, [e["store wall 4"], e["store shelf 4"]], ARC)
        # 'Apartment' holds a nested 'Bath Pod'; a second 'Bath Pod' stands alone. Each pod's basin is REMOVE
        pod_t = e["Bath Pod"] = GroupType(d, "Bath Pod")
        for k in ("6", "7"):
            b1 = e["basin " + k] = FamilyInstance(d, "OST_PlumbingFixtures", "Basin", INT, "REMOVE")
            b2 = e["bath " + k] = FamilyInstance(d, "OST_PlumbingFixtures", "Bath", INT)
            e["pod " + k] = Group(d, pod_t, [b1, b2], ARC)
        apt_t = e["Apartment"] = GroupType(d, "Apartment")
        e["apt wall"] = Element(d, "OST_Walls", "Apartment Wall 150", ARC)
        e["apt 5"] = Group(d, apt_t, [e["apt wall"], e["pod 6"]], ARC)

        # filters
        e["To Remove"] = ParameterFilterElement(d, "To Remove", ["OST_Walls", "OST_Doors", "OST_PlumbingFixtures"],
                                                CommentsRule("REMOVE"))
        e["All Walls"] = ParameterFilterElement(d, "All Walls", ["OST_Walls"])
        e["Pick list"] = SelectionFilterElement(d, "Pick list", [e["store 4"], e["store wall 4"], e["sofa"],
                                                                 e["L02"]])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = "http://127.0.0.1:%d/revit_mcp/execute_code/" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def run(self, code):
        out = []
        ns = {"doc": self.doc, "uidoc": None, "__builtins__": builtins,
              "print": lambda *a: out.append(" ".join(str(x) for x in a) + "\n")}
        try:
            exec(compile(code, "<revit>", "exec"), ns)
            return 200, {"status": "success", "output": "".join(out) or "Code executed successfully (no output)"}
        except Exception as e:
            return 500, {"status": "error", "error": "%s: %s" % (type(e).__name__, e),
                         "partial_output": "".join(out)}

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                code = json.loads(body.decode("utf-8"))["code"]
                with fake.lock:
                    fake.calls += 1
                    if fake.paused:
                        status, data = 503, {"status": "paused", "error": "Revit MCP has been manually stopped"}
                    else:
                        status, data = fake.run(code)
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return H

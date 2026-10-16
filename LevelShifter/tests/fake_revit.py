"""A stand-in for Revit + the pyRevit MCP listener, for tests (no Revit needed).

Serves POST /revit_mcp/execute_code/ like the real route and runs the posted payload with
``doc`` bound to the active document. The Revit API pieces the payload imports are stubbed
with Revit's behaviour where it matters:

* each element's geometry (bounding box Z) is computed from its level's elevation plus its
  offsets, the way Revit regenerates it: a wall from base level + base offset to top level +
  top offset, a door from its level + sill height, a face-hosted fixture from its host floor,
  a pipe fitting from its pipe, a group member from the group origin, ...;
* every change outside a Transaction raises, as in Revit; Transaction / TransactionGroup
  roll back to a snapshot; commit runs the failures preprocessor (warnings, errors) and
  refuses elements borrowed by another user.

Units are feet, as in the Revit API.
"""

import builtins
import copy
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def mm(v):
    return v / 304.8


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


class _Names(object):
    """BuiltInParameter: every name exists and is its own key."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return name


class _Categories(object):
    """BuiltInCategory: every name maps to a stable negative int, like the real enum."""

    def __init__(self):
        self.__dict__["_ids"] = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._ids.setdefault(name, -2000000 - len(self._ids))


BuiltInParameter = _Names()
BuiltInCategory = _Categories()


class _Enum(object):
    def __init__(self, *names):
        for n in names:
            setattr(self, n, n)


StorageType = _Enum("Double", "ElementId", "Integer", "String")
CategoryType = _Enum("Model", "Annotation", "AnalyticalModel")
FailureSeverity = _Enum("Warning", "Error")
FailureProcessingResult = _Enum("Continue", "ProceedWithRollBack")
TransactionStatus = _Enum("Committed", "RolledBack")
CheckoutStatus = _Enum("OwnedByOtherUser", "OwnedByCurrentUser", "NotOwned")


class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class BoundingBoxXYZ(object):
    def __init__(self, z0, z1):
        self.Min, self.Max = XYZ(0, 0, z0), XYZ(1, 1, z1)


class Category(object):
    def __init__(self, bic, name, kind="Model"):
        self.Id = ElementId(getattr(BuiltInCategory, bic))
        self.Name, self.CategoryType = name, kind


class Definition(object):
    def __init__(self, name):
        self.Name = name


class Parameter(object):
    def __init__(self, el, key):
        self.el, self.key = el, key
        self.StorageType = el.p[key][0]
        self.IsReadOnly = key in el.readonly
        self.Definition = Definition(key)

    def AsDouble(self):
        return float(self.el.p[self.key][1])

    def AsInteger(self):
        return int(self.el.p[self.key][1])

    def AsElementId(self):
        return ElementId(self.el.p[self.key][1])

    def Set(self, value):
        if self.IsReadOnly:
            raise Exception("parameter %s is read-only" % self.key)
        self.el.doc.touch(self.el)
        self.el.p[self.key][1] = value.Value if isinstance(value, ElementId) else value
        return True


class Element(object):
    def __init__(self, doc, cat, name, params=None, readonly=(), level=None, zfn=None):
        self.doc = doc
        self.Id = ElementId(doc.new_id())
        self.Category = doc.category(cat) if cat else None
        self.Name = name
        self.p = {}
        for key, val in (params or {}).items():
            if isinstance(val, Element) or val is None:     # a level reference; None = unconnected
                self.p[key] = [StorageType.ElementId, val.Id.Value if val is not None else -1]
            elif isinstance(val, int) and not isinstance(val, bool):
                self.p[key] = [StorageType.Integer, val]
            else:
                self.p[key] = [StorageType.Double, float(val)]
        self.readonly = set(readonly)
        self.LevelId = level.Id if level is not None else INVALID
        self.GroupId = INVALID
        self.Pinned = False
        self.IsValidObject = True
        self.free = 0.0                     # what MoveElement added
        self.zfn = zfn
        doc.add(self)

    def get_Parameter(self, bip):
        return Parameter(self, bip) if bip in self.p else None

    def v(self, key):
        return self.p[key][1]

    def lvl(self, key):
        """Elevation of the level a parameter points at (None for an invalid id)."""
        lid = self.p[key][1]
        return self.doc.by_id[lid].Elevation if lid > 0 else None

    def z(self):
        if self.zfn is None:
            return None
        z0, z1 = self.zfn(self)
        return z0 + self.free, z1 + self.free

    def get_BoundingBox(self, view):
        z = self.z()
        return BoundingBoxXYZ(*z) if z else None

    def GetTypeId(self):
        return INVALID


class ElementType(Element):
    pass


class Level(Element):
    def __init__(self, doc, name, elev, level_type):
        super().__init__(doc, "OST_Levels", name, {"LEVEL_ELEV": float(elev)})
        self.type_id = level_type.Id

    @property
    def Elevation(self):
        return self.p["LEVEL_ELEV"][1]

    @Elevation.setter
    def Elevation(self, value):
        self.doc.touch(self)
        self.p["LEVEL_ELEV"][1] = float(value)

    @property
    def ProjectElevation(self):
        return self.Elevation

    def GetTypeId(self):
        return self.type_id

    def IsMonitoringLinkElement(self):
        return False

    def IsMonitoringLocalElement(self):
        return False


class FamilyInstance(Element):
    def __init__(self, doc, cat, name, params=None, readonly=(), level=None, zfn=None, host=None, mep_run=None):
        super().__init__(doc, cat, name, params, readonly, level, zfn)
        self.Host = host
        self.Symbol = "symbol"
        self.SuperComponent = None
        self.MEPModel = MEPModel(self, mep_run) if mep_run is not None else None


class Group(Element):
    pass


class _Conn(object):
    def __init__(self, owner, refs=()):
        self.Owner, self.AllRefs = owner, list(refs)


class MEPModel(object):
    def __init__(self, owner, run):
        self.ConnectorManager = types.SimpleNamespace(Connectors=[_Conn(owner, [_Conn(run), _Conn(owner)])])


class Collector(object):
    def __init__(self, doc):
        self.items = list(doc.by_id.values())

    def OfClass(self, cls):
        self.items = [e for e in self.items if isinstance(e, cls)]
        return self

    def WhereElementIsNotElementType(self):
        self.items = [e for e in self.items if not isinstance(e, ElementType)]
        return self

    def WhereElementIsViewIndependent(self):
        return self

    def ToElements(self):
        return list(self.items)

    def __iter__(self):
        return iter(list(self.items))


class IFailuresPreprocessor(object):
    pass


class _Failure(object):
    def __init__(self, severity, text):
        self.severity, self.text = severity, text

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
        self.doc.log.append(self.name)
        fails = [_Failure(FailureSeverity.Warning, t) for t in doc.commit_warnings]
        fails += [_Failure(FailureSeverity.Error, t) for t in doc.commit_errors]
        for i in sorted(doc.touched):
            if i in doc.owners:
                fails.append(_Failure(FailureSeverity.Error, "Can't edit the element until '%s' saves changes "
                                      "to central and relinquishes it" % doc.owners[i]))
        for el in doc.by_id.values():
            z = el.z()
            if z and z[1] < z[0] - 1e-9:
                fails.append(_Failure(FailureSeverity.Error, "%s %s: top is below base" % (el.Name, el.Id.Value)))
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


class ElementTransformUtils(object):
    @staticmethod
    def MoveElement(doc, eid, xyz):
        el = doc.GetElement(eid)
        if el.GroupId.Value > 0:
            raise Exception("can't move a group member")
        doc.touch(el)
        el.free += xyz.Z


class WorksharingUtils(object):
    @staticmethod
    def GetCheckoutStatus(doc, eid):
        return CheckoutStatus.OwnedByOtherUser if eid.Value in doc.owners else CheckoutStatus.OwnedByCurrentUser

    @staticmethod
    def GetWorksharingTooltipInfo(doc, eid):
        return types.SimpleNamespace(Owner=doc.owners.get(eid.Value, ""))


def install_stubs():
    db = types.ModuleType("Autodesk.Revit.DB")
    for name in ("BuiltInCategory", "BuiltInParameter", "CategoryType", "ElementTransformUtils",
                 "FailureProcessingResult", "FailureSeverity", "IFailuresPreprocessor", "Level",
                 "StorageType", "Transaction", "TransactionGroup", "TransactionStatus", "WorksharingUtils",
                 "CheckoutStatus", "XYZ", "ElementId"):
        setattr(db, name, globals()[name])
    db.FilteredElementCollector = Collector
    revit_mod = types.ModuleType("Autodesk.Revit")
    revit_mod.DB = db
    autodesk = types.ModuleType("Autodesk")
    autodesk.Revit = revit_mod
    sys.modules.update({"Autodesk": autodesk, "Autodesk.Revit": revit_mod, "Autodesk.Revit.DB": db})
    return db


# ------------------------------------------------------------ the model

class Doc(object):
    def __init__(self, title, app):
        self.Title, self.Application = title, app
        self.PathName = r"C:\Revit_Local\%s.rvt" % title
        self.IsLinked = self.IsFamilyDocument = self.IsReadOnly = False
        self.IsWorkshared = True
        self.by_id = {}
        self._next = 300000
        self._cats = {}
        self.tx = None
        self.touched = set()
        self.owners = {}            # element id -> user who borrowed it
        self.commit_warnings, self.commit_errors = [], []
        self.log, self.groups = [], []
        app.Documents.append(self)

    def new_id(self):
        self._next += 1
        return self._next

    def category(self, bic):
        if bic not in self._cats:
            name = bic[4:].replace("_", " ")
            kind = "Annotation" if bic in ("OST_TextNotes",) else "Model"
            self._cats[bic] = Category(bic, name, kind)
        return self._cats[bic]

    def add(self, el):
        self.by_id[el.Id.Value] = el

    def GetElement(self, eid):
        return self.by_id.get(eid.Value)

    def touch(self, el):
        if self.tx is None:
            raise Exception("Attempt to modify the model outside of transaction.")
        self.touched.add(el.Id.Value)

    def Regenerate(self):
        pass

    def snapshot(self):
        return dict((i, (copy.deepcopy(e.p), e.free)) for i, e in self.by_id.items())

    def restore(self, snap):
        for i, (p, free) in snap.items():
            self.by_id[i].p, self.by_id[i].free = copy.deepcopy(p), free

    def geometry(self):
        """{element id: (z min, z max)} for everything that has geometry."""
        return dict((i, e.z()) for i, e in self.by_id.items() if e.z() is not None and not isinstance(e, Level))


class FakeRevit(object):
    def __init__(self, extra=()):
        install_stubs()
        self.app = types.SimpleNamespace(Documents=[])
        self.paused = False
        self.stale_calls = set()
        self.calls = 0
        self._last_output = ""
        self.lock = threading.Lock()
        d = self.doc = Doc("ProjectF-Studio-BIM-T00O-ZZZ-BM-950001_user", self.app)
        lt = ElementType(d, None, "Level Type", {"LEVEL_RELATIVE_BASE_TYPE": 0})
        self.lv = {}
        for name, elev in (("B1", -4000), ("L00 GF", 0), ("L01", 3500), ("L02", 7000), ("L03", 10500),
                           ("Roof", 14000)):
            self.lv[name] = Level(d, name, mm(elev), lt)
        L = self.lv
        e = self.el = {}

        def wall_z(w):
            base = w.lvl("WALL_BASE_CONSTRAINT") + w.v("WALL_BASE_OFFSET")
            top = (w.lvl("WALL_HEIGHT_TYPE") + w.v("WALL_TOP_OFFSET")) if w.v("WALL_HEIGHT_TYPE") > 0 \
                else base + w.v("WALL_USER_HEIGHT_PARAM")
            return base, top

        def wall(name, base, top=None, height=3000.0, level=None):
            return Element(d, "OST_Walls", name, {"WALL_BASE_CONSTRAINT": base, "WALL_BASE_OFFSET": 0.0,
                                                  "WALL_HEIGHT_TYPE": top, "WALL_TOP_OFFSET": 0.0,
                                                  "WALL_USER_HEIGHT_PARAM": mm(height)},
                           level=base, zfn=wall_z)

        e["wall L01-L02"] = wall("Basic Wall 200", L["L01"], L["L02"])
        e["wall L01 unconnected"] = wall("Basic Wall 100", L["L01"], height=2400)
        e["wall L00-L01"] = wall("Basic Wall 300", L["L00 GF"], L["L01"])
        e["wall L03-Roof"] = wall("Basic Wall 200", L["L03"], L["Roof"])        # untouched levels
        e["floor L02"] = Element(d, "OST_Floors", "Slab 300", {"LEVEL_PARAM": L["L02"],
                                                                 "FLOOR_HEIGHTABOVELEVEL_PARAM": 0.0},
                                 level=L["L02"], zfn=lambda f: (f.lvl("LEVEL_PARAM") + f.v(
                                     "FLOOR_HEIGHTABOVELEVEL_PARAM") - mm(300),
                                     f.lvl("LEVEL_PARAM") + f.v("FLOOR_HEIGHTABOVELEVEL_PARAM")))
        e["ceiling L01"] = Element(d, "OST_Ceilings", "Ceiling 600x600", {
            "LEVEL_PARAM": L["L01"], "CEILING_HEIGHTABOVELEVEL_PARAM": mm(2700)}, level=L["L01"],
            zfn=lambda c: (c.lvl("LEVEL_PARAM") + c.v("CEILING_HEIGHTABOVELEVEL_PARAM"),
                           c.lvl("LEVEL_PARAM") + c.v("CEILING_HEIGHTABOVELEVEL_PARAM") + mm(20)))
        # a door in the L01-L02 wall: sill measured from its level
        e["door"] = FamilyInstance(d, "OST_Doors", "Single Flush 900x2100", {"INSTANCE_SILL_HEIGHT_PARAM": 0.0},
                                   level=L["L01"], host=e["wall L01-L02"],
                                   zfn=lambda x: (L["L01"].Elevation + x.v("INSTANCE_SILL_HEIGHT_PARAM"),
                                                  L["L01"].Elevation + x.v("INSTANCE_SILL_HEIGHT_PARAM") + mm(2100)))
        # level-based furniture
        e["desk"] = FamilyInstance(d, "OST_Furniture", "Desk 1600", {"INSTANCE_ELEVATION_PARAM": 0.0},
                                   level=L["L01"],
                                   zfn=lambda x: (x.lvl_of() + x.v("INSTANCE_ELEVATION_PARAM"),
                                                  x.lvl_of() + x.v("INSTANCE_ELEVATION_PARAM") + mm(750)))
        # face-hosted on the L02 slab: follows the slab, its 'level' is only a schedule level
        e["light"] = FamilyInstance(d, "OST_LightingFixtures", "Downlight", {"INSTANCE_FREE_HOST_OFFSET_PARAM": 0.0},
                                    level=L["L02"], host=e["floor L02"],
                                    zfn=lambda x: (e["floor L02"].z()[1] + x.v("INSTANCE_FREE_HOST_OFFSET_PARAM"),
                                                   e["floor L02"].z()[1] + x.v("INSTANCE_FREE_HOST_OFFSET_PARAM")
                                                   + mm(100)))
        e["column"] = FamilyInstance(d, "OST_StructuralColumns", "C 600x600", {
            "FAMILY_BASE_LEVEL_PARAM": L["L01"], "FAMILY_BASE_LEVEL_OFFSET_PARAM": 0.0,
            "FAMILY_TOP_LEVEL_PARAM": L["L02"], "FAMILY_TOP_LEVEL_OFFSET_PARAM": 0.0}, level=L["L01"],
            zfn=lambda c: (c.lvl("FAMILY_BASE_LEVEL_PARAM") + c.v("FAMILY_BASE_LEVEL_OFFSET_PARAM"),
                           c.lvl("FAMILY_TOP_LEVEL_PARAM") + c.v("FAMILY_TOP_LEVEL_OFFSET_PARAM")))
        e["beam"] = FamilyInstance(d, "OST_StructuralFraming", "B 300x600", {
            "INSTANCE_REFERENCE_LEVEL_PARAM": L["L02"], "STRUCTURAL_BEAM_END0_ELEVATION": 0.0,
            "STRUCTURAL_BEAM_END1_ELEVATION": 0.0}, level=L["L02"],
            zfn=lambda b: (b.lvl("INSTANCE_REFERENCE_LEVEL_PARAM") + min(
                b.v("STRUCTURAL_BEAM_END0_ELEVATION"), b.v("STRUCTURAL_BEAM_END1_ELEVATION")) - mm(600),
                b.lvl("INSTANCE_REFERENCE_LEVEL_PARAM") + max(
                b.v("STRUCTURAL_BEAM_END0_ELEVATION"), b.v("STRUCTURAL_BEAM_END1_ELEVATION"))))
        e["stair"] = Element(d, "OST_Stairs", "Stair 1200", {
            "STAIRS_BASE_LEVEL_PARAM": L["L00 GF"], "STAIRS_BASE_OFFSET": 0.0,
            "STAIRS_TOP_LEVEL_PARAM": L["L01"], "STAIRS_TOP_OFFSET": 0.0}, level=L["L00 GF"],
            zfn=lambda s: (s.lvl("STAIRS_BASE_LEVEL_PARAM") + s.v("STAIRS_BASE_OFFSET"),
                           s.lvl("STAIRS_TOP_LEVEL_PARAM") + s.v("STAIRS_TOP_OFFSET")))
        e["room"] = Element(d, "OST_Rooms", "Office 101", {
            "ROOM_LEVEL_ID": L["L01"], "ROOM_LOWER_OFFSET": 0.0, "ROOM_UPPER_LEVEL": L["L02"],
            "ROOM_UPPER_OFFSET": 0.0}, readonly=("ROOM_LEVEL_ID",), level=L["L01"],
            zfn=lambda r: (r.lvl("ROOM_LEVEL_ID") + r.v("ROOM_LOWER_OFFSET"),
                           r.lvl("ROOM_UPPER_LEVEL") + r.v("ROOM_UPPER_OFFSET")))
        e["pipe"] = Element(d, "OST_PipeCurves", "Pipe 100", {"RBS_START_LEVEL_PARAM": L["L01"],
                                                              "RBS_OFFSET_PARAM": mm(2800)}, level=L["L01"],
                            zfn=lambda p: (p.lvl("RBS_START_LEVEL_PARAM") + p.v("RBS_OFFSET_PARAM") - mm(50),
                                           p.lvl("RBS_START_LEVEL_PARAM") + p.v("RBS_OFFSET_PARAM") + mm(50)))
        # an elbow follows its pipe; its own 'Elevation from Level' must not be touched
        e["elbow"] = FamilyInstance(d, "OST_PipeFitting", "Elbow 100", {"INSTANCE_ELEVATION_PARAM": mm(2800)},
                                    level=L["L01"], mep_run=e["pipe"],
                                    zfn=lambda x: e["pipe"].z())
        # model group on L01: members follow the group origin
        grp = e["group"] = Group(d, "OST_IOSModelGroups", "Toilet Core", {"GROUP_LEVEL": L["L01"],
                                                                          "GROUP_OFFSET_FROM_LEVEL": 0.0},
                                 level=L["L01"], zfn=lambda g: (g.lvl("GROUP_LEVEL") + g.v("GROUP_OFFSET_FROM_LEVEL"),
                                                                g.lvl("GROUP_LEVEL") + g.v("GROUP_OFFSET_FROM_LEVEL")
                                                                + mm(2400)))
        member = e["group member"] = Element(d, "OST_Walls", "Partition 100", {
            "WALL_BASE_CONSTRAINT": L["L01"], "WALL_BASE_OFFSET": 0.0, "WALL_HEIGHT_TYPE": None,
            "WALL_TOP_OFFSET": 0.0, "WALL_USER_HEIGHT_PARAM": mm(2400)}, level=L["L01"],
            zfn=lambda m: (grp.z()[0], grp.z()[0] + mm(2400)))
        member.GroupId = grp.Id
        # in-place / generic family with no offset parameter at all: only a move can keep it in place
        e["generic"] = FamilyInstance(d, "OST_GenericModel", "In-place plinth", {}, level=L["L01"],
                                      zfn=lambda x: (L["L01"].Elevation + mm(1000), L["L01"].Elevation + mm(1200)))
        e["text"] = Element(d, "OST_TextNotes", "note", {}, level=None, zfn=None)
        if "sloped" in extra:
            # slope arrow from L01 (tail) to L03 (head): changes shape when L01 moves -- cannot be kept
            e["sloped"] = Element(d, "OST_Roofs", "Sloped roof", {"SLOPE_TAIL_LEVEL": L["L01"]}, level=None,
                                  zfn=lambda r: (L["L01"].Elevation, L["L03"].Elevation))
        for x in list(d.by_id.values()):
            x.lvl_of = (lambda el: lambda: d.by_id[el.LevelId.Value].Elevation)(x)

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
                    idx = fake.calls
                    fake.calls += 1
                    if fake.paused:
                        status, data = 503, {"status": "paused", "error": "Revit MCP has been manually stopped"}
                    else:
                        status, data = fake.run(code)
                        if idx in fake.stale_calls:
                            status, data = 200, {"status": "success", "output": fake._last_output}
                        else:
                            fake._last_output = data.get("output") or data.get("partial_output") or ""
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return H

"""A stand-in Revit model for Model Prep: user worksets, link types + instances, other elements, transactions.

Behaves like Revit where Model Prep depends on it: changes outside a Transaction raise, Transaction /
TransactionGroup roll back to a snapshot, workset names are unique, a deleted link type takes its instances with it,
ELEM_PARTITION_PARAM moves an element to another workset, a group's Assimilate leaves one Undo entry.
install() puts it in sys.modules as Autodesk.Revit.DB (model_prep.revit imports it on use).
"""

import copy
import sys
import types


class Id(object):
    def __init__(self, n):
        self.Value = self.IntegerValue = int(n)

    def __eq__(self, other):
        return isinstance(other, Id) and other.Value == self.Value

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.Value)


class _Names(object):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return name


BuiltInParameter = _Names()
WorksetKind = types.SimpleNamespace(UserWorkset="UserWorkset")
TransactionStatus = types.SimpleNamespace(Committed="Committed", RolledBack="RolledBack")
CheckoutStatus = types.SimpleNamespace(OwnedByOtherUser="OwnedByOtherUser", OwnedByCurrentUser="OwnedByCurrentUser")
DeleteWorksetOption = types.SimpleNamespace(DeleteAllElements="DeleteAllElements")


class WorksetId(Id):
    pass


WorksetId.InvalidWorksetId = WorksetId(-1)


class Workset(object):
    def __init__(self, n, name):
        self.Id, self.Name = WorksetId(n), name

    @staticmethod
    def Create(doc, name):
        doc.need_tx()
        if name in [w.Name for w in doc.worksets]:
            raise ValueError("workset name in use: %s" % name)
        doc.next_ws += 1
        w = Workset(doc.next_ws, name)
        doc.worksets.append(w)
        return w


class Param(object):
    def __init__(self, el, bip):
        self.el, self.bip = el, bip
        self.IsReadOnly = bip != "ELEM_PARTITION_PARAM" or el.ws_locked

    def AsString(self):
        return self.el.type_name

    def Set(self, value):
        self.el.doc.need_tx()
        if value not in [w.Id.Value for w in self.el.doc.worksets]:
            raise ValueError("no such workset %s" % value)
        self.el.ws = value


class Element(object):
    def __init__(self, doc, ws):
        doc.next_id += 1
        self.doc, self.Id, self.ws = doc, Id(doc.next_id), ws
        self.type_name, self.ws_locked = None, False
        doc.elements[self.Id.Value] = self

    @property
    def WorksetId(self):
        return WorksetId(self.ws)

    def get_Parameter(self, bip):
        if bip == "ALL_MODEL_TYPE_NAME" and self.type_name is None:
            return None
        return Param(self, bip)


class RevitLinkType(Element):
    def __init__(self, doc, ws, name, nested=False):
        Element.__init__(self, doc, ws)
        self.type_name, self.IsNestedLink = name, nested


class RevitLinkInstance(Element):
    def __init__(self, doc, ws, link_type):
        Element.__init__(self, doc, ws)
        self.type_id = link_type.Id

    def GetTypeId(self):
        return self.type_id


class ElementWorksetFilter(object):
    def __init__(self, wid, inverted=False):
        self.wid = wid.Value


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.doc, self.items = doc, list(doc.elements.values())

    def OfClass(self, cls):
        self.items = [e for e in self.items if type(e) is cls]
        return self

    def WherePasses(self, f):
        self.items = [e for e in self.items if e.ws == f.wid]
        return self

    def ToElements(self):
        return list(self.items)

    def GetElementCount(self):
        return len(self.items)


class FilteredWorksetCollector(object):
    def __init__(self, doc):
        self.doc = doc

    def OfKind(self, kind):
        return self

    def ToWorksets(self):
        return list(self.doc.worksets)


class DeleteWorksetSettings(object):
    def __init__(self, option, move_to):
        self.option, self.move_to = option, move_to


class WorksetTable(object):
    @staticmethod
    def RenameWorkset(doc, wid, name):
        doc.need_tx()
        if name in [w.Name for w in doc.worksets]:
            raise ValueError("workset name in use: %s" % name)
        [w for w in doc.worksets if w.Id == wid][0].Name = name

    @staticmethod
    def DeleteWorkset(doc, wid, settings):
        doc.need_tx()
        doc.worksets = [w for w in doc.worksets if w.Id != wid]
        for eid in [k for k, e in doc.elements.items() if e.ws == wid.Value]:
            del doc.elements[eid]


class WorksharingUtils(object):
    @staticmethod
    def GetCheckoutStatus(doc, eid):
        return CheckoutStatus.OwnedByOtherUser if eid.Value in doc.owners else CheckoutStatus.OwnedByCurrentUser

    @staticmethod
    def GetWorksharingTooltipInfo(doc, eid):
        return types.SimpleNamespace(Owner=doc.owners.get(eid.Value, ""))


class _Tx(object):
    def __init__(self, doc, name):
        self.doc, self.name, self.state = doc, name, None

    def Start(self):
        self.saved = self.doc.save()
        self.state = "started"

    def HasStarted(self):
        return self.state is not None

    def HasEnded(self):
        return self.state in ("committed", "rolled back")

    def RollBack(self):
        self.doc.restore(self.saved)
        self.state = "rolled back"


class Transaction(_Tx):
    def Start(self):
        assert self.doc.tx is None, "a transaction is already open"
        _Tx.Start(self)
        self.doc.tx = self

    def Commit(self):
        self.doc.tx = None
        self.state = "committed"
        if self.doc.fail_on == self.name:
            self.doc.restore(self.saved)
            return TransactionStatus.RolledBack
        return TransactionStatus.Committed

    def RollBack(self):
        self.doc.tx = None
        _Tx.RollBack(self)


class TransactionGroup(_Tx):
    def Assimilate(self):
        assert self.doc.tx is None, "a transaction is still open"
        self.state = "committed"
        self.doc.undo.append(self.name)

    def RollBack(self):
        assert self.doc.tx is None, "a transaction is still open"
        _Tx.RollBack(self)


class Doc(object):
    def __init__(self, title):
        self.Title = title
        self.IsFamilyDocument = self.IsReadOnly = False
        self.IsWorkshared = True
        self.worksets, self.elements, self.owners = [], {}, {}
        self.next_ws, self.next_id = 100, 1000
        self.tx, self.undo, self.fail_on = None, [], None

    def need_tx(self):
        if self.tx is None:
            raise RuntimeError("Modifying the document outside a transaction")

    def Delete(self, eid):
        self.need_tx()
        el = self.elements.pop(eid.Value)
        if isinstance(el, RevitLinkType):
            for k in [k for k, e in self.elements.items() if getattr(e, "type_id", None) == el.Id]:
                del self.elements[k]

    def GetElement(self, eid):
        return self.elements.get(eid.Value)

    def save(self):
        return ([(w, w.Name) for w in self.worksets], dict(self.elements),
                dict((k, e.ws) for k, e in self.elements.items()))

    def restore(self, saved):
        worksets, elements, ws = saved
        self.worksets = [w for w, _ in worksets]
        for w, name in worksets:
            w.Name = name
        self.elements = dict(elements)
        for k, e in self.elements.items():
            e.ws = ws[k]

    # ---- building the model
    def workset(self, name):
        doc_tx, self.tx = self.tx, True
        try:
            return Workset.Create(self, name)
        finally:
            self.tx = doc_tx

    def ws(self, name):
        return [w for w in self.worksets if w.Name == name][0].Id.Value

    def link(self, name, ws_name, instances=1, inst_ws=None, nested=False):
        lt = RevitLinkType(self, self.ws(ws_name), name, nested)
        for _ in range(instances):
            RevitLinkInstance(self, self.ws(inst_ws or ws_name), lt)
        return lt

    def element_on(self, ws_name):
        return Element(self, self.ws(ws_name))

    def placed(self):
        """{link name: (type workset, [instance worksets])} by name."""
        names = dict((w.Id.Value, w.Name) for w in self.worksets)
        out = {}
        for e in self.elements.values():
            if isinstance(e, RevitLinkType):
                out[e.type_name] = (names[e.ws], sorted(names[i.ws] for i in self.elements.values()
                                                        if getattr(i, "type_id", None) == e.Id))
        return out

    def names(self):
        return [w.Name for w in self.worksets]


def install():
    db = types.ModuleType("Autodesk.Revit.DB")
    for name in ("BuiltInParameter", "WorksetKind", "TransactionStatus", "CheckoutStatus", "DeleteWorksetOption",
                 "WorksetId", "Workset", "RevitLinkType", "RevitLinkInstance", "ElementWorksetFilter",
                 "FilteredElementCollector", "FilteredWorksetCollector", "DeleteWorksetSettings", "WorksetTable",
                 "WorksharingUtils", "Transaction", "TransactionGroup"):
        setattr(db, name, globals()[name])
    db.ElementId = Id
    db.Element = Element
    revit_mod = types.ModuleType("Autodesk.Revit")
    revit_mod.DB = db
    autodesk = types.ModuleType("Autodesk")
    autodesk.Revit = revit_mod
    sys.modules.update({"Autodesk": autodesk, "Autodesk.Revit": revit_mod, "Autodesk.Revit.DB": db})
    return db


def b001_bm():
    """A B001 BM host the way the rollout found them: some links on the default workset, a Site-Wide Landscape link
    instead of B001's own, two look-alike worksets, a cross-building AR link, a stray Workset1."""
    doc = Doc("ProjectC-Studio-BIM-B001-ZZZ-BM-950001_user")
    for name in ("Studio_AR-Walls ", "Workset1", "Studio_AR-00 Link-EL", "Studio_AR-00 Link-PL", "Studio_AR-Wall Fixtures",
                 "Studio_AR-00 Link-STR", "Studio_AR-00 Link-FF", "Studio_AR-00 Link-MEC", "Studio_AR-00 Link-Podium Buildings",
                 "Studio_AR-00 Link-Core", "Studio_AR-00 Link-Levels ", "Studio_AR-ID Placeholder"):
        doc.workset(name)
    doc.link("ProjectC-Studio-BIM-B001-ZZZ-AR-900001.rvt", "Studio_AR-Walls ")             # own AR in a BM host
    doc.link("ProjectC-DEC-BIM-B001-ZZZ-ST-400001.rvt", "Studio_AR-00 Link-STR")        # already right
    doc.link("ProjectC-DEC-BIM-B001-ZZZ-EL-400001.rvt", "Studio_AR-00 Link-EL")         # -> Link-ELE (to create)
    doc.link("ProjectC-DEC-BIM-B001-ZZZ-PL-400001.rvt", "Studio_AR-00 Link-MEC", 2)     # wrong default, 2 instances
    doc.link("ProjectC-DEC-BIM-B001-ZZZ-FF-400001.rvt", "Studio_AR-00 Link-FF", 1, "Studio_AR-Walls ")  # instance off
    doc.link("ProjectC-DEC-BIM-B001-ZZZ-HV-400001.rvt", "Studio_AR-00 Link-MEC")
    doc.link("ProjectC-Studio-BIM-SW00-ZZZ-LA-300001.rvt", "Studio_AR-Walls ")             # WRONG SCOPE (site-wide LA)
    doc.link("ProjectC-Studio-BIM-SW00-ZZZ-BM-925001.rvt", "Studio_AR-Walls ")             # exact-file rule -> Levels
    doc.link("ProjectC-Studio-BIM-T00O-ZZZ-AR-900001.rvt", "Studio_AR-Walls ")             # building rule -> Core
    doc.link("ProjectC-Studio-BIM-TO-ZZZ-AR-900003.rvt", "Studio_AR-Walls ")               # Tower Tier 3
    doc.link("ProjectC-Studio-BIM-B005-ZZZ-AR-900001.rvt", "Studio_AR-Walls ")             # cross-building AR -> ask
    doc.link("Old survey.rvt", "Studio_AR-Walls ")                                    # no naming rule -> ask
    doc.link("ProjectC-Studio-BIM-B001-ZZZ-AR-900001.rvt nested", "Studio_AR-Walls ", nested=True)
    for _ in range(3):
        doc.element_on("Studio_AR-00 Link-EL")
    doc.element_on("Studio_AR-Wall Fixtures")
    return doc

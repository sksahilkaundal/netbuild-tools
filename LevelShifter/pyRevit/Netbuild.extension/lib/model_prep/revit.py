"""Model Prep inside Revit: read the links and worksets into a snapshot (core.py's input) and apply a plan
(IronPython 2.7 under pyRevit).

Apply runs one TransactionGroup named after the product -- one Undo entry, 'Model Prep by Netbuild' -- holding a
transaction per step; if any step fails the whole group is rolled back and the model is as it was.
A link's workset is two assignments: the RevitLinkType's and each RevitLinkInstance's (ELEM_PARTITION_PARAM).
"""

from . import about


def _db():
    from Autodesk.Revit import DB          # imported on use, so the tests can stand in for Revit
    return DB


def _int(an_id):
    """ElementId / WorksetId as int: .Value (Revit 2024+, only one in 2026), else .IntegerValue."""
    v = getattr(an_id, "Value", None)
    return int(v) if v is not None else int(an_id.IntegerValue)


def _owner(DB, doc, eid):
    """Who has the element borrowed, when it is someone else; "" otherwise (or not workshared)."""
    try:
        if DB.WorksharingUtils.GetCheckoutStatus(doc, eid) == DB.CheckoutStatus.OwnedByOtherUser:
            return DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, eid).Owner or "another user"
    except Exception:
        pass
    return ""


def link_name(DB, link_type):
    p = link_type.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
    name = p.AsString() if p is not None else None
    if not name:
        try:
            name = DB.Element.Name.GetValue(link_type)
        except Exception:
            name = getattr(link_type, "Name", "") or ""
    return name


def user_worksets(doc):
    DB = _db()
    return list(DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset).ToWorksets())


def snapshot(doc):
    """{"title", "worksets", "links"} as core.py describes; every link / instance also carries its element ("elem").
    Nested links (links inside a linked model) are left out: only the host's own links are placed."""
    DB = _db()
    worksets = [{"id": _int(w.Id), "name": w.Name} for w in user_worksets(doc)]
    by_type = {}
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance).ToElements():
        by_type.setdefault(_int(inst.GetTypeId()), []).append(
            {"id": _int(inst.Id), "ws": _int(inst.WorksetId), "owner": _owner(DB, doc, inst.Id), "elem": inst})
    links = []
    for lt in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType).ToElements():
        if getattr(lt, "IsNestedLink", False):
            continue
        links.append({"id": _int(lt.Id), "name": link_name(DB, lt), "ws": _int(lt.WorksetId),
                      "owner": _owner(DB, doc, lt.Id), "instances": by_type.get(_int(lt.Id), []), "elem": lt})
    links.sort(key=lambda l: l["name"])
    return {"title": doc.Title, "worksets": worksets, "links": links}


def count_elements(doc, name):
    """Elements on the user workset of that exact name (None if there is no such workset)."""
    DB = _db()
    for w in user_worksets(doc):
        if w.Name == name:
            return DB.FilteredElementCollector(doc).WherePasses(DB.ElementWorksetFilter(w.Id, False)).GetElementCount()
    return None


def _commit(DB, t, what):
    status = t.Commit()
    if status != DB.TransactionStatus.Committed:
        raise RuntimeError("%s was not committed by Revit (%s)" % (what, status))


def apply(doc, plan, log=None):
    """Make the plan's changes. Returns {"removed", "created", "renamed", "set", "skipped": [text]}; raises (after
    rolling everything back) when a step fails."""
    DB = _db()
    log = log if log is not None else []
    done = {"removed": 0, "created": 0, "renamed": 0, "set": 0, "skipped": []}
    tg = DB.TransactionGroup(doc, about.PRODUCT)
    tg.Start()
    t = None
    try:
        if plan["remove"]:
            t = DB.Transaction(doc, "Step 01: remove wrong-scope links")
            t.Start()
            for w in plan["remove"]:
                doc.Delete(w["link"]["elem"].Id)
                done["removed"] += 1
                log.append(u"removed link %s" % w["link"]["name"])
            _commit(DB, t, "Step 01")

        s2 = plan["step02"]
        if s2 and (s2["create"] or s2["renames"]):
            t = DB.Transaction(doc, "Step 02: create / rename worksets")
            t.Start()
            for name in s2["create"]:
                DB.Workset.Create(doc, name)
                done["created"] += 1
                log.append(u"created workset '%s'" % name)
            for r in s2["renames"]:
                by_name = dict((w.Name, w) for w in user_worksets(doc))
                if r["delete_new"]:
                    new = by_name[r["new"]]
                    n = DB.FilteredElementCollector(doc).WherePasses(
                        DB.ElementWorksetFilter(new.Id, False)).GetElementCount()
                    if n:
                        raise RuntimeError("'%s' holds %d element(s) -- not merged" % (r["new"], n))
                    if not hasattr(DB.WorksetTable, "DeleteWorkset"):
                        raise RuntimeError("merging into an existing workset needs Revit 2022 or later")
                    settings = DB.DeleteWorksetSettings(DB.DeleteWorksetOption.DeleteAllElements,
                                                        DB.WorksetId.InvalidWorksetId)
                    DB.WorksetTable.DeleteWorkset(doc, new.Id, settings)
                DB.WorksetTable.RenameWorkset(doc, by_name[r["old"]].Id, r["new"])
                done["renamed"] += 1
                log.append(u"renamed workset '%s' -> '%s'" % (r["old"], r["new"]))
            _commit(DB, t, "Step 02")

        moves = [r for r in (plan["step03"] or []) if r["status"] == "MOVE"]
        if moves:
            by_name = dict((w.Name, w) for w in user_worksets(doc))
            t = DB.Transaction(doc, "Step 03: link worksets")
            t.Start()
            for r in moves:
                target = by_name[r["target"]]
                wid = _int(target.Id)
                for el in [r["link"]["elem"]] + [i["elem"] for i in r["link"]["instances"]]:
                    if _int(el.WorksetId) == wid:
                        continue
                    p = el.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                    if p is None or p.IsReadOnly:
                        done["skipped"].append(u"%s: workset is read-only on element %d" % (r["name"], _int(el.Id)))
                        continue
                    p.Set(wid)
                    done["set"] += 1
                log.append(u"placed %s on '%s'" % (r["name"], r["target"]))
            _commit(DB, t, "Step 03")
        tg.Assimilate()
    except Exception:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
        raise
    return done


def model_problem(doc):
    """Why Model Prep cannot work on this document, or None."""
    if doc is None or doc.IsFamilyDocument:
        return "Open a project model first."
    if not doc.IsWorkshared:
        return "%s is not workshared -- Model Prep places links on worksets." % doc.Title
    if doc.IsReadOnly:
        return "%s is read-only -- open it editable (a local copy) to prepare it." % doc.Title
    return None

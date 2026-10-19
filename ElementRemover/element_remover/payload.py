"""The code that runs inside Revit (IronPython 2.7 under pyRevit; also CPython 3 in the tests).

It is sent through the MCP listener by the exe, or run in-process by the pyRevit "Element Remover"
button (core.run_local), which sets ``_ER_SINK`` to receive the results instead of printed lines.

One payload serves every action; ``_ER`` (a literal dict prepended per call) says which:

* ``sources`` -- list what can be targeted: user worksets (open / closed, element count), view filters
                 (rule-based and saved selection) with their categories, and the model categories in use.
* ``plan``    -- resolve the targets: the elements on the chosen worksets and / or passing the chosen
                 filters, restricted to the chosen categories.  Report what will be removed, what is
                 skipped and why (pinned, protected, nested, inside a group with the option off), the
                 group instances that must be ungrouped, and anything that blocks it (element borrowed
                 by another user).  Nothing is changed.
* ``trial``   -- do the whole removal inside a TransactionGroup, check every target is gone, then ROLL
                 BACK.  The model is left exactly as it was.
* ``apply``   -- the same, then Assimilate (one Undo entry: "Element Remover by Netbuild").

How elements inside model groups are removed
--------------------------------------------
Revit does not let a member be deleted from one group instance on its own (the instances of a type
must stay identical).  So every group instance that holds a target is ungrouped (outermost first, for
nested groups), the targets are deleted, and the remaining members are regrouped (innermost first).
The new group type keeps the original name when no other instance of the old type is left (the old
type is deleted; several regrouped instances become "<name>", "<name> (2)", ... in Element Id order);
otherwise it is named "<name> (elements removed)".  Member Element Ids do not change.

What Revit deletes with a target (hosted doors / windows, tags, dimensions, sketches, ...) is found by
deleting once in a probe transaction that is rolled back, so every deleted element is reported by Id.
"""

CODE = r'''
import json as _er_json
from Autodesk.Revit.DB import (BuiltInCategory, Category, CategoryType, ElementId, ElementMulticategoryFilter,
                               ElementType, ElementWorksetFilter, FailureProcessingResult, FailureSeverity,
                               FilteredElementCollector, FilteredWorksetCollector, Group, IFailuresPreprocessor,
                               ParameterFilterElement, SelectionFilterElement, Transaction, TransactionGroup,
                               TransactionStatus, View, WorksetKind, WorksharingUtils, CheckoutStatus)
from System.Collections.Generic import List


def _emit(tag, data):
    sink = globals().get("_ER_SINK")       # set when a pyRevit button runs the engine in-process
    if sink is not None:
        sink(tag, data)
    else:
        print("@@ER-%s:%s@@ %s" % (tag, _ER["nonce"], _er_json.dumps(data)))


def _iid(eid):
    if eid is None:
        return -1
    v = getattr(eid, "Value", None)      # Revit 2024+ (Int64); IntegerValue is gone in 2026
    if v is None:
        v = eid.IntegerValue
    return int(v)


def _txt(x):
    try:
        return u"%s" % x
    except Exception:
        return "?"


def _name(el):
    try:
        n = el.Name
    except Exception:
        n = ""
    return _txt(n)


def _pick_doc():
    try:
        active = doc
    except NameError:
        active = __revit__.ActiveUIDocument.Document
    want = [m.lower() for m in (_ER.get("match") or []) if m]
    if not want:
        d = active
    else:
        docs = [x for x in active.Application.Documents if not x.IsLinked and not x.IsFamilyDocument]
        hits = [x for x in docs if [w for w in want if w in x.Title.lower()]]
        if len(hits) != 1:
            raise Exception("ER: %d open model(s) match %s -- open models: %s"
                            % (len(hits), _ER.get("match"), [x.Title for x in docs]))
        d = hits[0]
    _emit("DOC", {"title": d.Title, "path": d.PathName, "readonly": bool(d.IsReadOnly),
                  "workshared": bool(d.IsWorkshared),
                  "active": d.Title == active.Title and d.PathName == active.PathName})
    return d


# never removed: datums, links, views and the elements Revit owns for them
_PROTECT_CATS = ("OST_Levels", "OST_Grids", "OST_RvtLinks", "OST_ProjectBasePoint", "OST_SharedBasePoint",
                 "OST_IOS_GeoSite", "OST_VolumeOfInterest", "OST_Cameras", "OST_Viewers", "OST_SectionBox",
                 "OST_Views", "OST_Sheets", "OST_Viewports", "OST_Matchline", "OST_CLines", "OST_SketchLines",
                 "OST_ProjectInformation")


def _cat_ids(names):
    out = set()
    for n in names:
        c = getattr(BuiltInCategory, n, None)
        if c is not None:
            try:
                out.add(int(c))
            except Exception:
                pass
    return out


_PROTECT = _cat_ids(_PROTECT_CATS)


def _cat_name(d, cid):
    try:
        return _txt(Category.GetCategory(d, cid).Name)
    except Exception:
        return "?"


def _ws_name(d, el):
    if not d.IsWorkshared:
        return ""
    try:
        return _txt(d.GetWorksetTable().GetWorkset(el.WorksetId).Name)
    except Exception:
        return ""


def _gid(el):
    return _iid(getattr(el, "GroupId", None))


def _chain(d, el):
    """The group instances above an element, innermost first."""
    out, seen = [], set()
    gid = getattr(el, "GroupId", None)
    while _iid(gid) > 0 and _iid(gid) not in seen:
        g = d.GetElement(gid)
        if g is None:
            break
        seen.add(_iid(gid))
        out.append(g)
        gid = getattr(g, "GroupId", None)
    return out


def _info(d, el, matched=None):
    cat = el.Category
    g = _chain(d, el)
    return {"id": _iid(el.Id), "category": _txt(cat.Name) if cat is not None else "", "name": _name(el),
            "workset": _ws_name(d, el), "group": ("%s (id %d)" % (_name(g[0]), _iid(g[0].Id))) if g else "",
            "matched": "; ".join(matched or []), "status": ""}


def _owner(d, eid):
    if not d.IsWorkshared:
        return None
    try:
        if WorksharingUtils.GetCheckoutStatus(d, eid) == CheckoutStatus.OwnedByOtherUser:
            try:
                return _txt(WorksharingUtils.GetWorksharingTooltipInfo(d, eid).Owner) or "another user"
            except Exception:
                return "another user"
    except Exception:
        pass
    return None


def _why_not(el, model_only, skip_pinned):
    """(summary, detail) of why a matched element is not removed, or None when it is removed."""
    if isinstance(el, ElementType):
        return "element type", "element type (only instances are removed)"
    if isinstance(el, View):
        return "view", "view (never removed)"
    if type(el).__name__ in ("Sketch", "SketchPlane"):
        return "sketch", "sketch (goes with the element it shapes)"
    cat = el.Category
    if cat is None:
        return "internal element", "internal element (no category)"
    if _iid(cat.Id) in _PROTECT:
        return "protected: " + _txt(cat.Name), "protected: %s (never removed)" % _txt(cat.Name)
    try:
        if el.SuperComponent is not None:
            return "nested in a family instance", "nested in family instance %d (goes with it)" % _iid(
                el.SuperComponent.Id)
    except Exception:
        pass
    if model_only:
        try:
            view_specific = bool(el.ViewSpecific)
        except Exception:
            view_specific = False
        if cat.CategoryType != CategoryType.Model or view_specific:
            return "annotation / view-specific", "annotation / view-specific (model elements only)"
    if skip_pinned and el.Pinned:
        return "pinned", "pinned (tick 'remove pinned elements too' to remove it)"
    return None


def _user_worksets(d):
    if not d.IsWorkshared:
        return []
    return list(FilteredWorksetCollector(d).OfKind(WorksetKind.UserWorkset))


def _filters(d):
    """{lower-case name: filter element} -- rule-based view filters and saved selection filters."""
    out = {}
    for cls in (ParameterFilterElement, SelectionFilterElement):
        for f in FilteredElementCollector(d).OfClass(cls):
            out[_name(f).strip().lower()] = f
    return out


def _filter_elements(d, f):
    if isinstance(f, SelectionFilterElement):
        return [x for x in (d.GetElement(i) for i in f.GetElementIds()) if x is not None]
    cats = list(f.GetCategories())
    if not cats:
        return []
    col = FilteredElementCollector(d).WherePasses(ElementMulticategoryFilter(List[ElementId](cats)))
    col = col.WhereElementIsNotElementType()
    try:
        rules = f.GetElementFilter()         # Revit 2019+; None = every element of the categories
    except Exception:
        rules = None
    if rules is not None:
        col = col.WherePasses(rules)
    return list(col)


def _sources(d):
    wss = []
    for ws in _user_worksets(d):
        n = FilteredElementCollector(d).WherePasses(ElementWorksetFilter(ws.Id, False))
        wss.append({"id": _iid(ws.Id), "name": _txt(ws.Name), "open": bool(ws.IsOpen),
                    "elements": n.WhereElementIsNotElementType().GetElementCount()})
    wss.sort(key=lambda r: r["name"].lower())
    flts = []
    for f in _filters(d).values():
        sel = isinstance(f, SelectionFilterElement)
        flts.append({"id": _iid(f.Id), "name": _name(f), "kind": "selection" if sel else "rules",
                     "categories": [] if sel else sorted(_cat_name(d, c) for c in f.GetCategories()),
                     "elements": len(list(f.GetElementIds())) if sel else None})
    flts.sort(key=lambda r: r["name"].lower())
    cats = set()
    for el in FilteredElementCollector(d).WhereElementIsNotElementType():
        try:
            c = el.Category
            if c is not None and c.CategoryType == CategoryType.Model and _iid(c.Id) not in _PROTECT \
                    and not _txt(c.Name).startswith("<"):
                cats.add(_txt(c.Name))
        except Exception:
            pass
    return {"workshared": bool(d.IsWorkshared), "worksets": wss, "filters": flts,
            "categories": sorted(cats, key=lambda s: s.lower())}


class _ErFailures(IFailuresPreprocessor):
    """Warnings (joins, overlaps, room separation, ...) are logged and dismissed; any error rolls back."""

    def PreprocessFailures(self, fa):
        err = False
        for f in list(fa.GetFailureMessages()):
            text = _txt(f.GetDescriptionText()).strip()
            try:
                ids = [_iid(i) for i in f.GetFailingElementIds()][:8]
            except Exception:
                ids = []
            if ids and f.GetSeverity() != FailureSeverity.Warning:
                text += " [element ids %s]" % ", ".join(str(i) for i in ids)
            if f.GetSeverity() == FailureSeverity.Warning:
                _MSGS.append(["warning", text])
                fa.DeleteWarning(f)
            else:
                _MSGS.append(["error", text])
                err = True
        return FailureProcessingResult.ProceedWithRollBack if err else FailureProcessingResult.Continue


_MSGS = []


def _run_tx(d, name, fn):
    t = Transaction(d, name)
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(_ErFailures())
    t.SetFailureHandlingOptions(opts)
    t.Start()
    try:
        fn()
    except Exception:
        t.RollBack()
        raise
    return t.Commit() == TransactionStatus.Committed


def _main():
    d = _pick_doc()
    if _ER["action"] == "sources":
        _emit("SOURCES", _sources(d))
        return
    model_only = bool(_ER.get("model_only", True))
    skip_pinned = bool(_ER.get("skip_pinned", True))
    fix_groups = bool(_ER.get("fix_groups", True))
    max_rows = int(_ER.get("max_rows", 20000))

    # ---- resolve the targets: worksets and / or filters, then categories
    missing, closed = [], []
    on_ws = None
    if _ER.get("worksets"):
        on_ws = {}
        by_name = dict((_txt(w.Name).strip().lower(), w) for w in _user_worksets(d))
        for n in _ER["worksets"]:
            ws = by_name.get(n.strip().lower())
            if ws is None:
                missing.append("workset '%s' (%s)" % (n, ", ".join(sorted(_txt(w.Name) for w in by_name.values()))
                                                     if by_name else "the model is not workshared"))
                continue
            if not ws.IsOpen:
                closed.append(_txt(ws.Name))
            col = FilteredElementCollector(d).WherePasses(ElementWorksetFilter(ws.Id, False))
            for el in col.WhereElementIsNotElementType():
                on_ws.setdefault(_iid(el.Id), [el, []])[1].append("workset " + _txt(ws.Name))
    in_flt = None
    if _ER.get("filters"):
        in_flt = {}
        flts = _filters(d)
        for n in _ER["filters"]:
            f = flts.get(n.strip().lower())
            if f is None:
                missing.append("filter '%s' (%s)" % (n, ", ".join(sorted(_name(x) for x in flts.values())) or
                                                     "the model has no filters"))
                continue
            for el in _filter_elements(d, f):
                in_flt.setdefault(_iid(el.Id), [el, []])[1].append("filter " + _name(f))
    found = {}
    if on_ws is not None and in_flt is not None and _ER.get("combine") == "all":
        for iid in set(on_ws) & set(in_flt):
            found[iid] = [on_ws[iid][0], on_ws[iid][1] + in_flt[iid][1]]
    else:
        for part in (on_ws or {}, in_flt or {}):
            for iid, (el, why) in part.items():
                found.setdefault(iid, [el, []])[1].extend(why)
    cats = [c.strip().lower() for c in (_ER.get("categories") or []) if c.strip()]
    if cats:
        known = set(_txt(c.Name).strip().lower() for c in d.Settings.Categories)
        missing.extend("category '%s'" % c for c in cats if c not in known)
        found = dict((i, v) for i, v in found.items()
                     if v[0].Category is not None and _txt(v[0].Category.Name).strip().lower() in cats)

    targets, skipped, skip_why = {}, [], {}

    def skip(el, why, reason):
        r = _info(d, el, why)
        r["status"] = "skipped: " + reason[1]
        skipped.append(r)
        skip_why[reason[0]] = skip_why.get(reason[0], 0) + 1

    for iid, (el, why) in found.items():
        reason = _why_not(el, model_only, skip_pinned)
        if reason:
            skip(el, why, reason)
        else:
            targets[iid] = (el, why)

    # ---- groups: a target inside a targeted group goes with it; a member needs its group instances ungrouped.
    # Outermost first, so a targeted group is settled before the targets inside it.
    covered, members, hit = [], {}, {}
    chains = dict((iid, _chain(d, v[0])) for iid, v in targets.items())
    for iid in sorted(targets, key=lambda i: (len(chains[i]), i)):
        el, why = targets[iid]
        ch = chains[iid]
        if not ch:
            continue
        if [g for g in ch if _iid(g.Id) in targets]:
            r = _info(d, el, why)
            r["status"] = "to remove with its group"
            covered.append(r)
            del targets[iid]
            continue
        pinned = [g for g in ch if g.Pinned]
        reason = None
        if not fix_groups:
            reason = ("inside a model group (groups option off)",
                      "inside model group '%s' (groups option off)" % _name(ch[0]))
        elif skip_pinned and pinned:
            reason = ("inside a pinned model group", "inside pinned model group '%s' (id %d)" % (
                _name(pinned[0]), _iid(pinned[0].Id)))
        if reason:
            skip(el, why, reason)
            del targets[iid]
            continue
        members[iid] = ch
        for g in ch:
            hit[_iid(g.Id)] = g
    blockers = []
    for iid, el in [(i, v[0]) for i, v in targets.items()] + list(hit.items()):
        who = _owner(d, el.Id)
        if who:
            blockers.append({"id": iid, "category": _txt(el.Category.Name) if el.Category is not None else "",
                             "name": _name(el), "why": "borrowed by %s" % who})
    rows = {}
    for iid, (el, why) in targets.items():
        rows[iid] = _info(d, el, why)
        rows[iid]["status"] = "to remove" + (" (taken out of its group)" if iid in members else "")

    def counts(rs, key):
        out = {}
        for r in rs:
            out[r[key]] = out.get(r[key], 0) + 1
        return sorted([k, v] for k, v in out.items())

    sources = {}
    for el, why in targets.values():
        for w in why:
            sources[w] = sources.get(w, 0) + 1
    _emit("PLAN", {"targets": len(targets), "standalone": len(targets) - len(members), "in_groups": len(members),
                   "groups": len(hit), "group_types": sorted(set(_name(g) for g in hit.values())),
                   "whole_groups": len([1 for el, w in targets.values() if isinstance(el, Group)]),
                   "with_group": len(covered), "by_category": counts(rows.values(), "category"),
                   "by_source": sorted([k, v] for k, v in sources.items()),
                   "skipped": len(skipped), "skipped_why": sorted([k, v] for k, v in skip_why.items()),
                   "blockers": blockers, "missing": missing, "closed": closed, "modifiable": not d.IsReadOnly,
                   "fix_groups": fix_groups,
                   "rows": sorted(list(rows.values()) + covered + skipped, key=lambda r: r["id"])[:max_rows]})
    if _ER["action"] == "plan":
        return
    if d.IsReadOnly:
        raise Exception("ER: %s is read-only" % d.Title)
    stop = None
    if missing:
        stop = "not found in the model: %s" % "; ".join(missing)
    elif not targets:
        stop = "nothing to remove"
    elif blockers and _ER["action"] == "apply":
        stop = "elements borrowed by other users -- ask them to Synchronize / Relinquish, then try again"
    if stop:
        _emit("RESULT", {"committed": False, "stopped": stop, "rows": []})
        return

    # ---- do it: ungroup -> delete (probe, then real) -> regroup, all in one TransactionGroup
    regrouped, notes = [], []

    def errors_now():
        return sorted(set(t for k, t in _MSGS if k == "error"))

    def ungroup():
        """Ungroup every group instance that holds a target (outermost first)."""
        depth = dict((i, len(_chain(d, g))) for i, g in hit.items())
        order = sorted(hit.values(), key=lambda g: depth[_iid(g.Id)])

        def work():
            for g in order:
                gtype = d.GetElement(g.GetTypeId())
                try:
                    detail = len(list(g.GetAvailableAttachedDetailGroupTypeIds())) > 0
                except Exception:
                    detail = False
                rec = {"old": _iid(g.Id), "type_id": g.GetTypeId(), "type_name": _name(gtype) or _name(g),
                       "depth": depth[_iid(g.Id)], "detail": detail}
                if g.Pinned:
                    g.Pinned = False                 # only reached with "remove pinned elements too"
                rec["members"] = list(g.UngroupMembers())
                regrouped.append(rec)
        return _run_tx(d, "Element Remover: ungroup %d group(s)" % len(order), work)

    def regroup():
        """Regroup what is left of every ungrouped instance (innermost first) and name the new group types."""
        new_of = {}

        def work():
            for rec in sorted(regrouped, key=lambda r: -r["depth"]):
                ids = [new_of.get(_iid(m), m) for m in rec["members"]]
                ids = [i for i in ids if d.GetElement(i) is not None]
                rec["kept"] = len(ids)
                if not ids:
                    continue                         # every member removed: the instance is gone
                g = d.Create.NewGroup(List[ElementId](ids))
                new_of[rec["old"]] = g.Id
                rec["new"] = g
            mine = set(_iid(r["new"].Id) for r in regrouped if r.get("new") is not None)
            by_type = {}
            for rec in regrouped:
                by_type.setdefault(_iid(rec["type_id"]), []).append(rec)
            for tid, recs in by_type.items():
                left = [x for x in FilteredElementCollector(d).OfClass(Group).ToElements()
                        if _iid(x.GetTypeId()) == tid and _iid(x.Id) not in mine]
                base, old_type = recs[0]["type_name"], recs[0]["type_id"]
                recs = sorted([r for r in recs if r.get("new") is not None], key=lambda r: r["old"])
                if left:
                    names = [base + " (elements removed)"] + [base + " (elements removed %d)" % k
                                                              for k in range(2, len(recs) + 1)]
                else:
                    try:
                        d.Delete(old_type)          # no instance of it is left
                    except Exception:
                        pass
                    names = [base] + [base + " (%d)" % k for k in range(2, len(recs) + 1)]
                for rec, name in zip(recs, names):
                    t = rec["new"].GroupType
                    for k in range(20):
                        try:
                            t.Name = name if k == 0 else "%s %d" % (name, k + 1)
                            break
                        except Exception:
                            continue
                    rec["new_type"] = _name(t)
        return _run_tx(d, "Element Remover: regroup %d group(s)" % len(regrouped), work)

    def delete(ids):
        """Delete the targets (unpinning them first when asked); returns every id Revit deleted."""
        for i in ids:
            el = d.GetElement(i)
            if el is not None and el.Pinned:
                el.Pinned = False                    # only reached with "remove pinned elements too"
        return list(d.Delete(List[ElementId](ids)))

    tg = TransactionGroup(d, "Element Remover by Netbuild")
    tg.Start()
    committed = False
    try:
        if hit and not ungroup():
            raise Exception("ER: Revit refused to ungroup -- %s" % "; ".join(errors_now()))
        # ElementIds, not Elements, from here on: a rolled-back deletion can invalidate the Element wrappers
        id_of = dict((i, targets[i][0].Id) for i in targets)
        ids = [id_of[i] for i in sorted(id_of)]
        # probe: what does Revit delete with the targets? (rolled back at once, so it can be described)
        probe = Transaction(d, "Element Remover: probe")
        probe.Start()
        try:
            probed = delete(ids)
        finally:
            probe.RollBack()
        extra = {}
        for eid in probed:
            el = d.GetElement(eid)
            if _iid(eid) not in targets and el is not None:
                extra[_iid(eid)] = _info(d, el)
        gone = []
        if not _run_tx(d, "Element Remover: delete %d element(s)" % len(ids), lambda: gone.extend(delete(ids))):
            raise Exception("ER: Revit rolled back the deletion -- %s" % "; ".join(errors_now()))
        if regrouped and not regroup():
            raise Exception("ER: Revit refused to regroup -- %s" % "; ".join(errors_now()))

        gone = set(_iid(x) for x in gone)
        left = []
        for iid, r in rows.items():
            if d.GetElement(id_of[iid]) is None:
                r["status"] = "deleted" + (" (taken out of its group)" if iid in members else "")
            else:
                r["status"] = "still in the model"
                left.append(r)
        for r in covered:
            r["status"] = "deleted with its group"
        deps = []
        for iid in sorted(gone):
            if iid in rows:
                continue
            r = extra.get(iid) or {"id": iid, "category": "", "name": "", "workset": "", "group": "",
                                   "matched": "", "status": ""}
            r["status"] = "deleted with a removed element"
            deps.append(r)
        for rec in regrouped:
            if rec.get("new") is not None:
                notes.append("group '%s' (id %d): ungrouped, %d member(s) kept, regrouped as '%s' (id %d)" % (
                    rec["type_name"], rec["old"], rec["kept"], rec.get("new_type", ""), _iid(rec["new"].Id)))
            else:
                notes.append("group '%s' (id %d): every member removed -- the instance is gone" % (
                    rec["type_name"], rec["old"]))
        errors = errors_now()
        keep = _ER["action"] == "apply" and not errors and not left
        groups = [{"old_id": r["old"], "type": r["type_name"], "kept": r.get("kept", 0),
                   "new_id": _iid(r["new"].Id) if r.get("new") is not None else -1,
                   "new_type": r.get("new_type", ""), "detail": r["detail"]} for r in regrouped]
        if keep:
            tg.Assimilate()
            committed = True
        else:
            tg.RollBack()
    except Exception:
        if not committed and tg.HasStarted():
            tg.RollBack()
        raise
    all_rows = sorted(list(rows.values()) + covered + deps + skipped, key=lambda r: r["id"])
    _emit("RESULT", {"committed": committed, "requested": len(rows), "deleted": len(rows) - len(left),
                     "with_group": len(covered), "dependents": counts(deps, "category"), "total": len(gone),
                     "left": left, "groups": groups, "notes": notes,
                     "warnings": [t for k, t in _MSGS if k == "warning"], "errors": errors,
                     "rows": all_rows[:max_rows]})


_emit("BEGIN", {})
_main()
_emit("END", {})
'''

"""The code sent to Revit (IronPython 2.7 under pyRevit; also runs on CPython 3 in the tests).

One payload serves every action; ``_LS`` (a literal dict prepended per call) says which:

* ``levels`` -- list the levels: name, displayed "Elevation", elevation base, pinned / monitored.
* ``plan``   -- for the requested moves, find every element whose position a moved level drives,
                the offset parameter that will compensate it, and anything that blocks the edit
                (element borrowed by another user, read-only offset, member of a group).  Nothing
                is changed.
* ``trial``  -- do the whole move inside a TransactionGroup, measure every model element, then
                ROLL BACK.  The model is left exactly as it was.
* ``apply``  -- the same, then Assimilate (one Undo entry: "Netbuild Level Shift") -- unless an
                element still moved and ``rollback_on_drift`` is set, in which case roll back.

How the elements keep their X, Y, Z
-----------------------------------
1. Snapshot the bounding box (min Z, max Z) of every model element (view-independent, not a
   level / grid / area).
2. Transaction 1: for every element driven by a moved level, subtract the level's move from the
   offset that pairs with it (wall base/top offset, floor height offset, column base/top offset,
   beam start/end level offset, stair base/top offset, room base/limit offset, group origin level
   offset, MEP middle elevation, family "Elevation from Level" / door-window sill height, ...),
   then set the new level elevations.  Hosted elements, group members, nested families and MEP
   fittings are left alone: they follow their host / group / connected run.
3. Measure again.  Any element that still moved rigidly (min and max Z moved by the same dz) is
   corrected by -dz on its own offsets, or -- if it has none -- moved by (0, 0, -dz).  Elements
   whose host / group / connected run also drifted wait for the next round.  Up to N rounds.
4. Whatever still differs is reported element by element.  Geometry is the judge, not the
   parameter edits.
"""

CODE = r'''
import json as _ls_json
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, CategoryType, ElementTransformUtils,
                               FailureProcessingResult, FailureSeverity, FilteredElementCollector,
                               IFailuresPreprocessor, Level, StorageType, Transaction, TransactionGroup,
                               TransactionStatus, WorksharingUtils, CheckoutStatus, XYZ)


def _emit(tag, data):
    print("@@LS-%s:%s@@ %s" % (tag, _LS["nonce"], _ls_json.dumps(data)))


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


def _pick_doc():
    try:
        active = doc
    except NameError:
        active = __revit__.ActiveUIDocument.Document
    want = [m.lower() for m in (_LS.get("match") or []) if m]
    if not want:
        d = active
    else:
        docs = [x for x in active.Application.Documents if not x.IsLinked and not x.IsFamilyDocument]
        hits = [x for x in docs if [w for w in want if w in x.Title.lower()]]
        if len(hits) != 1:
            raise Exception("LS: %d open model(s) match %s -- open models: %s"
                            % (len(hits), _LS.get("match"), [x.Title for x in docs]))
        d = hits[0]
    _emit("DOC", {"title": d.Title, "path": d.PathName, "readonly": bool(d.IsReadOnly),
                  "workshared": bool(d.IsWorkshared),
                  "active": d.Title == active.Title and d.PathName == active.PathName})
    return d


_BIPS = {}


def _bip(name):
    if name not in _BIPS:                # names missing in this Revit version resolve to None
        _BIPS[name] = getattr(BuiltInParameter, name, None)
    return _BIPS[name]


def _param(el, name):
    b = _bip(name)
    if b is None:
        return None
    try:
        return el.get_Parameter(b)
    except Exception:
        return None


def _pid(p):
    """The level id a parameter points at, or -1."""
    try:
        if p is None or p.StorageType != StorageType.ElementId:
            return -1
        return _iid(p.AsElementId())
    except Exception:
        return -1


def _writable(p):
    return p is not None and not p.IsReadOnly and p.StorageType == StorageType.Double


# (level parameter, how to pick its offsets, offset parameters, role)
# "all": every listed offset that exists is shifted (beam start + end); "first": the first writable one.
_RULES = [
    ("WALL_BASE_CONSTRAINT", "all", ("WALL_BASE_OFFSET",), "base"),
    ("WALL_HEIGHT_TYPE", "all", ("WALL_TOP_OFFSET",), "top"),
    ("FAMILY_BASE_LEVEL_PARAM", "all", ("FAMILY_BASE_LEVEL_OFFSET_PARAM",), "base"),
    ("FAMILY_TOP_LEVEL_PARAM", "all", ("FAMILY_TOP_LEVEL_OFFSET_PARAM",), "top"),
    ("STAIRS_BASE_LEVEL_PARAM", "all", ("STAIRS_BASE_OFFSET",), "base"),
    ("STAIRS_TOP_LEVEL_PARAM", "all", ("STAIRS_TOP_OFFSET",), "top"),
    ("STAIRS_RAILING_BASE_LEVEL_PARAM", "all", ("STAIRS_RAILING_HEIGHT_OFFSET",), "base"),
    ("ROOF_BASE_LEVEL_PARAM", "all", ("ROOF_LEVEL_OFFSET_PARAM",), "base"),
    ("ROOF_CONSTRAINT_LEVEL_PARAM", "all", ("ROOF_CONSTRAINT_OFFSET_PARAM",), "base"),
    ("ROOF_UPTO_LEVEL_PARAM", "all", ("ROOF_UPTO_LEVEL_OFFSET_PARAM",), "top"),
    ("ROOM_LEVEL_ID", "all", ("ROOM_LOWER_OFFSET",), "base"),
    ("ROOM_UPPER_LEVEL", "all", ("ROOM_UPPER_OFFSET",), "top"),
    ("INSTANCE_REFERENCE_LEVEL_PARAM", "all",
     ("STRUCTURAL_BEAM_END0_ELEVATION", "STRUCTURAL_BEAM_END1_ELEVATION"), "base"),
    ("GROUP_LEVEL", "all", ("GROUP_OFFSET_FROM_LEVEL",), "base"),
    ("RBS_START_LEVEL_PARAM", "all", ("RBS_OFFSET_PARAM",), "base"),
    ("LEVEL_PARAM", "first", ("FLOOR_HEIGHTABOVELEVEL_PARAM", "CEILING_HEIGHTABOVELEVEL_PARAM",
                              "TOPOSOLID_HEIGHTABOVELEVEL_PARAM", "SLAB_EDGE_OFFSET_PARAM"), "base"),
]
# a level-hosted / level-based family instance: its own offset from the level
_FI_OFFSETS = ("INSTANCE_SILL_HEIGHT_PARAM", "INSTANCE_ELEVATION_PARAM", "INSTANCE_FREE_HOST_OFFSET_PARAM")

# never measured: they ARE the levels, or are 2D / view helpers
_SKIP_CATS = ("OST_Levels", "OST_Grids", "OST_Areas", "OST_Cameras", "OST_Viewers", "OST_SectionBox",
              "OST_VolumeOfInterest", "OST_RvtLinks", "OST_ReferenceLines", "OST_CLines")
# follow the pipe / duct / tray run they are connected to
_FOLLOWER_CATS = ("OST_DuctFitting", "OST_PipeFitting", "OST_CableTrayFitting", "OST_ConduitFitting",
                  "OST_DuctAccessory", "OST_PipeAccessory", "OST_FlexDuctCurves", "OST_FlexPipeCurves")


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


_SKIP = _cat_ids(_SKIP_CATS)
_FOLLOW = _cat_ids(_FOLLOWER_CATS)


def _is_family_instance(el):
    return hasattr(el, "Host") and hasattr(el, "Symbol")


def _host(el):
    try:
        return el.Host
    except Exception:
        return None


def _drivers(el):
    """Ids of what positions this element besides its own offsets: host, group, parent family, MEP run."""
    out = set()
    g = _iid(getattr(el, "GroupId", None))
    if g > 0:
        out.add(g)
    h = _host(el) if _is_family_instance(el) else None
    if h is not None and not isinstance(h, Level):
        out.add(_iid(h.Id))
    try:
        sc = el.SuperComponent
        if sc is not None:
            out.add(_iid(sc.Id))
    except Exception:
        pass
    try:
        if el.MEPModel is not None and el.MEPModel.ConnectorManager is not None:
            for c in el.MEPModel.ConnectorManager.Connectors:
                for r in c.AllRefs:
                    o = r.Owner
                    if o is not None and _iid(o.Id) != _iid(el.Id):
                        out.add(_iid(o.Id))
    except Exception:
        pass
    return out


def _is_follower(el):
    """True when the element's position comes from something else (never compensated directly)."""
    if _iid(getattr(el, "GroupId", None)) > 0:
        return True
    try:
        if el.SuperComponent is not None:
            return True
    except Exception:
        pass
    cat = el.Category
    return cat is not None and _iid(cat.Id) in _FOLLOW


def _refs(el):
    """[(level id, role, [offset Parameter, ...], rule name)] -- the level(s) that position this element."""
    out = []
    matched = False
    for lvl_name, how, offs, role in _RULES:
        lp = _param(el, lvl_name)
        lid = _pid(lp)
        if lid <= 0:
            continue
        ps = [p for p in [_param(el, o) for o in offs] if p is not None]
        if how == "first":
            w = [p for p in ps if _writable(p)]
            ps = w[:1] if w else ps[:1]
        if not ps:
            continue
        matched = True
        out.append((lid, role, ps, lvl_name))
    if matched or not _is_family_instance(el):
        return out
    # family instance positioned by a level: hosted on the level, unhosted level-based,
    # or a door / window whose sill height is measured from its level
    h = _host(el)
    lid = -1
    if h is not None and isinstance(h, Level):
        lid = _iid(h.Id)
    else:
        lid = _iid(getattr(el, "LevelId", None))
        sill = _param(el, "INSTANCE_SILL_HEIGHT_PARAM")
        if h is not None and not _writable(sill):
            lid = -1
    if lid > 0:
        for o in _FI_OFFSETS:
            p = _param(el, o)
            if _writable(p):
                out.append((lid, "base", [p], "FAMILY_LEVEL_PARAM"))
                break
        else:
            out.append((lid, "base", [], "FAMILY_LEVEL_PARAM"))
    return out


def _model_elements(d):
    els = []
    for el in FilteredElementCollector(d).WhereElementIsNotElementType().WhereElementIsViewIndependent():
        try:
            cat = el.Category
            if cat is None or cat.CategoryType != CategoryType.Model or _iid(cat.Id) in _SKIP:
                continue
            if isinstance(el, Level):
                continue
        except Exception:
            continue
        els.append(el)
    return els


def _bbox(el):
    try:
        if not el.IsValidObject:
            return None
        bb = el.get_BoundingBox(None)
    except Exception:
        return None
    if bb is None:
        return None
    return (bb.Min.Z, bb.Max.Z)


def _name(el):
    try:
        n = el.Name
    except Exception:
        n = ""
    return _txt(n)


def _info(el, levels_by_id):
    cat = el.Category
    lvl = levels_by_id.get(_iid(getattr(el, "LevelId", None)))
    return {"id": _iid(el.Id), "category": _txt(cat.Name) if cat is not None else "",
            "name": _name(el), "level": lvl.Name if lvl is not None else ""}


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


def _level_row(d, lv):
    base = None
    try:
        t = d.GetElement(lv.GetTypeId())
        p = t.get_Parameter(BuiltInParameter.LEVEL_RELATIVE_BASE_TYPE) if t is not None else None
        if p is not None:
            base = {0: "Project Base Point", 1: "Survey Point"}.get(p.AsInteger(), "value %s" % p.AsInteger())
    except Exception:
        pass
    p = lv.get_Parameter(BuiltInParameter.LEVEL_ELEV)
    shown = p.AsDouble() if p is not None else lv.Elevation
    mon = False
    for m in ("IsMonitoringLinkElement", "IsMonitoringLocalElement"):
        try:
            mon = mon or bool(getattr(lv, m)())
        except Exception:
            pass
    return {"id": _iid(lv.Id), "name": _txt(lv.Name), "elev": shown, "internal": lv.Elevation,
            "base": base, "pinned": bool(lv.Pinned), "monitored": mon}


def _levels(d):
    rows = [_level_row(d, lv) for lv in FilteredElementCollector(d).OfClass(Level).ToElements()]
    rows.sort(key=lambda r: r["elev"])
    return rows


class _LsFailures(IFailuresPreprocessor):
    """Warnings (overlaps, room separation, ...) are logged and dismissed; any error rolls back."""

    def PreprocessFailures(self, fa):
        err = False
        for f in list(fa.GetFailureMessages()):
            text = _txt(f.GetDescriptionText())
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
    opts.SetFailuresPreprocessor(_LsFailures())
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
    lv_rows = _levels(d)
    if _LS["action"] == "levels":
        _emit("LEVELS", lv_rows)
        return
    levels = dict((_iid(lv.Id), lv) for lv in FilteredElementCollector(d).OfClass(Level).ToElements())
    moves = {}
    for m in _LS["moves"]:
        if m["id"] not in levels:
            raise Exception("LS: level id %s (%s) is not in %s" % (m["id"], m.get("name"), d.Title))
        moves[m["id"]] = float(m["delta"])
    tol = float(_LS["tol"])

    # ---- plan: who is driven by a moved level, and how it is compensated
    els = _model_elements(d)
    plan, blockers, counts = [], [], {}
    for el in els:
        if _is_follower(el):
            continue
        for lid, role, ps, rule in _refs(el):
            if lid not in moves:
                continue
            cat = el.Category.Name if el.Category is not None else "?"
            key = "%s|%s" % (lid, cat)
            counts[key] = counts.get(key, 0) + 1
            ok = [p for p in ps if _writable(p)]
            item = {"el": el, "lid": lid, "role": role, "params": ok, "rule": rule}
            if not ok:
                item["note"] = "no writable offset -- measured and moved if it drifts"
            plan.append(item)
    touched = {}
    for it in plan:
        touched[_iid(it["el"].Id)] = it["el"]
    for lid in moves:
        touched[lid] = levels[lid]
    for iid, el in touched.items():
        who = _owner(d, el.Id)
        if who:
            blockers.append({"id": iid, "category": _txt(el.Category.Name) if el.Category else "Level",
                             "name": _name(el), "why": "borrowed by %s" % who})
    groups_hit = {}
    for el in els:
        g = _iid(getattr(el, "GroupId", None))
        if g <= 0:
            continue
        for lid, role, ps, rule in _refs(el):
            if lid in moves:
                groups_hit[g] = groups_hit.get(g, 0) + 1
    _emit("PLAN", {"elements": len(els), "compensate": len(plan),
                   "counts": [[int(k.split("|", 1)[0]), k.split("|", 1)[1], v] for k, v in counts.items()],
                   "no_offset": [_info(it["el"], levels) for it in plan if not it["params"]][:200],
                   "group_members": sum(groups_hit.values()), "groups": len(groups_hit),
                   "blockers": blockers, "modifiable": not d.IsReadOnly})
    if _LS["action"] == "plan":
        return
    if d.IsReadOnly:
        raise Exception("LS: %s is read-only" % d.Title)
    if blockers and _LS["action"] == "apply":
        _emit("RESULT", {"committed": False, "stopped": "elements borrowed by other users -- ask them to "
                         "Synchronize / Relinquish, then try again", "drift": [], "rows": []})
        return

    # ---- do it, measured
    before = {}
    for el in els:
        b = _bbox(el)
        if b is not None:
            before[_iid(el.Id)] = b
    by_id = dict((_iid(el.Id), el) for el in els)
    rows = {}

    def row(el, **kw):
        r = rows.get(_iid(el.Id))
        if r is None:
            r = _info(el, levels)
            r.update({"rule": "", "params": [], "method": "", "drift": 0.0, "status": ""})
            rows[_iid(el.Id)] = r
        for k, v in kw.items():
            if k == "params":
                r["params"].extend(v)
            elif k in ("method", "rule"):
                parts = r[k].split("+") if r[k] else []
                if v not in parts:
                    parts.append(v)
                r[k] = "+".join(parts)
            else:
                r[k] = v
        return r

    def shift(p, by):
        old = p.AsDouble()
        p.Set(old - by)
        return [_txt(p.Definition.Name), old, old - by]

    tg = TransactionGroup(d, "Netbuild Level Shift")
    tg.Start()
    committed = False
    try:
        def step1():
            for it in plan:
                by = moves[it["lid"]]
                for p in it["params"]:
                    row(it["el"], rule=it["rule"], params=[shift(p, by)], method="offset")
            for lid, by in moves.items():
                lv = levels[lid]
                lv.Elevation = lv.Elevation + by
        ok = _run_tx(d, "Level Shift: move levels + compensate", step1)
        if not ok:
            raise Exception("LS: Revit rolled back the level move -- %s"
                            % "; ".join(t for k, t in _MSGS if k == "error"))

        def measure():
            out = {}
            for iid, b0 in before.items():
                b1 = _bbox(by_id[iid])
                if b1 is None:
                    continue
                d0, d1 = b1[0] - b0[0], b1[1] - b0[1]
                if abs(d0) > tol or abs(d1) > tol:
                    out[iid] = (d0, d1)
            return out

        drift = measure()
        rounds = int(_LS.get("rounds", 4))
        tried = {}
        for rnd in range(rounds):
            if not drift:
                break
            fixes = []
            for iid, (d0, d1) in drift.items():
                el = by_id[iid]
                if abs(d0 - d1) > tol:
                    continue                         # changed shape -- not a rigid move; reported
                if _drivers(el) & set(drift):
                    continue                         # its host / group / run is still being fixed
                if _iid(getattr(el, "GroupId", None)) > 0:
                    continue                         # group members follow the group
                fixes.append((el, (d0 + d1) / 2.0))
            if not fixes:
                break

            def step2():
                for el, dz in fixes:
                    iid = _iid(el.Id)
                    n = tried.get(iid, 0)
                    tried[iid] = n + 1
                    ps = []
                    if n == 0:
                        for lid, role, cand, rule in _refs(el):
                            ps.extend([p for p in cand if _writable(p)])
                    if ps:
                        row(el, params=[shift(p, dz) for p in ps], method="re-offset")
                    elif _LS.get("move_fallback", True):
                        try:
                            ElementTransformUtils.MoveElement(d, el.Id, XYZ(0, 0, -dz))
                            row(el, method="moved")
                        except Exception as e:
                            row(el, method="move failed: %s" % _txt(e))
            if not _run_tx(d, "Level Shift: correct round %d" % (rnd + 1), step2):
                break
            drift = measure()

        for iid, (d0, d1) in drift.items():
            el = by_id[iid]
            why = "changed shape" if abs(d0 - d1) > tol else "moved"
            g = _iid(getattr(el, "GroupId", None))
            if g > 0:
                why += " (member of group id %d)" % g
            row(el, drift=max(d0, d1, key=abs), status=why)
        for r in rows.values():
            if not r["status"]:
                r["status"] = "OK"
        stay = [r for r in rows.values() if r["status"] != "OK"]
        errors = [t for k, t in _MSGS if k == "error"]
        keep = _LS["action"] == "apply" and not errors and not (stay and _LS.get("rollback_on_drift", True))
        after = dict((_iid(lv.Id), _level_row(d, lv)) for lv in levels.values())
        if keep:
            tg.Assimilate()
            committed = True
        else:
            tg.RollBack()
    except Exception:
        if not committed and tg.HasStarted():
            tg.RollBack()
        raise
    _emit("RESULT", {"committed": committed, "measured": len(before),
                     "drift": stay, "rows": sorted(rows.values(), key=lambda r: r["id"])[:int(_LS.get("max_rows", 20000))],
                     "levels_after": [after[lid] for lid in moves],
                     "warnings": [t for k, t in _MSGS if k == "warning"], "errors": errors})


_emit("BEGIN", {})
_main()
_emit("END", {})
'''

"""The code that runs inside Revit (IronPython 2.7 under pyRevit; also CPython 3 in the tests).

It is sent through the MCP listener by the exe, or run in-process by the pyRevit "Level Shift"
button (core.run_local), which sets ``_LS_SINK`` to receive the results instead of printed lines.

One payload serves every action; ``_LS`` (a literal dict prepended per call) says which:

* ``levels`` -- list the levels: name, displayed "Elevation", elevation base, pinned / monitored.
* ``plan``   -- for the requested moves, find every element whose position a moved level drives,
                the offset parameter that will compensate it, and anything that blocks the edit
                (element borrowed by another user, read-only offset, member of a group).  Nothing
                is changed.
* ``trial``  -- do the whole move inside a TransactionGroup, measure every model element, then
                ROLL BACK.  The model is left exactly as it was.
* ``apply``  -- the same, then Assimilate (one Undo entry: "Level Shift by Netbuild") -- unless an
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
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, CategoryType, CurveElement, ElementId,
                               ElementTransformUtils, FailureProcessingResult, FailureSeverity,
                               FilteredElementCollector, Group, IFailuresPreprocessor, Level, Sketch,
                               SketchPlane, StorageType, Transaction, TransactionGroup, TransactionStatus,
                               WorksharingUtils, CheckoutStatus, XYZ)
from System.Collections.Generic import List


def _emit(tag, data):
    sink = globals().get("_LS_SINK")       # set when a pyRevit button runs the engine in-process
    if sink is not None:
        sink(tag, data)
    else:
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
    """Ids of what positions this element besides its own offsets: host, parent family, MEP run."""
    out = set()
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


def _on_plane(el):
    """Sketch lines (floor / opening / railing boundaries), room / area / space separation lines and model
    lines: they lie on their level's plane and follow it by design -- the element they shape keeps its
    position through its own offset. Reported, never counted as moved, never moved back."""
    if isinstance(el, (CurveElement, Sketch, SketchPlane)):
        return True
    cat = el.Category
    return cat is not None and _txt(cat.Name).startswith("<")


def _is_follower(el):
    """True when the element's position comes from something else (never compensated directly)."""
    if _on_plane(el):
        return True
    try:
        if el.SuperComponent is not None:
            return True
    except Exception:
        pass
    cat = el.Category
    return cat is not None and _iid(cat.Id) in _FOLLOW


def _gid(el):
    return _iid(getattr(el, "GroupId", None))


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
    by_id = dict((_iid(el.Id), el) for el in els)
    fix_groups = bool(_LS.get("fix_groups", True))

    def make_plan():
        out, counts = [], {}
        for el in els:
            if not el.IsValidObject or _is_follower(el):
                continue
            for lid, role, ps, rule in _refs(el):
                if lid not in moves:
                    continue
                cat = el.Category.Name if el.Category is not None else "?"
                key = "%s|%s" % (lid, cat)
                counts[key] = counts.get(key, 0) + 1
                out.append({"el": el, "lid": lid, "role": role, "params": [p for p in ps if _writable(p)],
                            "rule": rule})
        return out, counts

    def chain(el):
        """The group ids above an element, innermost first."""
        out, g = [], _gid(el)
        while g > 0 and g not in out:
            out.append(g)
            ge = by_id.get(g)
            g = _gid(ge) if ge is not None else -1
        return out

    plan, counts = make_plan()
    blockers = []
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
    in_groups = [it["el"] for it in plan if _gid(it["el"]) > 0]
    hit_groups = set()
    for el in in_groups:
        hit_groups.update(chain(el))
    _emit("PLAN", {"elements": len(els), "compensate": len(plan),
                   "counts": [[int(k.split("|", 1)[0]), k.split("|", 1)[1], v] for k, v in counts.items()],
                   "no_offset": [_info(it["el"], levels) for it in plan if not it["params"]][:200],
                   "group_members": len(set(_iid(e.Id) for e in in_groups)), "groups": len(hit_groups),
                   "fix_groups": fix_groups, "blockers": blockers, "modifiable": not d.IsReadOnly})
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
    rows = {}
    regrouped = []                  # one record per group instance that was ungrouped and regrouped

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

    def shift(el, p, by, method):
        """Offset -= by. A refused write (e.g. a group member Revit will not edit) is recorded, not fatal."""
        old = p.AsDouble()
        try:
            p.Set(old - by)
        except Exception as e:
            row(el, method="%s refused: %s" % (method, _txt(e)[:120]))
            return False
        row(el, params=[[_txt(p.Definition.Name), old, old - by]], method=method)
        return True

    def ungroup(gids):
        """Ungroup these group instances (outermost first). Members become free elements."""
        gids = [g for g in gids if g in by_id and by_id[g].IsValidObject]
        depth = dict((g, len(chain(by_id[g]))) for g in gids)
        parent = dict((g, _gid(by_id[g])) for g in gids)
        done = set(r["old"] for r in regrouped)

        def work():
            for g in sorted(gids, key=lambda x: depth[x]):
                if g in done:
                    continue
                grp = by_id[g]
                gtype = d.GetElement(grp.GetTypeId())
                try:
                    detail = len(list(grp.GetAvailableAttachedDetailGroupTypeIds())) > 0
                except Exception:
                    detail = False
                rec = {"old": g, "type_id": grp.GetTypeId(), "type_name": _name(gtype) or _name(grp),
                       "parent": parent[g], "depth": depth[g], "detail": detail}
                try:
                    rec["members"] = list(grp.UngroupMembers())
                except Exception as e:           # e.g. pinned: its members stay grouped and are reported
                    notes.append("could not ungroup '%s' (id %d): %s" % (rec["type_name"], g, _txt(e)[:120]))
                    continue
                regrouped.append(rec)
        return _run_tx(d, "Level Shift: ungroup %d group(s)" % len(gids), work)

    def regroup():
        """Regroup every ungrouped instance (innermost first) and name the new group types."""
        new_of = {}

        def work():
            for rec in sorted(regrouped, key=lambda r: -r["depth"]):
                ids = [new_of.get(_iid(m), m) for m in rec["members"]]
                ids = [i for i in ids if d.GetElement(i) is not None]
                g = d.Create.NewGroup(List[ElementId](ids))
                new_of[rec["old"]] = g.Id
                rec["new"] = g
            mine = set(_iid(r["new"].Id) for r in regrouped)
            by_type = {}
            for rec in regrouped:
                by_type.setdefault(_iid(rec["type_id"]), []).append(rec)
            for tid, recs in by_type.items():
                left = [x for x in FilteredElementCollector(d).OfClass(Group).ToElements()
                        if _iid(x.GetTypeId()) == tid and _iid(x.Id) not in mine]
                base = recs[0]["type_name"]
                if left:
                    names = [base + " (levels moved)"] + [base + " (levels moved %d)" % k
                                                          for k in range(2, len(recs) + 1)]
                else:
                    try:
                        d.Delete(recs[0]["type_id"])
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
        return _run_tx(d, "Level Shift: regroup %d group(s)" % len(regrouped), work)

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

    def errors_now():
        return [t for k, t in _MSGS if k == "error"]

    tg = TransactionGroup(d, "Level Shift by Netbuild")
    tg.Start()
    committed = False
    notes = []
    try:
        def step1():
            for it in plan:
                if not it["el"].IsValidObject:
                    continue
                by = moves[it["lid"]]
                row(it["el"], rule=it["rule"])
                for p in it["params"]:
                    shift(it["el"], p, by, "offset")
            for lid, by in moves.items():
                lv = levels[lid]
                lv.Elevation = lv.Elevation + by
        ok = _run_tx(d, "Level Shift: move levels + compensate", step1)
        if not ok and fix_groups and hit_groups:
            # Revit refused (typically: group instances no longer identical) -> ungroup the groups whose
            # members a moved level positions, then move again
            notes.append("Revit refused the move with the groups in place (%s) -- ungrouped %d group(s), "
                         "moved, regrouped" % ("; ".join(sorted(set(errors_now())))[:300], len(hit_groups)))
            _MSGS[:] = [m for m in _MSGS if m[0] != "error"]
            rows.clear()
            if not ungroup(hit_groups):
                raise Exception("LS: Revit refused to ungroup -- %s" % "; ".join(sorted(set(errors_now()))))
            plan, counts = make_plan()
            ok = _run_tx(d, "Level Shift: move levels + compensate", step1)
        if not ok:
            raise Exception("LS: Revit rolled back the level move -- %s" % "; ".join(sorted(set(errors_now())) + notes))

        drift = measure()
        if fix_groups:
            # group members that still moved: ungroup their groups so they can be fixed as free elements
            gids = set()
            for iid in drift:
                el = by_id[iid]
                if _gid(el) > 0 and not _on_plane(el):
                    gids.update(chain(el))
            if gids:
                notes.append("%d group(s) whose members moved with the groups in place -- ungrouped, fixed, "
                             "regrouped" % len(gids))
                if not ungroup(gids):
                    raise Exception("LS: Revit refused to ungroup -- %s" % "; ".join(sorted(set(errors_now()))))
                drift = measure()

        rounds = int(_LS.get("rounds", 4))
        tried = {}
        for rnd in range(rounds):
            fixes = []
            for iid, (d0, d1) in drift.items():
                el = by_id[iid]
                if _on_plane(el) or isinstance(el, Group) or tried.get(iid, 0) >= 2:
                    continue                         # lines follow their plane; a group = its members
                if _drivers(el) & set(drift):
                    continue                         # its host / parent / run is still being fixed
                fixes.append((el, d0, d1))
            if not fixes:
                break

            def step2():
                for el, d0, d1 in fixes:
                    iid = _iid(el.Id)
                    n = tried.get(iid, 0)
                    tried[iid] = n + 1
                    rigid = abs(d0 - d1) <= tol
                    base, top = [], []
                    for lid, role, cand, rule in _refs(el):
                        (top if role == "top" else base).extend([p for p in cand if _writable(p)])
                    done = False
                    if n == 0 and top:               # base and top drift separately (walls, columns, rooms)
                        done = [shift(el, p, d0, "re-offset") for p in base] + \
                               [shift(el, p, d1, "re-offset") for p in top]
                        done = any(done)
                    elif n == 0 and base and rigid:
                        done = any([shift(el, p, (d0 + d1) / 2.0, "re-offset") for p in base])
                    if done or not rigid or _gid(el) > 0 or not _LS.get("move_fallback", True):
                        continue
                    try:
                        ElementTransformUtils.MoveElement(d, el.Id, XYZ(0, 0, -(d0 + d1) / 2.0))
                        row(el, method="moved")
                    except Exception as e:
                        row(el, method="move failed: %s" % _txt(e)[:120])
            if not _run_tx(d, "Level Shift: correct round %d" % (rnd + 1), step2):
                break
            drift = measure()

        if regrouped:
            if not regroup():
                raise Exception("LS: Revit refused to regroup -- %s" % "; ".join(sorted(set(errors_now()))))
            drift = measure()

        on_plane = {}
        for iid, (d0, d1) in drift.items():
            el = by_id[iid]
            if _on_plane(el):
                cat = _txt(el.Category.Name) if el.Category is not None else "lines"
                on_plane[cat] = on_plane.get(cat, 0) + 1
                continue
            if isinstance(el, Group):
                continue                             # its members are reported one by one
            why = "changed shape" if abs(d0 - d1) > tol else "moved"
            if _gid(el) > 0:
                why += " (member of group id %d)" % _gid(el)
            row(el, drift=max(d0, d1, key=abs), status=why)
        for rec in regrouped:
            if rec["old"] in rows:
                rows[rec["old"]]["method"] = "ungrouped + regrouped as '%s'" % rec.get("new_type", "")
        for r in rows.values():
            if not r["status"]:
                r["status"] = "OK"
        stay = [r for r in rows.values() if r["status"] != "OK"]
        errors = sorted(set(errors_now()))
        keep = _LS["action"] == "apply" and not errors and not (stay and _LS.get("rollback_on_drift", True))
        after = dict((_iid(lv.Id), _level_row(d, lv)) for lv in levels.values())
        groups = [{"old_id": r["old"], "type": r["type_name"], "new_id": _iid(r["new"].Id) if r.get("new") else -1,
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
    _emit("RESULT", {"committed": committed, "measured": len(before),
                     "drift": stay, "rows": sorted(rows.values(), key=lambda r: r["id"])[:int(_LS.get("max_rows", 20000))],
                     "levels_after": [after[lid] for lid in moves], "on_plane": on_plane, "groups": groups,
                     "notes": notes, "warnings": [t for k, t in _MSGS if k == "warning"], "errors": errors})


_emit("BEGIN", {})
_main()
_emit("END", {})
'''

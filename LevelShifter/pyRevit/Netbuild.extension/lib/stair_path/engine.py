"""Stair Path by Netbuild -- the part that talks to Revit (IronPython 2.7, inside Revit, from the pyRevit button).

read_model() turns the model into rules.py's plain shapes; run() places the annotations those rules ask for:
Check (plan only, nothing changes) -> Trial run (everything placed, then rolled back) -> Apply (one Undo
entry: 'Stair Path by Netbuild'). View templates and View Range are never changed: a Down that Revit cannot
show is reported as a gap for the user to decide.
"""

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, ElementId, FailureProcessingResult,
                               FailureSeverity, FilteredElementCollector, IFailuresPreprocessor, Level,
                               LinkElementId, Transaction, TransactionGroup, TransactionStatus, ViewPlan,
                               ViewType, XYZ)
from Autodesk.Revit.DB.Architecture import StairsPath
from System.Collections.Generic import List

from . import rules
from .rules import Check

TITLE = "Stair Path by Netbuild"
FT = rules.MM_PER_FT


def iid(eid):
    if eid is None:
        return -1
    v = getattr(eid, "Value", None)          # Revit 2024+ (Int64); IntegerValue is gone in 2026
    if v is None:
        v = eid.IntegerValue
    return int(v)


def _txt(x):
    try:
        return u"%s" % x
    except Exception:
        return repr(x)


def _param(el, bip):
    try:
        return el.get_Parameter(getattr(BuiltInParameter, bip))
    except Exception:
        return None


def _level_param(doc, el, bip):
    p = _param(el, bip)
    if p is None:
        return None
    lv = doc.GetElement(p.AsElementId())
    return lv if isinstance(lv, Level) else None


def _double(el, bip):
    p = _param(el, bip)
    try:
        return p.AsDouble() if p is not None else 0.0
    except Exception:
        return 0.0


def _string(el, bip):
    p = _param(el, bip)
    try:
        return p.AsString() if p is not None else None
    except Exception:
        return None


def _elements(doc, cat, view_id=None, types=False):
    coll = FilteredElementCollector(doc, view_id) if view_id is not None else FilteredElementCollector(doc)
    coll = coll.OfCategory(getattr(BuiltInCategory, cat))
    coll = coll.WhereElementIsElementType() if types else coll.WhereElementIsNotElementType()
    return list(coll.ToElements())


def _xy_box(bb):
    return (bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y)


def _first_run(doc, stair):
    """Plan travel (dx, dy) of the stair's own first flight: the run at BaseElevation 0 (or the lowest run) --
    GetStairsRuns() order is not the physical up-sequence."""
    runs = []
    for rid in stair.GetStairsRuns():
        run = doc.GetElement(rid)
        if run is not None:
            runs.append((getattr(run, "BaseElevation", 0.0), run))
    if not runs:
        return (0.0, 0.0)
    runs.sort(key=lambda r: r[0])
    try:
        curves = list(runs[0][1].GetStairsPath())
        p0, p1 = curves[0].GetEndPoint(0), curves[-1].GetEndPoint(1)
        return (p1.X - p0.X, p1.Y - p0.Y)
    except Exception:
        return (0.0, 0.0)


def _crop(view):
    if not getattr(view, "CropBoxActive", False):
        return None
    try:
        bb = view.CropBox
        t = bb.Transform
        pts = [t.OfPoint(XYZ(x, y, bb.Min.Z)) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
        return (min(p.X for p in pts), min(p.Y for p in pts), max(p.X for p in pts), max(p.Y for p in pts))
    except Exception:
        return None


def _template(doc, view):
    """(template name, True when that template controls View Range) -- (None, False) without a template."""
    tid = getattr(view, "ViewTemplateId", None)
    tpl = doc.GetElement(tid) if tid is not None and iid(tid) > 0 else None
    if tpl is None:
        return None, False
    try:
        free = set(iid(i) for i in tpl.GetNonControlledTemplateParameterIds())
        controls = iid(ElementId(BuiltInParameter.PLAN_VIEW_RANGE)) not in free
    except Exception:
        controls = True
    return _txt(tpl.Name), controls


def target_views(doc, uidoc, s):
    if s["views"] == "name":
        want = s["name_filter"].strip().lower()
        views = [v for v in FilteredElementCollector(doc).OfClass(ViewPlan).ToElements()
                 if want in _txt(v.Name).lower()]
    else:
        views = [doc.GetElement(uv.ViewId) for uv in uidoc.GetOpenUIViews()] if uidoc is not None else []
    out = []
    for v in views:
        if (isinstance(v, ViewPlan) and not v.IsTemplate and v.ViewType == ViewType.FloorPlan
                and getattr(v, "GenLevel", None) is not None):
            out.append(v)
    return sorted(out, key=lambda v: _txt(v.Name))


def read_model(doc, uidoc, s):
    """The model as rules.py shapes, plus the Revit objects behind them ("_stairs", "_views", "_types")."""
    levels = sorted([{"id": iid(lv.Id), "name": _txt(lv.Name), "elev": lv.Elevation}
                     for lv in FilteredElementCollector(doc).OfClass(Level).ToElements()],
                    key=lambda lv: (lv["elev"], lv["name"]))
    stairs, by_id = [], {}
    for st in _elements(doc, "OST_Stairs"):
        if not hasattr(st, "GetStairsRuns"):
            continue                                     # not a component stair: Revit cannot path it
        bb = st.get_BoundingBox(None)
        if bb is None:
            continue
        base, top = _level_param(doc, st, "STAIRS_BASE_LEVEL_PARAM"), _level_param(doc, st, "STAIRS_TOP_LEVEL_PARAM")
        base_elev = base.Elevation + _double(st, "STAIRS_BASE_OFFSET") if base is not None else None
        top_elev = top.Elevation + _double(st, "STAIRS_TOP_OFFSET") if top is not None else None
        if top_elev is None and base_elev is not None and getattr(st, "Height", None):
            top_elev = base_elev + st.Height
        sid = iid(st.Id)
        stairs.append({"id": sid, "base": _txt(base.Name) if base is not None else None,
                       "top": _txt(top.Name) if top is not None else None, "base_elev": base_elev,
                       "top_elev": top_elev, "box": _xy_box(bb), "run": _first_run(doc, st)})
        by_id[sid] = st
    views, view_objs = [], {}
    for v in target_views(doc, uidoc, s):
        visible = [iid(e.Id) for e in _elements(doc, "OST_Stairs", v.Id) if iid(e.Id) in by_id]
        tpl, controls = _template(doc, v)
        views.append({"id": iid(v.Id), "name": _txt(v.Name), "scale": v.Scale, "level": _txt(v.GenLevel.Name),
                      "crop": _crop(v), "visible": visible, "template": tpl, "template_range": controls})
        view_objs[iid(v.Id)] = v
    types, type_objs = [], {}
    for t in _elements(doc, "OST_StairsPaths", types=True):
        family = _string(t, "ALL_MODEL_FAMILY_NAME") or _txt(getattr(t, "FamilyName", ""))
        name = _string(t, "ALL_MODEL_TYPE_NAME") or _string(t, "SYMBOL_NAME_PARAM") or ""
        types.append({"id": iid(t.Id), "family": family, "name": name})
        type_objs[iid(t.Id)] = t
    return {"doc": doc.Title, "levels": levels, "stairs": stairs, "views": views, "types": types,
            "_stairs": by_id, "_views": view_objs, "_types": type_objs}


class _Quiet(IFailuresPreprocessor):
    """Warnings are logged and dismissed; any error rolls the step back."""

    def __init__(self, msgs):
        self.msgs = msgs

    def PreprocessFailures(self, fa):
        err = False
        for f in list(fa.GetFailureMessages()):
            text = _txt(f.GetDescriptionText()).strip()
            if f.GetSeverity() == FailureSeverity.Warning:
                self.msgs.append("warning: " + text)
                fa.DeleteWarning(f)
            else:
                self.msgs.append("error: " + text)
                err = True
        return FailureProcessingResult.ProceedWithRollBack if err else FailureProcessingResult.Continue


def _step(doc, name, msgs, fn):
    t = Transaction(doc, "%s -- %s" % (TITLE, name))
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(_Quiet(msgs))
    t.SetFailureHandlingOptions(opts)
    t.Start()
    try:
        out = fn()
    except Exception:
        t.RollBack()
        raise
    status = t.Commit()
    if status != TransactionStatus.Committed:
        raise RuntimeError("%s: Revit did not commit (%s) -- %s" % (name, status, "; ".join(msgs[-3:])))
    return out


class Run(object):
    """One Check / Trial run / Apply. ``report()`` gives (checks, lines, rows) for the window and the log."""

    def __init__(self, doc, uidoc, values=None):
        self.doc, self.uidoc = doc, uidoc
        self.s = rules.settings(values)
        self.checks, self.lines, self.rows, self.msgs = [], [], [], []

    # ------------------------------------------------------------ plan
    def plan(self):
        s = self.s
        self.checks += rules.check_settings(s)
        m = self.model = read_model(self.doc, self.uidoc, s)
        views = m["views"]
        where = "open plan views" if s["views"] == "open" else "plan views named '*%s*'" % s["name_filter"]
        self.checks.append(Check("Target views", bool(views), "%d %s" % (len(views), where) if views else
                                 "no %s -- open the floor plans to annotate, or pick views by name" % where))
        odd = rules.scale_problems(views)
        if odd:
            self.checks.append(Check("Views at other scales", None, "skipped (only 1:500, 1:200 and 1:100 are in "
                                     "the standard): %s" % ", ".join("%s (1:%d)" % (v["name"], v["scale"])
                                                                     for v in odd)))
        self.views = [v for v in views if v["scale"] in rules.SCALES]
        self.missing = rules.missing_types(m["types"], [v["scale"] for v in self.views])
        for kind, sc in self.missing:
            src, new = rules.type_to_create(m["types"], kind, sc)
            if s["create_types"] and src is not None:
                self.checks.append(Check("Stair path type %s : 1-%d" % (kind, sc), None,
                                         "not in the model -- '%s : %s' will be created from '%s'"
                                         % (kind, new, src["name"])))
            else:
                self.checks.append(Check("Stair path type %s : 1-%d" % (kind, sc), False,
                                         "not in the model (names are matched loosely, e.g. 'Standard 1-%d')%s"
                                         % (sc, "" if src is None else " -- tick 'Create missing types'")))
        self.cores, skipped, notes = rules.build_cores(m["stairs"], m["levels"], s)
        self.ups, self.downs = rules.up_down(self.cores)
        self.checks.append(Check("Stair cores", True if self.cores else None, "%d core(s), %d flight(s) of %d stairs" % (
            len(self.cores), sum(len(c["flights"]) for c in self.cores), len(m["stairs"]))))
        for c in self.cores:
            fl = c["flights"]
            self.lines.append("  %s: %d flight(s) %s -> %s  [%s]" % (
                c["name"], len(fl), fl[0]["base"], max(fl, key=lambda f: self._order(f["top"]))["top"],
                ", ".join("%d %s->%s" % (f["id"], f["base"], f["top"]) for f in fl)))
        if skipped:
            self.checks.append(Check("Stairs left out of the Up/Down chain", None, "%d (the sweep still tags them "
                                     "where visible): %s" % (len(skipped), "; ".join("%d %s" % x for x in skipped))))
        if notes:
            self.checks.append(Check("Base / top taken from the real elevation", None, "; ".join(
                "%d %s" % n for n in notes)))
        by_id = dict((st["id"], st) for st in m["stairs"])
        self.jobs = []
        for v in self.views:
            jobs, outside = rules.plan_view(v, self.cores, m["levels"], self.ups, self.downs, by_id)
            self.jobs.append((v, jobs))
            self.lines.extend("  " + n for n in outside)
            ups = len([j for j in jobs if j["kind"] == "up"])
            self.lines.append("  %s (1:%d, %s): Up x%d, Down x%d" % (v["name"], v["scale"], v["level"], ups,
                                                                     len(jobs) - ups))
        self.by_id = by_id
        return self.ok()

    def _order(self, name):
        for i, lv in enumerate(self.model["levels"]):
            if lv["name"] == name:
                return i
        return -1

    def ok(self):
        return not [c for c in self.checks if c.ok is False]

    # ------------------------------------------------------------ place
    def type_id(self, kind, scale):
        t = rules.pick_type(self.model["types"], kind, scale)
        return self.model["_types"][t["id"]].Id if t else None

    def place(self, view, sid, kind):
        """Create one stair path; returns it (Revit raises when the flight is not visible in the view)."""
        scale = view["scale"]
        fam, show_up, show_down, offsets = rules.style(scale, kind)
        type_id = self.type_id(fam, scale)
        if type_id is None:
            raise LookupError("no %s type for 1:%d" % (fam, scale))
        st = self.model["_stairs"][sid]
        sp = StairsPath.Create(self.doc, LinkElementId(st.Id), type_id, self.model["_views"][view["id"]].Id)
        sp.ShowUpText = show_up
        if show_down is not None:
            sp.ShowDownText = show_down
        ox, oy = rules.text_offset(self.by_id[sid], scale, self.s)
        vec = XYZ(ox / FT, oy / FT, 0)
        if "up" in offsets:
            sp.UpTextOffset = vec
        if "down" in offsets:
            sp.DownTextOffset = vec
        return sp, (ox, oy)

    def row(self, view, job, result, sid, sp=None, offset=None, why=""):
        self.rows.append({"view": view["name"], "scale": view["scale"], "level": view["level"],
                          "core": job.get("core") or "", "kind": job["kind"], "stair": sid, "result": result,
                          "path": iid(sp.Id) if sp is not None else "",
                          "offset_mm": "%.0f, %.0f" % offset if offset else "", "why": why})

    def create_types(self):
        made = []
        for kind, sc in self.missing:
            src, new = rules.type_to_create(self.model["types"], kind, sc)
            if src is None:
                continue
            t = self.model["_types"][src["id"]].Duplicate(new)
            self.model["types"].append({"id": iid(t.Id), "family": src["family"], "name": new})
            self.model["_types"][iid(t.Id)] = t
            made.append("%s : %s" % (kind, new))
        return made

    def clear(self):
        paths = _elements(self.doc, "OST_StairsPaths")
        if self.s["clear"] == "views":
            keep = set(v["id"] for v in self.views)
            paths = [p for p in paths if iid(p.OwnerViewId) in keep]
        if paths:
            self.doc.Delete(List[ElementId]([p.Id for p in paths]))
        return len(paths)

    def place_main(self):
        self.created, self.gaps, self.failed, self.through = [], [], [], 0
        for v, jobs in self.jobs:
            for job in jobs:
                try:
                    sp, off = self.place(v, job["stair"], job["kind"])
                    self.created.append((v, sp))
                    self.row(v, job, "placed", job["stair"], sp, off)
                    continue
                except Exception as e:
                    first = _txt(e)
                if job["kind"] == "down" and job["fallback"] is not None:
                    try:
                        sp, off = self.place(v, job["fallback"], "through")
                        self.created.append((v, sp))
                        self.through += 1
                        self.row(v, job, "through", job["fallback"], sp, off,
                                 "stair %d not visible here -- passing flight used" % job["stair"])
                        continue
                    except Exception as e:
                        first += " / passing flight %d: %s" % (job["fallback"], _txt(e))
                if job["kind"] == "down":
                    self.gaps.append((v, job, first))
                    self.row(v, job, "gap", job["stair"], why=first)
                else:
                    self.failed.append((v, job, first))
                    self.row(v, job, "not placed", job["stair"], why=first)

    def tagged(self):
        out = {}
        for p in _elements(self.doc, "OST_StairsPaths"):
            try:
                out.setdefault(iid(p.OwnerViewId), set()).add(iid(p.StairsId.HostElementId))
            except Exception:
                pass
        return out

    def sweep(self):
        done = []
        tagged = self.tagged()
        for v in self.views:
            for job in rules.sweep_jobs(v, tagged.get(v["id"], set())):
                try:
                    sp, off = self.place(v, job["stair"], "sweep")
                except Exception as e:
                    self.row(v, job, "not placed", job["stair"], why=_txt(e))
                    continue
                self.created.append((v, sp))
                done.append((v, job["stair"]))
                self.row(v, job, "placed", job["stair"], sp, off)
        return done

    def _path_boxes(self, view_obj, pad):
        out = []
        for v, sp in self.created:
            if v["id"] != iid(view_obj.Id):
                continue
            bb = sp.get_BoundingBox(view_obj)
            if bb is not None:
                out.append((iid(sp.Id), (bb.Min.X - pad, bb.Min.Y - pad, bb.Max.X + pad, bb.Max.Y + pad)))
        return out

    def room_tags(self):
        nudge, pad = self.s["tag_nudge_mm"] / FT, self.s["tag_pad_mm"] / FT
        word = self.s["staircase_keyword"].strip().lower()
        moved, back = 0, 0
        for v in self.views:
            view = self.model["_views"][v["id"]]
            boxes = [b for _, b in self._path_boxes(view, pad)]
            tags = _elements(self.doc, "OST_RoomTags", view.Id)
            for tag in tags:
                tbb = tag.get_BoundingBox(view)
                loc = getattr(tag, "Location", None)
                if tbb is None or not hasattr(loc, "Point"):
                    continue
                if [b for b in boxes if rules.boxes_overlap(_xy_box(tbb), b)]:
                    pt = loc.Point
                    loc.Point = XYZ(pt.X, pt.Y + nudge, pt.Z)
                    moved += 1
            if not word:
                continue
            for tag in tags:
                room = getattr(tag, "Room", None)
                loc = getattr(tag, "Location", None)
                if room is None or not hasattr(loc, "Point"):
                    continue
                if word not in (_string(room, "ROOM_NAME") or "").lower():
                    continue
                rpt = getattr(room.Location, "Point", None)
                pt = loc.Point
                if rpt is None or room.IsPointInRoom(XYZ(pt.X, pt.Y, rpt.Z + 0.5)):
                    continue
                loc.Point = XYZ(rpt.X, rpt.Y, pt.Z)
                back += 1
        return moved, back

    def dimension_overlaps(self):
        out = []
        for v in self.views:
            view = self.model["_views"][v["id"]]
            boxes = self._path_boxes(view, 0.0)
            if not boxes:
                continue
            for d in _elements(self.doc, "OST_Dimensions", view.Id):
                bb = d.get_BoundingBox(view)
                if bb is None:
                    continue
                for pid, b in boxes:
                    if rules.boxes_overlap(_xy_box(bb), b):
                        out.append("%s: stair path %d overlaps dimension %d" % (v["name"], pid, iid(d.Id)))
        return out

    def gap_text(self, v, job, why):
        text = "%s (%s): %s Down -- stair %d is not visible in this view and no flight of %s passes through %s" % (
            v["name"], v["level"], job["core"], job["stair"], job["core"], v["level"])
        if v.get("template") and v.get("template_range"):
            text += (". View Range is set by view template '%s': extending it would change every view using "
                     "that template, so nothing was changed -- decide in Revit (or ask the template owner)"
                     % v["template"])
        else:
            text += ". Extend this view's View Range (bottom / view depth) to show the arriving flight"
        return text + "  [%s]" % why

    # ------------------------------------------------------------ run
    def run(self, action):
        """action: plan | trial | apply. Returns True when nothing FAILed."""
        if not self.plan() or action == "plan":
            if action != "plan":
                self.checks.append(Check("Not run", False, "fix the FAIL lines first"))
            return self.ok()
        doc, s = self.doc, self.s
        tg = TransactionGroup(doc, TITLE)
        tg.Start()
        try:
            made = _step(doc, "types", self.msgs, self.create_types) if s["create_types"] and self.missing else []
            cleared = _step(doc, "clear", self.msgs, self.clear)
            _step(doc, "place", self.msgs, self.place_main)
            swept = _step(doc, "sweep", self.msgs, self.sweep) if s["sweep"] else []
            moved, back = _step(doc, "room tags", self.msgs, self.room_tags) if s["room_tags"] else (0, 0)
            dims = self.dimension_overlaps() if s["check_dimensions"] else []
            if action == "trial":
                tg.RollBack()
            else:
                tg.Assimilate()
        except Exception:
            if tg.HasStarted():
                tg.RollBack()
            raise
        main = len(self.created) - len(swept)
        if made:
            self.checks.append(Check("Stair path types created", True, ", ".join(made)))
        self.checks.append(Check("Cleared", True, "%d existing stair path(s) in the %s" % (
            cleared, "target views" if s["clear"] == "views" else "whole model")))
        self.checks.append(Check("Up / Down placed", True, "%d (%d Down via a flight passing through the level)"
                                 % (main, self.through)))
        if s["sweep"]:
            self.checks.append(Check("Other visible stairs tagged", True, "%d (Automatic Up/Down, both texts)"
                                     % len(swept)))
        for v, job, why in self.failed:
            self.checks.append(Check("Up not placed", None, "%s: %s stair %d -- %s" % (v["name"], job["core"],
                                                                                    job["stair"], why)))
        if self.gaps:
            self.checks.append(Check("Down gaps", None, "%d level(s) without Down -- see below; no view template or "
                                     "View Range was changed" % len(self.gaps)))
            self.lines.extend("  GAP " + self.gap_text(v, job, why) for v, job, why in self.gaps)
        if s["room_tags"]:
            self.checks.append(Check("Room tags", True, "%d nudged off a stair path, %d Staircase tag(s) moved back "
                                     "inside the room" % (moved, back)))
        if dims:
            self.checks.append(Check("Dimension strings", None, "%d overlap(s) with a stair path -- not moved, "
                                     "check them in the view" % len(dims)))
            self.lines.extend("  " + d for d in dims[:50])
        self.lines.extend("  Revit " + m for m in self.msgs[:30])
        if action == "trial":
            self.checks.append(Check("Trial -- rolled back", True, "the model is unchanged"))
        else:
            self.checks.append(Check("Applied", True, "one Undo entry in Revit: '%s'. Save / Synchronize to keep it"
                                     % TITLE))
        return self.ok()

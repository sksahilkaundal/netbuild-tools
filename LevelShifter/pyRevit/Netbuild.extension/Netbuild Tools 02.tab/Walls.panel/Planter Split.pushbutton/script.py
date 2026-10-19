# -*- coding: utf-8 -*-
"""Curtain Wall Planter Split

Discovers all instances of the target curtain wall type in the active
document, verifies the concrete/mullion/grass-floor types exist, shows a
per-floor summary, and (on confirmation) runs the 4-step pipeline:

1. Split each wall at a level-specific height above its base; convert the
   bottom row of panels to a concrete Basic Wall type.
2. For bottom-row columns that were originally glass: merge back to
   continuous glass UNLESS the column sits over a real planter-floor loop.
3. Delete any mullion that doesn't touch a glass panel on any side.
4. Reversion sweep: re-fix any bottom-row panel a later regen silently
   reset back to its pre-conversion type.

Does NOT save or sync the document — that is left for the user to confirm
manually. Ported from the Claude-session-validated CurtainWallPlanterSplit_MCP.py
(see OneDrive Documents/Claude folder) with the same element/type names,
which are standard across this project's buildings — but the concrete wall
type has been missing on 2 of the buildings tried so far, so this script
will stop and tell you rather than silently substituting or auto-creating it.
"""
import System
from pyrevit import revit, DB, forms, script

doc = revit.doc
output = script.get_output()

TARGET_CW_TYPE = "Studio-WAL-Curtain Wall_220mm_Custom Mullion(V+H)"
CONCRETE_WALL_TYPE = "Studio-WAL-concrete 220"
MULLION_TYPE_NAME = "Studio_Aluminium 50x220mm"
GRASS_FLOOR_TYPE = "Earth. 650+50 = 700 Grass"
LOCATION_LINE = 2  # Finish Face: Exterior (WALL_KEY_REF_PARAM enum)
PLANTER_MIN_OVERLAP_FT = 0.3
GLASS_TOUCH_TOL_FT = 0.2
PARAM_TOL_FT = 0.2

LEVEL_SPLIT_HEIGHTS_MM = {
    "01st Floor": 275.0,
    "02nd Floor": 525.0,
    "03rd Floor": 525.0,
    "04th Floor": 525.0,
    "05th Floor": 525.0,
}


def eid(i):
    try:
        return int(i.IntegerValue)
    except Exception:
        return int(i.Value)


def gname(e):
    if e is None:
        return "N/A"
    p = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
    return p.AsString() if p else "N/A"


wall_filt = DB.ElementClassFilter(DB.Wall)


def embedded_wall_bbox(panel, ptype):
    """Wall-type system panels have no own bbox; real geometry is the dependent Wall."""
    if ptype != 'Wall':
        return panel.get_BoundingBox(None), None
    deps = panel.GetDependentElements(wall_filt)
    if not deps:
        return None, None
    ew = doc.GetElement(deps[0])
    return ew.get_BoundingBox(None), ew


def param_of(curve, point):
    return curve.Project(point).Parameter


def bbox_param_range(curve, bb):
    corners = [DB.XYZ(bb.Min.X, bb.Min.Y, 0), DB.XYZ(bb.Max.X, bb.Max.Y, 0),
               DB.XYZ(bb.Min.X, bb.Max.Y, 0), DB.XYZ(bb.Max.X, bb.Min.Y, 0)]
    params = [param_of(curve, c) for c in corners]
    return min(params), max(params)


def get_grass_loops(level_name):
    floors = DB.FilteredElementCollector(doc).OfClass(DB.Floor).WhereElementIsNotElementType().ToElements()
    target = None
    for f in floors:
        if gname(doc.GetElement(f.GetTypeId())) != GRASS_FLOOR_TYPE:
            continue
        lvlp = f.get_Parameter(DB.BuiltInParameter.LEVEL_PARAM)
        lvl = doc.GetElement(lvlp.AsElementId()) if lvlp else None
        if lvl and lvl.Name == level_name:
            target = f
            break
    if target is None:
        return []
    opt = DB.Options()
    loops = []
    for s in target.get_Geometry(opt):
        if isinstance(s, DB.Solid) and s.Volume > 0:
            for face in s.Faces:
                if isinstance(face, DB.PlanarFace) and face.FaceNormal.Z > 0.9:
                    for loop in face.EdgeLoops:
                        pts = [e.AsCurve().GetEndPoint(0) for e in loop]
                        xs = [p.X for p in pts]
                        ys = [p.Y for p in pts]
                        loops.append((min(xs), max(xs), min(ys), max(ys)))
                    break
    return loops


def is_planter(bb, loops):
    xmin, xmax, ymin, ymax = bb.Min.X, bb.Max.X, bb.Min.Y, bb.Max.Y
    for lx0, lx1, ly0, ly1 in loops:
        xover = min(xmax, lx1) - max(xmin, lx0)
        yover = min(ymax, ly1) - max(ymin, ly0)
        if xover > PLANTER_MIN_OVERLAP_FT and yover > -0.02:
            return True
    return False


def mullion_param(curve, m):
    loc = m.Location
    if hasattr(loc, 'Point'):
        return param_of(curve, loc.Point)
    a, b = loc.Curve.GetEndPoint(0), loc.Curve.GetEndPoint(1)
    mid = DB.XYZ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, 0)
    return param_of(curve, mid)


def step1_split_and_convert(wid, concrete_wt):
    w = doc.GetElement(DB.ElementId(System.Int64(wid)))
    cg = w.CurtainGrid
    curve = w.Location.Curve
    lvlp = w.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
    lvl = doc.GetElement(lvlp.AsElementId())
    level_name = lvl.Name
    split_height_mm = LEVEL_SPLIT_HEIGHTS_MM[level_name]
    base_off = w.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    base_mm = lvl.Elevation * 304.8 + base_off * 304.8
    target_ft = (base_mm + split_height_mm) / 304.8
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
    mid = DB.XYZ((p0.X + p1.X) / 2.0, (p0.Y + p1.Y) / 2.0, target_ft)

    panels_before = [eid(x) for x in cg.GetPanelIds()]
    cg.AddGridLine(True, mid, False)
    doc.Regenerate()

    bottom_glass_cols = []
    for pid in panels_before:
        p = doc.GetElement(DB.ElementId(System.Int64(pid)))
        bb = p.get_BoundingBox(None)
        if not bb or bb.Max.Z * 304.8 > base_mm + split_height_mm + 5.0:
            continue
        orig_type = gname(doc.GetElement(p.GetTypeId()))
        if 'vision' in orig_type.lower():
            pmin, pmax = bbox_param_range(curve, bb)
            bottom_glass_cols.append((pmin, pmax, bb))
        p.get_Parameter(DB.BuiltInParameter.ELEM_TYPE_PARAM).Set(concrete_wt.Id)
    doc.Regenerate()

    for pid in panels_before:
        p = doc.GetElement(DB.ElementId(System.Int64(pid)))
        bb, ew = embedded_wall_bbox(p, gname(doc.GetElement(p.GetTypeId())))
        if ew:
            lp = ew.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM)
            if lp:
                lp.Set(LOCATION_LINE)

    return base_mm, level_name, bottom_glass_cols


def step2_merge_non_planter_glass(wid, base_mm, level_name, bottom_glass_cols, mullion_type):
    w = doc.GetElement(DB.ElementId(System.Int64(wid)))
    cg = w.CurtainGrid
    curve = w.Location.Curve
    split_height_mm = LEVEL_SPLIT_HEIGHTS_MM[level_name]
    loops = get_grass_loops(level_name)

    non_planter_cols = [(pmin, pmax) for pmin, pmax, bb in bottom_glass_cols if not is_planter(bb, loops)]
    if not non_planter_cols:
        return 0

    split_mm = base_mm + split_height_mm
    to_delete = set()
    for pmin, pmax in non_planter_cols:
        for mid in list(cg.GetMullionIds()):
            m = doc.GetElement(mid)
            bb = m.get_BoundingBox(None)
            if not bb or bb.Min.Z * 304.8 > split_mm + 5.0 or bb.Max.Z * 304.8 < base_mm - 5.0:
                continue
            mp = mullion_param(curve, m)
            if pmin - PARAM_TOL_FT <= mp <= pmax + PARAM_TOL_FT:
                to_delete.add(eid(mid))
    for mid in to_delete:
        m = doc.GetElement(DB.ElementId(System.Int64(mid)))
        if m and m.IsValidObject:
            if m.Pinned:
                m.Pinned = False
            doc.Delete(m.Id)
    doc.Regenerate()

    for pmin, pmax in non_planter_cols:
        uid = next(iter(cg.GetUGridLineIds()))
        gl = doc.GetElement(uid)
        for seg in list(gl.ExistingSegmentCurves):
            a, b = seg.GetEndPoint(0), seg.GetEndPoint(1)
            segmid = DB.XYZ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, 0)
            sp = param_of(curve, segmid)
            if pmin - PARAM_TOL_FT <= sp <= pmax + PARAM_TOL_FT:
                gl.RemoveSegment(seg)
                doc.Regenerate()
                break

    boundary_p = set()
    for pmin, pmax in non_planter_cols:
        boundary_p.add(round(pmin, 1))
        boundary_p.add(round(pmax, 1))
    for glid in list(cg.GetVGridLineIds()):
        vgl = doc.GetElement(glid)
        for seg in list(vgl.ExistingSegmentCurves):
            a, b = seg.GetEndPoint(0), seg.GetEndPoint(1)
            segmid = DB.XYZ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, 0)
            sp = param_of(curve, segmid)
            if any(abs(sp - bp) < PARAM_TOL_FT for bp in boundary_p):
                try:
                    vgl.AddMullions(seg, mullion_type, False)
                except Exception:
                    pass
    doc.Regenerate()
    return len(non_planter_cols)


def step3_glass_touch_cleanup(wid):
    w = doc.GetElement(DB.ElementId(System.Int64(wid)))
    cg = w.CurtainGrid
    pinfo = []
    for pid in cg.GetPanelIds():
        p = doc.GetElement(pid)
        ptype = gname(doc.GetElement(p.GetTypeId()))
        bb, _ = embedded_wall_bbox(p, ptype)
        if bb is not None:
            pinfo.append((bb, 'vision' in ptype.lower()))
    deleted = 0
    for mid in list(cg.GetMullionIds()):
        m = doc.GetElement(mid)
        mbb = m.get_BoundingBox(None)
        if not mbb:
            continue
        touches_glass = any(
            not (mbb.Max.X + GLASS_TOUCH_TOL_FT < bb.Min.X or mbb.Min.X - GLASS_TOUCH_TOL_FT > bb.Max.X or
                 mbb.Max.Y + GLASS_TOUCH_TOL_FT < bb.Min.Y or mbb.Min.Y - GLASS_TOUCH_TOL_FT > bb.Max.Y or
                 mbb.Max.Z + GLASS_TOUCH_TOL_FT < bb.Min.Z or mbb.Min.Z - GLASS_TOUCH_TOL_FT > bb.Max.Z)
            for bb, isg in pinfo if isg)
        if not touches_glass:
            if m.Pinned:
                m.Pinned = False
            doc.Delete(mid)
            deleted += 1
    doc.Regenerate()
    return deleted


def step4_verify_and_fix_reversions(wid, concrete_wt):
    w = doc.GetElement(DB.ElementId(System.Int64(wid)))
    cg = w.CurtainGrid
    fixed = []
    for pid in cg.GetPanelIds():
        p = doc.GetElement(pid)
        ptype = gname(doc.GetElement(p.GetTypeId()))
        bb = p.get_BoundingBox(None)
        if bb and (bb.Max.Z - bb.Min.Z) * 304.8 < 400.0 and ptype != 'Wall':
            p.get_Parameter(DB.BuiltInParameter.ELEM_TYPE_PARAM).Set(concrete_wt.Id)
            fixed.append(eid(pid))
    doc.Regenerate()
    for pid in fixed:
        p = doc.GetElement(DB.ElementId(System.Int64(pid)))
        _, ew = embedded_wall_bbox(p, gname(doc.GetElement(p.GetTypeId())))
        if ew:
            lp = ew.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM)
            if lp:
                lp.Set(LOCATION_LINE)
    return fixed


# ---------------------------------------------------------------------------
# Discover instances + verify required types
# ---------------------------------------------------------------------------
wall_types_all = list(DB.FilteredElementCollector(doc).OfClass(DB.WallType))
mullion_types_all = list(DB.FilteredElementCollector(doc).OfClass(DB.MullionType))
floor_types_all = list(DB.FilteredElementCollector(doc).OfClass(DB.FloorType))

concrete_wt = next((x for x in wall_types_all if gname(x) == CONCRETE_WALL_TYPE), None)
mullion_type = next((x for x in mullion_types_all if gname(x) == MULLION_TYPE_NAME), None)
cw_type_exists = any(gname(x) == TARGET_CW_TYPE for x in wall_types_all)
grass_exists = any(gname(x) == GRASS_FLOOR_TYPE for x in floor_types_all)

missing = []
if not cw_type_exists:
    missing.append(TARGET_CW_TYPE)
if concrete_wt is None:
    missing.append(CONCRETE_WALL_TYPE)
if mullion_type is None:
    missing.append(MULLION_TYPE_NAME)
if not grass_exists:
    missing.append(GRASS_FLOOR_TYPE)

if missing:
    forms.alert(
        "This document is missing required type(s):\n\n  - " + "\n  - ".join(missing) +
        "\n\nThe concrete wall type in particular has been missing on 2 of the "
        "buildings tried so far (only a 200mm variant existed) — if that's the "
        "case here too, create/resize it yourself first (or ask Claude to), "
        "then re-run this button.",
        title="Curtain Wall Planter Split — Missing Types",
        exitscript=True
    )

walls = DB.FilteredElementCollector(doc).OfClass(DB.Wall).WhereElementIsNotElementType().ToElements()
by_level = {}
for w in walls:
    wt = doc.GetElement(w.GetTypeId())
    if gname(wt) != TARGET_CW_TYPE:
        continue
    lvlp = w.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
    lvl = doc.GetElement(lvlp.AsElementId()) if lvlp else None
    lvl_name = lvl.Name if lvl else "UNKNOWN"
    by_level.setdefault(lvl_name, []).append(eid(w.Id))

total_walls = sum(len(v) for v in by_level.values())
if total_walls == 0:
    forms.alert(
        "No curtain walls of type '%s' found in this document." % TARGET_CW_TYPE,
        title="Curtain Wall Planter Split",
        exitscript=True
    )

summary_lines = ["  {0}: {1} walls".format(lvl, len(ids)) for lvl, ids in sorted(by_level.items())]
proceed = forms.alert(
    "Found {0} target curtain wall instances:\n\n{1}\n\n"
    "Run the full planter-split pipeline now?\n\n"
    "This modifies the model but will NOT save or sync — do that "
    "yourself afterward once you've reviewed the result.".format(
        total_walls, "\n".join(summary_lines)),
    title="Curtain Wall Planter Split",
    ok=False, yes=True, no=True
)
if not proceed:
    script.exit()

results = {}
for level_name in sorted(by_level.keys()):
    wids = by_level[level_name]
    floor_result = {"ok": 0, "failed": []}
    for wid in wids:
        t = DB.Transaction(doc, "Curtain wall planter split - wall %d" % wid)
        t.Start()
        try:
            base_mm, lvl, glass_cols = step1_split_and_convert(wid, concrete_wt)
            step2_merge_non_planter_glass(wid, base_mm, lvl, glass_cols, mullion_type)
            step3_glass_touch_cleanup(wid)
            t.Commit()
            floor_result["ok"] += 1
        except Exception as e:
            t.RollBack()
            floor_result["failed"].append((wid, str(e)))

    t4 = DB.Transaction(doc, "Step4 reversion sweep - %s" % level_name)
    t4.Start()
    reversions_fixed = 0
    try:
        for wid in wids:
            fixed = step4_verify_and_fix_reversions(wid, concrete_wt)
            reversions_fixed += len(fixed)
        t4.Commit()
    except Exception as e:
        t4.RollBack()
        floor_result["failed"].append(("step4-sweep", str(e)))

    floor_result["reversions_fixed"] = reversions_fixed
    results[level_name] = floor_result

output.print_md("## Curtain Wall Planter Split — Result")
total_ok = 0
total_failed = 0
total_reversions = 0
for level_name in sorted(results.keys()):
    r = results[level_name]
    total_ok += r["ok"]
    total_failed += len(r["failed"])
    total_reversions += r["reversions_fixed"]
    output.print_md("- **{0}**: {1} OK, {2} failed, {3} reversions fixed".format(
        level_name, r["ok"], len(r["failed"]), r["reversions_fixed"]))
    for wid, err in r["failed"]:
        output.print_md("  - Wall {0} FAILED: {1}".format(wid, err))

output.print_md("\n**Totals: {0} OK, {1} failed, {2} reversions fixed. Document NOT saved/synced.**".format(
    total_ok, total_failed, total_reversions))

forms.alert(
    "Done: {0} OK, {1} failed, {2} reversions fixed.\n\n"
    "See the pyRevit output window for the per-floor breakdown.\n\n"
    "Document has NOT been saved or synced — review and do that yourself.".format(
        total_ok, total_failed, total_reversions),
    title="Curtain Wall Planter Split — Done"
)

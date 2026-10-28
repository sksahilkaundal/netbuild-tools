# -*- coding: utf-8 -*-
"""
Sets "Stair Path" (Stairs Path) direction annotations in every open plan
view, per scale, following the office standard below. Run via
execute_revit_code (Revit MCP) against the currently open model.

REUSABLE TEMPLATE — edit only the CONFIG block for a new building/run.
See [[stair-path-direction-prompt-template]] for the matching chat prompt.

STANDARD (as agreed for Studio Podium/Tower buildings):
  1. Clear any existing Stair Path annotations first.
  2. Group Stairs elements into "cores" (same plan location across levels)
     via CORES config below — discover by clustering on plan centroid
     (see discover_cores() helper). Where a core has duplicate/legacy
     flights at the same base or top level (seen on B002 — messy models
     can have several overlapping Stairs elements per level), the
     most-recent ElementId wins for the main Up/Down map — see
     resolve_base_top_maps().
  3. For every level a core passes through:
       - a flight BASED there (continues upward) -> "Up" annotation
       - a flight TOPPING OUT there (arrived from below) -> "Down"
         annotation
     Both can apply at the same level (through-level).
  4. Family type + text per view scale:
       - 1:500 -> Automatic Up/Down Direction : Standard 1-500,
         Show Up/Down Text = No (arrows only)
       - 1:200 / 1:100, Up case -> Fixed Up Direction : Standard
         1-200/1-100, Show Up Text = Yes (this family has NO Down Text
         property at all — setting it raises "the type of this stairs
         path is not automatic up/down direction", don't attempt it)
       - 1:200 / 1:100, Down case -> Automatic Up/Down Direction :
         Standard 1-200/1-100, Show Up Text = No, Show Down Text = Yes
     Type names are fuzzy-matched by the 1-500/1-200/1-100 suffix.
  5. PASS-THROUGH FALLBACK (needed on messy models like B002): placing a
     StairsPath fails with "the stairsId is not visible in planViewId"
     when the referenced flight's own geometry doesn't intersect that
     view's View Range/Crop — this is common for the flight ARRIVING
     from below when a view's template has a shallow View Range (only
     reaches slightly below its own level). When the direct down-flight
     reference fails, look for any OTHER stair in the same core whose
     base is strictly below and top is strictly above the current level
     (i.e. it genuinely passes through) and reference THAT one instead,
     using Automatic Up/Down Direction with BOTH Show Up/Down Text = Yes
     — this mirrors exactly what native Revit produces when you manually
     pick a through-spanning stair with the UI tool. If no pass-through
     candidate exists either, the level is left without Down for that
     core (see "genuinely unresolvable" below).
  6. UNTAGGED-VISIBLE-STAIR SWEEP (run after the main pass): some models
     have bystander/duplicate stair elements that are visible in a view
     (pass FilteredElementCollector(doc, view.Id) on OST_Stairs) but
     aren't part of any core's Up/Down map (e.g. a duplicate flight that
     lost the most-recent-Id tiebreak, or one only visible in a
     split "Part 01/02" partial-plan view). Sweep every open view and
     tag any such visible-but-unpathed stair with Automatic Up/Down +
     both texts, so nothing visible is left blank.
  7. Text offset (UpTextOffset/DownTextOffset, XYZ instance properties):
     axis chosen per stair by its plan bbox — length>=width (bbox longer
     in X) -> offset along X; width>length -> offset along Y. Magnitude
     per OFFSET_MAGNITUDE_MM_BY_SCALE. For a per-level DIRECTIONAL
     override (e.g. Ground Floor needed the sign flipped per stair based
     on which way it actually travels, not a fixed sign for everyone) —
     see signed_offset_for_run_y()/signed_offset_for_run_x() and
     DIRECTIONAL_OVERRIDE_LEVELS/DIRECTIONAL_X_OVERRIDE_LEVELS (each
     accepts an 'ALL' sentinel to apply to every level, not just a
     named list — used on B005 for every width>length stair, and B004
     for every length>=width stair): the
     rule is "away from the stair's own start-run direction", determined
     from the run whose BaseElevation == 0 (the true first flight), not
     from GetStairsRuns() list order (that order is NOT guaranteed to be
     the physical up-sequence).
  8. Room tag cleanup: nudge any Room Tag whose bbox overlaps a stair
     path's padded extent; separately, reset any "Staircase"-named
     room's tag that ends up outside its own room (overlapping a wall)
     back to that room's own Location.Point.
  9. Touches OPEN views by default (uidoc.GetOpenUIViews()); or every
     plan view whose name ends with TARGET_VIEW_NAME_SUFFIX when
     TARGET_VIEW_MODE = 'name_suffix'.

BUILDINGS RUN SO FAR: B001 (clean baseline). B002 (duplicate/legacy
flights, split Part 01/02 views, View-Template-locked View Range — 10
residual gaps left by user choice). B003 (unreliable base/top params,
one non-connecting stub stair, X-directional offset tuned to -100mm/+X
side, standard/+X side for -X). B004 (same param unreliability + split
half-flight through an unnamed landing, X-directional offset re-tuned
to -300mm/+X side — clean run, zero pass-through/sweep needed). B005
(same param unreliability + split half-flight, Y-directional offset
'ALL' at 300mm; a run-width text-centering refinement was tried here
then explicitly rejected by the user and reverted — don't reintroduce
it without being asked). TOWER 3505-ProjectG-Studio-ARC-RVT-00003 (2026-09-21):
clean model, params == geometry, 2 cores (ST-01 x~31.9m, ST-02 x~58.3m),
90 flights -> 180 Up/Down annotations in the 54 "<Level> GA Plan_Linked
View" views at 1:200, zero pass-through/zero gaps; run in
TARGET_VIEW_MODE='name_suffix' + CLEAR_SCOPE='targets' (162 unrelated
annotations in stair-detail/00_BIM views preserved) + AUTO_CREATE_TYPES
(model only had the two plain "Standard" types) + AUTO_CORES_BY_X +
Y-directional 'ALL' at 300mm. NOTE: a full-view ImageExportOptions
export dropped one "UP" text at random — it's a raster-export artifact,
not a missing annotation; verify with a cropped export or in the UI.

GENUINELY UNRESOLVABLE CASES: if a level has no pass-through candidate
AND the direct down-flight reference fails, the only remaining fix is
extending View Range on that specific view — which usually can't be done
directly if a View Template controls View Range there (a per-instance
SetViewRange edit gets silently reverted by the template on regenerate).
Fixing that requires excluding "View Range" from template control on
just the affected views (view-specific override), which changes view
behavior beyond this script's scope — confirm with the user before doing
that; on B002 the user chose to leave it and accept the small residual
gap instead.

Run inside Revit via execute_revit_code with `doc`/`uidoc` already bound.
"""
import System
from Autodesk.Revit.DB import (
    Transaction, ElementId, LinkElementId, XYZ, UnitUtils, UnitTypeId,
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ViewPlan,
)
from Autodesk.Revit.DB.Architecture import StairsPath
from System.Collections.Generic import List

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ----------------------------- CONFIG ---------------------------------
# Level order (ascending) — needed for pass-through detection (strictly
# base < level < top) and for clustering. Include every level any core
# touches, even ones with no open view (e.g. basements).
LEVEL_ORDER = [
    'Ground Floor', 'B1-01st Floor', 'B1-02nd Floor', 'B1-03rd Floor',
]

# Stair cores: {core_name: [(stairs_element_id, base_level_name, top_level_name), ...]}
# Discover per building with discover_cores() (clusters on plan centroid),
# then hand-verify/clean before pasting in here — duplicate/legacy flights
# are common on older models (see resolve_base_top_maps()).
CORES = {
    'coreA': [
        (11509278, 'Ground Floor', 'B1-01st Floor'),
        (11516932, 'B1-01st Floor', 'B1-02nd Floor'),
        (11517070, 'B1-02nd Floor', 'B1-03rd Floor'),
    ],
    'coreB': [
        (11519556, 'Ground Floor', 'B1-01st Floor'),
        (11518846, 'B1-01st Floor', 'B1-02nd Floor'),
        (11518891, 'B1-02nd Floor', 'B1-03rd Floor'),
    ],
}

TYPE_SUFFIX_BY_SCALE = {500: '1-500', 200: '1-200', 100: '1-100'}

OFFSET_MAGNITUDE_MM_BY_SCALE = {
    200: {'X': 600.0, 'Y': 200.0},
    100: {'X': 400.0, 'Y': 200.0},
    # 500 intentionally absent: no text shown at 1:500, offset moot.
}

# Levels where the Y-offset sign must follow each stair's own start-run
# travel direction instead of a flat positive magnitude (see
# signed_offset_for_run_y()). Leave empty to just use a flat +offset
# everywhere (the common case). Built for Ground Floor on B001.
DIRECTIONAL_OVERRIDE_LEVELS = set()  # e.g. {'Ground Floor'} or {'ALL'} for every level
DIRECTIONAL_OFFSET_MM = 300.0  # tuned per building: 400mm on B001 (Ground Floor only), 300mm on B005 (all levels, 'ALL')

# X-axis equivalent, built on B003, re-tuned per building since (B004):
# length>=width (X-axis) stairs whose text placement needs to differ by
# which way the stair's own first flight actually travels along X (not
# a fixed side for everyone). Set of level names this applies to ('ALL'
# sentinel = every level). Magnitude is asymmetric by design (tuned
# live per-direction, not meant to be symmetric) — keyed by
# (direction_sign, view_scale). RE-TUNE THIS PER BUILDING, don't assume
# a prior building's values carry over — B003 used {1: -100, -1: std},
# B004 used {1: -300, -1: std} (same shape, different +X-side distance).
DIRECTIONAL_X_OVERRIDE_LEVELS = set()  # e.g. {'ALL'}
DIRECTIONAL_X_OFFSET_MM_BY_DIR_SCALE = {
    # dir_sign: {scale: signed mm}  -- dir_sign = sign of the stair's own
    # start-run X-travel (its first flight, BaseElevation == 0). Values
    # are SIGNED (not a magnitude to be multiplied by dir_sign) — the
    # two directions are independently tuned and NOT mirror images.
    # Current values are B004's: runs toward +X -> flat -300mm (both
    # scales); runs toward -X -> "keep as previous" i.e. the standard
    # scale-based OFFSET_MAGNITUDE_MM_BY_SCALE distance (600/400mm) on
    # the +X side — B004 had zero stairs actually needing this second
    # branch, so it's unverified visually there, just carried over from
    # the stated rule.
    1:  {200: -300.0, 100: -300.0},
    -1: {200: 600.0, 100: 400.0},
}

ROOM_TAG_NUDGE_MM = 300.0
ROOM_TAG_OVERLAP_PAD_MM = 400.0
STAIRCASE_ROOM_KEYWORD = 'stair'

# --- Target-view selection (added on Tower 00003, 2026-09-21) ---
# 'open'        -> only views open in the UI (original behaviour, B001-B005)
# 'name_suffix' -> every non-template plan view whose Name ends with
#                  TARGET_VIEW_NAME_SUFFIX, open or not (Tower: the 54
#                  "<Level> GA Plan_Linked View" views created in bulk)
TARGET_VIEW_MODE = 'open'
TARGET_VIEW_NAME_SUFFIX = ' GA Plan_Linked View'

# --- Clear scope ---
# 'model'   -> delete every StairsPath in the model first (original)
# 'targets' -> only delete StairsPaths owned by the target views (Tower
#              00003 had 162 legit annotations in stair-detail / 00_BIM
#              views that must survive)
CLEAR_SCOPE = 'model'

# --- Auto-create missing Stair Path types ---
# If a needed "Standard 1-500/1-200/1-100" type is missing, duplicate the
# family's plain "Standard" type under that name (identical graphics —
# text/arrow size can be tuned afterwards). Tower 00003 shipped with
# only the two plain "Standard" types.
AUTO_CREATE_TYPES = False
AUTO_CREATE_SUFFIXES = ['1-500', '1-200', '1-100']

# --- Auto cores (clean models only) ---
# When base/top params are trustworthy and there are no duplicates,
# build CORES by clustering on plan-centroid X (metres) instead of
# hand-pasting 90 rows. {core_name: (centroid_x_m, tol_m)}; None = use
# the hand-written CORES above. Verify with discover_cores() first.
AUTO_CORES_BY_X = None  # e.g. {'ST-01': (31.9, 1.0), 'ST-02': (58.3, 1.0)}
SAVE_AFTER_RUN = True
# ------------------------------------------------------------------------


def eid(v):
    return ElementId(System.Int64(v))


def mm(v):
    return UnitUtils.ConvertToInternalUnits(v, UnitTypeId.Millimeters)


def discover_cores(cluster_tolerance_ft=2.0):
    """One-off discovery helper — run separately, inspect the printed
    clusters, hand-clean duplicates, then paste the result into CORES.
    Does not touch the model."""
    stairs = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Stairs).WhereElementIsNotElementType().ToElements()
    data = []
    for s in stairs:
        base = s.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM)
        top = s.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM)
        base_el = doc.GetElement(base.AsElementId()) if base else None
        top_el = doc.GetElement(top.AsElementId()) if top else None
        bbox = s.get_BoundingBox(None)
        cx = (bbox.Min.X + bbox.Max.X) / 2.0
        cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
        data.append({'id': int(s.Id.ToString()), 'base': base_el.Name if base_el else None,
                     'top': top_el.Name if top_el else None, 'cx': cx, 'cy': cy})

    def key(d):
        return (round(d['cx'] / cluster_tolerance_ft) * cluster_tolerance_ft,
                round(d['cy'] / cluster_tolerance_ft) * cluster_tolerance_ft)

    clusters = {}
    for d in data:
        clusters.setdefault(key(d), []).append(d)
    for k, members in clusters.items():
        print("CORE @", k, "members:", [(m['id'], m['base'], m['top']) for m in members])
    return clusters


def target_views():
    """Views the script operates on, per TARGET_VIEW_MODE."""
    if TARGET_VIEW_MODE == 'name_suffix':
        out = []
        for v in FilteredElementCollector(doc).OfClass(ViewPlan).ToElements():
            if not v.IsTemplate and v.Name.endswith(TARGET_VIEW_NAME_SUFFIX):
                out.append(v)
        return out
    return [doc.GetElement(uv.ViewId) for uv in uidoc.GetOpenUIViews()]


def build_cores_auto():
    """Clusters every Stairs element into cores by plan-centroid X using
    the (trusted) base/top level params. Only for clean models — run
    discover_cores() first and compare against geometry."""
    cores = {}
    stairs = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Stairs).WhereElementIsNotElementType().ToElements()
    unassigned = []
    for s in stairs:
        bb = s.get_BoundingBox(None)
        if bb is None:
            continue
        cx = (bb.Min.X + bb.Max.X) / 2.0 * 0.3048
        base = s.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM)
        top = s.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM)
        b = doc.GetElement(base.AsElementId()) if base else None
        t = doc.GetElement(top.AsElementId()) if top else None
        if b is None or t is None or b.Name == t.Name:
            unassigned.append((int(s.Id.ToString()), b.Name if b else None, t.Name if t else None))
            continue
        hit = None
        for name, (x, tol) in AUTO_CORES_BY_X.items():
            if abs(cx - x) <= tol:
                hit = name
                break
        if hit is None:
            unassigned.append((int(s.Id.ToString()), b.Name, t.Name))
            continue
        cores.setdefault(hit, []).append((int(s.Id.ToString()), b.Name, t.Name))
    if unassigned:
        print("AUTO_CORES: %d stairs not assigned to any core (excluded from Up/Down map, sweep may still tag them):" % len(unassigned))
        for u in unassigned:
            print("   ", u)
    return cores


def ensure_types():
    """Duplicates each Stair Path family's plain 'Standard' type into any
    missing 'Standard <suffix>' variant. Must run inside a transaction."""
    made = []
    existing = get_type_lookup()
    for fam in ('Fixed Up Direction', 'Automatic Up/Down Direction'):
        base_id = existing.get((fam, 'Standard'))
        if base_id is None:
            print("ensure_types: no '%s : Standard' to duplicate from" % fam)
            continue
        base = doc.GetElement(base_id)
        for suf in AUTO_CREATE_SUFFIXES:
            tname = 'Standard ' + suf
            if (fam, tname) in existing:
                continue
            new_t = base.Duplicate(tname)
            existing[(fam, tname)] = new_t.Id
            made.append((fam, tname))
    return made


def resolve_base_top_maps():
    """Builds level -> [(core, stairId)] for Up (base_map) and Down
    (top_map), picking the highest ElementId when a core has duplicate
    flights sharing a base or top level."""
    base_map, top_map = {}, {}
    for core, members in CORES.items():
        by_base, by_top = {}, {}
        for sid, b, t in members:
            by_base.setdefault(b, []).append((sid, t))
            by_top.setdefault(t, []).append((sid, b))
        for lvl, lst in by_base.items():
            chosen = max(lst, key=lambda x: x[0])
            base_map.setdefault(lvl, []).append((core, chosen[0]))
        for lvl, lst in by_top.items():
            chosen = max(lst, key=lambda x: x[0])
            top_map.setdefault(lvl, []).append((core, chosen[0]))
    return base_map, top_map


def find_pass_through(level_name):
    """level -> {core: stairId} for any flight that genuinely spans
    through this level (base strictly below, top strictly above)."""
    idx = {n: i for i, n in enumerate(LEVEL_ORDER)}
    li = idx[level_name]
    result = {}
    for core, members in CORES.items():
        cands = [sid for sid, b, t in members if idx.get(b, -1) < li < idx.get(t, 999)]
        if cands:
            result[core] = max(cands)
    return result


def get_type_lookup():
    lookup = {}
    for f in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StairsPaths).WhereElementIsElementType().ToElements():
        fam = f.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME).AsString()
        tname = f.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
        lookup[(fam, tname)] = f.Id
    return lookup


def stair_axis(stair_id):
    """'X' if the stair's plan bbox is longer in X (length>=width), else 'Y'."""
    stair = doc.GetElement(eid(stair_id))
    bb = stair.get_BoundingBox(None)
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    return 'X' if dx >= dy else 'Y'


def start_run_direction_y(stair_id):
    """Sign of the Y-travel of the stair's own first flight (the run
    whose BaseElevation == 0), NOT GetStairsRuns() list order — that
    order is not guaranteed to match the physical up-sequence."""
    stair = doc.GetElement(eid(stair_id))
    first_run = None
    for rid in stair.GetStairsRuns():
        run = doc.GetElement(rid)
        if abs(getattr(run, 'BaseElevation', 1.0)) < 1e-6:
            first_run = run
            break
    if first_run is None:
        return 0
    curve = list(first_run.GetStairsPath())[0]
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
    return 1 if (p1.Y - p0.Y) > 0 else -1


def signed_offset_for_run_y(stair_id):
    """'Away from start' rule: if the stair's own start-run travels +Y,
    push the text -Y (and vice versa) by DIRECTIONAL_OFFSET_MM.
    NOTE: an earlier version of this also centered the X-component on
    the stair's true run width (see git/memory history) — tried on
    B005, then explicitly rejected by the user ("this step is not
    required") and reverted. Don't reintroduce that without being asked."""
    d = mm(DIRECTIONAL_OFFSET_MM)
    sign = -1 if start_run_direction_y(stair_id) > 0 else 1
    return XYZ(0, sign * d, 0)


def start_run_direction_x(stair_id):
    """Sign of the X-travel of the stair's own first flight (BaseElevation
    == 0 run) — same GetStairsRuns()-order caveat as the Y version."""
    stair = doc.GetElement(eid(stair_id))
    for rid in stair.GetStairsRuns():
        run = doc.GetElement(rid)
        if abs(getattr(run, 'BaseElevation', 1.0)) < 1e-6:
            curve = list(run.GetStairsPath())[0]
            p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
            return 1 if (p1.X - p0.X) > 0 else -1
    return 0


def signed_offset_for_run_x(stair_id, scale):
    """Per-direction, per-scale magnitude from
    DIRECTIONAL_X_OFFSET_MM_BY_DIR_SCALE — asymmetric by design (tuned
    live with the user on B003), NOT a mirrored +/- of one distance."""
    dir_sign = start_run_direction_x(stair_id)
    mags = DIRECTIONAL_X_OFFSET_MM_BY_DIR_SCALE.get(dir_sign, {})
    dist_mm = mags.get(scale)
    if dist_mm is None:
        return XYZ(0, 0, 0)
    return XYZ(mm(dist_mm), 0, 0)


def offset_vector(stair_id, level_name, scale):
    axis = stair_axis(stair_id)
    if axis == 'X' and (level_name in DIRECTIONAL_X_OVERRIDE_LEVELS or 'ALL' in DIRECTIONAL_X_OVERRIDE_LEVELS):
        return signed_offset_for_run_x(stair_id, scale)
    if axis == 'Y' and (level_name in DIRECTIONAL_OVERRIDE_LEVELS or 'ALL' in DIRECTIONAL_OVERRIDE_LEVELS):
        return signed_offset_for_run_y(stair_id)
    mags = OFFSET_MAGNITUDE_MM_BY_SCALE.get(scale)
    if not mags:
        return XYZ(0, 0, 0)
    dist = mm(mags[axis])
    return XYZ(dist, 0, 0) if axis == 'X' else XYZ(0, dist, 0)


def clear_existing_paths(views):
    existing = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StairsPaths).WhereElementIsNotElementType().ToElements()
    if CLEAR_SCOPE == 'targets':
        keep = set(str(v.Id) for v in views)
        existing = [e for e in existing if str(e.OwnerViewId) in keep]
    ids = [e.Id for e in existing]
    if ids:
        doc.Delete(List[ElementId](ids))
    return len(ids)


def create_paths(type_lookup, base_map, top_map, open_views):
    target_levels = set(base_map.keys()) | set(top_map.keys())
    created, fallback_used, truly_missing = [], 0, []

    for v in open_views:
        lvl = getattr(v, 'GenLevel', None)
        if not lvl or lvl.Name not in target_levels:
            continue
        level_name, scale = lvl.Name, v.Scale
        up_stairs = list(base_map.get(level_name, []))          # [(core, sid), ...]
        down_entries = list(top_map.get(level_name, []))        # [(core, sid), ...]

        visible_ids = None
        if 'Part Plan' in v.Name:
            coll = FilteredElementCollector(doc, v.Id).OfCategory(BuiltInCategory.OST_Stairs).WhereElementIsNotElementType().ToElements()
            visible_ids = set(int(e.Id.ToString()) for e in coll)
            up_stairs = [(c, s) for c, s in up_stairs if s in visible_ids]
            down_entries = [(c, s) for c, s in down_entries if s in visible_ids]

        pass_through = find_pass_through(level_name)

        if scale == 500:
            type_id = type_lookup[('Automatic Up/Down Direction', 'Standard 1-500')]
            for core, sid in up_stairs:
                try:
                    sp = StairsPath.Create(doc, LinkElementId(eid(sid)), type_id, v.Id)
                    sp.ShowUpText = False
                    sp.ShowDownText = False
                    created.append(sp)
                except Exception:
                    pass
            for core, sid in down_entries:
                try:
                    sp = StairsPath.Create(doc, LinkElementId(eid(sid)), type_id, v.Id)
                    sp.ShowUpText = False
                    sp.ShowDownText = False
                    created.append(sp)
                except Exception:
                    pt = pass_through.get(core)
                    if pt is not None:
                        try:
                            sp = StairsPath.Create(doc, LinkElementId(eid(pt)), type_id, v.Id)
                            sp.ShowUpText = False
                            sp.ShowDownText = False
                            created.append(sp)
                            fallback_used += 1
                        except Exception:
                            truly_missing.append((v.Name, level_name, scale, core, sid))
                    else:
                        truly_missing.append((v.Name, level_name, scale, core, sid))
        else:
            suffix = TYPE_SUFFIX_BY_SCALE[scale]
            up_type_id = type_lookup[('Fixed Up Direction', 'Standard ' + suffix)]
            down_type_id = type_lookup[('Automatic Up/Down Direction', 'Standard ' + suffix)]
            for core, sid in up_stairs:
                try:
                    sp = StairsPath.Create(doc, LinkElementId(eid(sid)), up_type_id, v.Id)
                    sp.ShowUpText = True
                    sp.UpTextOffset = offset_vector(sid, level_name, scale)
                    created.append(sp)
                except Exception:
                    pass
            for core, sid in down_entries:
                try:
                    sp = StairsPath.Create(doc, LinkElementId(eid(sid)), down_type_id, v.Id)
                    sp.ShowUpText = False
                    sp.ShowDownText = True
                    sp.DownTextOffset = offset_vector(sid, level_name, scale)
                    created.append(sp)
                except Exception:
                    pt = pass_through.get(core)
                    if pt is not None:
                        try:
                            sp = StairsPath.Create(doc, LinkElementId(eid(pt)), down_type_id, v.Id)
                            sp.ShowUpText = True
                            sp.ShowDownText = True
                            off = offset_vector(pt, level_name, scale)
                            sp.UpTextOffset = off
                            sp.DownTextOffset = off
                            created.append(sp)
                            fallback_used += 1
                        except Exception:
                            truly_missing.append((v.Name, level_name, scale, core, sid))
                    else:
                        truly_missing.append((v.Name, level_name, scale, core, sid))

    return created, fallback_used, truly_missing


def sweep_untagged_visible_stairs(type_lookup, open_views):
    """Catches bystander/duplicate stairs that are genuinely visible in
    an open view (incl. split Part 01/02 partial plans) but weren't part
    of any core's Up/Down map, and tags them Automatic Up/Down + both
    texts (or no text at 1:500) so nothing visible is left blank."""
    insts = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StairsPaths).WhereElementIsNotElementType().ToElements()
    by_view = {}
    for i in insts:
        by_view.setdefault(i.OwnerViewId, set()).add(int(i.StairsId.HostElementId.ToString()))

    fixed = []
    for v in open_views:
        lvl = getattr(v, 'GenLevel', None)
        if not lvl:
            continue
        scale = v.Scale
        coll = FilteredElementCollector(doc, v.Id).OfCategory(BuiltInCategory.OST_Stairs).WhereElementIsNotElementType().ToElements()
        if not coll:
            continue
        tagged = by_view.get(v.Id, set())
        for c in coll:
            sid = int(c.Id.ToString())
            if sid in tagged:
                continue
            suffix = TYPE_SUFFIX_BY_SCALE.get(scale, '1-100')
            type_id = type_lookup[('Automatic Up/Down Direction', 'Standard ' + suffix)]
            try:
                sp = StairsPath.Create(doc, LinkElementId(eid(sid)), type_id, v.Id)
                if scale == 500:
                    sp.ShowUpText = False
                    sp.ShowDownText = False
                else:
                    sp.ShowUpText = True
                    sp.ShowDownText = True
                    off = offset_vector(sid, lvl.Name, scale)
                    sp.UpTextOffset = off
                    sp.DownTextOffset = off
                fixed.append((v.Name, scale, sid))
            except Exception:
                pass
    return fixed


def fix_room_tag_collisions(views):
    nudge = mm(ROOM_TAG_NUDGE_MM)
    pad = mm(ROOM_TAG_OVERLAP_PAD_MM)
    insts = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StairsPaths).WhereElementIsNotElementType().ToElements()
    keep = set(str(v.Id) for v in views)
    moved = 0
    for i in insts:
        if str(i.OwnerViewId) not in keep:
            continue
        v = doc.GetElement(i.OwnerViewId)
        path_bb = i.get_BoundingBox(v)
        if path_bb is None:
            continue
        pmin = XYZ(path_bb.Min.X - pad, path_bb.Min.Y - pad, path_bb.Min.Z)
        pmax = XYZ(path_bb.Max.X + pad, path_bb.Max.Y + pad, path_bb.Max.Z)
        tags = FilteredElementCollector(doc, v.Id).OfCategory(BuiltInCategory.OST_RoomTags).WhereElementIsNotElementType().ToElements()
        for tag in tags:
            tbb = tag.get_BoundingBox(v)
            if tbb is None:
                continue
            overlap = not (tbb.Max.X < pmin.X or tbb.Min.X > pmax.X or tbb.Max.Y < pmin.Y or tbb.Min.Y > pmax.Y)
            if overlap:
                loc = tag.Location
                if hasattr(loc, 'Point'):
                    pt = loc.Point
                    loc.Point = XYZ(pt.X, pt.Y + nudge, pt.Z)
                    moved += 1
    return moved


def fix_staircase_room_tags():
    """Keeps Staircase room tags inside their room (not on/outside a
    wall). Any tag found outside its own room is reset to the room's
    own Location.Point, which Revit guarantees sits inside the room."""
    tags = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RoomTags).WhereElementIsNotElementType().ToElements()
    fixed = 0
    for tag in tags:
        room = tag.Room
        if room is None:
            continue
        rname = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() or ''
        if STAIRCASE_ROOM_KEYWORD not in rname.lower():
            continue
        loc = tag.Location
        if not hasattr(loc, 'Point'):
            continue
        tag_pt = loc.Point
        if room.IsPointInRoom(tag_pt):
            continue
        room_loc = room.Location
        if hasattr(room_loc, 'Point'):
            safe_pt = room_loc.Point
            loc.Point = XYZ(safe_pt.X, safe_pt.Y, tag_pt.Z)
            fixed += 1
    return fixed


def main():
    global CORES
    if AUTO_CORES_BY_X:
        CORES = build_cores_auto()
        print("AUTO_CORES built: " + ", ".join("%s=%d flights" % (k, len(v)) for k, v in CORES.items()))
    base_map, top_map = resolve_base_top_maps()
    views = target_views()
    print("Target views: %d (%s)" % (len(views), TARGET_VIEW_MODE))

    t = Transaction(doc, "Stair Path Direction Update")
    t.Start()
    made = ensure_types() if AUTO_CREATE_TYPES else []
    cleared = clear_existing_paths(views)
    type_lookup = get_type_lookup()
    created, fallback_used, truly_missing = create_paths(type_lookup, base_map, top_map, views)
    st = t.Commit()
    print("Main transaction:", st)

    t2 = Transaction(doc, "Stair Path Untagged-Visible Sweep")
    t2.Start()
    swept = sweep_untagged_visible_stairs(type_lookup, views)
    t2.Commit()

    t3 = Transaction(doc, "Stair Path Room Tag Fixes")
    t3.Start()
    nudged = fix_room_tag_collisions(views)
    fixed = fix_staircase_room_tags()
    t3.Commit()

    if SAVE_AFTER_RUN:
        try:
            doc.Save()
        except Exception as e:
            print("Save skipped:", e)
    if made:
        print("Created Stair Path types: %s" % made)
    print("Cleared %d existing paths (%s scope)" % (cleared, CLEAR_SCOPE))
    print("Created %d new stair path annotations (%d via pass-through fallback)" % (len(created), fallback_used))
    print("Swept %d untagged-but-visible bystander stairs" % len(swept))
    for w in swept:
        print("   sweep:", w)
    if truly_missing:
        print("Genuinely unresolvable (no pass-through, needs View Range/template change):")
        for m in truly_missing:
            print("  ", m)
    print("Nudged %d overlapping room tags" % nudged)
    print("Fixed %d staircase room tags (moved back inside room, clear of walls)" % fixed)


main()

# -*- coding: utf-8 -*-
r"""
Apply a standard model's MATERIAL GRAPHICS (hatches) to the materials used by the
USED wall types of one or more target models.

Run this inside Revit through the Revit MCP `execute_revit_code` tool (IronPython 2.7):
paste the file, or exec() it. Everything configurable lives in the CONFIG block below.

  SOURCE_JSON   dump of every material in the standard model, produced by the companion
                dump in this session ( exports\_src_podium_materials.json ).
  TARGETS       document titles to change. Each must be OPEN in this Revit session
                (they are bound by title, never by the active view - see MultiModelBatch).
  EXTRA_MAP     target material name -> standard material name, for materials that have
                no same-name counterpart in the standard model (a human decision).
  DRY_RUN       True prints what would change and writes nothing. Set False to commit.

What it changes on a material (graphics only - no wall type or layer edits):
  cut foreground/background pattern + colour, surface foreground/background pattern +
  colour, shading colour, transparency, material class, UseRenderAppearanceForShading.
Fill patterns are matched BY NAME in the target document; a pattern that does not exist
there is reported and that one property is skipped (nothing is created).
"""
import json

# ------------------------------------------------------------------ CONFIG ---
SOURCE_JSON = r"C:\SK\OneDrive\Netbuild\exports\_src_podium_materials.json"
SOURCE_WALLS_JSON = r"C:\SK\OneDrive\Netbuild\exports\_src_podium_walls.json"   # disambiguates duplicate material names
TARGETS = ["3505-ProjectG-Studio-ARC-RVT-00001", "3505-ProjectG-Studio-ARC-RVT-00002"]
EXTRA_MAP = {
    "Studio_Wall_Dry Wall": "Studio_Gypsum Board",
    "HBA-Indicative - Wall": "Studio_Gypsum Board",
}
SKIP = ["HBA-Indicative - Wall 25mm ID Finish"]   # target material names to leave untouched
DRY_RUN = True            # False = commit (one transaction per document)
# Known limit: with UseRenderAppearanceForShading on, Revit derives the shading colour and
# transparency from the material's render appearance ASSET, which this script does not copy
# between documents - so those two properties can still read differently afterwards
# (e.g. "[Studio] glass" in TA-00001/00002, 2026-09-22). The cut/surface patterns are unaffected.
# ------------------------------------------------------------------------------

try:
    from Autodesk.Revit import DB
except ImportError:
    pass


def _nm(e):
    return DB.Element.Name.__get__(e) if e else ""


def _color(rgb):
    return DB.Color(rgb[0], rgb[1], rgb[2]) if rgb else None


def _same_color(c, rgb):
    if rgb is None:
        return c is None or not c.IsValid
    try:
        return c is not None and c.IsValid and [int(c.Red), int(c.Green), int(c.Blue)] == list(rgb)
    except Exception:
        return False


def _patterns(tdoc):
    out = {}
    for fp in DB.FilteredElementCollector(tdoc).OfClass(DB.FillPatternElement).ToElements():
        out[_nm(fp)] = fp.Id
    return out


def used_wall_materials(tdoc):
    """{material name: Material} for every layer material of every PLACED wall type."""
    out = {}
    for w in DB.FilteredElementCollector(tdoc).OfCategory(DB.BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements():
        if not isinstance(w, DB.Wall):
            continue
        cs = w.WallType.GetCompoundStructure()
        if cs is None:
            continue
        for L in cs.GetLayers():
            if L.MaterialId != DB.ElementId.InvalidElementId:
                m = tdoc.GetElement(L.MaterialId)
                if m is not None:
                    out[_nm(m)] = m
    return out


def plan_for(tdoc, std_by_name):
    """[(material, standard dict, [(property, from, to)])] - what would change."""
    pats = _patterns(tdoc)
    plan = []
    for name, m in sorted(used_wall_materials(tdoc).items()):
        if name in SKIP:
            continue
        std = std_by_name.get(EXTRA_MAP.get(name, name))
        if std is None:
            plan.append((m, None, [("no standard material named '%s'" % EXTRA_MAP.get(name, name), "", "")]))
            continue
        changes = []
        pat_props = (("cut fg", "CutForegroundPatternId", "cut_fg"), ("cut bg", "CutBackgroundPatternId", "cut_bg"),
                     ("surface fg", "SurfaceForegroundPatternId", "surface_fg"), ("surface bg", "SurfaceBackgroundPatternId", "surface_bg"))
        for label, prop, key in pat_props:
            cur_id = getattr(m, prop)
            cur = _nm(tdoc.GetElement(cur_id)) if cur_id != DB.ElementId.InvalidElementId else None
            want = std.get(key)
            if cur == want:
                continue
            if want is not None and want not in pats:
                changes.append(("%s pattern MISSING in target" % label, cur or "-", want))
                continue
            changes.append((label + " pattern", cur or "-", want or "-"))
        col_props = (("cut fg colour", "CutForegroundPatternColor", "cut_fg_color"),
                     ("cut bg colour", "CutBackgroundPatternColor", "cut_bg_color"),
                     ("surface fg colour", "SurfaceForegroundPatternColor", "surface_fg_color"),
                     ("surface bg colour", "SurfaceBackgroundPatternColor", "surface_bg_color"),
                     ("shading colour", "Color", "color"))
        for label, prop, key in col_props:
            if not _same_color(getattr(m, prop), std.get(key)):
                cur = getattr(m, prop)
                cur_txt = "%s" % ([int(cur.Red), int(cur.Green), int(cur.Blue)] if cur and cur.IsValid else None)
                changes.append((label, cur_txt, "%s" % std.get(key)))
        if int(m.Transparency) != int(std.get("transparency", m.Transparency)):
            changes.append(("transparency", m.Transparency, std["transparency"]))
        if (m.MaterialClass or "") != (std.get("material_class") or ""):
            changes.append(("class", m.MaterialClass or "-", std.get("material_class") or "-"))
        if bool(m.UseRenderAppearanceForShading) != bool(std.get("use_render")):
            changes.append(("use render appearance", m.UseRenderAppearanceForShading, std.get("use_render")))
        plan.append((m, std, changes))
    return plan, pats


def apply_plan(tdoc, plan, pats):
    n = 0
    t = DB.Transaction(tdoc, "Apply standard wall material hatches")
    t.Start()
    try:
        for m, std, changes in plan:
            if std is None or not changes:
                continue
            for label, prop, key in (("cut fg", "CutForegroundPatternId", "cut_fg"), ("cut bg", "CutBackgroundPatternId", "cut_bg"),
                                     ("surface fg", "SurfaceForegroundPatternId", "surface_fg"), ("surface bg", "SurfaceBackgroundPatternId", "surface_bg")):
                want = std.get(key)
                if want is not None and want not in pats:
                    continue                                  # reported in the plan, never created
                setattr(m, prop, pats[want] if want else DB.ElementId.InvalidElementId)
            for prop, key in (("CutForegroundPatternColor", "cut_fg_color"), ("CutBackgroundPatternColor", "cut_bg_color"),
                              ("SurfaceForegroundPatternColor", "surface_fg_color"), ("SurfaceBackgroundPatternColor", "surface_bg_color"),
                              ("Color", "color")):
                c = _color(std.get(key))
                if c is not None:
                    setattr(m, prop, c)
            m.Transparency = int(std.get("transparency", m.Transparency))
            if std.get("material_class"):
                m.MaterialClass = std["material_class"]
            m.UseRenderAppearanceForShading = bool(std.get("use_render"))
            n += 1
        status = t.Commit()
    except Exception:
        t.RollBack()
        raise
    return n, str(status)


def main(doc):
    import io
    with io.open(SOURCE_JSON, "r", encoding="utf-8") as fh:
        S = json.loads(fh.read())
    # A material name is NOT unique in this dump: the Podium model returns 16 duplicated
    # names ("Glass" exists once as the real material and 14 more times as the default
    # blue stub). Pick deterministically - a material the standard model actually uses on
    # its walls wins, then a real class, then one carrying patterns, then the lowest id.
    wall_mat_names = set()
    try:
        with io.open(SOURCE_WALLS_JSON, "r", encoding="utf-8") as fh:
            for t in json.loads(fh.read())["types"]:
                for L in t["layers"]:
                    if L.get("material"):
                        wall_mat_names.add(L["material"])
    except Exception as e:
        print("    (could not read SOURCE_WALLS_JSON: %s)" % e)

    def rank(v):
        r = 0
        if v["name"] in wall_mat_names:
            r += 100
        if (v.get("material_class") or "Unassigned") != "Unassigned":
            r += 10
        if any(v.get(k) for k in ("cut_fg", "cut_bg", "surface_fg", "surface_bg")):
            r += 5
        return (r, -int(v["id"]))

    std_by_name = {}
    for v in S["materials"].values():
        cur = std_by_name.get(v["name"])
        if cur is None or rank(v) > rank(cur):
            std_by_name[v["name"]] = v
    print("STANDARD: %s (%d materials)   %s" % (S["doc"], len(std_by_name), "DRY RUN" if DRY_RUN else "APPLY"))
    open_docs = dict((d.Title, d) for d in doc.Application.Documents if not d.IsLinked)
    for title in TARGETS:
        tdoc = open_docs.get(title)
        print("\n=== %s" % title)
        if tdoc is None:
            print("    NOT OPEN in this Revit session - skipped (open docs: %s)" % ", ".join(sorted(open_docs)))
            continue
        plan, pats = plan_for(tdoc, std_by_name)
        touched = [p for p in plan if p[1] is not None and p[2]]
        for m, std, changes in plan:
            if std is None:
                print("    %-34s -> %s" % (_nm(m), changes[0][0]))
            elif not changes:
                print("    %-34s -> already standard" % _nm(m))
            else:
                print("    %-34s -> from '%s'" % (_nm(m), std["name"]))
                for label, a, b in changes:
                    print("         %-28s %s -> %s" % (label, a, b))
        if DRY_RUN:
            print("    DRY RUN: %d of %d materials would change. Nothing written." % (len(touched), len(plan)))
        else:
            n, status = apply_plan(tdoc, plan, pats)
            print("    APPLIED to %d materials, transaction %s" % (n, status))


main(doc)

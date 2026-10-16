# view3d_camera_profile.py
#
# Save 3D views to a JSON profile and put them back later: camera (eye / up /
# forward), crop box, section box, lock state, instance parameters, the window
# zoom of the views that are open on screen, and the full settings of the view
# templates those views use (parameters, controlled parameters, category V/G,
# filters, worksets, link overrides, graphic display options).
#
# Two modes:
#   MODE = "capture"  -> read the views whose name starts with NAME_PREFIX, write
#                        PROFILE_PATH (JSON). Changes nothing in the model.
#   MODE = "restore"  -> read PROFILE_PATH and put the views (and, with
#                        RESTORE_TEMPLATES, their templates) back.
#                        DRY_RUN = True lists every difference and changes nothing.
#
# Views and templates are matched by NAME; categories by "parent/name"; filters,
# worksets, links and patterns by name. A deleted view is recreated
# (CREATE_MISSING_VIEWS), a deleted template is recreated from one of its views.
#
# Run via Revit MCP `execute_revit_code` (IronPython, pyRevit). `doc`, `uidoc`
# and `DB` are provided. Everything tunable lives in the CONFIG block - do not
# hardcode elsewhere.

import os
import json
import datetime
import System
from System.Collections.Generic import List
from Autodesk.Revit.DB import IFailuresPreprocessor, FailureProcessingResult, FailureSeverity

# ----------------------------------------------------------------- CONFIG ---
MODE = "restore"                    # "capture" | "restore"
DRY_RUN = True                      # restore: True = list differences only, change nothing

EXPECTED_DOC_TITLE = "ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001"   # refuse any other model ("" = no check)
NAME_PREFIX = "Enscape View"        # 3D views whose name starts with this
ONLY_VIEWS = []                     # restore: if non-empty, only these exact view names
PROFILE_PATH = r"C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profiles\SW0O_BM-950001_Enscape_Views.json"

# capture
OVERWRITE_PROFILE = False           # True = replace an existing profile (old one kept as .bak_<time>.json)
CAPTURE_TEMPLATES = True            # also save every view template the views use
CAPTURE_ZOOM = True                 # save the window zoom of the views OPEN on screen
                                    # (closed views keep the zoom stored in the old profile)

# restore
RESTORE_CAMERA = True               # eye / up / forward (unlock -> set -> lock again)
RESTORE_CROP = True                 # crop box + Crop View / Crop Region Visible
RESTORE_SECTION_BOX = True          # section box on/off + box
RESTORE_PARAMETERS = True           # writable instance parameters (template, phase, far clip, ...)
CREATE_MISSING_VIEWS = True         # recreate a profile view that no longer exists
RESTORE_TEMPLATES = False           # also write the saved template settings back
RESTORE_ZOOM = True                 # zoom the views that are open on screen (UI only)
OPEN_VIEWS_FOR_ZOOM = False         # also open closed views to zoom them; Enscape re-processes
                                    # each view that becomes active, so leave False unless asked
# -----------------------------------------------------------------------------

FT = 304.8
TOL = 1e-6                          # feet / unit vectors
ZOOM_TOL_MM = 1.0
INVALID = DB.ElementId.InvalidElementId

# view parameters the parameter pass never writes (handled elsewhere or derived)
VIEW_SKIP = set([
    "VIEW_NAME", "ELEM_FAMILY_PARAM", "ELEM_FAMILY_AND_TYPE_PARAM", "ELEM_TYPE_PARAM",
    "VIEW_TEMPLATE_FOR_SCHEDULE", "VIEWER_EYE_ELEVATION", "VIEWER_TARGET_ELEVATION",
    "VIEWER_CROP_REGION", "VIEWER_CROP_REGION_VISIBLE", "VIEWER_MODEL_CLIP_BOX_ACTIVE",
    "VIEW_FIXED_SKETCH_PLANE", "VIEW_POSITION", "VIEW_CAMERA_ORIENTATION", "VIEWER_PERSPECTIVE",
    "ELEM_PARTITION_PARAM"])
TEMPLATE_SKIP = set([
    "VIEW_NAME", "ELEM_FAMILY_PARAM", "ELEM_FAMILY_AND_TYPE_PARAM", "ELEM_TYPE_PARAM",
    "VIEW_TEMPLATE_FOR_SCHEDULE", "VIEW_TEMPLATE", "ELEM_PARTITION_PARAM", "VIEW_POSITION"])
# write these first: the template locks other parameters, far clip unlocks its offset,
# a scope box drives the crop
PARAM_ORDER = {"VIEW_TEMPLATE": 0, "VIEWER_BOUND_ACTIVE_FAR": 1, "VIEWER_VOLUME_OF_INTEREST_CROP": 2}

OGS = [  # (getter, setter, kind) of OverrideGraphicSettings
    ("ProjectionLinePatternId", "SetProjectionLinePatternId", "lpat"),
    ("ProjectionLineColor", "SetProjectionLineColor", "color"),
    ("ProjectionLineWeight", "SetProjectionLineWeight", "pen"),
    ("SurfaceForegroundPatternId", "SetSurfaceForegroundPatternId", "fpat"),
    ("SurfaceForegroundPatternColor", "SetSurfaceForegroundPatternColor", "color"),
    ("IsSurfaceForegroundPatternVisible", "SetSurfaceForegroundPatternVisible", "on"),
    ("SurfaceBackgroundPatternId", "SetSurfaceBackgroundPatternId", "fpat"),
    ("SurfaceBackgroundPatternColor", "SetSurfaceBackgroundPatternColor", "color"),
    ("IsSurfaceBackgroundPatternVisible", "SetSurfaceBackgroundPatternVisible", "on"),
    ("CutLinePatternId", "SetCutLinePatternId", "lpat"),
    ("CutLineColor", "SetCutLineColor", "color"),
    ("CutLineWeight", "SetCutLineWeight", "pen"),
    ("CutForegroundPatternId", "SetCutForegroundPatternId", "fpat"),
    ("CutForegroundPatternColor", "SetCutForegroundPatternColor", "color"),
    ("IsCutForegroundPatternVisible", "SetCutForegroundPatternVisible", "on"),
    ("CutBackgroundPatternId", "SetCutBackgroundPatternId", "fpat"),
    ("CutBackgroundPatternColor", "SetCutBackgroundPatternColor", "color"),
    ("IsCutBackgroundPatternVisible", "SetCutBackgroundPatternVisible", "on"),
    ("Transparency", "SetSurfaceTransparency", "int"),
    ("Halftone", "SetHalftone", "off"),
    ("DetailLevel", "SetDetailLevel", "detail"),
]
LINK_ENUMS = ["LinkVisibilityType", "ObjectStyles", "ViewFilterType", "ColorFill", "NestedLinks", "ViewRange"]
HIDDEN_FLAGS = ["AreModelCategoriesHidden", "AreAnnotationCategoriesHidden", "AreImportCategoriesHidden",
                "AreAnalyticalModelCategoriesHidden", "ArePointCloudsHidden"]


class SwallowWarnings(IFailuresPreprocessor):
    """Delete warnings so a warning cannot silently roll the transaction back
    in a headless MCP call; errors are recorded and left to Revit."""

    def __init__(self):
        self.seen = []

    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            try:
                self.seen.append(f.GetDescriptionText())
            except Exception:
                self.seen.append("?")
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
        return FailureProcessingResult.Continue


# ------------------------------------------------------------------ helpers ---
def eid(e_id):
    # Revit 2026 dropped ElementId.IntegerValue
    return int(e_id.Value)


def mk_id(n):
    return DB.ElementId(System.Int64(int(n)))


def name_of(e):
    if e is None:
        return None
    try:
        n = e.Name
        if n:
            return n
    except Exception:
        pass
    p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)   # ElementType.Name in IronPython
    return p.AsString() if p else None


def el_name(e_id):
    if e_id is None or e_id == INVALID:
        return None
    return name_of(doc.GetElement(e_id))


def js(o, ind=0):
    # own JSON writer: IronPython's json chokes on non-ASCII (m2 etc.)
    sp = "  " * ind
    if o is None:
        return "null"
    if isinstance(o, bool):
        return "true" if o else "false"
    if isinstance(o, (int, long)):
        return str(o)
    if isinstance(o, float):
        return repr(round(o, 9))
    if isinstance(o, dict):
        if not o:
            return "{}"
        return "{\n" + ",\n".join(sp + "  " + js(str(k)) + ": " + js(o[k], ind + 1) for k in o.keys()) + "\n" + sp + "}"
    if isinstance(o, (list, tuple)):
        if not o:
            return "[]"
        if all(isinstance(x, (int, long, float)) and not isinstance(x, bool) for x in o):
            return "[" + ", ".join(js(x) for x in o) + "]"
        return "[\n" + ",\n".join(sp + "  " + js(x, ind + 1) for x in o) + "\n" + sp + "]"
    r = []
    for c in unicode(o):
        n = ord(c)
        if c == '"':
            r.append('\\"')
        elif c == '\\':
            r.append('\\\\')
        elif c == '\n':
            r.append('\\n')
        elif c == '\r':
            r.append('\\r')
        elif c == '\t':
            r.append('\\t')
        elif n < 32 or n > 126:
            r.append('\\u%04x' % n)
        else:
            r.append(c)
    return '"' + "".join(r) + '"'


def xyz(p):
    return [p.X, p.Y, p.Z]


def xyz_mm(p):
    return [round(p.X * FT, 3), round(p.Y * FT, 3), round(p.Z * FT, 3)]


def to_xyz(a):
    return DB.XYZ(a[0], a[1], a[2])


def gap(a, b):
    # max abs component difference between an XYZ and a saved [x, y, z]
    return max(abs(a.X - b[0]), abs(a.Y - b[1]), abs(a.Z - b[2]))


def tf(t):
    return {"origin_ft": xyz(t.Origin), "origin_mm": xyz_mm(t.Origin),
            "basis_x": xyz(t.BasisX), "basis_y": xyz(t.BasisY), "basis_z": xyz(t.BasisZ)}


def box(b):
    if b is None:
        return None
    return {"min_ft": xyz(b.Min), "max_ft": xyz(b.Max), "min_mm": xyz_mm(b.Min), "max_mm": xyz_mm(b.Max),
            "enabled": b.Enabled, "transform": tf(b.Transform)}


def box_from(d):
    bb = DB.BoundingBoxXYZ()
    t = DB.Transform(DB.Transform.Identity)
    tr = d["transform"]
    t.Origin = to_xyz(tr["origin_ft"])
    t.BasisX = to_xyz(tr["basis_x"])
    t.BasisY = to_xyz(tr["basis_y"])
    t.BasisZ = to_xyz(tr["basis_z"])
    bb.Transform = t
    bb.Min = to_xyz(d["min_ft"])
    bb.Max = to_xyz(d["max_ft"])
    bb.Enabled = d.get("enabled", True)
    return bb


def box_gap(b, d):
    if b is None or d is None:
        return 0.0 if b is None and d is None else 1e9
    t, tr = b.Transform, d["transform"]
    return max(gap(b.Min, d["min_ft"]), gap(b.Max, d["max_ft"]), gap(t.Origin, tr["origin_ft"]),
               gap(t.BasisX, tr["basis_x"]), gap(t.BasisY, tr["basis_y"]), gap(t.BasisZ, tr["basis_z"]))


def enum_parse(sample, text):
    # parse "Custom" into the same enum type as `sample`
    return System.Enum.Parse(sample.GetType(), text)


def ws_blocked(e):
    """Reason this element cannot be written in a workshared model, else None."""
    if not doc.IsWorkshared:
        return None
    if DB.WorksharingUtils.GetCheckoutStatus(doc, e.Id) == DB.CheckoutStatus.OwnedByOtherUser:
        return "owned by %s" % DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, e.Id).Owner
    st = DB.WorksharingUtils.GetModelUpdatesStatus(doc, e.Id)
    if st in (DB.ModelUpdatesStatus.UpdatedInCentral, DB.ModelUpdatesStatus.DeletedInCentral):
        return "%s - reload latest first" % st
    return None


def run_tx(name, fn):
    """One transaction with a warning swallower; returns (status, warnings, error)."""
    t = DB.Transaction(doc, name)
    opts = t.GetFailureHandlingOptions()
    sw = SwallowWarnings()
    opts.SetFailuresPreprocessor(sw)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    try:
        fn()
    except Exception as ex:
        t.RollBack()
        return "RolledBack", sw.seen, str(ex)
    return str(t.Commit()), sw.seen, None


# --------------------------------------------------------------- parameters ---
def params(e):
    out = []
    for p in e.Parameters:
        d = p.Definition
        rec = {"name": d.Name, "id": eid(p.Id), "storage": str(p.StorageType),
               "read_only": p.IsReadOnly, "has_value": p.HasValue}
        try:
            bip = d.BuiltInParameter
            if bip != DB.BuiltInParameter.INVALID:
                rec["builtin"] = str(bip)
        except Exception:
            pass
        try:
            if p.IsShared:
                rec["shared_guid"] = str(p.GUID)
        except Exception:
            pass
        st = p.StorageType
        if st == DB.StorageType.Double:
            rec["raw"] = p.AsDouble()
        elif st == DB.StorageType.Integer:
            rec["raw"] = p.AsInteger()
        elif st == DB.StorageType.String:
            rec["raw"] = p.AsString()
        elif st == DB.StorageType.ElementId:
            i = p.AsElementId()
            rec["raw"] = eid(i)
            rec["element_name"] = el_name(i)
        try:
            rec["display"] = p.AsValueString()
        except Exception:
            pass
        out.append(rec)
    out.sort(key=lambda r: r["name"])
    return out


def find_param(e, rec):
    b = rec.get("builtin")
    if b:
        try:
            return e.get_Parameter(getattr(DB.BuiltInParameter, b))
        except Exception:
            return None
    g = rec.get("shared_guid")
    if g:
        p = e.get_Parameter(System.Guid(g))
        if p:
            return p
    for p in e.Parameters:
        if p.Definition.Name == rec["name"] and str(p.StorageType) == rec["storage"]:
            return p
    return None


def by_name(builtin, nm):
    """Find the element an ElementId parameter pointed to, by name."""
    if builtin in ("VIEW_TEMPLATE", "VIEW_TEMPLATE_FOR_SCHEDULE"):
        pool = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if v.IsTemplate]
    elif builtin == "VIEW_PHASE":
        pool = DB.FilteredElementCollector(doc).OfClass(DB.Phase)
    elif builtin == "VIEW_PHASE_FILTER":
        pool = DB.FilteredElementCollector(doc).OfClass(DB.PhaseFilter)
    elif builtin == "VIEWER_VOLUME_OF_INTEREST_CROP":
        pool = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType()
    else:
        return None
    for x in pool:
        if name_of(x) == nm:
            return x.Id
    return None


def resolve_id(rec):
    raw, nm = rec.get("raw"), rec.get("element_name")
    if raw is None or raw == -1:
        return INVALID
    e = doc.GetElement(mk_id(raw))
    if e is not None and (nm is None or name_of(e) == nm):
        return e.Id
    if nm:
        return by_name(rec.get("builtin"), nm)
    return None


def sync_params(e, recs, skip, write, out):
    """Compare (and with write, set) every writable saved parameter."""
    seen = set()
    for rec in sorted(recs, key=lambda r: (PARAM_ORDER.get(r.get("builtin"), 50), r["name"])):
        b = rec.get("builtin")
        if rec["storage"] == "None" or b in skip or rec.get("read_only"):
            continue
        key = b or rec.get("shared_guid") or rec["name"]
        if key in seen:
            continue
        seen.add(key)
        p = find_param(e, rec)
        if p is None:
            out.append("param '%s': not on this element" % rec["name"])
            continue
        if p.IsReadOnly:
            continue
        st = rec["storage"]
        want = None
        if st == "ElementId":
            want = resolve_id(rec)
            if want is None:
                out.append("param '%s': '%s' not found in model - skipped" % (rec["name"], rec.get("element_name")))
                continue
            same = eid(p.AsElementId()) == eid(want)
            now = el_name(p.AsElementId()) or eid(p.AsElementId())
            was = rec.get("element_name") or rec.get("raw")
        elif st == "Double":
            same = abs(p.AsDouble() - rec["raw"]) < TOL
            now, was = p.AsValueString(), rec.get("display")
        elif st == "Integer":
            same = p.AsInteger() == rec["raw"]
            now, was = p.AsValueString(), rec.get("display")
        else:
            same = (p.AsString() or "") == (rec["raw"] or "")
            now, was = p.AsString(), rec["raw"]
        if same:
            continue
        out.append("param '%s': %s -> %s" % (rec["name"], now, was))
        if write:
            try:
                if st == "ElementId":
                    p.Set(want)
                elif st == "Double":
                    p.Set(float(rec["raw"]))
                elif st == "Integer":
                    p.Set(int(rec["raw"]))
                else:
                    p.Set(rec["raw"] or "")
            except Exception as ex:
                out.append("  FAILED: %s" % ex)


# -------------------------------------------------------------------- views ---
def target_views():
    vs = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D)
          if not v.IsTemplate and v.Name.startswith(NAME_PREFIX)]
    return sorted(vs, key=lambda v: v.Name)


def find_view(nm):
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if not v.IsTemplate and v.Name == nm:
            return v
    return None


def find_template(nm):
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if v.IsTemplate and v.Name == nm:
            return v
    return None


def find_vft(nm):
    for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if t.ViewFamily == DB.ViewFamily.ThreeDimensional and name_of(t) == nm:
            return t
    return None


def view_rec(v, zoom):
    o = v.GetOrientation()
    vft = doc.GetElement(v.GetTypeId())
    r = {"name": v.Name, "element_id": eid(v.Id), "view_family_type": name_of(vft),
         "is_perspective": v.IsPerspective, "is_locked": v.IsLocked, "can_be_locked": v.CanBeLocked(),
         "camera": {"eye_position_ft": xyz(o.EyePosition), "eye_position_mm": xyz_mm(o.EyePosition),
                    "up_direction": xyz(o.UpDirection), "forward_direction": xyz(o.ForwardDirection)},
         "crop_box_active": v.CropBoxActive, "crop_box_visible": v.CropBoxVisible, "crop_box": box(v.CropBox),
         "section_box_active": v.IsSectionBoxActive,
         "section_box": box(v.GetSectionBox()) if v.IsSectionBoxActive else None,
         "scale": v.Scale, "detail_level": str(v.DetailLevel), "display_style": str(v.DisplayStyle),
         "discipline": str(v.Discipline), "view_template": el_name(v.ViewTemplateId),
         "phase": None, "extensible_storage_schemas": [str(g) for g in v.GetEntitySchemaGuids()],
         "zoom": zoom.get(v.Name), "parameters": params(v)}
    ph = v.get_Parameter(DB.BuiltInParameter.VIEW_PHASE)
    if ph:
        r["phase"] = el_name(ph.AsElementId())
    try:
        bg = v.GetBackground()
        r["background"] = str(bg.Type) if bg else None
    except Exception:
        r["background"] = None
    try:
        ss = v.SunAndShadowSettings
        if ss:
            r["sun_and_shadow"] = {"style": str(ss.SunAndShadowType), "name": ss.Name}
    except Exception:
        pass
    return r


def restore_view(v, rec, write, out):
    """Compare a view with its record; with write, set what differs.
    Must run inside a transaction when write is True."""
    if not write and v is None:
        out.append("view missing - would be created (CREATE_MISSING_VIEWS)")
        return
    vft = find_vft(rec["view_family_type"])
    if vft is None:
        out.append("view type '%s' not in model - type left as is" % rec["view_family_type"])
    elif eid(v.GetTypeId()) != eid(vft.Id):
        out.append("type: %s -> %s" % (name_of(doc.GetElement(v.GetTypeId())), rec["view_family_type"]))
        if write:
            v.ChangeTypeId(vft.Id)
    if v.IsPerspective != rec["is_perspective"]:
        out.append("projection: %s -> %s" % ("perspective" if v.IsPerspective else "orthographic",
                                             "perspective" if rec["is_perspective"] else "orthographic"))
        if write and v.IsLocked:
            v.Unlock()
        if write and v.CanToggleBetweenPerspectiveAndIsometric():
            if rec["is_perspective"]:
                v.ToggleToPerspective()
            else:
                v.ToggleToIsometric()
    if RESTORE_PARAMETERS:
        sync_params(v, rec["parameters"], VIEW_SKIP, write, out)

    c = rec["camera"]
    o = v.GetOrientation()
    cam = RESTORE_CAMERA and max(gap(o.EyePosition, c["eye_position_ft"]), gap(o.UpDirection, c["up_direction"]),
                                 gap(o.ForwardDirection, c["forward_direction"])) > TOL
    crop_box_diff = rec["crop_box"] is not None and box_gap(v.CropBox, rec["crop_box"]) > TOL
    crop = RESTORE_CROP and (crop_box_diff or v.CropBoxActive != rec["crop_box_active"]
                             or v.CropBoxVisible != rec["crop_box_visible"])
    sb = RESTORE_SECTION_BOX and (v.IsSectionBoxActive != rec["section_box_active"] or (
        rec["section_box_active"] and box_gap(v.GetSectionBox(), rec["section_box"]) > TOL))
    if cam:
        out.append("camera: eye %s -> %s mm" % (xyz_mm(o.EyePosition), c["eye_position_mm"]))
    if crop:
        out.append("crop: active %s->%s, visible %s->%s, box %s" % (
            v.CropBoxActive, rec["crop_box_active"], v.CropBoxVisible, rec["crop_box_visible"],
            "differs" if crop_box_diff else "same"))
    if sb:
        out.append("section box: active %s -> %s" % (v.IsSectionBoxActive, rec["section_box_active"]))
    if write and v.IsLocked and (cam or crop or sb):
        v.Unlock()
    if write and cam:
        v.SetOrientation(DB.ViewOrientation3D(to_xyz(c["eye_position_ft"]), to_xyz(c["up_direction"]),
                                              to_xyz(c["forward_direction"])))
    if write and crop:
        if crop_box_diff or cam:
            v.CropBox = box_from(rec["crop_box"])
        v.CropBoxActive = rec["crop_box_active"]
        v.CropBoxVisible = rec["crop_box_visible"]
    if write and sb:
        if rec["section_box_active"]:
            v.SetSectionBox(box_from(rec["section_box"]))
        else:
            v.IsSectionBoxActive = False
    if v.IsLocked != rec["is_locked"] or (write and rec["is_locked"] and (cam or crop or sb)):
        if v.IsLocked != rec["is_locked"]:
            out.append("lock: %s -> %s" % (v.IsLocked, rec["is_locked"]))
        if write:
            if rec["is_locked"]:
                v.SaveOrientationAndLock()
            elif v.IsLocked:
                v.Unlock()


# ---------------------------------------------------------------- templates ---
def pattern_ref(pid, kind):
    if pid is None or pid == INVALID:
        return None
    e = doc.GetElement(pid)
    d = {"id": eid(pid), "name": name_of(e)}
    if kind == "fpat" and isinstance(e, DB.FillPatternElement):
        d["target"] = str(e.GetFillPattern().Target)
    return d


def pattern_id(d, kind):
    e = doc.GetElement(mk_id(d["id"]))
    if e is not None and (d.get("name") is None or name_of(e) == d["name"]):
        return e.Id
    if d.get("name") is None:
        return mk_id(d["id"])              # built-in pattern (e.g. solid line) has no element
    if kind == "fpat":
        tgt = getattr(DB.FillPatternTarget, d.get("target", "Drafting"))
        e = DB.FillPatternElement.GetFillPatternElementByName(doc, tgt, d["name"])
    else:
        e = DB.LinePatternElement.GetLinePatternElementByName(doc, d["name"])
    return e.Id if e is not None else None


def ogs_to(o):
    d = {}
    for g, s, k in OGS:
        val = getattr(o, g)
        if k in ("lpat", "fpat"):
            if val != INVALID:
                d[g] = pattern_ref(val, k)
        elif k == "color":
            if val.IsValid:
                d[g] = [int(val.Red), int(val.Green), int(val.Blue)]
        elif k == "pen":
            if val != DB.OverrideGraphicSettings.InvalidPenNumber:
                d[g] = int(val)
        elif k == "on":
            if not val:
                d[g] = False
        elif k == "off":
            if val:
                d[g] = True
        elif k == "int":
            if val:
                d[g] = int(val)
        elif k == "detail":
            if val != DB.ViewDetailLevel.Undefined:
                d[g] = str(val)
    return d


def ogs_key(d):
    # comparable form: patterns by name (or id when unnamed)
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out[str(k)] = v.get("name") or v.get("id")
        elif isinstance(v, list):
            out[str(k)] = tuple(v)
        else:
            out[str(k)] = v
    return out


def ogs_from(d, out, where):
    o = DB.OverrideGraphicSettings()
    for g, s, k in OGS:
        if g not in d:
            continue
        val = d[g]
        if k in ("lpat", "fpat"):
            val = pattern_id(val, k)
            if val is None:
                out.append("%s: pattern '%s' not in model - left default" % (where, d[g].get("name")))
                continue
        elif k == "color":
            val = DB.Color(System.Byte(val[0]), System.Byte(val[1]), System.Byte(val[2]))
        elif k == "detail":
            val = getattr(DB.ViewDetailLevel, val)
        getattr(o, s)(val)
    return o


def iter_categories():
    for c in doc.Settings.Categories:
        yield c, ""
        for s in c.SubCategories:
            yield s, c.Name


def link_sources():
    for lt in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType):
        yield "type", name_of(lt), lt
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        yield "instance", li.Name, li


def link_rec(lo):
    r = {}
    for a in LINK_ENUMS:
        try:
            r[a] = str(getattr(lo, a))
        except Exception:
            pass
    r["LinkedViewId"] = eid(lo.LinkedViewId)
    for nm, gt, gv in (("discipline", "GetDisciplineType", "GetDiscipline"), ("phase", "GetPhaseType", "GetPhaseId"),
                       ("phase_filter", "GetPhaseFilterType", "GetPhaseFilterId"),
                       ("detail_level", "GetViewDetailLevelType", "GetViewDetailLevel")):
        try:
            val = getattr(lo, gv)()
            r[nm] = [str(getattr(lo, gt)()), eid(val) if isinstance(val, DB.ElementId) else str(val)]
        except Exception:
            pass
    return r


def link_from(d):
    s = DB.RevitLinkGraphicsSettings()
    for a in LINK_ENUMS:
        if a in d:
            setattr(s, a, enum_parse(getattr(s, a), d[a]))
    if d.get("LinkedViewId", -1) != -1:
        s.LinkedViewId = mk_id(d["LinkedViewId"])
    if "discipline" in d:
        s.SetDiscipline(enum_parse(s.GetDisciplineType(), d["discipline"][0]), getattr(DB.ViewDiscipline, d["discipline"][1]))
    if "phase" in d:
        s.SetPhase(enum_parse(s.GetPhaseType(), d["phase"][0]), mk_id(d["phase"][1]))
    if "phase_filter" in d:
        s.SetPhaseFilter(enum_parse(s.GetPhaseFilterType(), d["phase_filter"][0]), mk_id(d["phase_filter"][1]))
    if "detail_level" in d:
        s.SetViewDetailLevel(enum_parse(s.GetViewDetailLevelType(), d["detail_level"][0]),
                             getattr(DB.ViewDetailLevel, d["detail_level"][1]))
    return s


def color_list(c):
    return [int(c.Red), int(c.Green), int(c.Blue)] if c is not None and c.IsValid else None


def display_rec(t):
    r = {"DisplayStyle": str(t.DisplayStyle), "PartsVisibility": str(t.PartsVisibility),
         "ShadowIntensity": t.ShadowIntensity, "SunlightIntensity": t.SunlightIntensity}
    try:
        s = t.GetSketchyLines()
        r["sketchy_lines"] = {"EnableSketchyLines": s.EnableSketchyLines, "Extension": s.Extension, "Jitter": s.Jitter}
    except Exception:
        pass
    try:
        m = t.GetViewDisplayModel()
        r["model_display"] = {"EnableSilhouettes": m.EnableSilhouettes, "ShowHiddenLines": str(m.ShowHiddenLines),
                              "SilhouetteEdgesGStyleId": eid(m.SilhouetteEdgesGStyleId),
                              "SilhouetteEdgesGStyle": el_name(m.SilhouetteEdgesGStyleId),
                              "SmoothEdges": m.SmoothEdges, "Transparency": m.Transparency}
    except Exception:
        pass
    try:
        b = t.GetBackground()
        r["background"] = {"Type": str(b.Type), "SkyColor": color_list(b.SkyColor),
                           "BackgroundColor": color_list(b.BackgroundColor), "GroundColor": color_list(b.GroundColor),
                           "ImagePath": b.ImagePath, "ImageFlags": str(b.ImageFlags),
                           "HorizontalImageOffset": b.HorizontalImageOffset, "VerticalImageOffset": b.VerticalImageOffset,
                           "HorizontalImageScale": b.HorizontalImageScale, "VerticalImageScale": b.VerticalImageScale}
    except Exception:
        pass
    try:
        r["WorksharingDisplayMode"] = str(t.GetWorksharingDisplayMode())
    except Exception:
        pass
    ss = t.SunAndShadowSettings
    if ss is not None:
        r["sun_and_shadow"] = {"name": ss.Name, "type": str(ss.SunAndShadowType), "parameters": params(ss)}
    return r


def template_rec(t):
    names = dict((eid(p.Id), p.Definition.Name) for p in t.Parameters)
    nc = set(eid(i) for i in t.GetNonControlledTemplateParameterIds())
    cats = []
    for c, parent in iter_categories():
        try:
            hidden = t.GetCategoryHidden(c.Id)
        except Exception:
            continue
        cr = {"key": parent + "/" + c.Name, "hidden": hidden}
        try:
            g = ogs_to(t.GetCategoryOverrides(c.Id))
            if g:
                cr["ogs"] = g
        except Exception:
            pass
        cats.append(cr)
    flt = []
    for fid in t.GetOrderedFilters():
        f = doc.GetElement(fid)
        flt.append({"name": f.Name, "kind": f.GetType().Name, "visible": t.GetFilterVisibility(fid),
                    "enabled": t.GetIsFilterEnabled(fid), "ogs": ogs_to(t.GetFilterOverrides(fid))})
    wss = [{"name": w.Name, "visibility": str(t.GetWorksetVisibility(w.Id))}
           for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)]
    links = []
    for kind, nm, e in link_sources():
        try:
            lo = t.GetLinkOverrides(e.Id)
        except Exception:
            lo = None
        if lo is not None:
            d = link_rec(lo)
            d["kind"], d["name"] = kind, nm
            links.append(d)
    return {"name": t.Name, "element_id": eid(t.Id), "view_type": str(t.ViewType),
            "template_parameters": [{"id": eid(i), "name": names.get(eid(i)), "controlled": eid(i) not in nc}
                                    for i in t.GetTemplateParameterIds()],
            "hidden_flags": dict((a, getattr(t, a)) for a in HIDDEN_FLAGS),
            "display": display_rec(t),
            "parameters": params(t),
            "categories": cats, "filters": flt, "worksets": wss, "link_overrides": links,
            "not_captured": "Lighting details, Photographic Exposure and Rendering Settings are not exposed by the "
                            "API; the custom category ticks inside a 'Custom' RVT Links override are not exposed either."}


def restore_template(t, rec, write, out):
    sync_params(t, rec["parameters"], TEMPLATE_SKIP, write, out)

    # which template parameters are ticked ("Include")
    by_name_ = dict((p.Definition.Name, eid(p.Id)) for p in t.Parameters)
    want_nc = [by_name_.get(r["name"], r["id"]) for r in rec["template_parameters"] if not r["controlled"]]
    now_nc = sorted(eid(i) for i in t.GetNonControlledTemplateParameterIds())
    if sorted(want_nc) != now_nc:
        out.append("template 'Include' ticks differ: non-controlled %s -> %s" % (now_nc, sorted(want_nc)))
        if write:
            ids = List[DB.ElementId]([mk_id(i) for i in want_nc])
            t.SetNonControlledTemplateParameterIds(ids)

    for a, val in rec["hidden_flags"].items():
        if getattr(t, a) != val:
            out.append("%s: %s -> %s" % (a, getattr(t, a), val))
            if write:
                try:
                    setattr(t, a, val)
                except Exception as ex:
                    out.append("  FAILED: %s" % ex)

    # categories: visibility + overrides
    cur = dict((parent + "/" + c.Name, c) for c, parent in iter_categories())
    nh = no = nmiss = 0
    for cr in rec["categories"]:
        c = cur.get(cr["key"])
        if c is None:
            nmiss += 1
            continue
        try:
            if t.GetCategoryHidden(c.Id) != cr["hidden"]:
                nh += 1
                out.append("category '%s' hidden: %s -> %s" % (cr["key"], not cr["hidden"], cr["hidden"]))
                if write:
                    t.SetCategoryHidden(c.Id, cr["hidden"])
            if ogs_key(ogs_to(t.GetCategoryOverrides(c.Id))) != ogs_key(cr.get("ogs")):
                no += 1
                out.append("category '%s' overrides differ" % cr["key"])
                if write:
                    t.SetCategoryOverrides(c.Id, ogs_from(cr.get("ogs") or {}, out, cr["key"]))
        except Exception as ex:
            out.append("category '%s': %s" % (cr["key"], ex))
    if nmiss:
        out.append("%d saved categories not in this model (skipped)" % nmiss)

    # filters
    on_t = dict((doc.GetElement(i).Name, i) for i in t.GetFilters())
    saved = set()
    for fr in rec["filters"]:
        saved.add(fr["name"])
        fid = on_t.get(fr["name"])
        if fid is None:
            f = next((x for x in DB.FilteredElementCollector(doc).OfClass(DB.FilterElement) if x.Name == fr["name"]), None)
            if f is None:
                out.append("filter '%s' not in model - skipped" % fr["name"])
                continue
            out.append("filter '%s' missing on template - add" % fr["name"])
            if not write:
                continue
            t.AddFilter(f.Id)
            fid = f.Id
        if t.GetFilterVisibility(fid) != fr["visible"]:
            out.append("filter '%s' visible -> %s" % (fr["name"], fr["visible"]))
            if write:
                t.SetFilterVisibility(fid, fr["visible"])
        if t.GetIsFilterEnabled(fid) != fr["enabled"]:
            out.append("filter '%s' enabled -> %s" % (fr["name"], fr["enabled"]))
            if write:
                t.SetIsFilterEnabled(fid, fr["enabled"])
        if ogs_key(ogs_to(t.GetFilterOverrides(fid))) != ogs_key(fr["ogs"]):
            out.append("filter '%s' overrides differ" % fr["name"])
            if write:
                t.SetFilterOverrides(fid, ogs_from(fr["ogs"], out, fr["name"]))
    for nm in on_t:
        if nm not in saved:
            out.append("filter '%s' is on the template but not in the profile - left (remove by hand if unwanted)" % nm)

    # worksets
    wsm = dict((w.Name, w) for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))
    for wr in rec["worksets"]:
        w = wsm.get(wr["name"])
        if w is None:
            continue
        if str(t.GetWorksetVisibility(w.Id)) != wr["visibility"]:
            out.append("workset '%s': %s -> %s" % (wr["name"], t.GetWorksetVisibility(w.Id), wr["visibility"]))
            if write:
                t.SetWorksetVisibility(w.Id, getattr(DB.WorksetVisibility, wr["visibility"]))

    # RVT links (exposed fields only)
    saved_links = dict(((d["kind"], d["name"]), d) for d in rec["link_overrides"])
    for kind, nm, e in link_sources():
        d = saved_links.get((kind, nm))
        try:
            lo = t.GetLinkOverrides(e.Id)
        except Exception:
            continue
        now = link_rec(lo) if lo is not None else None
        want = dict((k, v) for k, v in d.items() if k not in ("kind", "name")) if d else None
        if (now is None) != (want is None) or (now is not None and
                                               dict((k, tuple(v) if isinstance(v, list) else v) for k, v in now.items()) !=
                                               dict((k, tuple(v) if isinstance(v, list) else v) for k, v in want.items())):
            out.append("link %s '%s': %s -> %s" % (kind, nm, now and now.get("LinkVisibilityType"),
                                                    want and want.get("LinkVisibilityType")))
            if want and want.get("LinkVisibilityType") == "Custom":
                out.append("  note: custom category ticks inside this link override cannot be restored - check V/G")
            if write:
                if want is None:
                    t.RemoveLinkOverrides(e.Id)
                else:
                    t.SetLinkOverrides(e.Id, link_from(want))

    # graphic display options
    dr = rec["display"]
    if str(t.DisplayStyle) != dr["DisplayStyle"]:
        out.append("DisplayStyle: %s -> %s" % (t.DisplayStyle, dr["DisplayStyle"]))
        if write:
            t.DisplayStyle = getattr(DB.DisplayStyle, dr["DisplayStyle"])
    for a in ("ShadowIntensity", "SunlightIntensity"):
        if getattr(t, a) != dr[a]:
            out.append("%s: %s -> %s" % (a, getattr(t, a), dr[a]))
            if write:
                try:
                    setattr(t, a, dr[a])
                except Exception as ex:
                    out.append("  FAILED: %s" % ex)
    if "sketchy_lines" in dr:
        s = t.GetSketchyLines()
        if any(getattr(s, k) != v for k, v in dr["sketchy_lines"].items()):
            out.append("sketchy lines differ")
            if write:
                for k, v in dr["sketchy_lines"].items():
                    setattr(s, k, v)
                t.SetSketchyLines(s)
    if "model_display" in dr:
        m, md = t.GetViewDisplayModel(), dr["model_display"]
        if (m.EnableSilhouettes != md["EnableSilhouettes"] or str(m.ShowHiddenLines) != md["ShowHiddenLines"]
                or m.SmoothEdges != md["SmoothEdges"] or m.Transparency != md["Transparency"]
                or eid(m.SilhouetteEdgesGStyleId) != md["SilhouetteEdgesGStyleId"]):
            out.append("model display (silhouettes / hidden lines / smooth edges / transparency) differs")
            if write:
                m.EnableSilhouettes = md["EnableSilhouettes"]
                m.ShowHiddenLines = getattr(DB.ShowHiddenLinesValues, md["ShowHiddenLines"])
                m.SmoothEdges = md["SmoothEdges"]
                m.Transparency = md["Transparency"]
                if md["SilhouetteEdgesGStyleId"] != -1:
                    m.SilhouetteEdgesGStyleId = mk_id(md["SilhouetteEdgesGStyleId"])
                t.SetViewDisplayModel(m)
    if "background" in dr:
        b, bd = t.GetBackground(), dr["background"]
        now = {"Type": str(b.Type), "SkyColor": color_list(b.SkyColor), "GroundColor": color_list(b.GroundColor),
               "BackgroundColor": color_list(b.BackgroundColor), "ImagePath": b.ImagePath}
        if any(now[k] != (bd[k] if not isinstance(bd[k], list) else list(bd[k])) for k in now):
            out.append("background: %s -> %s" % (now["Type"], bd["Type"]))
            if write:
                col = lambda a: DB.Color(System.Byte(a[0]), System.Byte(a[1]), System.Byte(a[2]))
                if bd["Type"] == "Gradient":
                    t.SetBackground(DB.ViewDisplayBackground.CreateGradient(col(bd["SkyColor"]), col(bd["BackgroundColor"]),
                                                                            col(bd["GroundColor"])))
                elif bd["Type"] == "Sky":
                    t.SetBackground(DB.ViewDisplayBackground.CreateSky())
                elif bd["Type"] == "Image":
                    t.SetBackground(DB.ViewDisplayBackground.CreateImage(
                        bd["ImagePath"], getattr(DB.ViewDisplayBackgroundImageFlags, bd["ImageFlags"]),
                        DB.UV(bd["HorizontalImageOffset"], bd["VerticalImageOffset"]),
                        DB.UV(bd["HorizontalImageScale"], bd["VerticalImageScale"])))
                else:
                    out.append("  background type '%s' has no API setter - set it in Graphic Display Options" % bd["Type"])
    if "WorksharingDisplayMode" in dr and str(t.GetWorksharingDisplayMode()) != dr["WorksharingDisplayMode"]:
        out.append("worksharing display: %s -> %s" % (t.GetWorksharingDisplayMode(), dr["WorksharingDisplayMode"]))
        if write:
            t.SetWorksharingDisplayMode(getattr(DB.WorksharingDisplayMode, dr["WorksharingDisplayMode"]))


# --------------------------------------------------------------------- zoom ---
def capture_zoom():
    z = {}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for uv in uidoc.GetOpenUIViews():
        v = doc.GetElement(uv.ViewId)
        c = uv.GetZoomCorners()
        r = uv.GetWindowRectangle()
        z[v.Name] = {"c1_ft": xyz(c[0]), "c2_ft": xyz(c[1]), "c1_mm": xyz_mm(c[0]), "c2_mm": xyz_mm(c[1]),
                     "window_px": [r.Left, r.Top, r.Right, r.Bottom], "captured": now}
    return z


def restore_zoom(recs, write):
    lines, n_same, n_set, n_skip = [], 0, 0, 0
    first_active = doc.ActiveView
    opened = False
    for rec in recs:
        z = rec.get("zoom")
        if not z:
            continue
        open_map = dict((doc.GetElement(u.ViewId).Name, u) for u in uidoc.GetOpenUIViews())
        uv = open_map.get(rec["name"])
        if uv is None and write and OPEN_VIEWS_FOR_ZOOM:
            v = find_view(rec["name"])
            if v is not None:
                uidoc.ActiveView = v
                opened = True
                uv = dict((doc.GetElement(u.ViewId).Name, u) for u in uidoc.GetOpenUIViews()).get(rec["name"])
        if uv is None:
            n_skip += 1
            lines.append("zoom '%s': view not open - skipped" % rec["name"])
            continue
        c = uv.GetZoomCorners()
        d = max(gap(c[0], z["c1_ft"]), gap(c[1], z["c2_ft"])) * FT
        if d < ZOOM_TOL_MM:
            n_same += 1
            continue
        if not write:
            lines.append("zoom '%s': off by up to %d mm - would zoom" % (rec["name"], d))
            continue
        uv.ZoomAndCenterRectangle(to_xyz(z["c1_ft"]), to_xyz(z["c2_ft"]))
        c = uv.GetZoomCorners()
        d2 = max(gap(c[0], z["c1_ft"]), gap(c[1], z["c2_ft"])) * FT
        n_set += 1
        lines.append("zoom '%s': zoomed (was off %d mm, now %d mm)" % (rec["name"], d, d2))
    if opened and first_active is not None:
        uidoc.ActiveView = first_active
    return lines, n_same, n_set, n_skip


# --------------------------------------------------------------------- main ---
def load_profile():
    # close the handle at once: IronPython keeps it open otherwise and the
    # .bak rename then fails with "file is being used by another process"
    with open(PROFILE_PATH) as f:
        return json.loads(f.read())


def check_doc():
    if EXPECTED_DOC_TITLE and doc.Title != EXPECTED_DOC_TITLE:
        raise Exception("Wrong model: '%s' is active, expected '%s'" % (doc.Title, EXPECTED_DOC_TITLE))


def capture():
    check_doc()
    old = None
    if os.path.exists(PROFILE_PATH):
        if not OVERWRITE_PROFILE:
            raise Exception("Profile exists: %s (set OVERWRITE_PROFILE = True to replace it)" % PROFILE_PATH)
        old = load_profile()
    views = target_views()
    zoom = capture_zoom() if CAPTURE_ZOOM else {}
    recs = [view_rec(v, zoom) for v in views]
    carried = []
    if old:
        old_zoom = dict((r["name"], r.get("zoom")) for r in old.get("views", []))
        for r in recs:
            if not r["zoom"] and old_zoom.get(r["name"]):
                r["zoom"] = old_zoom[r["name"]]
                carried.append(r["name"])
    templates = []
    if CAPTURE_TEMPLATES:
        seen = set()
        for v in views:
            if v.ViewTemplateId != INVALID and eid(v.ViewTemplateId) not in seen:
                seen.add(eid(v.ViewTemplateId))
                templates.append(template_rec(doc.GetElement(v.ViewTemplateId)))
    data = {"captured": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "script": r"C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profile.py",
            "document_title": doc.Title, "document_path": doc.PathName,
            "revit_version": doc.Application.VersionNumber, "name_prefix": NAME_PREFIX, "count": len(recs),
            "units_note": "_ft = Revit internal feet (restore uses these); _mm = same values in mm. "
                          "Camera, crop, section box and zoom corners are model internal coordinates.",
            "views": recs, "templates": templates}
    folder = os.path.dirname(PROFILE_PATH)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    if old is not None:
        bak = PROFILE_PATH[:-5] + ".bak_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
        os.rename(PROFILE_PATH, bak)
        print("old profile kept as", bak)
    with open(PROFILE_PATH, "wb") as f:
        f.write(js(data).encode("ascii"))
    print("wrote %s (%d bytes): %d views, %d templates" % (PROFILE_PATH, os.path.getsize(PROFILE_PATH), len(recs), len(templates)))
    print("zoom captured (open now): %d | carried from old profile: %s | no zoom: %s" % (
        len([r for r in recs if r["zoom"] and r["name"] not in carried]), carried or "-",
        [r["name"] for r in recs if not r["zoom"]] or "-"))
    for t in templates:
        print("template '%s': %d params, %d categories (%d with overrides, %d hidden), %d filters, %d worksets, %d link overrides" % (
            t["name"], len(t["parameters"]), len(t["categories"]), len([c for c in t["categories"] if c.get("ogs")]),
            len([c for c in t["categories"] if c["hidden"]]), len(t["filters"]), len(t["worksets"]), len(t["link_overrides"])))


def apply_in_tx(label, elem, fn_write, fn_check):
    """Write in one transaction, then re-check in the same call."""
    why = ws_blocked(elem) if elem is not None else None
    if why:
        print("  SKIPPED (%s)" % why)
        return
    wout = []
    status, warns, err = run_tx(label, lambda: fn_write(wout))
    print("  commit=%s%s%s" % (status, " error: " + err if err else "", " warnings: %s" % warns if warns else ""))
    for l in wout:
        if "FAILED" in l or "note:" in l or "not in model" in l:
            print("  " + l.strip())
    left = fn_check()
    print("  re-check: %s" % ("matches profile" if not left else "%d still differ: %s" % (len(left), left[:5])))


def restore():
    check_doc()
    prof = load_profile()
    write = not DRY_RUN
    recs = [r for r in prof["views"] if not ONLY_VIEWS or r["name"] in ONLY_VIEWS]
    print("%s | profile captured %s from '%s' | %d views" % ("APPLY" if write else "DRY RUN", prof["captured"],
                                                           prof["document_title"], len(recs)))
    total = 0

    if RESTORE_TEMPLATES:
        used = set(r.get("view_template") for r in recs)
        for trec in prof.get("templates", []):
            if trec["name"] not in used:
                continue
            t = find_template(trec["name"])
            print("template '%s'" % trec["name"])
            if t is None:
                src = next((find_view(r["name"]) for r in recs if r.get("view_template") == trec["name"] and find_view(r["name"])), None)
                print("  missing - %s" % ("would be recreated from view '%s'" % src.Name if src else "no profile view left to recreate it from"))
                total += 1
                if not write or src is None:
                    continue
                holder = {}

                def mk(src=src, trec=trec, holder=holder):
                    nt = src.CreateViewTemplate()
                    nt.Name = trec["name"]
                    holder["t"] = nt
                status, warns, err = run_tx("Recreate template", mk)
                print("  recreate commit=%s%s" % (status, " error: " + err if err else ""))
                t = holder.get("t") if status == "Committed" else None
                if t is None:
                    continue
            diffs = []
            restore_template(t, trec, False, diffs)
            total += len(diffs)
            for d in diffs[:40]:
                print("  " + d)
            if len(diffs) > 40:
                print("  ... %d more" % (len(diffs) - 40))
            if write and diffs:
                apply_in_tx("Restore template " + trec["name"], t,
                            lambda o, t=t, trec=trec: restore_template(t, trec, True, o),
                            lambda t=t, trec=trec: (lambda o: (restore_template(t, trec, False, o), o)[1])([]))
            elif not diffs:
                print("  matches profile")

    for rec in recs:
        v = find_view(rec["name"])
        diffs = []
        if v is None:
            if not CREATE_MISSING_VIEWS:
                print("'%s': MISSING - skipped (CREATE_MISSING_VIEWS = False)" % rec["name"])
                continue
            print("'%s': MISSING - %s" % (rec["name"], "recreating" if write else "would be recreated"))
            total += 1
            if not write:
                continue
            vft = find_vft(rec["view_family_type"])
            if vft is None:
                print("  view type '%s' not in model - cannot recreate" % rec["view_family_type"])
                continue
            holder = {}

            def mk(rec=rec, vft=vft, holder=holder):
                nv = DB.View3D.CreatePerspective(doc, vft.Id) if rec["is_perspective"] else DB.View3D.CreateIsometric(doc, vft.Id)
                nv.Name = rec["name"]
                holder["v"] = nv
            status, warns, err = run_tx("Recreate view", mk)
            print("  recreate commit=%s%s" % (status, " error: " + err if err else ""))
            v = holder.get("v") if status == "Committed" else None
            if v is None:
                continue
        restore_view(v, rec, False, diffs)
        total += len(diffs)
        print("'%s': %s" % (rec["name"], "matches profile" if not diffs else "%d difference(s)" % len(diffs)))
        for d in diffs:
            print("  " + d)
        if write and diffs:
            apply_in_tx("Restore view " + rec["name"], v,
                        lambda o, v=v, rec=rec: restore_view(v, rec, True, o),
                        lambda v=v, rec=rec: (lambda o: (restore_view(v, rec, False, o), o)[1])([]))

    if RESTORE_ZOOM:
        lines, n_same, n_set, n_skip = restore_zoom(recs, write)
        for l in lines:
            print(l)
        print("zoom: %d already match, %d %s, %d not open" % (n_same, n_set if write else len(
            [l for l in lines if "would zoom" in l]), "zoomed" if write else "would zoom", n_skip))
    print("%s: %d difference(s) found" % ("APPLIED" if write else "DRY RUN done - nothing changed", total))


if MODE == "capture":
    capture()
elif MODE == "restore":
    restore()

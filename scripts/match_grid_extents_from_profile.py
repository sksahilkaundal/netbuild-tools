# match_grid_extents_from_profile.py
#
# Copy 2D (view-specific) grid extents, bubble visibility and elbows from one
# reference view onto many views of a given view family type.
#
# Two modes:
#   MODE = "capture"  -> read REF_VIEW_NAME, write PROFILE_PATH (JSON), change nothing
#   MODE = "apply"    -> read PROFILE_PATH, write it into every target view
#
# 3D / Model extents of the grids are NEVER touched: only per-view overrides
# (SetDatumExtentType / SetCurveInView / bubbles / leaders) are written.
#
# Run via Revit MCP `execute_revit_code` (IronPython, pyRevit). `doc` is provided.
# Everything tunable lives in the CONFIG block - do not hardcode elsewhere.

import json
from Autodesk.Revit.DB import IFailuresPreprocessor, FailureProcessingResult, FailureSeverity

# ----------------------------------------------------------------- CONFIG ---
MODE = "apply"                      # "capture" | "apply"
DRY_RUN = True                      # apply mode: True = report only, no transaction

PROFILE_PATH = r"C:\SK\OneDrive\Netbuild\scripts\grid_extent_profiles\GA_Plans_TA.json"

VFT_NAME = "10 _ GA Plans"          # view family type whose views are targets
REF_VIEW_NAME = "10-024 - Level 24 GA Plan"   # capture mode: source of truth
EXCLUDE_VIEWS = ["10-040- Lift Machine Room"] # apply mode: exact view names to skip
ONLY_VIEWS = []                     # apply mode: if non-empty, ONLY these view names
OPEN_VIEWS_ONLY = False             # apply mode: True = only views open on screen now
BATCH = (0, 9999)                   # (start, count) slice of the sorted target list
# -----------------------------------------------------------------------------

VS = DB.DatumExtentType.ViewSpecific
ENDS = (DB.DatumEnds.End0, DB.DatumEnds.End1)
MM = 1.0 / 304.8


class SwallowWarnings(IFailuresPreprocessor):
    """Grids often sit in a group; touching them raises 'a group has been changed
    outside group edit mode', which silently ROLLS BACK the whole transaction in
    a headless MCP context. Delete warnings so the commit survives."""

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


def type_name(e):
    # ViewFamilyType.Name is not reachable as a plain attribute in IronPython
    return getattr(e, "Name", None) or e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()


def elem_id(e):
    # Revit 2026 dropped ElementId.IntegerValue in favour of .value
    return getattr(e.Id, "IntegerValue", None) or getattr(e.Id, "value", None)


def find_vft():
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if v.ViewFamily == DB.ViewFamily.FloorPlan and type_name(v) == VFT_NAME:
            return v
    raise Exception("View family type not found: %s" % VFT_NAME)


def capture():
    ref = None
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if not v.IsTemplate and v.Name == REF_VIEW_NAME:
            ref = v
            break
    if ref is None:
        raise Exception("Reference view not found: %s" % REF_VIEW_NAME)

    out = {"profile_name": VFT_NAME,
           "captured_from_doc": doc.Title,
           "captured_from_view": ref.Name,
           "units": "feet (internal Revit units); XY only, Z is taken from each target view",
           "grids": {}}
    for g in DB.FilteredElementCollector(doc).OfClass(DB.Grid):
        try:
            c = g.GetCurvesInView(VS, ref)[0]
        except Exception:
            continue  # grid not visible in the reference view -> not part of the scope
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        rec = {"p0": [p0.X, p0.Y], "p1": [p1.X, p1.Y],
               "bub": [bool(g.IsBubbleVisibleInView(e, ref)) for e in ENDS],
               "ldr": []}
        for e in ENDS:
            try:
                l = g.GetLeader(e, ref)
            except Exception:
                l = None
            rec["ldr"].append(None if l is None else
                              {"elbow": [l.Elbow.X, l.Elbow.Y], "end": [l.End.X, l.End.Y]})
        out["grids"][g.Name] = rec

    f = open(PROFILE_PATH, "w")
    json.dump(out, f, indent=2)
    f.close()
    print("Captured %d grids from '%s' -> %s" % (len(out["grids"]), ref.Name, PROFILE_PATH))
    for n in sorted(out["grids"]):
        r = out["grids"][n]
        print("  %-6s bub=%s/%s elbows=%s/%s" % (n, r["bub"][0], r["bub"][1],
                                                 r["ldr"][0] is not None, r["ldr"][1] is not None))


def apply():
    f = open(PROFILE_PATH, "r")
    prof = json.load(f)
    f.close()
    by_name = prof["grids"]

    grids = [g for g in DB.FilteredElementCollector(doc).OfClass(DB.Grid) if g.Name in by_name]
    missing = sorted(set(by_name) - set(g.Name for g in grids))

    if OPEN_VIEWS_ONLY:
        # whatever the user has open on screen right now, regardless of view type
        targets = [doc.GetElement(u.ViewId) for u in uidoc.GetOpenUIViews()]
        targets = [v for v in targets if isinstance(v, DB.ViewPlan) and not v.IsTemplate
                   and v.Name not in EXCLUDE_VIEWS
                   and (not ONLY_VIEWS or v.Name in ONLY_VIEWS)]
    else:
        vft = find_vft()
        targets = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan)
                   if not v.IsTemplate and v.GetTypeId() == vft.Id
                   and v.Name not in EXCLUDE_VIEWS
                   and (not ONLY_VIEWS or v.Name in ONLY_VIEWS)]
    targets.sort(key=lambda v: v.Name)
    targets = targets[BATCH[0]:BATCH[0] + BATCH[1]]

    print("Profile: %s (from '%s' in %s)" % (PROFILE_PATH, prof.get("captured_from_view"),
                                             prof.get("captured_from_doc")))
    print("Grids matched in this model: %d/%d" % (len(grids), len(by_name)))
    if missing:
        print("  NOT IN THIS MODEL (skipped): %s" % ", ".join(missing))
    print("Target views: %d" % len(targets))
    if DRY_RUN:
        for v in targets:
            n_vis = 0
            for g in grids:
                try:
                    g.GetCurvesInView(VS, v)
                    n_vis += 1
                except Exception:
                    pass
            print("  %-45s %d/%d grids visible" % (v.Name, n_vis, len(grids)))
        print("\nDRY RUN - nothing changed.")
        return

    # One transaction PER VIEW: a rollback then costs one view, not the whole run.
    rows, strays, warns, swapped = [], [], set(), set()
    for v in targets:
        sw = SwallowWarnings()
        t = DB.Transaction(doc, "Grid extents: %s" % v.Name)
        t.Start()
        o = t.GetFailureHandlingOptions()
        o.SetFailuresPreprocessor(sw)
        o.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(o)
        ok = skip = err = 0
        for g in grids:
            rec = by_name[g.Name]
            try:
                cur = g.GetCurvesInView(VS, v)[0]
                a, b = cur.GetEndPoint(0), cur.GetEndPoint(1)
                d = (b - a).Normalize()
                z = a.Z   # Z comes from the target view's own plane, never the profile

                # Grids are rarely EXACTLY axis-aligned (seen: 0.04 mm skew over
                # 160 ft). A perfectly straight profile line is then "not
                # coincident with the original datum plane" and is rejected, so
                # project the profile endpoints onto this grid's actual line.
                P = [DB.XYZ(rec["p0"][0], rec["p0"][1], z),
                     DB.XYZ(rec["p1"][0], rec["p1"][1], z)]
                tv = [(p - a).DotProduct(d) for p in P]
                Q = [a + d * tv[0], a + d * tv[1]]
                bub = list(rec["bub"])
                ldr = list(rec["ldr"])
                if tv[0] > tv[1]:
                    # This grid's curve runs the other way round: write along its
                    # own direction and remap bubbles/elbows to the same PHYSICAL
                    # end, otherwise the bubble lands at the wrong side.
                    Q.reverse(); bub.reverse(); ldr.reverse(); P.reverse()
                    swapped.add(g.Name)

                for e in ENDS:
                    g.SetDatumExtentType(e, v, VS)
                g.SetCurveInView(VS, v, DB.Line.CreateBound(Q[0], Q[1]))
                for i, e in enumerate(ENDS):
                    if bub[i]:
                        g.ShowBubbleInView(e, v)
                    else:
                        g.HideBubbleInView(e, v)
                    want = ldr[i]
                    try:
                        have = g.GetLeader(e, v)
                    except Exception:
                        have = None
                    if want is None:
                        # The API has no RemoveLeader for datums - collapse it to a stub
                        # and report anything that refuses to collapse for manual cleanup.
                        if have is not None:
                            an = have.Anchor
                            dd = have.End - an
                            dd = dd.Normalize() if dd.GetLength() > 1e-9 else DB.XYZ(1, 0, 0)
                            try:
                                have.Elbow = an
                                have.End = an + dd * (2.0 * MM)
                                g.SetLeader(e, v, have)
                            except Exception:
                                pass
                            chk = g.GetLeader(e, v)
                            if chk is not None and (chk.End - chk.Anchor).GetLength() > 5 * MM:
                                strays.append("%s / %s %s (%.0fmm)" % (
                                    v.Name, g.Name, "E0" if i == 0 else "E1",
                                    (chk.End - chk.Anchor).GetLength() * 304.8))
                    else:
                        shift = Q[i] - P[i]   # follow the projection, sub-mm
                        if have is None:
                            g.AddLeader(e, v)
                            have = g.GetLeader(e, v)
                        have.Elbow = DB.XYZ(want["elbow"][0], want["elbow"][1], z) + shift
                        have.End = DB.XYZ(want["end"][0], want["end"][1], z) + shift
                ok += 1
            except Exception as ex:
                if "cannot be visible" in str(ex):
                    skip += 1  # grid genuinely not shown in this view - leave it alone
                else:
                    err += 1
                    if err == 1:
                        rows.append("      err %s: %s" % (g.Name, str(ex)[:80]))
        status = t.Commit()
        for w in sw.seen:
            warns.add(w)
        # ALWAYS report the real commit status - a silent RolledBack means the
        # view looks done in the log but nothing was written.
        rows.append("  %-45s ok=%2d skip=%2d err=%2d  commit=%s" % (
            v.Name, ok, skip, err, status))

    for r in rows:
        print(r)
    print("\nGrids written reversed (bubbles remapped to the same physical end): %s"
          % (", ".join(sorted(swapped)) or "none"))
    print("Warnings swallowed: %s" % ("; ".join(sorted(warns)) or "none"))
    print("Stray leaders needing a manual bubble drag: %d" % len(strays))
    for s in strays:
        print("   " + s)


if MODE == "capture":
    capture()
elif MODE == "apply":
    apply()
else:
    raise Exception("MODE must be 'capture' or 'apply'")

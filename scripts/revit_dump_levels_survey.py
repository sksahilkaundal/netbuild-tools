# -*- coding: utf-8 -*-
"""
Dump every Level of the open Revit model with its elevation in SHARED (survey)
metres -- the height system ACC/Navisworks BCF viewpoints use (ProjectA: camera
Z ~630 m at Ground Floor, X/Y ~665,800 / 2,741,200 UTM).

Runs inside Revit (IronPython 2.7): paste into execute_revit_code, or let
scripts\ProjectA_BcfViewpointLevels.py post it (`dump-levels`), which prepends
OUT_CSV_OVERRIDE. Read-only: no transaction, nothing in the model changes.

Any ProjectA tier model works: every tier model contains the full level list
(projecta-model-reference-by-tier memory), so the open one need not own the issue.

Two independent routes to the shared Z, printed side by side; they must agree:
  A  doc.ActiveProjectLocation.GetTotalTransform().Inverse.OfPoint(internal)
  B  internal Z - survey point internal Z + survey point shared Z
A mismatch > 0.01 m is printed as a WARNING -- do not trust the CSV then.
"""
import io

# ----------------------------- CONFIG ---------------------------------
OUT_CSV = r"C:\SK\Projects\ProjectA\Issues\260914\projecta_levels_survey.csv"
# ------------------------------------------------------------------------
try:
    OUT_CSV = OUT_CSV_OVERRIDE or OUT_CSV          # set by ProjectA_BcfViewpointLevels.py
except NameError:
    pass

FT_TO_M = 0.3048
nm = lambda e: DB.Element.Name.__get__(e)


def dump():
    if doc is None:
        print("no model open in Revit -- open any ProjectA tier model (all contain every level) and rerun")
        return
    to_shared = doc.ActiveProjectLocation.GetTotalTransform().Inverse
    sp = DB.BasePoint.GetSurveyPoint(doc)
    sp_internal_z = sp.Position.Z
    sp_shared_z = sp.SharedPosition.Z

    levels = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements(),
                    key=lambda l: l.ProjectElevation)
    lines = [u"level,elevation_survey_m,elevation_internal_m"]
    worst = 0.0
    for l in levels:
        z_int = l.ProjectElevation
        z_a = to_shared.OfPoint(DB.XYZ(0, 0, z_int)).Z * FT_TO_M
        z_b = (z_int - sp_internal_z + sp_shared_z) * FT_TO_M
        worst = max(worst, abs(z_a - z_b))
        lines.append(u'"%s",%.3f,%.3f' % (nm(l).replace(u'"', u''), z_a, z_int * FT_TO_M))

    with io.open(OUT_CSV, "w", encoding="utf-8") as f:
        f.write(u"\n".join(lines) + u"\n")

    print("%d levels from %s -> %s (route A vs B max diff %.3f m)" % (len(levels), doc.Title, OUT_CSV, worst))
    if worst > 0.01:
        print("WARNING: transform and survey-point routes disagree by %.3f m -- check the shared coordinates" % worst)
    print("\n".join(lines[:4] + [u"..."] + lines[-3:]))


dump()

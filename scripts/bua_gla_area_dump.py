# -*- coding: utf-8 -*-
r"""
BUA GLA/GSA area audit, step 1 of 2: dump every GLA/GSA-tagged Area behind the BUA schedule to JSON.

Run inside Revit through execute_revit_code (IronPython; needs `doc`, `DB`), with the model that
holds the schedule active (ProjectA: ProjectC-Studio-BIM-SW00-ZZZ-AR-970002, which links 970001):

    SCHEDULE_NAME = "Excel - Area - Overall With Assets For MEP Team"
    OUT_JSON = r"C:\SK\Projects\ProjectA\Exports\2026-10-01\_bua_gla_area_dump.json"
    exec(compile(open(r"C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_dump.py").read(),
                 "bua_gla_area_dump.py", "exec"))

Step 2 (outside Revit) matches it to the dated Option 1 workbook and reports:
    py -3.14 C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_audit.py "<dump.json>" "<YYMMDD>_..._Option 1.xlsx"

Read-only - opens no transaction, changes nothing in any model.

Scope: Areas of the schedule's area scheme (by name) in the host model AND every open linked model
(the schedule has "Include elements in links" on), whose Studio_Area_Department - the export's
"GLA/GSA Component" column - contains GLA or GSA. Per area: document, element id, level, area (m2)
and every non-empty parameter value as shown in Revit (Studio_Is GLA, Area Calc. Type, Name, ...).
"""
import os
import json
import codecs
import datetime

try:
    SCHEDULE_NAME
except NameError:
    SCHEDULE_NAME = "Excel - Area - Overall With Assets For MEP Team"
try:
    OUT_JSON
except NameError:
    OUT_JSON = os.path.join(r"C:\SK\Projects\ProjectA\Exports", datetime.date.today().strftime("%Y-%m-%d"),
                            "_bua_gla_area_dump.json")

DEPT = "Studio_Area_Department"
FT2_TO_M2 = 0.09290304


def value(p):
    try:
        if p.StorageType == DB.StorageType.String:
            return p.AsString()
        return p.AsValueString()
    except Exception:
        return None


sched = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule) if v.Name == SCHEDULE_NAME]
if not sched:
    raise Exception("schedule not found in the active model: %s" % SCHEDULE_NAME)
scheme_id = sched[0].Definition.AreaSchemeId
scheme = doc.GetElement(scheme_id).Name if scheme_id != DB.ElementId.InvalidElementId else None

out, per_doc = [], {}
for d in [x for x in doc.Application.Documents if not x.IsFamilyDocument]:
    n = 0
    for e in DB.FilteredElementCollector(d).OfCategory(DB.BuiltInCategory.OST_Areas).WhereElementIsNotElementType():
        if e.Area <= 0 or e.LevelId == DB.ElementId.InvalidElementId:
            continue                                   # unplaced / not enclosed - not in the schedule
        if scheme and (e.AreaScheme is None or e.AreaScheme.Name != scheme):
            continue
        p = e.LookupParameter(DEPT)
        dept = value(p) if p else None
        if not dept or not ("GLA" in dept or "GSA" in dept):
            continue
        params = {}
        for q in e.Parameters:
            v = value(q)
            if v not in (None, ""):
                params[q.Definition.Name] = v
        out.append({"doc": d.Title, "linked": d.IsLinked, "id": str(e.Id.Value),
                    "level": d.GetElement(e.LevelId).Name, "m2": round(e.Area * FT2_TO_M2, 2), "params": params})
        n += 1
    per_doc[d.Title] = n

folder = os.path.dirname(OUT_JSON)
if folder and not os.path.isdir(folder):
    os.makedirs(folder)
fh = codecs.open(OUT_JSON, "w", "utf-8")
fh.write(json.dumps({"schedule": SCHEDULE_NAME, "area_scheme": scheme, "host": doc.Title,
                     "dumped": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "areas": out}, ensure_ascii=False))
fh.close()
print("area scheme: %s | GLA/GSA-tagged areas: %d %s" % (scheme, len(out), per_doc))
print("wrote %s" % OUT_JSON)

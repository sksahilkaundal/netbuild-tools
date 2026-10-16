# -*- coding: utf-8 -*-
r"""
BUA raw pre-export check (inside Revit, read-only): is the BUA area schedule set to export one row per area?

Run through execute_revit_code with the schedule's host model active (ProjectA: ProjectC-Studio-BIM-SW00-ZZZ-AR-970002):

    SCHEDULE_NAME = "Excel - Area - Overall With Assets For MEP Team"
    exec(compile(open(r"C:\SK\OneDrive\Netbuild\scripts\bua_schedule_itemize_check.py").read(),
                 "bua_schedule_itemize_check.py", "exec"))

Prints: host document, "Itemize every instance" (ScheduleDefinition.IsItemized), "Include elements in links",
area scheme, the Sorting/Grouping fields and the visible field headings, then a verdict.

Why: bua_dated_export.py names the data sheet by the kind of raw ("<YYMMDD>_BUA Space Split-Itemized" vs
"<YYMMDD>_BUA Space Room Split"). A GROUPED raw (Itemize off) shows "<varies>" in the GLA/GSA Component
column (= Studio_Area_Department) wherever a level + function row mixes tags - on 2026-10-02 that hid 17,131.78 m2
of terraces and 3,680.32 m2 of tagged services, so projecta_calculations_build.py must never run on it.
Option 1 / Option 2 are fine either way.

Changes nothing. To fix, the user ticks Schedule Properties > Sorting/Grouping > "Itemize every instance"
and re-exports (or asks Claude to set it - a model change, only on request).
"""
try:
    SCHEDULE_NAME
except NameError:
    SCHEDULE_NAME = "Excel - Area - Overall With Assets For MEP Team"

found = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule) if v.Name == SCHEDULE_NAME]
if not found:
    print("schedule not found in the active model %s: %s" % (doc.Title, SCHEDULE_NAME))
else:
    sd = found[0].Definition
    scheme = doc.GetElement(sd.AreaSchemeId).Name if sd.AreaSchemeId != DB.ElementId.InvalidElementId else None
    print("host model:              %s" % doc.Title)
    print("schedule:                %s" % SCHEDULE_NAME)
    print("area scheme:             %s" % scheme)
    print("Itemize every instance:  %s" % sd.IsItemized)
    print("Include elements in links: %s" % sd.IncludeLinkedFiles)
    for i in range(sd.GetSortGroupFieldCount()):
        g = sd.GetSortGroupField(i)
        print("  sort/group %d: %-28s header=%s footer=%s" % (i + 1, sd.GetField(g.FieldId).GetName(), g.ShowHeader, g.ShowFooter))
    heads = [sd.GetField(i).ColumnHeading for i in range(sd.GetFieldCount()) if not sd.GetField(i).IsHidden]
    print("visible columns:         %s" % " | ".join(heads))
    print("")
    if sd.IsItemized:
        print("OK - itemized: the raw export has one row per area (data sheet '<YYMMDD>_BUA Space Split-Itemized'); ProjectA step allowed.")
    else:
        print("GROUPED - Itemize every instance is OFF: the raw gets one row per level + function and '<varies>' in "
              "GLA/GSA Component. Option 1/2 are fine; do NOT run the ProjectA Calculations step. Tick Itemize and re-export.")

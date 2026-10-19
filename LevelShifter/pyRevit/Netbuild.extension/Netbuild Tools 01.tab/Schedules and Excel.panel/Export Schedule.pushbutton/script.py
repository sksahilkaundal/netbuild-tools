# -*- coding: utf-8 -*-
"""Export the open schedule to an editable Excel workbook (schedule round-trip, step 1+2).

Host-model elements only (linked rows are left out). Area schedules that hold every column of
the curated Area layout get that layout; any other schedule gets all its visible columns in
the same style. Element ID is column A - the Import Excel button keys on it.
Logic: lib\\netbuild_roundtrip.py -> C:\\SK\\OneDrive\\Netbuild\\scripts\\schedule_roundtrip_*.py
"""
import datetime
import os

from pyrevit import revit, DB, forms, script

import netbuild_roundtrip as nr

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
TITLE = "Export Schedule to Excel"

view, seen = nr.active_schedule(doc, uidoc)
problem = nr.check_schedule(view, seen)
if problem:
    forms.alert(problem, title=TITLE, exitscript=True)

links = nr.loaded_links(doc)
ONLY, WITH = "This model only", "This model + linked models"
pick = forms.alert("Which rows should the workbook hold?", title=TITLE,
                   sub_msg="Loaded links: %s\n\nLinked rows get a Source Model column and are imported "
                           "later with that model open." % (", ".join(links) or "none"),
                   options=[ONLY, WITH], ok=False, cancel=True, warn_icon=False)
if pick not in (ONLY, WITH):
    script.exit()
include_links = pick == WITH
if include_links and not links:
    forms.alert("No Revit links are loaded in this model, so there are no linked rows to export.\n\n"
                "Load them first (Manage > Manage Links > Reload), or export this model only.",
                title=TITLE, exitscript=True)

name = nr.safe_name("%s - %s%s - %s.xlsx" % (view.Name, doc.Title, " + links" if include_links else "",
                                            datetime.date.today().strftime("%Y-%m-%d")))
path = forms.save_file(file_ext="xlsx", files_filter="Excel Workbook (*.xlsx)|*.xlsx",
                       init_dir=nr.default_dir(), default_name=name, title=TITLE + " - Save As")
if not path:
    script.exit()
if not path.lower().endswith(".xlsx"):
    path += ".xlsx"
if nr.is_locked(path):
    forms.alert("That workbook is open in Excel. Close it, or save under another name.",
                title=TITLE, exitscript=True)

output.print_md("## " + TITLE)
output.print_md("Schedule **%s** | model **%s** | %s" % (view.Name, doc.Title,
                 "with linked models" if include_links else "this model only"))
output.print_md("Saving to `%s` (working files in `_roundtrip`)" % path)
try:
    res = nr.export_schedule(doc, uidoc, view, path, include_links)
except Exception as e:
    output.print_md("**FAILED:** %s" % e)
    forms.alert("Export failed:\n\n%s" % e, title=TITLE, exitscript=True)

output.print_code(res["build_log"].strip())
tie = res["tie"]
rows = [[c["heading"], "{:,.2f}".format(c["host"]), "{:,.2f}".format(c["links"]),
         "-" if c["revit_total"] is None else "{:,.2f}".format(c["revit_total"]),
         "-" if c["diff"] is None else "{:+.2f}".format(c["diff"])] for c in tie["columns"]]
if rows:
    output.print_table(rows, columns=["Column", "In workbook", "Left out (links)", "Revit total", "Difference"],
                       title="Totals vs the Revit schedule")
ok_totals = (not tie["has_total"]) or tie["max_diff"] <= 0.15
msg = ["Saved: %s" % os.path.basename(path), "",
       "%d rows (%s), Element ID in column A." % (tie["rows"], res["layout"])]
if include_links:
    msg.append("This model: %d rows | linked: %d rows (%s)." % (res["host"], res["linked"],
                                                                ", ".join(res["link_models"]) or "none shown"))
    msg.append("Source Model column = where each row is imported.")
if res["excluded"]:
    msg.append("%d schedule rows left out (%s)." % (res["excluded"], "group headers / unmatched" if include_links
                                                   else "linked models / group headers"))
if tie["blank_component"]:
    msg.append("%s blank %s cells (highlighted amber)." % (tie["blank_component"], res["component"]))
if tie["has_total"] and rows:
    msg.append("Totals tie out to the Revit schedule." if ok_totals else
               "CHECK TOTALS: max difference %.2f (see output)." % tie["max_diff"])
if res["owned"]:
    msg.append("%d elements are borrowed by someone - an import will skip them." % res["owned"])
msg += ["", "Edit the yellow/parameter columns, save, then use Import Excel.", "", "Open the workbook now?"]
if forms.alert("\n".join(msg), title=TITLE, ok=False, yes=True, no=True):
    os.startfile(path)

# -*- coding: utf-8 -*-
"""Import an edited round-trip workbook back into the model (schedule round-trip, step 3).

Diffs the workbook against its hidden _Original sheet (keyed on Element ID), runs a DRY RUN
(conflicts, borrowed / out-of-date elements are skipped and listed), and writes only after
you click Yes. One transaction = one undo step. Does not save or sync.
Logic: lib\\netbuild_roundtrip.py -> C:\\SK\\OneDrive\\Netbuild\\scripts\\schedule_roundtrip_*.py
"""
from collections import Counter

from pyrevit import revit, DB, forms, script

import netbuild_roundtrip as nr

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
TITLE = "Import Excel to Revit"

path = forms.pick_file(file_ext="xlsx", init_dir=nr.default_dir(create=False),
                       title=TITLE + " - pick the edited workbook")
if not path:
    script.exit()

try:
    info = nr.workbook_info(path)
except Exception as e:
    forms.alert("Not a round-trip workbook (made by Export Schedule):\n\n%s" % e, title=TITLE, exitscript=True)
models = info.get("models") or [info["model"]]
if doc.Title not in models:
    forms.alert("This workbook holds rows for\n  %s\nbut the active model is\n  %s\n\nOpen one of those models "
                "(directly, not as a link) and run Import again." % ("\n  ".join(models), doc.Title),
                title=TITLE, exitscript=True)
if nr.is_locked(path) and not forms.alert(
        "The workbook is open in Excel. Only edits that are SAVED will be imported.\n\nContinue?",
        title=TITLE, ok=False, yes=True, no=True):
    script.exit()


class Opt(object):
    def __init__(self, p):
        self.param = p["param"]
        self.name = p["param"] if p["heading"] == p["param"] else "%s  (column '%s')" % (p["param"], p["heading"])


opts = [Opt(p) for p in info["params"]]
if not opts:
    forms.alert("The workbook has no writable parameter columns.", title=TITLE, exitscript=True)
pre = set(nr.DEFAULT_PARAMS) & set(o.param for o in opts) or set(o.param for o in opts)
chosen = forms.SelectFromList.show([forms.TemplateListItem(o, checked=o.param in pre, name_attr="name") for o in opts],
                                   title=TITLE + " - parameters to import", multiselect=True,
                                   button_name="Dry run")
if not chosen:
    script.exit()
params = [o.param for o in chosen]

output.print_md("## " + TITLE)
output.print_md("Workbook `%s` (exported %s) -> model **%s**" % (path, (info["exported"] or "")[:16], doc.Title))
output.print_md("Parameters: **%s**" % ", ".join(params))
try:
    changes, log = nr.diff(path, params, doc)
    output.print_code(log.strip())
    output.print_md("### Dry run")
    ns = nr.run_import(doc, uidoc, changes, True)
except Exception as e:
    output.print_md("**FAILED:** %s" % e)
    forms.alert("Import check failed:\n\n%s" % e, title=TITLE, exitscript=True)

todo, problems = ns["todo"], ns["problems"]
skipped = sum(len(v) for v in problems.values())
others = ["  %d change(s) for %s" % (k, m) for m, k in sorted(ns.get("other_models", {}).items())]
other_note = (["", "Not for this model - open each and run Import again:"] + others) if others else []
if not todo:
    forms.alert("\n".join(["Nothing to write in %s: no edited values differ from the model." % doc.Title, "",
                           "Already set: %d | skipped: %d" % (sum(ns["already"].values()), skipped)] + other_note),
                title=TITLE, exitscript=True)

crash = nr.worker_crash(doc.Application)
if crash and not forms.alert(
        "Revit's background worker has crashed in this session (%s).\nA large write can hang Revit for good.\n\n"
        "Recommended: Save, Synchronize and restart Revit first.\n\nWrite anyway?" % ", ".join(crash[:2]),
        title=TITLE, ok=False, yes=True, no=True):
    script.exit()

per = Counter((c["param"], c["new"] or "<blank>") for _, _, c in todo)
lines = ["Write %d values to %s?" % (len(todo), doc.Title), ""]
for (p, v), k in per.most_common(10):
    lines.append("  %5d  %s = %s" % (k, p, v))
if len(per) > 10:
    lines.append("  ... %d more (see output)" % (len(per) - 10))
if skipped:
    lines += ["", "Skipped (see output): %d" % skipped]
lines += other_note
lines += ["", "One transaction (one Undo). Not saved or synced."]
if not forms.alert("\n".join(lines), title=TITLE + " - Apply?", ok=False, yes=True, no=True):
    output.print_md("**Dry run only - nothing written.**")
    script.exit()

output.print_md("### Apply")
ns = nr.run_import(doc, uidoc, changes, False)
status = str(ns.get("status"))
if status != "Committed" and not ns.get("errs") and forms.alert(
        "Revit rolled the change back without an error message.\nThis happened once before and the "
        "same write worked on the second try.\n\nTry once more?", title=TITLE, ok=False, yes=True, no=True):
    output.print_md("### Apply - second try")
    ns = nr.run_import(doc, uidoc, changes, False)
    status = str(ns.get("status"))
if status == "Committed":
    forms.alert("Done: %d of %d values verified in the model.\n\nSynchronize with Central when ready "
                "(relinquish), or Undo to revert." % (ns.get("ok", 0), len(ns["todo"])), title=TITLE)
else:
    forms.alert("Nothing was written (transaction %s).\n\n%s" % (status, "\n".join(sorted(set(ns.get("errs") or []))[:5])),
                title=TITLE)

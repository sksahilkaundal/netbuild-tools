# -*- coding: utf-8 -*-
"""Wrapper button - runs scripts\\restore_ga_plan_link_views.py inside Revit
with the same doc/uidoc/DB context the Revit MCP execute_revit_code tool gives
it. Restores "By Linked View" on every GA Plan view on the 10_GA Plans sheets
for the core link (...-00003) and the grid link (...-BIM-00001), on the link
TYPE row. Edit the source script (CONFIG block), not this wrapper.
"""
import System
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

SCRIPT_PATH = r"C:\SK\OneDrive\Netbuild\scripts\restore_ga_plan_link_views.py"

proceed = forms.alert(
    "Restore 'By Linked View' on all GA Plan views (10_GA Plans sheets) for:\n\n"
    "  - Core link  3505-ProjectG-Studio-ARC-RVT-00003  -> '<Level> GA Plan_Linked View'\n"
    "  - Grid link  3505-ProjectG-Studio-ARC-BIM-00001  -> B / P2-L3 / GF-P1, L4-Roof views\n\n"
    "Both links must be loaded (their worksets open).\n"
    "This modifies the ACTIVE model. Continue?",
    title="Restore GA Link Views - Confirm",
    ok=False, yes=True, no=True
)
if not proceed:
    script.exit()

with open(SCRIPT_PATH, 'r') as f:
    _code = f.read()

_namespace = {
    "doc": doc,
    "uidoc": uidoc,
    "DB": DB,
    "System": System,
    "revit": revit,
    "DRY_RUN": False,
    "__file__": SCRIPT_PATH,
    "__name__": "__main__",
}

output.print_md("## Restore GA Link Views")
try:
    exec(compile(_code, SCRIPT_PATH, 'exec'), _namespace)
    output.print_md("**Done.** Now **Save** and **Synchronize with Central** so the settings are not lost.")
except Exception as e:
    output.print_md("**FAILED:** {0}".format(e))
    forms.alert("Script failed:\n\n{0}\n\nSee pyRevit output window for details.".format(e),
                title="Restore GA Link Views - Error")

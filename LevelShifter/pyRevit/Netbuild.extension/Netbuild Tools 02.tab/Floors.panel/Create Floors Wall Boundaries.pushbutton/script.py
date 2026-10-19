# -*- coding: utf-8 -*-
"""Wrapper button — runs CreateFloorsFromWallBoundaries_MCP.py from the OneDrive Claude scripts
folder inside Revit, providing the same doc/uidoc/DB/System/print context
that the Revit MCP execute_revit_code tool gives it. Edit the source file
directly (not this wrapper) to change behavior or hardcoded values.
"""
import System
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

SCRIPT_PATH = r"C:\SK\OneDrive\Netbuild\CreateFloorsFromWallBoundaries_MCP.py"

proceed = forms.alert(
    "This will create new finish floors from wall boundary loops per room/level in the ACTIVE document. This modifies the model (adds elements). Continue?",
    title="Create Floors from Walls - Confirm",
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
    "__file__": SCRIPT_PATH,
}

output.print_md("## Running `CreateFloorsFromWallBoundaries_MCP.py`")
try:
    exec(compile(_code, SCRIPT_PATH, 'exec'), _namespace)
    output.print_md("**Done.** Review the output above and the model before saving/syncing.")
except Exception as e:
    output.print_md("**FAILED:** {0}".format(e))
    forms.alert("Script failed:\n\n{0}\n\nSee pyRevit output window for details.".format(e),
                title="Create Floors from Walls - Error")

# -*- coding: utf-8 -*-
"""Wrapper button — runs floor_plate_area.py from the OneDrive Claude scripts
folder inside Revit, providing the same doc/uidoc/DB/System/print context
that the Revit MCP execute_revit_code tool gives it. Edit the source file
directly (not this wrapper) to change behavior or hardcoded values.
"""

__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import System
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# Found by name in any sub-folder of the script folders (Netbuild > Script Folder);
# OLD_PATH is used when they do not have it.
SCRIPT_NAME = "floor_plate_area.py"
OLD_PATH = r"C:\SK\OneDrive\Netbuild\floor_plate_area.py"
SCRIPT_PATH = netbuild_scripts.script_path(SCRIPT_NAME, OLD_PATH)
if not SCRIPT_PATH:
    forms.alert(netbuild_scripts.missing_text(SCRIPT_NAME, OLD_PATH), title="Floor Plate Area", exitscript=True)

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

output.print_md("## Running `floor_plate_area.py`")
try:
    exec(compile(_code, SCRIPT_PATH, 'exec'), _namespace)
    output.print_md("**Done.** Review the output above and the model before saving/syncing.")
except Exception as e:
    output.print_md("**FAILED:** {0}".format(e))
    forms.alert("Script failed:\n\n{0}\n\nSee pyRevit output window for details.".format(e),
                title="Floor Plate\nArea - Error")

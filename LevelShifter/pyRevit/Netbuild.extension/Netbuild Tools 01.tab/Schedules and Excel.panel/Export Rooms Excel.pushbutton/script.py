# -*- coding: utf-8 -*-
"""Wrapper button — runs export_rooms_to_excel.py from the OneDrive Claude
scripts folder inside Revit, providing the same doc/uidoc/DB/System/print
context that the Revit MCP execute_revit_code tool gives it. Prompts for
save location/filename each run (defaulting to the ProjectA Exports
date-stamped folder) instead of always overwriting the same file.
Edit the source file directly (not this wrapper) to change export logic.
"""

__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import os
import datetime
import System
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# Found by name in any sub-folder of the script folders (Netbuild > Script Folder);
# OLD_PATH is used when they do not have it.
SCRIPT_NAME = "export_rooms_to_excel.py"
OLD_PATH = r"C:\SK\OneDrive\Netbuild\export_rooms_to_excel.py"
SCRIPT_PATH = netbuild_scripts.script_path(SCRIPT_NAME, OLD_PATH)
if not SCRIPT_PATH:
    forms.alert(netbuild_scripts.missing_text(SCRIPT_NAME, OLD_PATH), title="Export Rooms Excel", exitscript=True)

DEFAULT_BASE_DIR = r"C:\Users\user\OneDrive - Studio\Projects\ProjectA\Exports"
default_date_dir = os.path.join(DEFAULT_BASE_DIR, datetime.date.today().strftime("%Y-%m-%d"))
if not os.path.isdir(default_date_dir):
    os.makedirs(default_date_dir)

chosen_path = forms.save_file(
    file_ext='xlsx',
    files_filter='Excel Workbook (*.xlsx)|*.xlsx',
    init_dir=default_date_dir,
    title='Export Rooms to Excel - Save As'
)

if not chosen_path:
    script.exit()

OUTPUT_PATH = chosen_path

with open(SCRIPT_PATH, 'r') as f:
    _code = f.read()

_namespace = {
    "doc": doc,
    "uidoc": uidoc,
    "DB": DB,
    "System": System,
    "revit": revit,
    "OUTPUT_PATH": OUTPUT_PATH,
    "__file__": SCRIPT_PATH,
}

output.print_md("## Running `export_rooms_to_excel.py`")
output.print_md("Saving to: `{0}`".format(OUTPUT_PATH))
try:
    exec(compile(_code, SCRIPT_PATH, 'exec'), _namespace)
    output.print_md("**Done.** File saved to `{0}`.".format(OUTPUT_PATH))
except Exception as e:
    output.print_md("**FAILED:** {0}".format(e))
    forms.alert("Script failed:\n\n{0}\n\nSee pyRevit output window for details.".format(e),
                title="Export Rooms to Excel - Error")

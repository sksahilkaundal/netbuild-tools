# -*- coding: utf-8 -*-
"""BUA Update by Netbuild -- open the app ("BUA Update by Netbuild.exe"): re-feed the raw Revit Area export
into the Option 1 / Option 2 BUA workbooks (frozen 274-column format) and check every total.

No model needs to be open. Shift+Click: choose where the exe is.
(c) 2026 Netbuild. All rights reserved. https://skaec.com
"""

__title__ = "BUA\nUpdate"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import os

from pyrevit import forms, script

from System.Diagnostics import Process, ProcessStartInfo

import buaupdate_app as app

CFG = script.get_config()


def pick_exe():
    path = forms.pick_file(file_ext="exe", title="Where is %s?" % app.EXE)
    if path:
        CFG.exe_path = path
        script.save_config()
    return path


exe = app.find_exe(CFG.get_option("exe_path", ""))
if not exe:
    forms.alert("%s was not found. Looked in:\n\n%s\n\nPick it now (it is remembered; "
                "Shift+Click the button to change it later)." % (app.EXE, "\n".join(app.candidates(CFG.get_option(
                    "exe_path", "")))), title=app.PRODUCT)
    exe = pick_exe()
    if not exe:
        script.exit()

psi = ProcessStartInfo(exe, "")
psi.WorkingDirectory = os.path.dirname(exe)
psi.UseShellExecute = True
Process.Start(psi)

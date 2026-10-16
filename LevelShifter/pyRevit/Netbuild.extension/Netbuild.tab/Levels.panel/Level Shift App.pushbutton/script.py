# -*- coding: utf-8 -*-
"""Level Shift by Netbuild -- open the app window ("Level Shift by Netbuild.exe"), bound to this model.

The app talks to Revit through the pyRevit MCP listener -- keep MCP Status running.
Shift+Click: choose where the exe is.  (c) 2026 SKAEC.COM -- MIT License.
"""

__title__ = "Level Shift\nApp"
__author__ = "Netbuild -- SKAEC.COM"

import os

from pyrevit import forms, revit, script

from System.Diagnostics import Process, ProcessStartInfo

import levelshift_app as app

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

doc = revit.doc
psi = ProcessStartInfo(exe, app.args_line(doc.Title if doc is not None and not doc.IsFamilyDocument else ""))
psi.WorkingDirectory = os.path.dirname(exe)
psi.UseShellExecute = True
Process.Start(psi)

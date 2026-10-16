# -*- coding: utf-8 -*-
"""Open the Level Shifter window (LevelShifter.exe), bound to this model.

The exe talks to Revit through the pyRevit MCP listener -- keep MCP Status running.
Shift+Click: choose where LevelShifter.exe is.
"""

__title__ = "Level Shifter\nApp"
__author__ = "Netbuild"

import os

from pyrevit import forms, revit, script

from System.Diagnostics import Process, ProcessStartInfo

import levelshift_app as app

CFG = script.get_config()


def pick_exe():
    path = forms.pick_file(file_ext="exe", title="Where is LevelShifter.exe?")
    if path:
        CFG.exe_path = path
        script.save_config()
    return path


exe = app.find_exe(CFG.get_option("exe_path", ""))
if not exe:
    forms.alert("LevelShifter.exe was not found. Looked in:\n\n%s\n\nPick it now (it is remembered; "
                "Shift+Click the button to change it later)." % "\n".join(app.candidates(CFG.get_option(
                    "exe_path", ""))), title="Level Shifter")
    exe = pick_exe()
    if not exe:
        script.exit()

doc = revit.doc
psi = ProcessStartInfo(exe, app.args_line(doc.Title if doc is not None and not doc.IsFamilyDocument else ""))
psi.WorkingDirectory = os.path.dirname(exe)
psi.UseShellExecute = True
Process.Start(psi)

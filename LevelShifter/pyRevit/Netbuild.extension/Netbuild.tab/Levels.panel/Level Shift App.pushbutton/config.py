# -*- coding: utf-8 -*-
"""Shift+Click: choose where LevelShifter.exe is."""

from pyrevit import forms, script

import levelshift_app as app

CFG = script.get_config()
current = app.find_exe(CFG.get_option("exe_path", ""))
path = forms.pick_file(file_ext="exe", title="Where is %s? (now: %s)" % (app.EXE, current or "not found"))
if path:
    CFG.exe_path = path
    script.save_config()
    forms.alert("Level Shift App will open:\n%s" % path, title=app.PRODUCT)

# -*- coding: utf-8 -*-
"""Shift+Click: choose where "BUA Update by Netbuild.exe" is."""

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

from pyrevit import forms, script

import buaupdate_app as app

CFG = script.get_config()
current = app.find_exe(CFG.get_option("exe_path", ""))
path = forms.pick_file(file_ext="exe", title="Where is %s? (now: %s)" % (app.EXE, current or "not found"))
if path:
    CFG.exe_path = path
    script.save_config()
    forms.alert("BUA Update will open:\n%s" % path, title=app.PRODUCT)

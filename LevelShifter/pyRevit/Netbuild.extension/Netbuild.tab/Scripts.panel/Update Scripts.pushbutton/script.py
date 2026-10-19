# -*- coding: utf-8 -*-
"""Update the installed Netbuild buttons from the script folder (Netbuild > Script Folder).

Every installed button whose folder ("Level Shift.pushbutton") is found in the script folder, in any sub-folder,
gets that folder's files; the lib of a same-named .extension found there is copied too. The replaced files are
backed up to %APPDATA%\\Netbuild\\pyRevit\\backups first.  (c) 2026 Netbuild. All rights reserved. https://skaec.com
"""

__title__ = "Update\nScripts"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

from pyrevit import forms

import netbuild_scripts as ns

TITLE = "Update Netbuild scripts"
SHOW = 30


def extension_roots():
    """pyRevit's own list of extension folders (empty when this pyRevit version does not have it)."""
    try:
        from pyrevit.userconfig import user_config
        return list(user_config.get_thirdparty_ext_root_dirs())
    except Exception:
        return []


def reload_pyrevit():
    try:
        from pyrevit.loader import sessionmgr
        sessionmgr.reload_pyrevit()
    except Exception as e:
        forms.alert("Reload pyRevit from the pyRevit tab (%s)." % e, title=TITLE)


s = ns.settings(ns.extension_root(__file__))
if not s["folders"]:
    forms.alert("No script folder set. Choose one with Netbuild > Script Folder.", title=TITLE, exitscript=True)
extensions = ns.installed_extensions(ns.extension_root(__file__), extension_roots())
plan = ns.plan_update(s["folders"], extensions)
if not plan:
    forms.alert("Everything is up to date.\n\n%s\n\nChecked: %s" % (ns.describe(s), ", ".join(extensions)),
                title=TITLE, exitscript=True)
lines = ["%s\n    <- %s" % (dst, src) for src, dst in plan[:SHOW]]
if len(plan) > SHOW:
    lines.append("... and %d more" % (len(plan) - SHOW))
if not forms.alert("Copy %d changed file%s from the script folder?\n\n%s" % (
        len(plan), "" if len(plan) == 1 else "s", "\n".join(lines)), title=TITLE, yes=True, no=True):
    forms.alert("Nothing copied.", title=TITLE, exitscript=True)
copied, errors, backup = ns.apply_update(plan)
msg = "%d file%s updated. The replaced files are in:\n%s" % (copied, "" if copied == 1 else "s", backup)
if errors:
    msg += "\n\nNot copied (%d):\n%s" % (len(errors), "\n".join(errors[:SHOW]))
if forms.alert(msg + "\n\nReload pyRevit now (new icons, titles and libraries)?", title=TITLE, yes=True, no=True):
    reload_pyrevit()

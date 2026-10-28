# -*- coding: utf-8 -*-
"""Netbuild script folder: the folder (network share, synced folder) the Netbuild buttons take their scripts from.

Each button is found there by its folder name ("Level Shift.pushbutton"), in any sub-folder.
Live on: buttons run their script from that folder. Off: Update Scripts copies the changes in.
"Add live scripts to other extensions" puts the same first lines into the buttons of your other extensions.
(c) 2026 Netbuild. All rights reserved. https://skaec.com
"""

__title__ = "Script\nFolder"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import os

from pyrevit import forms

import netbuild_about
import netbuild_scripts as ns
from netbuild_tools import about

TITLE = about.title("Script folder")
EXT = ns.extension_root(__file__)

SHOW_ALL = "Show folders and buttons found"
CHOOSE = "Choose the folder..."
ADD = "Add another folder..."
LIVE_ON = "Live scripts: turn on"
LIVE_OFF = "Live scripts: turn off"
RESCAN = "Look in the folder again"
CLEAR = "Clear my folder (use the default)"
OTHERS = "Add live scripts to other extensions..."
ABOUT = "About Netbuild Tools"
SHOW = 30


def add_to_other_extensions():
    folder = forms.pick_folder(title="Pick an extension folder (or the folder holding several .extension folders)")
    if not folder:
        return
    exts = [e for e in ns.extensions_in(folder) if ns._key(e) != ns._key(EXT)]
    if not exts:
        forms.alert("No .extension folder in:\n%s" % folder, title=TITLE)
        return
    lib = os.path.join(os.path.dirname(os.path.abspath(ns.__file__)), "netbuild_scripts.py")
    todo, skipped, _ = ns.add_header(exts, lib)
    if not todo:
        forms.alert("Nothing to change in:\n%s\n\n%d file(s) skipped (already done, or not a button script)." % (
            "\n".join(exts), len(skipped)), title=TITLE)
        return
    lines = todo[:SHOW] + (["... and %d more" % (len(todo) - SHOW)] if len(todo) > SHOW else [])
    if not forms.alert("Add the live-script lines to these %d file(s)? Each is backed up first.\n\n%s" % (
            len(todo), "\n".join(lines)), title=TITLE, yes=True, no=True):
        return
    done, skipped, backup = ns.add_header(exts, lib, apply=True)
    forms.alert("%d file(s) changed -- they run from the script folder from their next click.\n"
                "The originals are in:\n%s" % (len(done), backup), title=TITLE)


s = ns.settings(EXT)
choice = forms.CommandSwitchWindow.show(
    [SHOW_ALL, CHOOSE, ADD, LIVE_OFF if s["live"] else LIVE_ON, RESCAN, CLEAR, OTHERS, ABOUT],
    message=ns.summary(s))
if choice in (CHOOSE, ADD):
    folder = forms.pick_folder(title="Folder with the Netbuild button folders (sub-folders are searched)")
    if folder:
        ns.save_settings(folders=(s["folders"] + [folder]) if choice == ADD else [folder])
elif choice in (LIVE_ON, LIVE_OFF):
    ns.save_settings(live=choice == LIVE_ON)
elif choice == CLEAR:
    ns.save_settings(folders=[])
elif choice == OTHERS:
    add_to_other_extensions()
elif choice == ABOUT:
    netbuild_about.show(about)                  # its Licence button opens the Licence page
if choice and choice not in (OTHERS, ABOUT):
    s = ns.settings(EXT)
    forms.alert(ns.describe(s, ns.rescan(s["folders"]) if s["folders"] else None), title=TITLE)

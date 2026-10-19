# -*- coding: utf-8 -*-
"""Netbuild script folder: the folder (network share, synced folder) the Netbuild buttons take their scripts from.

Each button is found there by its folder name ("Level Shift.pushbutton"), in any sub-folder.
Live on: buttons run their script from that folder. Off: Update Scripts copies the changes in.
(c) 2026 Netbuild. All rights reserved. https://skaec.com
"""

__title__ = "Script\nFolder"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

from pyrevit import forms

import netbuild_scripts as ns

TITLE = "Netbuild script folder"
EXT = ns.extension_root(__file__)

CHOOSE = "Choose the folder..."
ADD = "Add another folder..."
LIVE_ON = "Live scripts: turn on"
LIVE_OFF = "Live scripts: turn off"
RESCAN = "Look in the folder again"
CLEAR = "Clear my folder (use the default)"

s = ns.settings(EXT)
choice = forms.CommandSwitchWindow.show(
    [CHOOSE, ADD, LIVE_OFF if s["live"] else LIVE_ON, RESCAN, CLEAR], message=ns.describe(s))
if choice in (CHOOSE, ADD):
    folder = forms.pick_folder(title="Folder with the Netbuild button folders (sub-folders are searched)")
    if folder:
        ns.save_settings(folders=(s["folders"] + [folder]) if choice == ADD else [folder])
elif choice in (LIVE_ON, LIVE_OFF):
    ns.save_settings(live=choice == LIVE_ON)
elif choice == CLEAR:
    ns.save_settings(folders=[])
if choice:
    s = ns.settings(EXT)
    forms.alert(ns.describe(s, ns.rescan(s["folders"]) if s["folders"] else None), title=TITLE)

# -*- coding: utf-8 -*-
"""Warnings summary of the active model: every warning grouped by its description, and whether it matches the
B001 profile (most warnings on Areas / Area Separation Lines). Read-only.  Part of Clear Warnings by Netbuild.
(c) 2026 Netbuild. All rights reserved. https://skaec.com
"""

__title__ = "Warnings\nSummary"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

from pyrevit import DB, forms, revit, script

from clear_warnings import about, core

doc = revit.doc
if doc is None or doc.IsFamilyDocument:
    forms.alert("Open a project model first.", title=about.PRODUCT, exitscript=True)

s = core.summary(doc, DB)
_, text = core.profile(s)
output = script.get_output()
output.print_md("## Warnings: %d -- %s" % (s["total"], doc.Title))
output.print_md("**%s**" % text)
if s["groups"]:
    rows = ["| Count | Description |", "|---:|---|"]
    for desc, n in s["groups"]:
        rows.append("| %d | %s |" % (n, desc.replace("|", "/").replace("\n", " ")))
    output.print_md("\n".join(rows))
output.print_md("_%s %s -- Netbuild > Clear Warnings clears them._" % (about.PRODUCT, about.VERSION))

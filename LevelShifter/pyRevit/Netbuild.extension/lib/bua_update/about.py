"""Product information shown in every About screen (window, command line, pyRevit buttons, exe properties).

IronPython 2.7 + CPython 3; the pyRevit extension carries a copy (sync_pyrevit_lib.py).
LICENSE_TEXT must equal the repository's LICENSE file -- a test checks it.
"""

from . import __version__

BRAND = "Netbuild"
NAME = "BUA Update"
PRODUCT = NAME + " by " + BRAND                      # "BUA Update by Netbuild"
VERSION = __version__
PUBLISHER = BRAND                                    # owner of the product
WEBSITE = "https://skaec.com"
YEAR = "2026"
OWNER = BRAND
COPYRIGHT = u"\u00a9 %s %s. All rights reserved." % (YEAR, OWNER)    # (c) 2026 Netbuild. All rights reserved.
LICENSE_NAME = "Netbuild Software Licence Agreement (proprietary)"
LICENSE_KIND = "Proprietary software -- owned by " + OWNER
LICENCE_KEY = "No licence key required for this product."

DESCRIPTION = ("Re-feeds the raw Revit Area export (\"Excel - Raw Area from RVT- Overall With Assets For MEP "
               "Team.xlsx\") into the two formatted BUA workbooks -- Option 1, one \"Overall BUA\" sheet with every "
               "asset stacked, and Option 2, one sheet per asset -- in the FROZEN column format (10 GFA Components "
               "x 24 Space/Room Categories) other disciplines use as a base, then checks every BUA / GFA total "
               "against the raw.")

FEATURES = [
    "Option 1: one 'Overall BUA' sheet -- each asset's own levels, '<Asset> Total' row, blank separator, Grand Total",
    "Option 2: one sheet per asset, its own levels; towers include the typical-floor cross-reference rows",
    "Frozen 274-column skeleton: a new GFA Component or Space/Room Category is reported (!!!), never added",
    "Typical-floor set picked to fit the raw's levels (07-20 / 26-36 / 65-72 or 07-20 / 21-22 / 27-36 / 66-71)",
    "BUA / GFA tie-out per asset and overall; a workbook open in Excel is skipped and named, never half-written",
    "Check (writes nothing), a dated backup of both workbooks before every update, window + command line",
]

REQUIREMENTS = [
    ("BUA Update app (window) and BuaUpdate command line", [
        "Windows 10 / 11, 64-bit -- no Python needed for the .exe files",
        "The two Option workbooks closed in Excel (the raw export may stay open)",
        "From source instead of the .exe: Python 3.9 or later with openpyxl (and tkinter for the window)",
    ]),
    ("BUA Update ribbon button (opens the app from Revit)", [
        "Autodesk Revit 2019 - 2026 with pyRevit 4.8 or later, IronPython engine (pyRevit's default)",
        "No model needs to be open -- the button only starts the app",
    ]),
    ("The project folder", [
        "The raw Revit Area export (schedule 'Excel - Area - Overall With Assets For MEP Team', exported to .xlsx)",
        "One '..._with All Levels_Option 1.xlsx' and one '..._Raw Levels Only_Option 2.xlsx' next to it",
    ]),
]

LICENSE_TEXT = u"""Netbuild Software Licence Agreement

Copyright (c) 2026 Netbuild. All rights reserved.
Website: https://skaec.com

This agreement covers every Netbuild software product -- including Level Shift by
Netbuild, Model Prep by Netbuild, Align Viewports by Netbuild, BUA Update by
Netbuild, Stair Path by Netbuild, Clear Warnings by Netbuild, Element Remover by
Netbuild, Plot Runner by Netbuild, Revit MCP Router by Netbuild, Remote Router by
Netbuild and Revit Status by Netbuild -- together with its updates and documentation
(the "Software").

1. Ownership. The Software is proprietary. It is owned by Netbuild and protected by
   copyright and other intellectual property laws. It is licensed, not sold.

2. Licence. Netbuild grants you a non-exclusive, non-transferable licence to install
   and use the Software for your own work, on the terms under which you obtained it
   from Netbuild or https://skaec.com (including any licence key, number of computers
   and licence period).

3. Restrictions. You may not: (a) copy the Software, except to install it and to keep
   one backup; (b) sell, rent, lease, lend, sublicense, publish or otherwise
   distribute the Software or its licence keys; (c) modify, adapt, decompile,
   disassemble or reverse engineer the Software, or bypass or disable its licence
   checks, except where the law expressly allows it; (d) remove or alter any
   copyright, trademark or licence notice.

4. Licence keys. Where the Software requires a licence key, the key is valid only for
   the computer(s) and period it was issued for. Moving a licence to another computer
   requires a transfer from Netbuild. Netbuild may revoke a licence key if this
   agreement is breached.

5. Termination. This licence ends automatically if you breach this agreement. You
   must then stop using the Software and delete all copies.

6. No warranty. The Software is provided "as is", without warranty of any kind,
   express or implied, including fitness for a particular purpose. You are
   responsible for checking its results and for keeping backups of your models and
   files.

7. Limitation of liability. To the extent permitted by law, Netbuild is not liable
   for any indirect, incidental or consequential damages, or for loss of data, of
   work in Autodesk Revit models, of profit or of business, arising from the use of
   or inability to use the Software.

8. Third parties. Autodesk and Revit are registered trademarks of Autodesk, Inc.
   pyRevit, the Model Context Protocol SDK and other third-party components are used
   under their own licences. Netbuild is not affiliated with or endorsed by Autodesk
   or Anthropic.

Contact: https://skaec.com
"""


def title(extra=""):
    """Window title: 'BUA Update by Netbuild 1.0.0' (+ ' -- extra')."""
    return u"%s %s%s" % (PRODUCT, VERSION, (u" -- " + extra) if extra else u"")


def requirements_text():
    lines = []
    for head, items in REQUIREMENTS:
        lines.append(head)
        lines.extend(u"  - " + i for i in items)
    return u"\n".join(lines)


def about_text(license=True):
    """The whole About screen as plain text."""
    parts = [u"%s  version %s" % (PRODUCT, VERSION), COPYRIGHT + u"  |  " + WEBSITE, u"", DESCRIPTION, u"",
             u"Features"] + [u"  - " + f for f in FEATURES] + [u"", u"Requirements", requirements_text(), u"",
                                                                u"Licence: %s -- owned by %s, %s" % (LICENSE_NAME, OWNER, WEBSITE)]
    if license:
        parts += [u"", LICENSE_TEXT.rstrip()]
    return u"\n".join(parts)


def licence_text():
    """The Licence page as plain text: product, ownership, website, key status and the full agreement."""
    return u"\n".join([u"%s  version %s" % (PRODUCT, VERSION), LICENSE_KIND, u"Website: " + WEBSITE,
                       LICENCE_KEY, COPYRIGHT, u"", LICENSE_TEXT.rstrip()])

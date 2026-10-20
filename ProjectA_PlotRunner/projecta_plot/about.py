"""Product information shown in every About screen (window, command line, exe properties).

LICENSE_TEXT must equal the repository's LICENSE file -- a test checks it.
"""

from . import __version__

BRAND = "Netbuild"
NAME = "Plot Runner"
PRODUCT = NAME + " by " + BRAND                      # "Plot Runner by Netbuild"
VERSION = __version__
PUBLISHER = "Netbuild"
OWNER = "Netbuild"                                   # proprietary software owned by Netbuild
WEBSITE = "https://skaec.com"
YEAR = "2026"
COPYRIGHT = u"\u00a9 %s Netbuild. All rights reserved." % YEAR   # (c) 2026 Netbuild. All rights reserved.
LICENSE_NAME = "Netbuild Software Licence Agreement (proprietary)"
LICENCE_KEY = "No licence key required for this product."

DESCRIPTION = ("Runs the ProjectA Plot GA export pass model by model -- SW00 master, Podium B001-B005, Tower and "
               "Areas -- through your own export scripts (read, never edited), with PDFs and DWGs "
               "verified on disk.")

FEATURES = [
    "One model at a time: you open it in Revit, the runner checks it is open and binds by its title",
    "Revision date in any spelling; each model's own date format is read live before exporting",
    "PDF only, CAD (DWG) only, or PDF + CAD: all PDFs first, then all DWGs, per category",
    "All sheets with that revision date, or only the sheets you list (single, list or series)",
    "Every file verified on disk (written this pass, not empty, %PDF / AC header); DWG byproducts swept",
    "Stalled batch -> one sheet per call; stale replies ignored; every step logged with a file list",
]

REQUIREMENTS = [
    ("Plot Runner app (window) and ProjectAPlot command line", [
        "Windows 10 / 11, 64-bit -- no Python needed for the .exe files",
        "From source instead of the .exe: Python 3.9 or later with tkinter",
    ]),
    ("Revit", [
        "Autodesk Revit 2022 or later -- the export scripts use Revit's PDF export (PDFExportOptions)",
        "pyRevit, IronPython engine (the scripts and the runner's additions are IronPython 2.7)",
        "The Revit MCP extension; its listener running (MCP Status: on) at http://127.0.0.1:48884",
    ]),
    ("Export scripts and models", [
        "export_master_ga_sheets_by_browser_filter.py and export_podium_sheets_by_revision.py, "
        "linked on Setup / Paths (default: <Netbuild folder>\\scripts\\)",
        "The ProjectA model being exported open in Revit (any window may be active)",
    ]),
]

LICENSE_TEXT = u"""Netbuild Software Licence Agreement

Copyright (c) 2026 Netbuild. All rights reserved.
Website: https://skaec.com

This agreement covers every Netbuild software product -- including Level Shift by
Netbuild, Model Prep by Netbuild, Plot Runner by Netbuild, Revit MCP Router by
Netbuild, Remote Router by Netbuild and Revit Status by Netbuild -- together with
its updates and documentation (the "Software").

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
    """Window title: 'Plot Runner by Netbuild 1.3.0' (+ ' -- extra')."""
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
                                                                u"Licence: %s -- owned by %s, %s" % (LICENSE_NAME, OWNER, WEBSITE),
                                                                LICENCE_KEY]
    if license:
        parts += [u"", LICENSE_TEXT.rstrip()]
    return u"\n".join(parts)

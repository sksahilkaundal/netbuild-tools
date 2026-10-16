"""Product information shown in every About screen (window, command line, exe properties).

LICENSE_TEXT must equal the repository's LICENSE file -- a test checks it.
"""

from . import __version__

BRAND = "Netbuild"
NAME = "Plot Runner"
PRODUCT = NAME + " by " + BRAND                      # "Plot Runner by Netbuild"
VERSION = __version__
PUBLISHER = "SKAEC.COM"
WEBSITE = "https://skaec.com"
YEAR = "2026"
COPYRIGHT = u"\u00a9 %s %s" % (YEAR, PUBLISHER)       # (c) 2026 SKAEC.COM
LICENSE_NAME = "MIT License"

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

LICENSE_TEXT = u"""MIT License

Copyright (c) 2026 SKAEC.COM

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def title(extra=""):
    """Window title: 'Plot Runner by Netbuild 1.2.0' (+ ' -- extra')."""
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
                                                                u"License: " + LICENSE_NAME]
    if license:
        parts += [u"", LICENSE_TEXT.rstrip()]
    return u"\n".join(parts)

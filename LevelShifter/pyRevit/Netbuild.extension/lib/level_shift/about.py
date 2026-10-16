"""Product information shown in every About screen (window, command line, pyRevit buttons, exe properties).

IronPython 2.7 + CPython 3; the pyRevit extension carries a copy (sync_pyrevit_lib.py).
LICENSE_TEXT must equal the repository's LICENSE file -- a test checks it.
"""

from . import __version__

BRAND = "Netbuild"
NAME = "Level Shift"
PRODUCT = NAME + " by " + BRAND                      # "Level Shift by Netbuild"
VERSION = __version__
PUBLISHER = "SKAEC.COM"
WEBSITE = "https://skaec.com"
YEAR = "2026"
COPYRIGHT = u"\u00a9 %s %s" % (YEAR, PUBLISHER)       # (c) 2026 SKAEC.COM
LICENSE_NAME = "MIT License"

DESCRIPTION = ("Moves up to 10 levels up or down in a Revit model while every element, group and model "
               "element hosted to them keeps its X, Y, Z: each offset from a moved level changes by the "
               "opposite amount, and every element is measured before and after.")

FEATURES = [
    "Up to 10 levels per run: new elevation or move (+up / -down), current elevation shown read-only",
    "Check (plan only) -> Trial run (rolled back) -> Apply (one Undo entry: 'Level Shift by Netbuild')",
    "Walls, floors, ceilings, roofs, columns, framing, stairs, railings, rooms, MEP, families, doors",
    "Model group members compensated in place; ungrouped, fixed and regrouped only when needed",
    "Every model element measured (bounding box) before and after; anything that moved is listed by Id",
]

REQUIREMENTS = [
    ("Level Shift ribbon button (runs inside Revit)", [
        "Windows 10 / 11, 64-bit",
        "Autodesk Revit 2019 - 2026",
        "pyRevit 4.8 or later, IronPython engine (pyRevit's default)",
    ]),
    ("Level Shift app (window) and LevelShift command line", [
        "Windows 10 / 11, 64-bit -- no Python needed for the .exe files",
        "Revit open with pyRevit and the Revit MCP extension; its listener running "
        "(MCP Status: on) at http://127.0.0.1:48884",
        "From source instead of the .exe: Python 3.9 or later with tkinter",
    ]),
    ("The model", [
        "A project model (not a family), opened editable -- not read-only",
        "Workshared: the moved levels and their elements not borrowed by other users",
        "Save / Synchronize after Apply; Ctrl+Z in Revit undoes the whole move",
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
    """Window title: 'Level Shift by Netbuild 1.3.0' (+ ' -- extra')."""
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

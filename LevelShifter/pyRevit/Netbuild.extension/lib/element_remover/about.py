"""Product information shown in every About screen (command line, pyRevit buttons, exe properties).

IronPython 2.7 + CPython 3; the pyRevit extension carries a copy (sync_pyrevit_lib.py).
LICENSE_TEXT must equal the repository's LICENSE file -- a test checks it.
"""

from . import __version__

BRAND = "Netbuild"
NAME = "Element Remover"
PRODUCT = NAME + " by " + BRAND                      # "Element Remover by Netbuild"
VERSION = __version__
PUBLISHER = BRAND                                    # owner of the product
WEBSITE = "https://skaec.com"
YEAR = "2026"
OWNER = BRAND
COPYRIGHT = u"\u00a9 %s %s. All rights reserved." % (YEAR, OWNER)    # (c) 2026 Netbuild. All rights reserved.
LICENSE_NAME = "Netbuild Software Licence Agreement (proprietary)"
LICENSE_KIND = "Proprietary software -- owned by " + OWNER
LICENCE_KEY = "No licence key required for this product."

DESCRIPTION = ("Removes the elements of a Revit model that sit on chosen worksets and / or pass chosen view "
               "filters (rule-based or saved selection), optionally only some categories such as Walls. "
               "Standalone elements are deleted directly; elements inside model groups are taken out of their "
               "group instances, which are regrouped without them.")

FEATURES = [
    "Targets: worksets, rule-based view filters and saved selection filters -- either or both, by category",
    "Check (plan only) -> Trial run (rolled back) -> Apply (one Undo entry: 'Element Remover by Netbuild')",
    "Elements inside model groups (nested too): ungrouped, removed, regrouped; group type names kept",
    "Identical regrouped instances share one group type again, checked member by member (option)",
    "Pinned elements, levels, grids, links and views are never removed unless asked (pinned) / at all",
    "Every element deleted is listed by Id, including the hosted / dependent ones Revit deletes with it",
]

REQUIREMENTS = [
    ("Element Remover ribbon button (runs inside Revit)", [
        "Windows 10 / 11, 64-bit",
        "Autodesk Revit 2019 - 2026",
        "pyRevit 4.8 or later, IronPython engine (pyRevit's default)",
    ]),
    ("ElementRemover command line", [
        "Windows 10 / 11, 64-bit -- no Python needed for the .exe",
        "Revit open with pyRevit and the Revit MCP extension; its listener running "
        "(MCP Status: on) at http://127.0.0.1:48884",
        "From source instead of the .exe: Python 3.9 or later",
    ]),
    ("The model", [
        "A project model (not a family), opened editable -- not read-only",
        "Workshared: the worksets that hold the targets open; targets and their groups not borrowed by "
        "other users",
        "Save / Synchronize after Apply; Ctrl+Z in Revit undoes the whole removal",
    ]),
]

LICENSE_TEXT = u"""Netbuild Software Licence Agreement

Copyright (c) 2026 Netbuild. All rights reserved.
Website: https://skaec.com

This agreement covers every Netbuild software product -- including Level Shift by
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
    """Window title: 'Element Remover by Netbuild 1.0.0' (+ ' -- extra')."""
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

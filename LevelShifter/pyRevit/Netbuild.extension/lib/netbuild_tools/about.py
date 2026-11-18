"""Product information for Netbuild Tools by Netbuild, shown by every About screen (the Netbuild > About and Licence
buttons, Script Folder > About Netbuild Tools, add_live_header.py about / licence / --version).

IronPython 2.7 + CPython 3. LICENSE_TEXT is Level Shift's copy of the repository's LICENSE (both products ship in
the same extension), so the agreement is the same text everywhere -- a test checks it against LICENSE.
"""

from level_shift.about import LICENSE_TEXT  # noqa: F401 -- the one agreement for every Netbuild product

from . import __version__

BRAND = "Netbuild"
NAME = "Netbuild Tools"
PRODUCT = NAME + " by " + BRAND                      # "Netbuild Tools by Netbuild"
VERSION = __version__
PUBLISHER = BRAND                                    # owner of the product
WEBSITE = "https://skaec.com"
YEAR = "2026"
OWNER = BRAND
COPYRIGHT = u"\u00a9 %s %s. All rights reserved." % (YEAR, OWNER)    # (c) 2026 Netbuild. All rights reserved.
LICENSE_NAME = "Netbuild Software Licence Agreement (proprietary)"
LICENSE_KIND = "Proprietary software -- owned by " + OWNER
LICENCE_KEY = "No licence key required for this product."

DESCRIPTION = ("The Netbuild Tools 01 and 02 ribbon tabs -- schedules and Excel, areas, views and links, joins and "
               "cuts, floors, walls and warnings -- and the script folder: every Netbuild button can run its "
               "script from one OneDrive or network folder, so a change there reaches everyone on the next click.")

FEATURES = [
    "Netbuild Tools 01: Export / Import Excel round trip, Export / Import Rooms Excel, Floor Plate Area, "
    "Restore GA Link Views",
    "Netbuild Tools 02: joins and cuts, floors from walls and room finishes, wall offsets, planter split, "
    "warning fixes",
    "Saved scripts found by file name in any sub-folder of the script folders",
    "Script Folder: choose the folders, live scripts on / off, show the buttons found",
    "Update Scripts: copy changed buttons in from the folder, with a backup first",
    "Add live scripts to other extensions (also add_live_header.py on the command line)",
]

REQUIREMENTS = [
    ("Netbuild Tools 01 / 02 and Scripts panel ribbon buttons (run inside Revit)", [
        "Windows 10 / 11, 64-bit",
        "Autodesk Revit 2022 or later; Export Schedule and Import Excel: Revit 2023 or later",
        "pyRevit 4.8 or later, IronPython engine (pyRevit's default)",
    ]),
    ("Saved scripts", [
        "The scripts the buttons run (e.g. CutFloorsAtColumns_MCP.py, schedule_roundtrip_*.py) in a script "
        "folder: by default %USERPROFILE%\\OneDrive - Studio\\Netbuild and its scripts sub-folder",
        "Export Schedule and Import Excel: Python 3.14 with openpyxl "
        "(%LOCALAPPDATA%\\Programs\\Python\\Python314 or the py launcher)",
    ]),
    ("add_live_header.py (command line)", [
        "Python 3 on Windows; next to Netbuild.extension",
    ]),
    ("The model", [
        "A project model; buttons that change it need it opened editable and the elements not borrowed",
        "Save / Synchronize after a run -- the buttons do not save or sync",
    ]),
]


def title(extra=""):
    """Window title: 'Netbuild Tools by Netbuild 1.0.0' (+ ' -- extra')."""
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

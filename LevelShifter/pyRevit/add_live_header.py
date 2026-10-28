"""Add the Netbuild live-script lines to the buttons of other pyRevit extensions (e.g. Netbuild 01 / 02).

    python add_live_header.py "C:\\pyRevit-Extensions\\Netbuild 01.extension" "C:\\...\\Netbuild 02.extension"
    python add_live_header.py C:\\pyRevit-Extensions            (every .extension folder in it)
    add --apply to change the files; without it, only the list of files is shown.
    python add_live_header.py about | licence | --version     (Netbuild Tools by Netbuild)

Every pushbutton / panelbutton script.py and config.py gets, after its docstring and __title__ / __author__ lines:

    import netbuild_scripts
    netbuild_scripts.run_live(globals())

and netbuild_scripts.py is copied into each extension's lib. Changed files are backed up to
%APPDATA%\\Netbuild\\pyRevit\\backups\\<time> first. The same is in Netbuild > Script Folder in Revit.
"""

import os
import sys

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Netbuild.extension", "lib")
sys.path.insert(0, LIB)

import netbuild_scripts as ns  # noqa: E402
from netbuild_tools import about  # noqa: E402


def main(argv):
    if argv[:1] == ["about"]:
        print(about.about_text())
        return 0
    if argv[:1] in (["license"], ["licence"]):
        print(about.licence_text())
        return 0
    if argv[:1] == ["--version"]:
        print(about.title())
        return 0
    apply = "--apply" in argv
    folders = [a for a in argv if a != "--apply"]
    if not folders:
        print(__doc__)
        return 2
    exts = [e for f in folders for e in ns.extensions_in(os.path.abspath(f))]
    if not exts:
        print("No .extension folder in: %s" % ", ".join(folders))
        return 1
    changed, skipped, backup = ns.add_header(exts, os.path.join(LIB, "netbuild_scripts.py"), apply=apply)
    for path in changed:
        print("%s %s" % ("changed " if apply else "to change", path))
    for path, why in skipped:
        print("skipped   %s -- %s" % (path, why))
    print("%d file(s) %s in %d extension(s)%s" % (
        len(changed), "changed" if apply else "to change", len(exts),
        (". Backup: %s" % backup) if apply and changed else ("" if apply else ". Add --apply to change them.")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Command-line front end. `BuaUpdate <command> -h` for each command.

Exit codes: 0 all totals tie out (or check only) | 1 mismatch | 2 new components / categories |
3 a workbook was open in Excel (skipped) | 4 error.
"""

import argparse
import sys

from . import about
from .engine import AUTO, EXIT, PROFILES, update
from .settings import Settings


def _print(text, tag=None):
    if sys.stdout is None:                             # a --windowed exe has no console
        return
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(enc, "replace").decode(enc))     # a console without the (c) sign
    sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="BuaUpdate", description=(
        "%s %s -- re-feed the raw Revit Area export into the Option 1 / Option 2 BUA workbooks (frozen "
        "274-column format) and check every BUA / GFA total against the raw" % (about.PRODUCT, about.VERSION)),
        epilog="%s  |  %s  |  %s" % (about.COPYRIGHT, about.WEBSITE, about.LICENSE_NAME))
    ap.add_argument("--version", action="version", version="%s %s" % (about.PRODUCT, about.VERSION))
    sub = ap.add_subparsers(dest="cmd")
    for name, text in (("update", "re-feed the raw into both workbooks, then check the totals"),
                       ("check", "read the raw and report new items / level problems -- nothing is written")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--folder", help="project folder (default: settings, the current folder when it holds "
                                        "the raw, else the OneDrive / C:\\SK project folder)")
        p.add_argument("--raw", help="raw export (default: <folder>\\Excel - Raw Area from RVT- Overall With "
                                     "Assets For MEP Team.xlsx)")
        p.add_argument("--option1", help="Option 1 workbook (default: the one '*_with All Levels_Option 1.xlsx')")
        p.add_argument("--option2", help="Option 2 workbook (default: the one '*_Raw Levels Only_Option 2.xlsx')")
        p.add_argument("--typical", choices=[AUTO] + list(PROFILES),
                       help="typical-floor set (default auto: the one that fits the raw's levels)")
        if name == "update":
            p.add_argument("--no-backup", action="store_true",
                           help="do not copy the workbooks to <folder>\\Backup\\<date_time>\\ first")
    sub.add_parser("gui", help="open the window (default)")
    sub.add_parser("about", help="product info, requirements and licence")
    sub.add_parser("license", aliases=["licence"], help="the licence: ownership, website and the full agreement")

    a = ap.parse_args(argv)
    if a.cmd in ("about", "license", "licence"):
        _print(about.about_text() if a.cmd == "about" else about.licence_text())
        return 0
    if a.cmd in (None, "gui"):
        from .gui import main as gui_main
        return gui_main([])

    s = Settings()
    folder = a.folder or s.project_folder()
    if not folder and not (a.raw and a.option1 and a.option2):
        _print("ERROR: no project folder -- pass --folder \"<folder with the raw export and both workbooks>\"")
        return 4
    try:
        res = update(folder=folder, raw=a.raw or s["raw"] or None, option1=a.option1 or s["option1"] or None,
                     option2=a.option2 or s["option2"] or None, typical=a.typical or s["typical"] or AUTO,
                     make_backup=(a.cmd == "update" and not a.no_backup and bool(s["backup"])),
                     write=(a.cmd == "update"), log=_print)
    except Exception as e:  # disk full, a backup that cannot be written, ... -- exit 4, never "mismatch"
        _print("ERROR: %s: %s" % (type(e).__name__, e))
        return EXIT["error"]
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())

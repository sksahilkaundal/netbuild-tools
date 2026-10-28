# -*- coding: utf-8 -*-
"""
BUA dated export - re-feed a raw Revit Area export into dated Option 1 / Option 2 BUA workbooks.

    py -3.14 bua_dated_export.py "<raw.xlsx>" [--date YYMMDD] [--out DIR] [--overwrite]

  * Writes, next to the raw (or into --out):
        <YYMMDD>_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx
        <YYMMDD>_ProjectB_Overall BUA_Space_Room Split_Raw Levels Only_Option 2.xlsx
    --date defaults to today. Existing outputs are refused unless --overwrite.
  * The logic is the project's own update_bua_workbooks.py (BUA_FOLDER below), run unchanged
    except for its three path lines. Its tracked 260702 workbooks are used only as templates
    (copied, never written), so the BUA git repo is not touched.
  * The templates' stale "260622_BUA - Roof Areas (Recrea..." sheet is dropped from both outputs
    (user, 2026-10-01; nothing references it).
  * The first sheet (the re-fed data, "260622_BUA Space Room Split" in the templates) is renamed to
    the --date once update_bua_workbooks.py has finished with it (user, 2026-10-01/02; no formula
    refers to it by name), by the kind of raw:
        itemized (one row per Area)            -> "<YYMMDD>_BUA Space Split-Itemized"
        grouped  (one row per level + Function) -> "<YYMMDD>_BUA Space Room Split"
    A raw is itemized when a Level + Building Asset + Function-Sub key repeats; a grouped export
    ("Itemize every instance" off) has each key once and shows "<varies>" in GLA/GSA Component.
  * Prints the script's own checks: the "!!!" new-items banner, the per-asset BUA/GFA tie-out,
    and "ALL TOTALS TIE OUT - DONE". When the banner fires, it also lists the exact raw rows
    behind it (row number, asset, level, column C value, BUA, GFA) - usually bad data in
    Revit (blank Function -> no "Function-" prefix, or a typo'd Sub-Function).
"""
import argparse
import datetime as dt
import os
import shutil
import sys

BUA_FOLDER = r"C:\SK\Projects\ProjectA\Excel\BUA - Overall With Assets For MEP Team"
SCRIPT = os.path.join(BUA_FOLDER, "update_bua_workbooks.py")
TEMPLATES = {
    "OPTION1": "260702_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx",
    "OPTION2": "260702_ProjectB_Overall BUA_Space_Room Split_Raw Levels Only_Option 2.xlsx",
}
OUT_NAMES = {
    "OPTION1": "%s_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx",
    "OPTION2": "%s_ProjectB_Overall BUA_Space_Room Split_Raw Levels Only_Option 2.xlsx",
}
PATH_LINES = {
    "RAW": 'RAW     = os.path.join(FOLDER, "Excel - Raw Area from RVT- Overall With Assets For MEP Team.xlsx")',
    "OPTION1": 'OPTION1 = os.path.join(FOLDER, "%s")' % TEMPLATES["OPTION1"],
    "OPTION2": 'OPTION2 = os.path.join(FOLDER, "%s")' % TEMPLATES["OPTION2"],
}
DROP_SHEETS = ("Roof Areas",)          # template sheets left out of the outputs (title contains)


def drop_sheets(path):
    import openpyxl
    wb = openpyxl.load_workbook(path)
    active = wb.active.title
    gone = [n for n in wb.sheetnames if any(s in n for s in DROP_SHEETS)]
    for n in gone:
        del wb[n]
    if gone:
        wb.active = wb.sheetnames.index(active) if active in wb.sheetnames else 0
        for ws in wb.worksheets:
            ws.sheet_view.tabSelected = ws.title == wb.active.title
        wb.save(path)


SHEET_NAMES = {True: "BUA Space Split-Itemized", False: "BUA Space Room Split"}   # itemized raw? -> data sheet


def raw_is_itemized(src):
    """True when a Level + Building Asset + Function-Sub key occurs on more than one raw row."""
    seen = set()
    for r in range(4, src.max_row + 1):
        lvl, asset, cval = (src.cell(r, c).value for c in (1, 2, 3))
        if not (asset and isinstance(cval, str) and cval.strip()):
            continue
        key = (lvl, asset, cval)
        if key in seen:
            return True
        seen.add(key)
    return False


def date_first_sheet(path, date, itemized):
    """first sheet -> '<date>_BUA Space Split-Itemized' (itemized raw) or '<date>_BUA Space Room Split'."""
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb.worksheets[0]
    new = ("%s_%s" % (date, SHEET_NAMES[itemized]))[:31]
    if new != ws.title:
        ws.title = new
        wb.save(path)
    return new


def unmapped_rows(g):
    """Raw rows whose column C (GFA Component-Category) is outside the frozen lists."""
    src, out, cur = g["src"], [], None
    for r in range(4, src.max_row + 1):
        a = g["LEVEL_ALIASES"].get(src.cell(r, 1).value, src.cell(r, 1).value)
        rest = [src.cell(r, c).value for c in range(2, 16)]
        if a not in (None, "") and not [x for x in rest if x not in (None, "")]:
            cur = a
            continue
        cval = src.cell(r, 3).value
        if not (isinstance(cval, str) and cval.strip()):
            continue
        asset, cat = g["split_ac"](cval)
        if asset not in g["FROZEN_COMPONENTS"] or cat not in g["FROZEN_CATS"]:
            out.append((r, cur, a, cval, src.cell(r, 15).value or 0, src.cell(r, 14).value or 0))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", help="raw Revit Area export (.xlsx)")
    ap.add_argument("--date", default=dt.date.today().strftime("%y%m%d"), help="YYMMDD prefix (default today)")
    ap.add_argument("--out", help="output folder (default: the raw's folder)")
    ap.add_argument("--overwrite", action="store_true", help="replace existing dated outputs")
    a = ap.parse_args()

    raw = os.path.abspath(a.raw)
    if not os.path.isfile(raw):
        sys.exit("raw file not found: %s" % raw)
    out_dir = os.path.abspath(a.out or os.path.dirname(raw))
    os.makedirs(out_dir, exist_ok=True)
    outputs = {k: os.path.join(out_dir, OUT_NAMES[k] % a.date) for k in OUT_NAMES}

    for k, dst in outputs.items():
        if os.path.exists(dst):
            if not a.overwrite:
                sys.exit("exists (use --overwrite): %s" % dst)
            try:
                os.remove(dst)
            except PermissionError:
                sys.exit("SKIPPED - close this workbook in Excel and rerun: %s" % dst)
        shutil.copyfile(os.path.join(BUA_FOLDER, TEMPLATES[k]), dst)
        drop_sheets(dst)

    src = open(SCRIPT, encoding="utf-8").read()
    for k, line in PATH_LINES.items():
        if src.count(line) != 1:
            sys.exit("update_bua_workbooks.py changed - its %s line is not the expected one; update PATH_LINES here" % k)
        src = src.replace(line, "%-7s = %r" % (k, raw if k == "RAW" else outputs[k]))

    print("raw:     %s\noutputs: %s\n         %s\n" % (raw, outputs["OPTION1"], outputs["OPTION2"]))
    g = {"__name__": "__main__", "__file__": SCRIPT}
    exec(compile(src, SCRIPT, "exec"), g)
    itemized = raw_is_itemized(g["src"])
    print("raw is %s; first sheet renamed: %s" % ("ITEMIZED (one row per area)" if itemized else
                                                 "GROUPED (Itemize every instance off - GLA/GSA may show <varies>)",
                                                 ", ".join(date_first_sheet(p, a.date, itemized) for p in outputs.values())))

    bad = unmapped_rows(g)
    if bad:
        print("\nRaw rows behind the !!! banner (fix in Revit, re-export the raw, rerun):")
        for r, sec, lvl, cval, bua, gfa in bad:
            print("  row %-5d %-22s %-20s C=%-32r BUA=%10.2f  GFA=%10.2f" % (r, sec, lvl, cval, bua, gfa))


if __name__ == "__main__":
    main()

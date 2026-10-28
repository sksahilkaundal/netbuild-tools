# -*- coding: utf-8 -*-
r"""
Schedule round-trip, Excel-side logic: copy how one Building Asset fills a column onto
other Building Assets, in a workbook built by schedule_roundtrip_build_grouped_xlsx.py
(--itemize --id-first). Excel only - Revit is not touched; the import (step 3) writes
the result to the model later.

    py -3.14 scripts\schedule_roundtrip_copy_logic.py <workbook.xlsx> <dump.json>
        --source "Building 2" --targets "Building 3,Building 4,Building 5"
        [--column "GLA/GSA Component"] [--overwrite] [--out <Updated\workbook.xlsx>]

Rule, per target row, keyed on Function + Sub-Function + Area Calc. Type (the key
parameter, read from the dump by Element ID):
  1. every source row with that key has the same value     -> use it (any level)
  2. otherwise, every source row with that key ON THE SAME LEVEL has the same value
                                                            -> use it (level-specific)
  3. otherwise (mixed on that level, level absent, or no source row with that key)
                                                            -> leave the cell, list it
Only blank cells are filled unless --overwrite; a rule that would change an existing
value is listed as a conflict instead. Only --column is written.

Output (default: an "Updated" folder next to the workbook, same file name - the
original is never modified):
  data sheet   filled cells shaded green; still-blank cells keep the amber highlight
  "<source> Logic"  the rules found, every change, and every row left for a decision
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ap = argparse.ArgumentParser()
ap.add_argument("workbook")
ap.add_argument("dump")
ap.add_argument("--source", required=True)
ap.add_argument("--targets", required=True, help="comma-separated Building Asset values")
ap.add_argument("--column", default="GLA/GSA Component")
ap.add_argument("--key-param", default="Area Calc. Type", help="extra key read from the dump (parameter name)")
ap.add_argument("--overwrite", action="store_true")
ap.add_argument("--out")
args = ap.parse_args()
targets = [t.strip() for t in args.targets.split(",") if t.strip()]

d = json.load(open(args.dump, encoding="utf-8"))
key_vals = {}
for e in d["elements"]:
    v = next((v for v in e["vals"].values() if v and v["n"] == args.key_param), None)
    key_vals[e["id"]] = (v or {}).get("disp") or ""

wb = load_workbook(args.workbook)
ws = wb.worksheets[0]
meta = dict((r[0], r[1]) for r in wb["_Meta"].iter_rows(values_only=True) if r and r[0]) if "_Meta" in wb.sheetnames else {}
HEAD = int(meta.get("heading_row", 2))
heads = {str(ws.cell(HEAD, c).value).strip(): c for c in range(1, ws.max_column + 1) if ws.cell(HEAD, c).value}


def col(*names):
    for n in names:
        if n in heads:
            return heads[n]
    raise SystemExit("column not found: %s" % " / ".join(names))


C_ID, C_LVL, C_BLD = col("Element ID(s)", "Element ID"), col("Level"), col("Building Asset")
C_FN, C_SUB, C_OUT = col("Studio_Function Code", "Function"), col("Studio_Sub-Function Code", "Sub-Function"), col(args.column)

rows = []
for r in range(HEAD + 1, ws.max_row + 1):
    i, b = ws.cell(r, C_ID).value, ws.cell(r, C_BLD).value
    if not isinstance(i, int) or not b:
        if isinstance(i, str) and ";" in i:
            raise SystemExit("row %d groups several elements - build the workbook with --itemize" % r)
        continue
    rows.append({"r": r, "id": i, "lvl": ws.cell(r, C_LVL).value, "b": b, "fn": ws.cell(r, C_FN).value,
                 "sub": ws.cell(r, C_SUB).value, "kp": key_vals.get(i, ""), "val": ws.cell(r, C_OUT).value or None})

# ---- learn from the source -----------------------------------------------------------
src = [x for x in rows if x["b"] == args.source]
if not src:
    raise SystemExit("no rows for source %r" % args.source)
all_lv, per_lv = defaultdict(Counter), defaultdict(lambda: defaultdict(Counter))
for x in src:
    k = (x["fn"], x["sub"], x["kp"])
    all_lv[k][x["val"]] += 1
    per_lv[k][x["lvl"]][x["val"]] += 1

# ---- apply to the targets ------------------------------------------------------------
changes, left, conflicts, same = [], [], [], 0
for x in rows:
    if x["b"] not in targets:
        continue
    k = (x["fn"], x["sub"], x["kp"])
    if k not in all_lv:
        new, how = None, "no %s row with this Function / Sub-Function / %s" % (args.source, args.key_param)
    elif len(all_lv[k]) == 1:
        new, how = next(iter(all_lv[k])), "same on every %s level" % args.source
    elif x["lvl"] in per_lv[k] and len(per_lv[k][x["lvl"]]) == 1:
        new, how = next(iter(per_lv[k][x["lvl"]])), "%s, %s only" % (args.source, x["lvl"])
    elif x["lvl"] in per_lv[k]:
        new, how = None, "%s mixed on %s" % (args.source, x["lvl"])
    else:
        new, how = None, "%s varies by level; none on %s" % (args.source, x["lvl"])
    if how.startswith("same on") or how.endswith(" only"):
        if new == x["val"]:
            same += 1
        elif x["val"] and not args.overwrite:
            conflicts.append((x, new, how))
        else:
            changes.append((x, new, how))
    elif not x["val"]:
        left.append((x, how))

def level_rank(name):
    """Basement Mezzanine, Basement 01.. then Ground, 01st, 02nd.. then the rest (as the data sheet)."""
    n = (name or "").lower()
    m = re.search(r"basement\s*(\d+)", n)
    if "basement" in n and "mezzanine" in n:
        return (0, 0, n)
    if m:
        return (0, int(m.group(1)), n)
    if "ground" in n:
        return (1, 0, n)
    m = re.match(r"\s*(\d+)\s*(st|nd|rd|th)\b", n)
    return (1, int(m.group(1)), n) if m else (2, 0, n)


GREEN = PatternFill("solid", fgColor="E2EFDA")
for x, new, how in changes:
    c = ws.cell(x["r"], C_OUT)
    c.value = new
    c.fill = GREEN

# ---- logic sheet ---------------------------------------------------------------------
name = ("%s Logic" % args.source)[:31]
if name in wb.sheetnames:
    del wb[name]
lg = wb.create_sheet(name, 1)
base = ws.cell(HEAD + 3, C_FN).font
F = lambda **kw: Font(name=base.name, size=kw.pop("size", 11), **kw)
HFILL = PatternFill("solid", fgColor="D9D9D9")
r = 1


def title(text, note=None):
    global r
    lg.cell(r, 1, text).font = F(size=14, bold=True)
    r += 1
    if note:
        lg.cell(r, 1, note).font = F(size=10, italic=True)
        r += 1


def header(cols):
    global r
    for j, h in enumerate(cols, 1):
        c = lg.cell(r, j, h)
        c.font, c.fill, c.alignment = F(bold=True, italic=True), HFILL, Alignment(wrap_text=True, vertical="center")
    r += 1


def line(vals, fill=None):
    global r
    for j, v in enumerate(vals, 1):
        c = lg.cell(r, j, v)
        c.font = F()
        if fill:
            c.fill = fill
    r += 1


title("%s logic applied to %s - column '%s' only" % (args.source, ", ".join(targets), args.column),
      "Excel only; Revit unchanged. %d cells filled (green on the data sheet), %d already matched, %d left for a decision "
      "(amber), %d conflicts not changed." % (len(changes), same, len(left), len(conflicts)))
r += 1
title("1. Rules found in %s" % args.source)
header(["Function", "Sub-Function", args.key_param, "Level", args.column, "%s Areas" % args.source, "Applies"])
for k in sorted(all_lv, key=lambda k: tuple(str(v) for v in k)):
    if len(all_lv[k]) == 1:
        v = next(iter(all_lv[k]))
        line([k[0], k[1], k[2], "all levels", v or "(blank)", sum(all_lv[k].values()), "yes"])
    else:
        for lv, cnt in sorted(per_lv[k].items(), key=lambda kv: level_rank(kv[0])):
            ok = len(cnt) == 1
            v = next(iter(cnt)) if ok else "; ".join("%s x%d" % (a or "(blank)", n) for a, n in cnt.items())
            line([k[0], k[1], k[2], lv, v or "(blank)", sum(cnt.values()), "yes, this level" if ok else "no - mixed"],
                 None if ok else PatternFill("solid", fgColor="FFE699"))
r += 1
title("2. Cells filled (%d)" % len(changes))
header(["Element ID", "Building Asset", "Level", "Function", "Sub-Function", args.key_param, "Was", "Now", "Rule"])
for x, new, how in changes:
    line([x["id"], x["b"], x["lvl"], x["fn"], x["sub"], x["kp"], x["val"] or "(blank)", new, how], GREEN)
r += 1
title("3. Left blank - needs a decision (%d)" % len(left))
header(["Element ID", "Building Asset", "Level", "Function", "Sub-Function", args.key_param, "Why"])
for x, how in left:
    line([x["id"], x["b"], x["lvl"], x["fn"], x["sub"], x["kp"], how], PatternFill("solid", fgColor="FFE699"))
if conflicts:
    r += 1
    title("4. Conflicts - existing value kept (%d)" % len(conflicts))
    header(["Element ID", "Building Asset", "Level", "Function", "Sub-Function", args.key_param, "Current", "Rule says", "Rule"])
    for x, new, how in conflicts:
        line([x["id"], x["b"], x["lvl"], x["fn"], x["sub"], x["kp"], x["val"], new or "(blank)", how])
for j, w in enumerate([13, 16, 30, 16, 26, 34, 26, 26, 36], 1):
    lg.column_dimensions[get_column_letter(j)].width = w
lg.freeze_panes = "A3"

out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.workbook)), "Updated", os.path.basename(args.workbook))
os.makedirs(os.path.dirname(out), exist_ok=True)
wb.active = 0
wb.save(out)
print("Wrote", out)
print("  filled %d | already matching %d | left blank %d | conflicts %d" % (len(changes), same, len(left), len(conflicts)))
print("  left by reason:", dict(Counter(h.split(" on ")[0] if " mixed" in h else h for _, h in left)))

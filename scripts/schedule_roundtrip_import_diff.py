# -*- coding: utf-8 -*-
r"""
Schedule round-trip, step 3a of 3: diff an edited round-trip workbook against its hidden
_Original sheet and write the change list the Revit step applies.

    py -3.14 scripts\schedule_roundtrip_import_diff.py <edited.xlsx> [changes.json]
        [--params "Studio_Function Code,Studio_Sub-Function Code,Studio_Area_Department"]

(step 1 = schedule_roundtrip_dump.py, step 2 = schedule_roundtrip_build_grouped_xlsx.py,
step 3b = schedule_roundtrip_import.py inside Revit, dry run by default.)

Reads the workbook built by the grouped builder: _Meta (data sheet, heading row, ID column,
column -> Revit parameter map), _Original (exported text values per ID set) and the data
sheet. Rows are keyed on the Element ID(s) cell, so sorting / filtering rows in Excel is
fine; a grouped row (IDs ';'-separated) applies its edit to every ID in it.

Only the parameters named in --params are imported; edits in any other column are listed
as ignored. A cleared cell becomes an empty-string write (listed separately). Cell text is
trimmed. Values not seen in the column before (in _Lists or _Original) are flagged as
possible typos - they are still written.

Writes <workbook folder>\_import_changes_<workbook stem>.json by default:
    {workbook, model, model_path, exported, data_sheet, params: {name: pid},
     changes: [{id, param, pid, old, new}]}
"""
import argparse
import collections
import json
import os
import warnings

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

warnings.filterwarnings("ignore", message="Data Validation extension")

ap = argparse.ArgumentParser()
ap.add_argument("workbook")
ap.add_argument("out", nargs="?")
ap.add_argument("--params", default="Studio_Function Code,Studio_Sub-Function Code,Studio_Area_Department",
                help="comma-separated Revit parameter names to import (all others are ignored)")
args = ap.parse_args()
wanted = [p.strip() for p in args.params.split(",") if p.strip()]

wb = load_workbook(args.workbook)
for s in ("_Meta", "_Original"):
    if s not in wb.sheetnames:
        raise SystemExit("%s has no %s sheet - not a round-trip workbook" % (args.workbook, s))

# ---- _Meta: key/value block, blank row, then the column map --------------------------
meta, colmap, in_map = {}, [], False
for r in wb["_Meta"].iter_rows(values_only=True):
    if not r or r[0] is None:
        continue
    if r[0] == "column" and r[1] == "heading":
        in_map = True
        continue
    if in_map:
        colmap.append({"col": r[0], "heading": r[1], "param": r[2], "pid": r[3], "kind": r[4]})
    else:
        meta[r[0]] = r[1]
ws = wb[meta["data_sheet"]]
head_row = int(meta["heading_row"])
id_col = column_index_from_string(meta["id_column"])
# Workbooks exported with linked models: rows are keyed "<source model>|<ids>" in _Original and
# every change carries its model, so each model only takes its own rows on import.
model_col = column_index_from_string(meta["model_column"]) if meta.get("model_column") else None

# workbook columns may have been moved: find each parameter's column by its heading
heads = {}
for c in range(1, ws.max_column + 1):
    h = ws.cell(head_row, c).value
    if h is not None and h not in heads:
        heads[h] = c
by_param = {m["param"]: m for m in colmap}
missing = [p for p in wanted if p not in by_param]
if missing:
    raise SystemExit("Parameter(s) not in this workbook: %s" % ", ".join(missing))
for m in colmap:
    if m["heading"] not in heads:
        raise SystemExit("Column %r is missing from sheet %r" % (m["heading"], ws.title))

og_sheet = wb["_Original"]
og_heads = [c.value for c in og_sheet[1]]
original = {}
for r in og_sheet.iter_rows(min_row=2, values_only=True):
    if r[0] is not None:
        original[str(r[0]).strip()] = dict(zip(og_heads[1:], r[1:]))

known = collections.defaultdict(set)              # values the column had before - typo check
for vals in original.values():
    for h, v in vals.items():
        if v not in (None, ""):
            known[h].add(str(v).strip())
if "_Lists" in wb.sheetnames:
    lst = wb["_Lists"]
    h = lst.cell(1, 1).value
    for (v,) in lst.iter_rows(min_row=2, max_col=1, values_only=True):
        if v not in (None, ""):
            known[h].add(str(v).strip())


def norm(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


changes, ignored, cleared, unknown = [], collections.Counter(), [], collections.Counter()
seen, stray = set(), []
for r in range(head_row + 1, ws.max_row + 1):
    key = norm(ws.cell(r, id_col).value)
    model = meta.get("model")
    if model_col and key[:1].isdigit():                       # data rows only (not headings / bands)
        model = norm(ws.cell(r, model_col).value)
        key = model + "|" + key
    if not key or key not in original:
        if key and key not in heads and any(ws.cell(r, heads[m["heading"]]).value not in (None, "")
                                            for m in colmap if m["kind"] not in ("sum", "ids", "model")):
            stray.append((r, key))
        continue
    seen.add(key)
    ids = [int(x) for x in key.split("|")[-1].split(";") if x.strip()]
    for m in colmap:
        if m["kind"] in ("sum", "ids", "model") or m["heading"] not in original[key]:
            continue
        old = norm(original[key][m["heading"]])
        new = norm(ws.cell(r, heads[m["heading"]]).value)
        if old == new:
            continue
        if m["param"] not in wanted:
            ignored[m["heading"]] += len(ids)
            continue
        if new and new not in known[m["heading"]]:
            unknown[(m["heading"], new)] += len(ids)
        for i in ids:
            changes.append({"id": i, "param": m["param"], "pid": m["pid"], "old": old, "new": new, "model": model})
            if not new:
                cleared.append((i, m["param"], old))

lost = sorted(set(original) - seen)
out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.workbook)),
                               "_import_changes_%s.json" % os.path.splitext(os.path.basename(args.workbook))[0])
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"workbook": os.path.abspath(args.workbook), "model": meta.get("model"),
               "model_path": meta.get("model_path"), "exported": meta.get("exported"),
               "schedule": meta.get("schedule"), "data_sheet": ws.title,
               "params": collections.OrderedDict((p, by_param[p]["pid"]) for p in wanted),
               "models": sorted(set(c["model"] for c in changes) | {meta.get("model")}),
               "changes": changes}, fh, indent=1, ensure_ascii=True)

print("Workbook : %s" % args.workbook)
print("Model    : %s | exported %s | sheet %r" % (meta.get("model"), meta.get("exported"), ws.title))
print("Rows     : %d of %d exported ID sets found%s" % (len(seen), len(original),
      "" if not lost else " - MISSING %d (deleted rows are NOT imported): %s" % (len(lost), ", ".join(lost[:10]))))
print("Changes  : %d parameter writes on %d elements" % (len(changes), len(set((c["model"], c["id"]) for c in changes))))
if model_col:
    for mdl, k in sorted(collections.Counter(c["model"] for c in changes).items()):
        print("  %5d  in %s" % (k, mdl))
per = collections.Counter((c["param"], c["old"] or "<blank>", c["new"] or "<blank>") for c in changes)
for (p, o, n), k in sorted(per.items(), key=lambda x: (x[0][0], -x[1])):
    print("  %4d  %s: %s -> %s" % (k, p, o, n))
if cleared:
    print("Cleared  : %d cells emptied (written as empty text)" % len(cleared))
if unknown:
    print("New values not seen in the column before (check for typos):")
    for (h, v), k in unknown.items():
        print("  %4d  %s = %r" % (k, h, v))
if ignored:
    print("Ignored edits (not in --params): %s" % ", ".join("%s x%d" % kv for kv in ignored.items()))
if stray:
    print("Rows without a known Element ID (not imported): %s" % ", ".join("row %d" % r for r, _ in stray[:10]))
print("Wrote %s" % out)

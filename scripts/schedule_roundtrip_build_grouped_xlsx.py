# -*- coding: utf-8 -*-
r"""
Schedule round-trip, step 2 (grouped variant): build a NON-itemized workbook that copies
the look of a reference Excel schedule, from the step-1 JSON dump.

    py -3.14 scripts\schedule_roundtrip_build_grouped_xlsx.py <dump.json> <reference.xlsx> [out.xlsx]
        [--sheet "260930_Assets Cross Check"] [--band "Building Asset"]
        [--id-first] [--add-after "GFA Component-Space/Room Category=Studio_Function Code,Studio_Sub-Function Code"]

(step 1 = scripts\schedule_roundtrip_dump.py inside Revit; the itemized variant is
scripts\schedule_roundtrip_build_xlsx.py; step 3 = import back, written once the parameter
logic is defined.)

The reference workbook is the template: its theme, fonts, fills, borders, column widths,
number formats, print setup and row layout are reused cell-for-cell:
    title row / heading row / blank row / band row (one per --band value) / data rows /
    totals row (=SUM) / repeated heading row / blank row.
Columns = the reference's heading row, matched by name to the schedule's field headings,
plus any schedule fields named in --add-after (placed after the given heading, styled like
it) and, with --id-first, an "Element ID(s)" column in front (styled like the reference's
first column).

Grouping: one row per unique combination of ALL text columns (Level, Building Asset,
GFA Component, Function, Sub-Function, GLA/GSA Component, Floor Count, ...), so
GLA/GSA Component is part of the key and a row never shows "<varies>". Area columns are
summed (unrounded, so the totals row ties out to the Revit grand total). Rows whose
GLA/GSA Component is empty in the model are highlighted - they still need a value.

Round-trip keys: the Element ID(s) of each row (visible first column with --id-first,
otherwise a hidden column after the last one), ';'-separated when a row groups several
elements. Hidden sheet _Original = the exported text values per ID set, so the importer
can apply an edited row to all its elements and write only what changed.
Hidden sheets _Lists (GLA/GSA dropdown values) and _Meta (column map) too.
"""
import argparse
import copy
import datetime
import json
import re
from collections import OrderedDict

from openpyxl import load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ap = argparse.ArgumentParser()
ap.add_argument("dump")
ap.add_argument("reference")
ap.add_argument("out", nargs="?")
ap.add_argument("--sheet", help="sheet name (default: <yymmdd>_<reference name after its date prefix>)")
ap.add_argument("--band", default="Building Asset", help="heading whose values make the grey band rows")
ap.add_argument("--component", default="GLA/GSA Component", help="heading that must be filled on every row")
ap.add_argument("--id-first", action="store_true", help="show the Element ID(s) as the first column")
ap.add_argument("--add-after", action="append", default=[],
                help='"<reference heading>=<schedule field>,<schedule field>" (repeatable)')
ap.add_argument("--itemize", action="store_true", help="one row per element instead of grouped rows")
ap.add_argument("--level-order", choices=["building", "alpha"], default="building",
                help="building = Basement Mezzanine, Basement 01, 02 ... then Ground, 01st, 02nd ... then the rest; "
                     "alpha = by name, as Revit sorts")
args = ap.parse_args()

d = json.load(open(args.dump, encoding="utf-8"))
stamp = datetime.datetime.fromisoformat(d["exported"])
fields = d["fields"]


def key(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# ---- read the template layout --------------------------------------------------------
wb = load_workbook(args.reference)
tpl = wb.active
tcols = max(c for c in range(1, tpl.max_column + 1) if tpl.cell(2, c).value is not None)
row_vals = lambda r: [tpl.cell(r, c).value for c in range(1, tcols + 1)]
HEAD = next(r for r in range(1, 10) if sum(v is not None for v in row_vals(r)) >= tcols - 1)
theads = row_vals(HEAD)
BAND = next(r for r in range(HEAD + 1, tpl.max_row + 1)
            if row_vals(r)[0] is not None and all(v is None for v in row_vals(r)[1:]))
DATA = next(r for r in range(BAND + 1, tpl.max_row + 1) if row_vals(r)[1] is not None)
TOTAL = next(r for r in range(DATA, tpl.max_row + 1)
             if any(isinstance(v, str) and v.startswith("=") for v in row_vals(r)))
TAIL = [r for r in range(TOTAL + 1, tpl.max_row + 1)]            # repeated heading + blank
pre = list(range(1, BAND))                                      # title, heading, blank
S = {r: [copy.copy(tpl.cell(r, c)._style) for c in range(1, tcols + 1)] for r in pre + [BAND, DATA, TOTAL] + TAIL}
H = {r: tpl.row_dimensions[r].height for r in S}
twidth = [tpl.column_dimensions[get_column_letter(c)].width for c in range(1, tcols + 1)]
existing_components = set()
ci_tpl = next((i for i, h in enumerate(theads) if key(h) == key(args.component)), None)
if ci_tpl is not None:
    for r in range(DATA, TOTAL):
        v = tpl.cell(r, ci_tpl + 1).value
        if v and v not in ("<varies>", theads[ci_tpl]):
            existing_components.add(v)

# ---- output columns: reference columns + inserted fields (+ ID in front) -------------
by_head = {}
for f in fields:
    by_head.setdefault(key(f["heading"]), f)
    by_head.setdefault(key(f["name"]), f)
inserts = {}
for spec in args.add_after:
    after, names = spec.split("=", 1)
    inserts[key(after)] = [n.strip() for n in names.split(",") if n.strip()]

cols = []                                    # {head, field|None, src (0-based template col), width}
for i, h in enumerate(theads):
    f = by_head.get(key(h))
    if f is None:
        raise SystemExit("Reference column %r has no matching schedule field" % h)
    cols.append({"head": h, "field": f, "src": i, "width": twidth[i]})
    for n in inserts.pop(key(h), []):
        g = by_head.get(key(n))
        if g is None:
            raise SystemExit("--add-after field %r is not in the schedule" % n)
        cols.append({"head": g["heading"], "field": g, "src": i, "width": max(18, len(g["heading"]) + 4)})
if inserts:
    raise SystemExit("--add-after heading(s) not in the reference: %s" % ", ".join(inserts))
if args.id_first:
    cols[0]["src"] = 1                       # old first column becomes an inner column
    cols[0]["width"] = max(twidth[1] or 18, 20)
    cols.insert(0, {"head": "Element ID(s)", "field": None, "src": 0, "width": 22})
# Dumps made with INCLUDE_LINKS carry elements of several models: add a Source Model column and
# key every row on model + id (ids of different models can be equal).
models = []
for e in d["elements"]:
    e.setdefault("model", d["doc"])
    if e["model"] not in models:
        models.append(e["model"])
MULTI = len(models) > 1 or bool(d.get("include_links"))
if MULTI:
    cols.insert(1 if args.id_first else 0, {"head": "Source Model", "field": None, "src": 1, "width": 36,
                                            "model": True})
ncol = len(cols)
for c in cols:
    c["numeric"] = c["field"] is not None and c["field"]["ftype"] not in ("Instance", "ElementType", "CombinedParameter")
    c["text"] = c["field"] is not None and not c["numeric"]


def text_of(e, f):
    if f["ftype"] == "CombinedParameter":
        parts = []
        for p in f["combined"]:
            v = e["vals"].get(str(p["pid"]))
            t = ((v["raw"] if v["st"] == "String" else v["disp"]) or "") if v else ""
            parts.append((p["prefix"] or "") + t + (p["suffix"] or ""))
        out = ""
        for i, p in enumerate(f["combined"]):
            out += parts[i] + ((p["sep"] or "") if i < len(parts) - 1 else "")
        return out if any(parts) else None
    v = e["vals"].get(str(f["pid"]))
    if not v or not v["has"]:
        return None
    if v["st"] == "String":
        return v["raw"] or None
    if v["st"] == "Double" and v.get("si") is not None and not re.search(r"area|length|volume", v["spec"]):
        x = v["si"]
        return int(x) if float(x).is_integer() else x
    return v["disp"] or None


def num_of(e, f):
    txt = (e.get("calc") or {}).get(str(f["idx"]))
    try:
        v = float((txt or "0").replace(",", "").split()[0])
    except (ValueError, IndexError):
        return 0.0
    a = e.get("area_m2")
    if a and v:
        k = max(1, int(round(v / a)))                   # formula = Area x Floor Count on typical floors
        if abs(v - a * k) <= 0.006:
            return a * k
    return v


# ---- group ---------------------------------------------------------------------------
groups = OrderedDict()
for e in d["elements"]:
    k = tuple(text_of(e, c["field"]) if c["text"] else (e["model"] if c.get("model") else None) for c in cols) \
        + ((e["model"], e["id"]) if args.itemize else ())
    g = groups.setdefault(k, {"ids": [], "sums": [0.0] * ncol})
    g["ids"].append(e["id"])
    for i, c in enumerate(cols):
        if c["numeric"]:
            g["sums"][i] += num_of(e, c["field"])

find = lambda h: next((i for i, c in enumerate(cols) if key(c["head"]) == key(h)), None)
band_i, comp_i, level_i = find(args.band), find(args.component), find("Level")
model_i = next((i for i, c in enumerate(cols) if c.get("model")), None)
text_cols = [i for i, c in enumerate(cols) if c["text"]]
order = [band_i] + ([level_i] if level_i is not None else []) + [i for i in text_cols if i not in (band_i, level_i)]


def level_rank(name):
    n = (name or "").lower()
    if args.level_order == "alpha":
        return (0, 0, n)
    m = re.search(r"basement\s*(\d+)", n)
    if "basement" in n and "mezzanine" in n:
        return (0, 0, n)
    if m:
        return (0, int(m.group(1)), n)
    if "ground" in n:
        return (1, 0, n)
    m = re.match(r"\s*(\d+)\s*(st|nd|rd|th)\b", n) or re.search(r"(?:level|floor)\s*(\d+)", n)
    if m:
        return (1, int(m.group(1)), n)
    return (2, 0, n)                                    # roof and anything else last


def sort_key(kv):
    k = kv[0]
    out = []
    for i in order:
        v = "" if k[i] is None else str(k[i])
        out.append(level_rank(v) if i == level_i else (0, 0, v.lower()))
    return tuple(out) + (min(kv[1]["ids"]),)


rows = sorted(groups.items(), key=sort_key)


def id_cell(ids):
    return ids[0] if len(ids) == 1 else ";".join(str(i) for i in ids)


# ---- write the new sheet into the template workbook ----------------------------------
name = args.sheet or (stamp.strftime("%y%m%d") + "_" + re.sub(r"^\d{6}_", "", tpl.title))[:31]
ws = wb.create_sheet(name + "_tmp")
IDCOL = 1 if args.id_first else ncol + 1
heads = [c["head"] for c in cols]


def put_row(r, src, values=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(r, j)
        cell._style = copy.copy(S[src][c["src"]])
        if values is not None and values[j - 1] is not None:
            cell.value = values[j - 1]
    if H.get(src):
        ws.row_dimensions[r].height = H[src]


r = 1
for p in pre:
    put_row(r, p, [d["schedule"]] + [None] * (ncol - 1) if p == 1 else (heads if p == HEAD else None))
    r += 1
first_data, blank_comp, cur_band = None, 0, object()
for k, g in rows:
    if k[band_i] != cur_band:
        cur_band = k[band_i]
        put_row(r, BAND, [cur_band or "<blank>"] + [None] * (ncol - 1))
        r += 1
    vals = [g["sums"][i] if c["numeric"] else k[i] for i, c in enumerate(cols)]
    put_row(r, DATA, vals)
    ws.cell(r, IDCOL, id_cell(g["ids"])).alignment = Alignment(horizontal="left")   # single id = number
    first_data = first_data or r
    if comp_i is not None and not k[comp_i]:
        blank_comp += 1
    r += 1
last_data = r - 1
tot = [("=SUM(%s%d:%s%d)" % (get_column_letter(i + 1), first_data, get_column_letter(i + 1), last_data))
       if c["numeric"] else None for i, c in enumerate(cols)]
put_row(r, TOTAL, tot)
total_row = r
r += 1
for t in TAIL:
    put_row(r, t, heads if row_vals(t)[0] is not None else None)
    r += 1

for j, c in enumerate(cols, 1):
    if c["width"]:
        ws.column_dimensions[get_column_letter(j)].width = c["width"]
IDL = get_column_letter(IDCOL)
if not args.id_first:
    ws.cell(HEAD, IDCOL, "Element IDs (import key - do not edit)")
    ws.column_dimensions[IDL].width = 40
    ws.column_dimensions[IDL].hidden = True
ws.freeze_panes = ws.cell(HEAD + 1, 1)
ws.sheet_view.zoomScale = tpl.sheet_view.zoomScale
ws.page_setup.orientation = tpl.page_setup.orientation
ws.page_setup.paperSize = tpl.page_setup.paperSize
ws.print_title_rows = "1:%d" % HEAD
ws.print_area = "A1:%s%d" % (get_column_letter(ncol), r - 1)

CL = get_column_letter(comp_i + 1) if comp_i is not None else None
BL = get_column_letter(band_i + 1)                      # filled on data rows, empty on band rows
if CL:
    ws.conditional_formatting.add(
        "%s%d:%s%d" % (CL, first_data, CL, last_data),
        FormulaRule(formula=['AND($%s%d<>"",LEN(TRIM($%s%d))=0)' % (BL, first_data, CL, first_data)],
                    fill=PatternFill(fill_type="solid", start_color="FFE699", end_color="FFE699"),  # dxf reads bgColor
                    stopIfTrue=False))

# ---- hidden helper sheets ------------------------------------------------------------
lst = wb.create_sheet("_Lists")
comp_values = sorted(existing_components | set(k[comp_i] for k in groups if comp_i is not None and k[comp_i]))
lst.cell(1, 1, args.component)
for i, v in enumerate(comp_values, 2):
    lst.cell(i, 1, v)
lst.sheet_state = "hidden"
if CL and comp_values:
    dv = DataValidation(type="list", formula1="=_Lists!$A$2:$A$%d" % (len(comp_values) + 1),
                        allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(dv)
    dv.add("%s%d:%s%d" % (CL, first_data, CL, last_data))

og = wb.create_sheet("_Original")
og.append(["Element IDs"] + [heads[i] for i in text_cols])
for k, g in rows:
    ids = ";".join(str(i) for i in g["ids"])
    og.append([(k[model_i] + "|" + ids) if MULTI else ids] + [k[i] for i in text_cols])
og.sheet_state = "hidden"

mt = wb.create_sheet("_Meta")
for kv in [("tool", "schedule_roundtrip grouped v2"), ("schedule", d["schedule"]), ("schedule_id", d["schedule_id"]),
           ("model", d["doc"]), ("model_path", d["doc_path"]), ("exported", d["exported"]),
           ("scope", ("host + linked models: " + "; ".join(models)) if MULTI
                     else "host model only - linked models excluded"), ("elements", len(d["elements"])),
           ("model_column", get_column_letter(model_i + 1) if MULTI else None),
           ("models", "; ".join(models)),
           ("rows", len(rows)), ("itemized", args.itemize), ("level_order", args.level_order),
           ("rows_without_" + key(args.component).replace(" ", "_"), blank_comp),
           ("data_sheet", name), ("heading_row", HEAD), ("id_column", IDL),
           ("grouped_by", ", ".join(heads[i] for i in text_cols)), ("reference_template", args.reference)]:
    mt.append(list(kv))
mt.append([])
mt.append(["column", "heading", "revit parameter", "parameter id", "kind"])
for j, c in enumerate(cols, 1):
    f = c["field"]
    if c.get("model"):
        mt.append([get_column_letter(j), c["head"], "(source model)", None, "model"])
        continue
    mt.append([get_column_letter(j), c["head"], f["name"] if f else "(element ids)", f["pid"] if f else None,
               "ids" if f is None else ("sum" if c["numeric"] else f["ftype"])])
mt.sheet_state = "hidden"

# drop the template sheet (and any names pointing at it), then take its place
for n in list(wb.defined_names.keys()) if hasattr(wb.defined_names, "keys") else []:
    if tpl.title in str(wb.defined_names[n].attr_text):
        del wb.defined_names[n]
wb.remove(tpl)
ws.title = name
wb.move_sheet(ws, offset=-wb.index(ws))
wb.active = 0
ws.sheet_view.tabSelected = True
wb.calculation.fullCalcOnLoad = True

out = args.out or args.dump.replace("_area_schedule_dump.json", "%s - %s - %s.xlsx" % (
    re.sub(r'[<>:"/\\|?*]', "_", d["schedule"]), d["doc"], stamp.strftime("%Y-%m-%d")))
wb.save(out)
print("Wrote", out)
print("  sheet %r | %d columns | %d grouped rows from %d elements | %d rows without %s | totals row %d"
      % (name, ncol, len(rows), len(d["elements"]), blank_comp, args.component, total_row))

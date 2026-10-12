# -*- coding: utf-8 -*-
r"""
Schedule round-trip, step 2 of 3: build the editable workbook from the step-1 JSON dump.

    py -3.14 scripts\schedule_roundtrip_build_xlsx.py <dump.json> [out.xlsx]

(step 1 = scripts\schedule_roundtrip_dump.py inside Revit; step 3 = import back, written
once the parameter logic is defined.)

Sheets
  <data>      One row per HOST-model element (linked models excluded), in schedule order.
              Every schedule field, including the ones hidden in the schedule.
              Row 3 = Revit parameter name, row 4 = access, row 5 = heading (filter row).
              Pale-yellow columns are writable; grey columns are read-only reference
              (built-in, key-schedule-driven, schedule formulas, combined parameters).
              Element ID + UniqueId are the import keys - never edit or delete them.
  Summary     Per-building SUMIFS of the calculated columns, tied out against the Revit
              schedule's own grand total.
  Fields      Column -> Revit parameter map (id, shared GUID, storage, units, access).
              The importer reads this sheet.
  Key - <p>   Every key of a key-schedule parameter and what it drives (dropdown source).
  Lists       Worksets + the values already used in each writable text parameter.
  _Original   (hidden) the exported values, so the importer writes only changed cells.
  _Meta       (hidden) model, schedule, export time.

Colours and fonts come from design\tokens.json (Revit Tools, light values).
"""
import datetime
import json
import os
import re
import sys
from collections import Counter, OrderedDict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS = os.path.join(HERE, "..", "design", "tokens.json")


def load_colours():
    tok = json.load(open(TOKENS, encoding="utf-8"))
    out = {}
    for t in tok["color"]["tokens"]:
        v = t["value"]["light"] if isinstance(t["value"], dict) else t["value"]
        if isinstance(v, str) and v.startswith("#"):
            out[t["name"]] = v.lstrip("#").upper()
    return out


C = load_colours()
UI, MONO = "Helvetica", "Consolas"


def fill(tok):
    return PatternFill("solid", fgColor=C[tok])


def font(size=10, bold=False, tok="ink", mono=False, italic=False):
    return Font(name=MONO if mono else UI, size=size, bold=bold, italic=italic, color=C[tok])


LINE = Side(style="thin", color=C["grid-line-light"])
RULE = Side(style="thin", color=C["grid-line"])
BOX = Border(left=LINE, right=LINE, top=LINE, bottom=LINE)
HEAD_BOX = Border(left=RULE, right=RULE, top=RULE, bottom=Side(style="medium", color=C["accent"]))
F_EDIT, F_RO, F_KEY, F_HEAD = fill("note-bg"), fill("row-alt"), fill("table-header"), fill("table-header-deep")

src = sys.argv[1]
d = json.load(open(src, encoding="utf-8"))
fields, elems = d["fields"], sorted(d["elements"], key=lambda e: e.get("row", 10 ** 9))
keysch = d.get("key_schedules", {})
stamp = datetime.datetime.fromisoformat(d["exported"])


def safe(s):
    return re.sub(r'[<>:"/\\|?*]', "_", s).strip()


out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(src), "%s - %s - %s.xlsx" % (safe(d["schedule"]), safe(d["doc"]), stamp.strftime("%Y-%m-%d")))


# ---- column model --------------------------------------------------------------------
def first_rec(pid):
    for e in elems:
        v = e["vals"].get(str(pid))
        if v:
            return v
    return None


key_driven = set()                                   # params filled by a key schedule
for k in keysch.values():
    key_driven.update(k["fields"][1:])               # [0] is "Key Name"

cols = [
    {"head": "Element ID", "param": "(key)", "kind": "id", "access": "key - do not edit"},
    {"head": "UniqueId", "param": "(key)", "kind": "uid", "access": "key - do not edit"},
]
for f in fields:
    c = {"head": f["heading"], "field": f, "hidden": f["hidden"], "param": f["name"]}
    if f["ftype"] in ("Instance", "ElementType"):
        rec = first_rec(f["pid"])
        c.update(kind="param", pid=f["pid"], rec=rec)
        name = rec["n"] if rec else f["name"]
        c["param"] = name
        if rec is None:
            c["access"] = "read-only (not on these elements)"
        elif name in keysch:
            c["access"], c["kind"] = "EDIT - pick a key", "keyparam"
        elif name == "Workset" and d.get("worksets"):
            c["access"], c["kind"] = "EDIT - pick a workset", "workset"
        elif rec["ro"] and name in key_driven:
            c["access"] = "read-only - set by key schedule"
        elif rec["ro"]:
            c["access"] = "read-only"
        else:
            c["access"] = "EDIT"
    elif f["ftype"] == "CombinedParameter":
        c.update(kind="calc", access="read-only - combined parameter")
        c["param"] = " + ".join((first_rec(p["pid"]) or {"n": str(p["pid"])})["n"] for p in f["combined"])
    else:
        c.update(kind="calc", access="read-only - schedule %s" % f["ftype"].lower())
    cols.append(c)
cols.append({"head": "Notes", "param": "(free text, ignored on import)", "kind": "notes", "access": "free"})
for i, c in enumerate(cols, 1):
    c["col"] = i
    c["L"] = get_column_letter(i)
    c["editable"] = c["access"].startswith("EDIT") or c["kind"] == "notes"


def is_numeric_calc(c):
    return c["kind"] == "calc" and c["field"]["ftype"] != "CombinedParameter"


def value_of(e, c):
    k = c["kind"]
    if k == "id":
        return e["id"]
    if k == "uid":
        return e["uid"]
    if k == "notes":
        return None
    if k == "calc":
        f = c["field"]
        if f["ftype"] == "CombinedParameter":
            parts = []
            for p in f["combined"]:
                v = e["vals"].get(str(p["pid"]))
                t = ((v["raw"] if v["st"] == "String" else v["disp"]) or "") if v else ""
                parts.append((p["prefix"] or "") + t + (p["suffix"] or ""))
            txt = ""
            for i, p in enumerate(f["combined"]):
                txt += parts[i] + ((p["sep"] or "") if i < len(parts) - 1 else "")
            return txt if any(parts) else None
        txt = (e.get("calc") or {}).get(str(f["idx"]))
        if txt in (None, ""):
            return None
        try:
            v = float(txt.replace(",", "").split()[0])
        except ValueError:
            return txt
        a = e.get("area_m2")                              # un-round values that ARE the area
        if a and v:                                       # (or Area x Floor Count on typical floors)
            k = max(1, int(round(v / a)))
            if abs(v - a * k) <= 0.006:
                return a * k
        return v
    v = e["vals"].get(str(c["pid"]))
    if not v or not v["has"]:
        return None
    st = v["st"]
    if st == "String":
        return v["raw"] if v["raw"] not in ("",) else None
    if st == "Double":
        return v.get("si", v["raw"])
    if st == "Integer":
        if c["kind"] == "workset" or (v["disp"] and not re.match(r"^-?\d+$", v["disp"])):
            return v["disp"]
        return v["raw"]
    if st == "ElementId":
        return v["disp"] or None
    return v["disp"]


def numfmt(c):
    if is_numeric_calc(c):
        return "#,##0.00"
    rec = c.get("rec")
    if rec and rec["st"] == "Double":
        return "#,##0.00" if ("area" in rec["spec"] or "length" in rec["spec"] or "volume" in rec["spec"]) else "General"
    return None


wb = Workbook()
ws = wb.active
ws.title = safe(d.get("sheet_title") or "Data")[:31]
data_title = ws.title
if data_title == "Data":
    cat = {-2003200: "Areas", -2000160: "Rooms"}.get(d["category_id"], "Elements")
    ws.title = data_title = cat

HR, FIRST = 5, 6                                      # heading row, first data row
last = FIRST + len(elems) - 1
n_other = sum(1 for e in elems if e.get("owner"))
ws["A1"] = d["schedule"]
ws["A1"].font = font(14, bold=True)
ws["A2"] = ("Model: %s   |   %d elements, current (host) model only - linked models excluded   |   "
            "exported %s   |   yellow = editable, grey = read-only; Element ID / UniqueId are the import keys"
            % (d["doc"], len(elems), stamp.strftime("%d %b %Y %H:%M")))
ws["A2"].font = font(9, tok="ink-muted")

for c in cols:
    L = c["L"]
    p = ws.cell(3, c["col"], c["param"] + ("  [hidden in schedule]" if c.get("hidden") else ""))
    p.font = font(8, tok="ink-muted", italic=bool(c.get("hidden")))
    p.alignment = Alignment(wrap_text=True, vertical="bottom")
    a = ws.cell(4, c["col"], c["access"])
    a.font = font(8, bold=c["editable"], tok="on-fill")
    a.fill = fill("note-border") if c["access"].startswith("EDIT") else (F_KEY if c["kind"] in ("id", "uid") else F_RO)
    a.alignment = Alignment(wrap_text=True, vertical="center")
    a.border = BOX
    h = ws.cell(HR, c["col"], c["head"])
    h.font = font(9, bold=True, tok="on-fill", italic=bool(c.get("hidden")))
    h.fill = F_HEAD
    h.border = HEAD_BOX
    h.alignment = Alignment(wrap_text=True, vertical="center")

for r, e in enumerate(elems, FIRST):
    for c in cols:
        cell = ws.cell(r, c["col"], value_of(e, c))
        cell.border = BOX
        if c["kind"] in ("id", "uid"):
            cell.font = font(9, mono=True, tok="ink-muted")
            cell.fill = F_KEY
        else:
            cell.font = font(10)
            cell.fill = F_EDIT if c["editable"] else F_RO
        nf = numfmt(c)
        if nf:
            cell.number_format = nf

widths = {"id": 11, "uid": 16, "notes": 30}
for c in cols:
    w = widths.get(c["kind"])
    if w is None:
        longest = max([len(str(ws.cell(r, c["col"]).value or "")) for r in range(FIRST, min(last, FIRST + 400) + 1)] + [8])
        w = max(11, min(34, max(longest, len(c["head"]) * 0.5) + 2))
    ws.column_dimensions[c["L"]].width = w
ws.row_dimensions[3].height = 24
ws.row_dimensions[4].height = 24
ws.row_dimensions[HR].height = 42
ws.freeze_panes = ws.cell(FIRST, 3)
ws.auto_filter.ref = "A%d:%s%d" % (HR, cols[-1]["L"], last)
ws.column_dimensions["B"].outlineLevel = 1                  # UniqueId collapsible
ws.sheet_view.zoomScale = 90

# ---- key schedule sheets + dropdowns -------------------------------------------------
used_keys = [c for c in cols if c["kind"] == "keyparam"]
for c in used_keys:
    k = keysch[c["param"]]
    ks = wb.create_sheet(safe("Key - " + c["param"])[:31])
    ks["A1"] = "%s  (key schedule \"%s\", %d keys)" % (c["param"], k["schedule"], len(k["items"]))
    ks["A1"].font = font(12, bold=True)
    ks["A2"] = "Picking a key in the %s column sets every value on its row (read-only columns on the data sheet)." % c["head"]
    ks["A2"].font = font(9, tok="ink-muted")
    for j, name in enumerate(k["fields"], 1):
        h = ks.cell(4, j, name)
        h.font, h.fill, h.border = font(9, bold=True, tok="on-fill"), F_HEAD, HEAD_BOX
        h.alignment = Alignment(wrap_text=True, vertical="center")
        ks.column_dimensions[get_column_letter(j)].width = 30 if j <= 2 else 18
    for i, it in enumerate(k["items"], 5):
        for j, v in enumerate(it["vals"], 1):
            cell = ks.cell(i, j, v)
            cell.font, cell.border = font(10, bold=(j == 1)), BOX
            if i % 2 == 0:
                cell.fill = fill("row-alt")
    ks.freeze_panes = "B5"
    ks.auto_filter.ref = "A4:%s%d" % (get_column_letter(len(k["fields"])), 4 + len(k["items"]))
    dv = DataValidation(type="list", formula1="='%s'!$A$5:$A$%d" % (ks.title, 4 + len(k["items"])), allow_blank=True,
                        showErrorMessage=True, errorTitle="Not a key",
                        error="Pick a key name from the '%s' sheet (or leave blank for <none>)." % ks.title)
    ws.add_data_validation(dv)
    dv.add("%s%d:%s%d" % (c["L"], FIRST, c["L"], last))
    c["keysheet"] = ks.title

# ---- Lists: worksets + values in use -------------------------------------------------
ls = wb.create_sheet("Lists")
ls["A1"] = "Worksets and values currently used by the editable parameters"
ls["A1"].font = font(12, bold=True)
listcols = []
if d.get("worksets"):
    listcols.append(("Worksets (user)", [w["name"] for w in d["worksets"]], None))
for c in cols:
    if c["access"] == "EDIT" and c.get("rec") and c["rec"]["st"] == "String":
        cnt = Counter(value_of(e, c) or "<blank>" for e in elems)
        listcols.append((c["param"], sorted(cnt, key=lambda x: (x == "<blank>", x.lower())), cnt))
j = 1
for title, vals, cnt in listcols:
    h = ls.cell(3, j, title)
    h.font, h.fill, h.border = font(9, bold=True, tok="on-fill"), F_HEAD, HEAD_BOX
    ls.column_dimensions[get_column_letter(j)].width = 34
    if cnt:
        h2 = ls.cell(3, j + 1, "Count")
        h2.font, h2.fill, h2.border = font(9, bold=True, tok="on-fill"), F_HEAD, HEAD_BOX
        ls.column_dimensions[get_column_letter(j + 1)].width = 8
    for i, v in enumerate(vals, 4):
        ls.cell(i, j, v).font = font(10)
        if cnt:
            ls.cell(i, j + 1, cnt[v]).font = font(10, tok="ink-muted")
    if title.startswith("Worksets"):
        ws_rng = "Lists!$%s$4:$%s$%d" % (get_column_letter(j), get_column_letter(j), 3 + len(vals))
    j += 3 if cnt else 2
for c in cols:
    if c["kind"] == "workset":
        dv = DataValidation(type="list", formula1="=" + ws_rng, allow_blank=False, showErrorMessage=True,
                            errorTitle="Not a workset", error="Pick a user workset from the Lists sheet.")
        ws.add_data_validation(dv)
        dv.add("%s%d:%s%d" % (c["L"], FIRST, c["L"], last))
ls.freeze_panes = "A4"

# ---- Summary: per building, tied out to the Revit grand total ------------------------
calc = [c for c in cols if is_numeric_calc(c)]
grp = next((c for c in cols if c.get("rec") and c["param"].lower().startswith("studio_building")), None) or \
      next((c for c in cols if c["kind"] == "param" and not c.get("hidden")), None)
sm = wb.create_sheet("Summary", 1)
sm["A1"] = "Summary by %s" % (grp["head"] if grp else "element")
sm["A1"].font = font(12, bold=True)
sm["A2"] = "Live SUMIFS over the %s sheet. The last rows tie the workbook out against the schedule's grand total in Revit." % data_title
sm["A2"].font = font(9, tok="ink-muted")
heads = [grp["head"] if grp else "Group", "Elements"] + [c["head"] for c in calc]
for j, t in enumerate(heads, 1):
    h = sm.cell(4, j, t)
    h.font, h.fill, h.border = font(9, bold=True, tok="on-fill"), F_HEAD, HEAD_BOX
    h.alignment = Alignment(wrap_text=True, vertical="center")
    sm.column_dimensions[get_column_letter(j)].width = 22 if j == 1 else (10 if j == 2 else 15)
sm.row_dimensions[4].height = 44
groups = sorted(set(value_of(e, grp) or "" for e in elems), key=lambda x: (x == "", x.lower())) if grp else [""]
rng = lambda L: "'%s'!$%s$%d:$%s$%d" % (data_title, L, FIRST, L, last)
r = 5
for g in groups:
    sm.cell(r, 1, g or "<blank>").font = font(10, bold=True)
    crit = '"%s"' % g if g else '""'
    sm.cell(r, 2, "=COUNTIFS(%s,%s)" % (rng(grp["L"]), crit)).font = font(10)
    for j, c in enumerate(calc, 3):
        cell = sm.cell(r, j, "=SUMIFS(%s,%s,%s)" % (rng(c["L"]), rng(grp["L"]), crit))
        cell.font, cell.number_format = font(10), "#,##0.00"
    for j in range(1, len(heads) + 1):
        sm.cell(r, j).border = BOX
    r += 1
tot_r = r
sm.cell(r, 1, "Total (this workbook)").font = font(10, bold=True)
sm.cell(r, 2, "=SUM(B5:B%d)" % (r - 1)).font = font(10, bold=True)
for j in range(3, len(heads) + 1):
    L = get_column_letter(j)
    cell = sm.cell(r, j, "=SUM(%s5:%s%d)" % (L, L, r - 1))
    cell.font, cell.number_format = font(10, bold=True), "#,##0.00"
for j in range(1, len(heads) + 1):
    sm.cell(r, j).fill, sm.cell(r, j).border = fill("row-total"), BOX
gt = d["summary_rows"][-1]["cells"] if d.get("summary_rows") else None
if gt:
    vis = [f for f in fields if not f["hidden"]]
    r += 1
    sm.cell(r, 1, "Revit schedule grand total").font = font(10, tok="ink-muted")
    for j, c in enumerate(calc, 3):
        txt = gt[vis.index(c["field"])]
        try:
            v = float(txt.replace(",", "").split()[0])
        except (ValueError, IndexError):
            v = None
        cell = sm.cell(r, j, v)
        cell.font, cell.number_format, cell.border = font(10, tok="ink-muted"), "#,##0.00", BOX
    r += 1
    sm.cell(r, 1, "Difference (should be 0.00)").font = font(10, tok="ink-muted")
    for j in range(3, len(heads) + 1):
        L = get_column_letter(j)
        cell = sm.cell(r, j, "=ROUND(%s%d-%s%d,2)" % (L, tot_r, L, tot_r + 1))
        cell.font, cell.number_format, cell.border = font(10, tok="ink-muted"), "#,##0.00", BOX
sm.freeze_panes = "B5"

# ---- Fields map ----------------------------------------------------------------------
fs = wb.create_sheet("Fields")
fs["A1"] = "Column map - the importer reads this sheet"
fs["A1"].font = font(12, bold=True)
fh = ["Column", "Heading", "Revit parameter", "Parameter Id", "Shared GUID", "Storage", "Excel units",
      "Access", "Source", "Shown in schedule", "How the importer writes it"]
for j, t in enumerate(fh, 1):
    h = fs.cell(3, j, t)
    h.font, h.fill, h.border = font(9, bold=True, tok="on-fill"), F_HEAD, HEAD_BOX
for i, c in enumerate(cols, 4):
    rec, f = c.get("rec"), c.get("field")
    units = ""
    if rec and rec["st"] == "Double":
        sp = rec["spec"]
        units = "m2" if "area" in sp else "mm" if "length" in sp else "m3" if "volume" in sp else "number"
    elif is_numeric_calc(c):
        units = "m2 (as shown in schedule)"
    how = {"EDIT": "set value (%s)" % (rec["st"] if rec else ""),
           "EDIT - pick a key": "key name -> key element (from '%s')" % c.get("keysheet", ""),
           "EDIT - pick a workset": "workset name -> WorksetId"}.get(c["access"], "not written")
    if c["kind"] in ("id", "uid"):
        how = "row -> element lookup"
    row = [c["L"], c["head"], c["param"], c.get("pid"), rec.get("guid") if rec else None, rec["st"] if rec else None,
           units, c["access"], (f["ftype"] if f else c["kind"]), ("" if not f else ("no" if f["hidden"] else "yes")), how]
    for j, v in enumerate(row, 1):
        cell = fs.cell(i, j, v)
        cell.font = font(9, mono=(j in (1, 4, 5)))
        cell.border = BOX
        if c["access"].startswith("EDIT"):
            cell.fill = F_EDIT
for j, w in enumerate([8, 34, 36, 12, 38, 11, 22, 30, 18, 10, 40], 1):
    fs.column_dimensions[get_column_letter(j)].width = w
fs.freeze_panes = "C4"

# ---- hidden: _Original snapshot + _Meta ---------------------------------------------
og = wb.create_sheet("_Original")
for c in cols:
    og.cell(1, c["col"], c["head"])
    og.cell(2, c["col"], c["param"])
for r, e in enumerate(elems, 3):
    for c in cols:
        og.cell(r, c["col"], value_of(e, c))
og.sheet_state = "hidden"

mt = wb.create_sheet("_Meta")
meta = OrderedDict([
    ("tool", "schedule_roundtrip v1"), ("schedule", d["schedule"]), ("schedule_id", d["schedule_id"]),
    ("category_id", d["category_id"]), ("model", d["doc"]), ("model_path", d["doc_path"]),
    ("exported", d["exported"]), ("scope", d["scope"]), ("include_links_setting_in_revit", d["include_links_setting"]),
    ("elements", len(elems)), ("rows_excluded_not_host", len(d.get("foreign_rows", []))),
    ("owned_by_others_at_export", n_other), ("data_sheet", data_title), ("heading_row", HR), ("first_data_row", FIRST),
])
for i, (k, v) in enumerate(meta.items(), 1):
    mt.cell(i, 1, k)
    mt.cell(i, 2, v)
mt.sheet_state = "hidden"

wb.active = 0
wb.calculation.fullCalcOnLoad = True                  # Summary formulas have no cached values
wb.save(out)
print("Wrote", out)
print("  %d rows | %d columns (%d editable) | key sheets: %s | excluded non-host rows: %d"
      % (len(elems), len(cols), sum(1 for c in cols if c["access"].startswith("EDIT")),
         ", ".join(c["keysheet"] for c in used_keys) or "-", len(d.get("foreign_rows", []))))

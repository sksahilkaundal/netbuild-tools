# -*- coding: utf-8 -*-
r"""
Build the wall-type round-trip workbook from the JSON dumped by execute_revit_code.

    python scripts\export_wall_types_xlsx.py <dump.json> <out.xlsx>

Sheet "Wall Types": one row per wall type layer (single-layer types = one row).
  Read-only key columns (grey): Type Id, Layer #, Material Id  -> the reimport keys on these.
  Editable columns (yellow):    New Type Name, New Material, New Type Mark, New Description.
  Leave an editable cell blank = no change for that field.
Sheet "Materials": every material in the model (data-validation list for "New Material").
Sheet "Legend": how to fill it in.
"""
import json
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

src, out = sys.argv[1], sys.argv[2]
data = json.load(open(src, encoding="utf-8"))
rows = sorted(data["rows"], key=lambda r: (r["family"], r["type"], r["layer"] or 0))
mats = data["materials"]

FONT = "Arial"
f_norm = Font(name=FONT, size=10)
f_head = Font(name=FONT, size=10, bold=True, color="FFFFFF")
f_key = Font(name=FONT, size=10, color="666666")
fill_head = PatternFill("solid", fgColor="1F4E78")
fill_key = PatternFill("solid", fgColor="EDEDED")
fill_edit = PatternFill("solid", fgColor="FFF2CC")
fill_flag = PatternFill("solid", fgColor="FCE4D6")
thin = Side(style="thin", color="BFBFBF")
border = Border(left=thin, right=thin, top=thin, bottom=thin)

wb = Workbook()
ws = wb.active
ws.title = "Wall Types"

headers = [
    ("Type Id", 10, "key"), ("Family", 13, None), ("Type Name", 36, None), ("Count", 8, None),
    ("Type Mark", 12, None), ("Description", 24, None), ("Total (mm)", 10, None),
    ("Layer #", 8, "key"), ("Function", 11, None), ("Core", 6, None), ("Width (mm)", 10, None),
    ("Material Id", 11, "key"), ("Material", 40, None),
    ("New Type Name", 36, "edit"), ("New Material", 40, "edit"), ("New Type Mark", 14, "edit"), ("New Description", 28, "edit"),
    ("Notes", 30, None),
]
ws.append(["Document: %s" % data["doc"], "", "", "", "", "", "",
           "Yellow = edit here (blank = keep).  Grey = keys for the reimport, do not edit.  Rows = one per layer."])
ws["A1"].font = Font(name=FONT, size=10, bold=True)
ws["H1"].font = Font(name=FONT, size=9, italic=True, color="7F7F7F")
ws.append([h for h, _, _ in headers])
for i, (h, width, kind) in enumerate(headers, 1):
    c = ws.cell(row=2, column=i)
    c.font, c.fill, c.border = f_head, fill_head, border
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.column_dimensions[get_column_letter(i)].width = width
ws.row_dimensions[2].height = 30

col_of = {h: i for i, (h, _, _) in enumerate(headers, 1)}
for r in rows:
    note = []
    if r["family"] == "Curtain Wall":
        note.append("curtain wall: no layers/material")
    if r["material"] and r["type"] and r["width_mm"]:
        # material named for a different thickness than the layer (e.g. "... 200mm" on a 150 wall)
        import re
        m = re.search(r"(\d{2,3})\s*mm", r["material"])
        if m and abs(float(m.group(1)) - r["width_mm"]) > 0.5:
            note.append("material name says %smm, layer is %gmm" % (m.group(1), r["width_mm"]))
    if r["material"] == "Default Wall":
        note.append("out-of-the-box material")
    ws.append([
        r["type_id"], r["family"], r["type"], r["count"], r["type_mark"], r["description"], r["total_mm"],
        r["layer"], r["function"], ("Y" if r["core"] else "") if r["layer"] else "", r["width_mm"],
        r["material_id"], r["material"], "", "", "", "", "; ".join(note),
    ])
    rr = ws.max_row
    for i, (h, _, kind) in enumerate(headers, 1):
        c = ws.cell(row=rr, column=i)
        c.font, c.border = f_norm, border
        if kind == "key":
            c.font, c.fill = f_key, fill_key
        elif kind == "edit":
            c.fill = fill_edit
        if h == "Notes" and note:
            c.fill = fill_flag
first, last = 3, ws.max_row
ws.freeze_panes = "D3"
ws.auto_filter.ref = "A2:%s%d" % (get_column_letter(len(headers)), last)
# totals row (formula, not a hardcoded number)
ws.cell(row=last + 2, column=col_of["Type Name"], value="Wall instances (sum of unique types)").font = Font(name=FONT, size=10, bold=True)
ws.cell(row=last + 2, column=col_of["Count"], value="=SUMPRODUCT((D%d:D%d)*(H%d:H%d<=1))" % (first, last, first, last)).font = Font(name=FONT, size=10, bold=True)
ws.cell(row=last + 3, column=col_of["Type Name"], value="Wall types").font = Font(name=FONT, size=10, bold=True)
ws.cell(row=last + 3, column=col_of["Count"], value="=SUMPRODUCT(1/COUNTIF(A%d:A%d,A%d:A%d))" % (first, last, first, last)).font = Font(name=FONT, size=10, bold=True)

# Materials sheet + validation list for "New Material"
wm = wb.create_sheet("Materials")
wm.append(["Material name (%d in model)" % len(mats)])
wm["A1"].font, wm["A1"].fill = f_head, fill_head
for m in mats:
    wm.append([m])
wm.column_dimensions["A"].width = 60
for row in wm.iter_rows(min_row=2, max_col=1):
    row[0].font = f_norm
dv = DataValidation(type="list", formula1="=Materials!$A$2:$A$%d" % (len(mats) + 1), allow_blank=True, showErrorMessage=False)
ws.add_data_validation(dv)
nm_col = get_column_letter(col_of["New Material"])
dv.add("%s%d:%s%d" % (nm_col, first, nm_col, last))

# Legend
wl = wb.create_sheet("Legend")
legend = [
    ("How to use this workbook", True),
    ("Exported from Revit model %s (host model only, links excluded). One row per wall-type layer; single-layer types are one row." % data["doc"], False),
    ("", False),
    ("Grey columns (Type Id, Layer #, Material Id) are the keys the reimport script uses. Do not edit or sort-break them.", False),
    ("Yellow columns are the only cells to edit:", True),
    ("  New Type Name   - renames the wall type (applies to the type, so fill it on the type's first layer row only).", False),
    ("  New Material     - swaps that layer's material; pick from the drop-down (Materials sheet). Must be an existing material name.", False),
    ("  New Type Mark    - sets the type's Type Mark parameter.", False),
    ("  New Description  - sets the type's Description parameter.", False),
    ("Blank yellow cell = keep as is. The reimport runs as a dry run first and reports every change before anything is committed.", False),
    ("Notes column flags things worth a look: material named for a different thickness, out-of-the-box material, duplicate-looking types.", False),
    ("", False),
    ("Example (do not copy): a row for Studio-WAL-concrete 300 with New Type Name = 'Studio-WAL-concrete 300mm' would merge it into that naming.", False),
    ("Merging one type INTO another (deleting a type) is not done via this sheet - ask for it separately so the instance swap is reviewed.", False),
]
for text, bold in legend:
    wl.append([text])
    wl.cell(row=wl.max_row, column=1).font = Font(name=FONT, size=10, bold=bold)
wl.column_dimensions["A"].width = 140

wb.save(out)
print("saved %s  (%d rows, %d materials)" % (out, len(rows), len(mats)))

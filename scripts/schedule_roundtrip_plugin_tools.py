# -*- coding: utf-8 -*-
r"""
Helpers for the pyRevit "Export Schedule" / "Import Excel" buttons (Studio-Claude.extension,
Netbuild 01 > Schedules and Excel). CPython (py -3.14 + openpyxl); prints ONE JSON line
on stdout for the button to read.

    py -3.14 schedule_roundtrip_plugin_tools.py template <dump.json> <base.xlsx> <out.xlsx>
        Picks the style template for the dumped schedule. If every heading of <base.xlsx>
        (the curated Area layout, scripts\templates\schedule_roundtrip_area_reference.xlsx)
        is a field of the schedule, the base itself is used (mode "reference"). Otherwise a
        template with ALL the schedule's visible fields, in schedule order, is written to
        <out.xlsx> in the same style (mode "generated"). Also returns the band heading
        (Building Asset > Level > first text field) and the must-fill component heading.

    py -3.14 schedule_roundtrip_plugin_tools.py tieout <dump.json> <workbook.xlsx>
        Sums every area/sum column of the built workbook and ties it out to the schedule's
        grand total in the dump (host rows + rows from loaded links = grand total).

    py -3.14 schedule_roundtrip_plugin_tools.py info <workbook.xlsx>
        Model / export stamp / schedule of a round-trip workbook and the parameters an
        import can write (instance parameters, not built-in, not combined).
"""
import json
import re
import sys
import warnings

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, column_index_from_string

warnings.filterwarnings("ignore")


def key(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def layout(t):
    """Row numbers of the template's title / heading / blank / band / data / total / tail."""
    tcols = max(c for c in range(1, t.max_column + 1) if t.cell(2, c).value is not None)
    vals = lambda r: [t.cell(r, c).value for c in range(1, tcols + 1)]
    head = next(r for r in range(1, 10) if sum(v is not None for v in vals(r)) >= tcols - 1)
    band = next(r for r in range(head + 1, t.max_row + 1)
                if vals(r)[0] is not None and all(v is None for v in vals(r)[1:]))
    data = next(r for r in range(band + 1, t.max_row + 1) if vals(r)[1] is not None)
    total = next(r for r in range(data, t.max_row + 1)
                 if any(isinstance(v, str) and v.startswith("=") for v in vals(r)))
    return tcols, head, band, data, total, list(range(total + 1, t.max_row + 1)), vals(head)


def cmd_template(dump, base, out):
    d = json.load(open(dump, encoding="utf-8"))
    vis = [f for f in d["fields"] if not f["hidden"]]
    heads = [f["heading"] for f in vis]
    have = set(key(h) for h in heads) | set(key(f["name"]) for f in vis)
    numeric = lambda f: f["ftype"] not in ("Instance", "ElementType", "CombinedParameter")
    texts = [f["heading"] for f in vis if not numeric(f)]
    band = next((h for h in ("Building Asset", "Level") if key(h) in set(key(x) for x in texts)),
                texts[0] if texts else heads[0])
    comp = next((h for h in ("Studio_Area_Department", "GLA/GSA Component") if key(h) in have), "")

    wb = load_workbook(base)
    t = wb.active
    tcols, HEAD, BAND, DATA, TOTAL, TAIL, theads = layout(t)
    if all(key(h) in have for h in theads):
        print(json.dumps({"template": base, "mode": "reference", "band": band, "component": comp,
                          "columns": len(theads)}))
        return

    # generated: one column per visible field, styled like the base (col 1 / a text col / a number col)
    num_src = next((c for c in range(1, tcols + 1)
                    if isinstance(t.cell(DATA, c).value, (int, float)) and c > 1), tcols)
    widths = dict((key(theads[c - 1]), t.column_dimensions[get_column_letter(c)].width) for c in range(1, tcols + 1))
    S = lambda r, c: t.cell(r, c)._style
    title = re.sub(r"[\[\]:*?/\\]", "-", "%s_%s" % (d["exported"][2:4] + d["exported"][5:7] + d["exported"][8:10],
                                                     d["schedule"]))[:27]   # builder adds "_tmp" while building
    ws = wb.create_sheet("tmp_generated")
    rows = {1: "title", HEAD: "head", BAND: "band", DATA: "data", TOTAL: "total"}
    for r in range(1, HEAD):
        rows.setdefault(r, "blank")
    for r in range(HEAD + 1, BAND):
        rows.setdefault(r, "blank")
    for i, r in enumerate(TAIL):
        rows[r] = "head" if i == 0 else "blank"
    for r, kind in sorted(rows.items()):
        for j, f in enumerate(vis, 1):
            src = 1 if j == 1 else (num_src if numeric(f) else 2)
            cell = ws.cell(r, j)
            cell._style = S(r, src)
            if kind == "title" and j == 1:
                cell.value = d["schedule"]
            elif kind == "head":
                cell.value = f["heading"]
            elif kind == "band" and j == 1:
                cell.value = "band"
            elif kind == "data":
                cell.value = 0 if numeric(f) else "x"
            elif kind == "total" and (numeric(f) or j == len(vis)):
                cell.value = "=SUM(%s%d:%s%d)" % (get_column_letter(j), DATA, get_column_letter(j), DATA)
        if t.row_dimensions[r].height:
            ws.row_dimensions[r].height = t.row_dimensions[r].height
    for j, f in enumerate(vis, 1):
        ws.column_dimensions[get_column_letter(j)].width = widths.get(key(f["heading"])) or \
            max(12, min(40, len(f["heading"]) + 4))
    ws.freeze_panes = ws.cell(HEAD + 1, 1)
    ws.sheet_view.zoomScale = t.sheet_view.zoomScale
    ws.page_setup.orientation = t.page_setup.orientation
    ws.page_setup.paperSize = t.page_setup.paperSize
    wb.remove(t)
    ws.title = title
    wb.active = 0
    wb.save(out)
    print(json.dumps({"template": out, "mode": "generated", "band": band, "component": comp,
                      "columns": len(vis)}))


def meta_of(wb):
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
    return meta, colmap


def num(t):
    try:
        return float(str(t).replace(",", "").split()[0])
    except (ValueError, IndexError):
        return 0.0


def cmd_tieout(dump, xlsx):
    d = json.load(open(dump, encoding="utf-8"))
    wb = load_workbook(xlsx)
    meta, colmap = meta_of(wb)
    ws = wb[meta["data_sheet"]]
    idc = column_index_from_string(meta["id_column"])
    head = int(meta["heading_row"])
    is_id = lambda v: isinstance(v, int) or bool(re.match(r"^\d+(;\d+)*$", str(v or "").strip()))
    data_rows = [r for r in range(head + 1, ws.max_row + 1) if is_id(ws.cell(r, idc).value)]   # not band rows
    vis = [f["heading"] for f in d["fields"] if not f["hidden"]]
    total = (d["summary_rows"] or [{"cells": []}])[-1]["cells"]
    out, worst = [], 0.0
    for m in colmap:
        if m["kind"] != "sum" or m["heading"] not in vis:
            continue
        i = vis.index(m["heading"])
        c = column_index_from_string(m["col"])
        host = sum(ws.cell(r, c).value or 0 for r in data_rows if isinstance(ws.cell(r, c).value, (int, float)))
        link = sum(num(fr["cells"][i]) for fr in d["foreign_rows"] if i < len(fr["cells"]))
        revit = num(total[i]) if i < len(total) and total[i] else None
        diff = None if revit is None else round(host + link - revit, 2)
        if diff is not None:
            worst = max(worst, abs(diff))
        out.append({"heading": m["heading"], "host": round(host, 2), "links": round(link, 2),
                    "revit_total": revit, "diff": diff})
    blank_key = next((k for k in meta if str(k).startswith("rows_without_")), None)
    print(json.dumps({"rows": len(data_rows), "columns": out, "max_diff": round(worst, 2),
                      "has_total": bool(total), "blank_component": meta.get(blank_key) if blank_key else None,
                      "component": blank_key[len("rows_without_"):] if blank_key else None}))


def cmd_info(xlsx):
    wb = load_workbook(xlsx)
    meta, colmap = meta_of(wb)
    params = [{"param": m["param"], "heading": m["heading"], "pid": m["pid"]} for m in colmap
              if m["kind"] == "Instance" and isinstance(m["pid"], int) and m["pid"] > 0]
    models = [m for m in str(meta.get("models") or meta.get("model") or "").split("; ") if m]
    print(json.dumps({"model": meta.get("model"), "exported": meta.get("exported"),
                      "schedule": meta.get("schedule"), "data_sheet": meta.get("data_sheet"),
                      "models": models, "with_links": bool(meta.get("model_column")),
                      "params": params}))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["template"] and len(a) == 4:
        cmd_template(*a[1:])
    elif a[:1] == ["tieout"] and len(a) == 3:
        cmd_tieout(*a[1:])
    elif a[:1] == ["info"] and len(a) == 2:
        cmd_info(*a[1:])
    else:
        sys.exit(__doc__)

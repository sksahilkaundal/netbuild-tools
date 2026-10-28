# -*- coding: utf-8 -*-
"""
ProjectA Calculations builder - adds an "ProjectA Calculations" sheet (GSA / GFA / BUA summary per asset) to a
dated BUA Option 1 workbook, laid out and styled like the reference schedule's sheet.

    py -3.14 projecta_calculations_build.py "<YYMMDD>_..._with All Levels_Option 1.xlsx" --out "<new.xlsx>"
                                       [--reference "<schedule with ProjectA Calculations>"] [--dry-run] [--overwrite]
                                       [--carry-from "<older ProjectA Calculations.xlsx>"]

What it does
  1. Reads the data sheet "<YYMMDD>_BUA Space Room Split" (the re-fed raw Revit Area export).
  2. Sums each ProjectA line per asset with fixed rules (below). The rules were reverse-engineered from the
     reference and reproduce all 550 of its leaf cells exactly from the reference's own 260911 data.
  3. Coverage check: every m2 of GFA and BUA in the data must land on exactly one line. If not, it
     lists the rows and STOPS (nothing written) - a new GFA Component-Category needs a decision.
  4. Writes a copy of the input workbook + "Detail Split" (copy of the data sheet) + "ProjectA Calculations"
     (reference styles copied row by row, the reference's formulas regenerated for the new row numbers).
  5. Verifies the WRITTEN file: evaluates every formula in the sheet and checks Total Combined GFA and
     Total BUA per asset / Tower Total / Grand Total against the data.

Rules (column used per line): GSA lines = Usable Area (A); "(GFA)" lines = GFA (A+B); Circulation /
Services / Storage / MEP Rooms non-GFA lines and Facade lines = BUA - GFA; Terraces and Parking = BUA.
Unit lines follow the GFA Component: Residential-Hotel Apartments -> Residential Units, Hotel-Residential
Units -> Hotel Apartments; any non-hotel "-Offices" -> Offices, Hotel-Offices -> Admin Offices for Hotel.

GLA/GSA (user, 2026-10-01): an area counts on a GSA line ONLY if its "GLA/GSA Component" (raw column D,
itemized export) contains GLA or GSA; otherwise it follows the GFA / BUA rules. So an untagged usable area
goes to "Usable Areas Not in GLA/GSA (GFA)", and an untagged terrace is BUA only (e.g. the podium 01st Floor
office terraces): terrace part -> "Terraces - Not in GLA/GSA - <level>" (one row per level, user 2026-10-01,
so they can be found), planter part -> "Planters - Not in GLA/GSA";
MEP terraces keep their own (BUA-only) line. Tagged terraces sort by the tag: GSA Residential Terrace /
GLA Hotel Apartment Terrace / GLA Hotel Terrace / GLA Office Terrace. A TAGGED usable area outside the
unit/amenity lines (services, storage, kitchens, pool ...) is common GLA/GSA to tenants (user, 2026-10-01):
its Usable Area goes to "Common GLA/GSA to Tenants - <tenant>" by tag (Offices / Hotel Apartments / Hotel /
Retail; in Total GSA Excl. Terraces), and its (GFA) line keeps only the rest. Any other tag stops the build.

Lines added vs the reference (user decisions, 2026-10-01):
  - Office Terrace/Balconies (terraces block, and counted in "Total GSA Incl. Terraces")
  - Hotel Apartment Terrace/Balconies split out of Hotel Terrace/Balconies (both blocks)
  - F&B Terraces and Retail Terraces: MANUAL input rows in the GSA block - not BUA/GFA, but counted in
    "Total GSA Incl. Terraces" and so in the Incl. Terraces efficiencies. Their values are carried over on
    every rebuild from the workbook being replaced (or --carry-from). Raw areas carrying GLA F&B Terrace /
    GLA Retail Terrace are placed on no line, so any GFA/BUA on them stops the build (coverage check).
  - Facade Structure (GFA) and Shared Circulation (GFA) in a new "Other Non Lettable GFA" block
  - Shared Circulation in the Circulation (Non-GFA) block
Reference fixes: the tower columns Q:S now carry real per-tower totals (the reference's Q68 helper
summed Q12:Q64, which double-counted, and its non-GFA subtotals had no Q:S); parking for towers sits
on the parking row itself instead of a separate row 120.
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from copy import copy

import openpyxl
from openpyxl.utils import get_column_letter as L

# Style template (copied 2026-10-01 from the user's Downloads\GLA_GSA\Copy of ProjectC-Studio-SCH-AR-000001_00.xlsx).
REFERENCE = r"C:\SK\Projects\ProjectA\Excel\Templates\ProjectA Calculations template - ProjectC-Studio-SCH-AR-000001_00.xlsx"
REF_SHEET = "ProjectA Calculations"
ACC_FMT = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'

PODIUM = {"G": "Basement", "H": "Building 1", "I": "Building 2", "J": "Building 3", "K": "Building 4",
          "L": "Building 5", "M": "Ellipsoid"}
TOWER = {"Q": "Tower A", "R": "Tower B", "S": "Tower GF to L6 Area"}
ASSETS = list(PODIUM.values()) + list(TOWER.values())
METRICS = {6: "A", 7: "B", 8: "C", 9: "D", 10: "E", 11: "F", 12: "G", 13: "H", 14: "N", 15: "O"}
UNITS = ("Residential Units", "Hotel Apartments")
INPUT_TERRACES = {"F&B Terraces": "GLA F&B Terrace", "Retail Terraces": "GLA Retail Terrace"}   # label -> GLA/GSA
NOT_GSA = "Not in GLA/GSA"
BY_LEVEL = {"NON_GSA_TERR"}     # lines written as one row per level ("<label> - <level>") so areas can be found


def level_key(lvl):
    """Basements (deepest first), Ground, then 01st, 02nd ... ("27th to 36th Floor" sorts at 27)."""
    s = str(lvl)
    n = re.search(r"\d+", s)
    if s.lower().startswith("basement"):
        return (0, -int(n.group()) if n else 0, s)
    if s.lower().startswith("ground"):
        return (1, 0, s)
    return (2, int(n.group()), s) if n else (3, 0, s)


def c_is(*vals):
    return lambda x: x["c"] in vals


def cat_is(*vals):
    return lambda x: x["cat"] in vals


def terr_is(val):
    return lambda x: x.get("terr") == val


def in_gla(x):
    """the area's GLA/GSA Component names a GLA or GSA (blank / "Shared Services" -> not GLA/GSA)"""
    return bool(x["gsa"]) and ("GLA" in x["gsa"] or "GSA" in x["gsa"])


# key: reference row number (existing lines) or a name (added lines) -> (predicate, metric)
# metric: A usable | N GFA | NG = BUA - GFA | O BUA
RULES = {
    7: (lambda x: x["cat"] in UNITS and (x["comp"] == "Residential" or
                                         (x["comp"] != "Hotel" and x["cat"] == "Residential Units")), "A"),
    8: (lambda x: x["cat"] == "Offices" and x["comp"] != "Hotel", "A"),
    9: (lambda x: x["cat"] in UNITS and (x["comp"] == "Hotel" or
                                         (x["comp"] != "Residential" and x["cat"] == "Hotel Apartments")), "A"),
    10: (cat_is("Hotel Guest Rooms"), "A"),
    11: (c_is("Hotel-Offices"), "A"),
    12: (cat_is("Ballroom"), "A"),
    13: (cat_is("Gym/Fitness"), "A"),
    14: (cat_is("Meeting Room"), "A"),
    15: (cat_is("SPA"), "A"),
    16: (lambda x: x["cat"] in ("F&B", "Restaurant", "F&B Seating / Beach Club Lounge") and
         x["gsa"] not in INPUT_TERRACES.values(), "A"),
    17: (cat_is("Retail"), "A"),
    20: (terr_is("GSA Residential Terrace"), "O"),
    39: (c_is("Hotel-Circulation"), "N"),
    40: (c_is("Hotel-Kitchen", "Hotel-F&B Kitchen"), "N"),
    41: (c_is("Hotel-Pool"), "N"),
    42: (c_is("Hotel-Services"), "N"),
    43: (c_is("Hotel-Storage"), "N"),
    46: (lambda x: x["c"] == "MEP-Circulation" or x["cat"] == "MEP Rooms", "N"),
    47: (c_is("MEP-Services"), "N"),
    48: (c_is("MEP-Storage"), "N"),
    51: (c_is("Office-Circulation"), "N"),
    52: (c_is("Office-Services"), "N"),
    53: (c_is("Office-Storage"), "N"),
    56: (c_is("Residential-Circulation"), "N"),
    57: (c_is("Residential-Services"), "N"),
    58: (c_is("Residential-Storage"), "N"),
    61: (c_is("Retail-Circulation"), "N"),
    62: (c_is("Retail-F&B Kitchen"), "N"),
    63: (c_is("Retail-Services"), "N"),
    64: (c_is("Retail-Storage"), "N"),
    "FACADE_GFA": (cat_is("Facade Structure"), "N"),
    "SHARED_CIRC_GFA": (c_is("Shared-Circulation"), "N"),
    75: (lambda x: x["cat"] == "Facade Structure" and x["comp"] == "Hotel", "NG"),
    76: (lambda x: x["cat"] == "Facade Structure" and x["comp"] == "MEP", "NG"),
    77: (lambda x: x["cat"] == "Facade Structure" and x["comp"] not in ("Hotel", "MEP"), "NG"),
    "HOTEL_APT_TERR": (terr_is("GLA Hotel Apartment Terrace"), "O"),
    81: (terr_is("GLA Hotel Terrace"), "O"),
    82: (terr_is("MEP Terrace"), "O"),
    "OFFICE_TERR": (terr_is("GLA Office Terrace"), "O"),
    "NON_GSA_TERR": (terr_is(NOT_GSA), "E"),
    "NON_GSA_PLANTER": (terr_is(NOT_GSA), "F"),
    85: (c_is("MEP-MEP Rooms"), "NG"),
    86: (c_is("Hotel-MEP Rooms"), "NG"),
    87: (c_is("Office-MEP Rooms"), "NG"),
    88: (c_is("Residential-MEP Rooms"), "NG"),
    89: (c_is("Retail-MEP Rooms"), "NG"),
    92: (c_is("Circulation-Circulation"), "NG"),
    93: (c_is("Hotel-Circulation"), "NG"),
    94: (c_is("MEP-Circulation"), "NG"),
    95: (c_is("Office-Circulation"), "NG"),
    96: (c_is("Residential-Circulation"), "NG"),
    97: (c_is("Retail-Circulation"), "NG"),
    "SHARED_CIRC_NG": (c_is("Shared-Circulation"), "NG"),
    100: (c_is("Hotel-Services"), "NG"),
    101: (c_is("MEP-Services"), "NG"),
    102: (c_is("Residential-Services"), "NG"),
    103: (c_is("Shared-Services"), "NG"),
    107: (c_is("Hotel-Storage"), "NG"),
    108: (c_is("Residential-Storage"), "NG"),
    109: (c_is("Retail-Storage"), "NG"),
    110: (c_is("Storage-Storage"), "NG"),
    117: (c_is("Parking-Parking"), "O"),
}
# GSA lines (7-17) take an area only when it is tagged GLA/GSA; an untagged one stays GFA on its own line
GSA_KEYS = tuple(range(7, 18))
_GSA_CAT = {k: RULES[k][0] for k in GSA_KEYS}
for _k in GSA_KEYS:
    RULES[_k] = ((lambda p: lambda x: in_gla(x) and p(x))(_GSA_CAT[_k]), RULES[_k][1])
RULES["NON_GSA_GFA"] = (lambda x: not in_gla(x) and any(p(x) for p in _GSA_CAT.values()), "A")


def is_common(x):
    """tagged GLA/GSA usable area outside the GSA lines: common GLA/GSA to tenants (terrace-input tags
    excluded, so area appearing on them still stops the build)"""
    return (in_gla(x) and x["A"] > 0 and x["gsa"] not in INPUT_TERRACES.values()
            and x["cat"] != "Terrace/Balconies" and not any(p(x) for p in _GSA_CAT.values()))


# one Common line per tenant (the area's GLA/GSA tag); a common area with any other tag stops the build
COMMON_TENANTS = {
    "COMMON_OFFICE": ("GLA Office", "Common GLA/GSA to Tenants - Offices"),
    "COMMON_HOTEL_APT": ("GLA Hotel Apartment", "Common GLA/GSA to Tenants - Hotel Apartments"),
    "COMMON_HOTEL": ("GLA Hotel", "Common GLA/GSA to Tenants - Hotel"),
    "COMMON_RETAIL": ("GLA Retail", "Common GLA/GSA to Tenants - Retail"),
}
for _k, (_tag, _) in COMMON_TENANTS.items():
    RULES[_k] = ((lambda t: lambda x: is_common(x) and x["gsa"] == t)(_tag), "A")
for _k, (_p, _m) in list(RULES.items()):   # GFA lines carry only the GFA not counted as common GSA
    if _m == "N":
        RULES[_k] = (_p, "NL")

# Sheet layout, top to bottom (starts at row 6 like the reference). Existing lines take label + style
# from their reference row; added lines borrow the style of the "donor" reference row.
LAYOUT = (
    [("copy", 6)] + [("leaf", r) for r in range(7, 18)] +
    [("leaf", k, {"donor": 17, "label": label}) for k, (_, label) in COMMON_TENANTS.items()] +
    [("sum_range", 18, {"members": (7, list(COMMON_TENANTS)[-1]), "qs": True}), ("blank", 19),
     ("leaf", 20),
     ("mirror", "HOTEL_APT_TERR_GSA", {"target": "HOTEL_APT_TERR", "donor": 21, "qs": True}),
     ("mirror", 21, {"target": 81, "qs": True}),
     ("mirror", "OFFICE_TERR_GSA", {"target": "OFFICE_TERR", "donor": 21, "qs": True}),
     ("input", "FB_TERR", {"donor": 20, "label": "F&B Terraces"}),
     ("input", "RETAIL_TERR", {"donor": 20, "label": "Retail Terraces"}),
     ("sum_list", 22, {"members": [20, 18, "HOTEL_APT_TERR_GSA", 21, "OFFICE_TERR_GSA", "FB_TERR", "RETAIL_TERR"],
                       "qs": True}), ("blank", 23),
     ("mirror", 24, {"target": 69}),
     ("ratio", 25, {"num": 18, "den": 24}), ("ratio", 26, {"num": 22, "den": 24}), ("blank", 27),
     ("mirror", 28, {"target": 115}),
     ("ratio", 29, {"num": 18, "den": 28}), ("ratio", 30, {"num": 22, "den": 28}), ("blank", 31),
     ("mirror", 32, {"target": 119}),
     ("ratio", 33, {"num": 18, "den": 32}), ("ratio", 34, {"num": 22, "den": 32}), ("blank", 35),
     ("copy", 36), ("mirror", 37, {"target": 18}), ("blank", 38)] +
    [("leaf", r) for r in range(39, 44)] + [("sum_range", 44, {"members": (39, 43), "qs": True}), ("blank", 45)] +
    [("leaf", r) for r in range(46, 49)] + [("sum_range", 49, {"members": (46, 48), "qs": True}), ("blank", 50)] +
    [("leaf", r) for r in range(51, 54)] + [("sum_range", 54, {"members": (51, 53), "qs": True}), ("blank", 55)] +
    [("leaf", r) for r in range(56, 59)] + [("sum_range", 59, {"members": (56, 58), "qs": True}), ("blank", 60)] +
    [("leaf", r) for r in range(61, 65)] + [("sum_range", 65, {"members": (61, 64), "qs": True}), ("blank", 66),
     ("leaf", "FACADE_GFA", {"donor": 64, "label": "Facade Structure (GFA)"}),
     ("leaf", "SHARED_CIRC_GFA", {"donor": 64, "label": "Shared Circulation (GFA)"}),
     ("leaf", "NON_GSA_GFA", {"donor": 64, "label": "Usable Areas Not in GLA/GSA (GFA)"}),
     ("sum_range", "OTHER_NL", {"donor": 65, "label": "Total Other Non Lettable GFA Spaces",
                                "members": ("FACADE_GFA", "NON_GSA_GFA"), "qs": True}),
     ("blank", "BLANK_OTHER_NL", {"donor": 66}),
     ("sum_list", 67, {"members": [44, 49, 54, 59, 65, "OTHER_NL"], "qs": True}),
     ("blank", 68),
     ("gfa_total", 69), ("blank", 70), ("blank", 71),
     ("copy", 72), ("mirror", 73, {"target": 69}), ("blank", 74)] +
    [("leaf", r) for r in range(75, 78)] + [("sum_range", 78, {"members": (75, 77), "qs": True}), ("blank", 79),
     ("mirror", 80, {"target": 20, "qs": True}),
     ("leaf", "HOTEL_APT_TERR", {"donor": 81, "label": "Hotel Apartment Terrace/Balconies"}),
     ("leaf", 81), ("leaf", 82),
     ("leaf", "OFFICE_TERR", {"donor": 82, "label": "Office Terrace/Balconies"}),
     ("leaf", "NON_GSA_TERR", {"donor": 82, "label": "Terraces - Not in GLA/GSA"}),
     ("leaf", "NON_GSA_PLANTER", {"donor": 82, "label": "Planters - Not in GLA/GSA"}),
     ("sum_range", 83, {"members": (80, "NON_GSA_PLANTER"), "qs": True}), ("blank", 84)] +
    [("leaf", r) for r in range(85, 90)] + [("sum_range", 90, {"members": (85, 89), "qs": True}), ("blank", 91)] +
    [("leaf", r) for r in range(92, 98)] +
    [("leaf", "SHARED_CIRC_NG", {"donor": 97, "label": "Shared Circulation"}),
     ("sum_range", 98, {"members": (92, "SHARED_CIRC_NG"), "qs": True}), ("blank", 99)] +
    [("leaf", r) for r in range(100, 104)] + [("sum_range", 104, {"members": (100, 103), "qs": True}),
                                               ("blank", 105), ("blank", 106)] +
    [("leaf", r) for r in range(107, 111)] + [("sum_range", 111, {"members": (107, 110), "qs": True}), ("blank", 112),
     ("nongfa_total", 113), ("blank", 114), ("bua_excl", 115), ("blank", 116),
     ("leaf", 117), ("basement_nongfa", 118), ("bua_incl", 119)]
)

PODIUM_COLS = list(PODIUM)                 # G..M
GO_COLS = PODIUM_COLS + ["N", "O"]          # G..O
TOWER_COLS = list(TOWER)                    # Q..S


# ------------------------------------------------------------------ data
DATA_SUFFIXES = ("_BUA Space Room Split", "_BUA Space Split-Itemized")   # grouped / itemized raw (bua_dated_export)


def find_data_sheet(wb):
    names = [n for n in wb.sheetnames if n.endswith(DATA_SUFFIXES)]
    if len(names) != 1:
        sys.exit("expected exactly one '*_BUA Space Room Split' / '*_BUA Space Split-Itemized' sheet, found %s" % names)
    return wb[names[0]]


def load_rows(ws):
    rows, cur = [], None
    for r in range(4, ws.max_row + 1):
        a = ws.cell(r, 1).value
        rest = [ws.cell(r, c).value for c in range(2, 16)]
        if a not in (None, "") and not [x for x in rest if x not in (None, "")]:
            cur = a
            continue
        c = ws.cell(r, 3).value
        if not isinstance(c, str) or not c.strip() or not isinstance(ws.cell(r, 15).value, (int, float)):
            continue
        comp, cat = c.split("-", 1) if "-" in c else (c, c)
        gsa = ws.cell(r, 4).value
        x = {"row": r, "sec": cur, "lvl": a, "c": c, "comp": comp, "cat": cat,
             "gsa": gsa.strip() if isinstance(gsa, str) and gsa.strip() else None,
             **{m: float(ws.cell(r, k).value or 0) for k, m in METRICS.items()}}
        x["NG"] = x["O"] - x["N"]
        rows.append(x)
    unknown = sorted({x["sec"] for x in rows} - set(ASSETS), key=str)
    if unknown:
        sys.exit("data has assets the ProjectA layout has no column for: %s" % unknown)
    sort_terraces(rows)
    return rows


def sort_terraces(rows):
    """x["terr"] for every Terrace/Balconies area: its GLA/GSA Component; without one it is BUA only
    (MEP terraces keep their own line)."""
    terr = [x for x in rows if x["cat"] == "Terrace/Balconies"]
    for x in terr:
        x["terr"] = x["gsa"] if in_gla(x) else ("MEP Terrace" if x["comp"] == "MEP" else NOT_GSA)
    return terr


def compute(rows):
    leaf, used_n, used_o = defaultdict(float), defaultdict(float), defaultdict(float)
    for x in rows:
        x["NL"] = x["N"] - (x["A"] if is_common(x) else 0)
        for key, (pred, m) in RULES.items():
            if pred(x):
                leaf[((key, x["lvl"]) if key in BY_LEVEL else key, x["sec"])] += x[m]
                if m in ("A", "N", "NL"):
                    used_n[x["row"]] += x[m]
                used_o[x["row"]] += x[m]
    gaps = []
    for x in rows:
        dn, do = used_n[x["row"]] - x["N"], used_o[x["row"]] - x["O"]
        if abs(dn) > 0.005 or abs(do) > 0.005:
            gaps.append((x, dn, do))
    return {k: round(v, 2) for k, v in leaf.items()}, gaps


# ------------------------------------------------------------------ sheet
def copy_style(src, dst):
    dst.font, dst.fill, dst.border = copy(src.font), copy(src.fill), copy(src.border)
    dst.alignment, dst.protection, dst.number_format = copy(src.alignment), copy(src.protection), src.number_format


def read_inputs(path):
    """{label: {col: value}} of the manual input rows in an existing ProjectA Calculations workbook."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except PermissionError:
        sys.exit("SKIPPED - close this workbook in Excel and rerun: %s" % path)
    if REF_SHEET not in wb.sheetnames:
        return {}
    ws, out = wb[REF_SHEET], {}
    for r in range(1, ws.max_row + 1):
        label = ws[f"F{r}"].value
        if label in INPUT_TERRACES:
            vals = {col: ws[f"{col}{r}"].value for col in PODIUM_COLS + TOWER_COLS}
            out[label] = {k: v for k, v in vals.items() if isinstance(v, (int, float))}
    return out


def expand_layout(leaf):
    """LAYOUT with each BY_LEVEL line split into one row per level that carries area (one row if none)."""
    out = []
    for kind, key, *opt in LAYOUT:
        if key not in BY_LEVEL:
            out.append((kind, key, *opt))
            continue
        o = opt[0] if opt else {}
        levels = sorted({k[1] for (k, sec), v in leaf.items() if isinstance(k, tuple) and k[0] == key and v},
                        key=level_key)
        out += [(kind, (key, lvl), dict(o, label="%s - %s" % (o["label"], lvl))) for lvl in levels] or [(kind, key, o)]
    return out


def build_sheet(wb, ref_ws, leaf, inputs):
    ws = wb.create_sheet(REF_SHEET)
    layout = expand_layout(leaf)
    rownum, r = {}, 6
    for kind, key, *opt in layout:          # pass 1: row numbers
        rownum[key] = r
        r += 1
    R = rownum.__getitem__

    def put(row, col, value, donor_row, numeric=True):
        cell = ws[f"{col}{row}"]
        cell.value = value
        src = ref_ws[f"{col}{donor_row}"]
        if numeric and col in TOWER_COLS and src.number_format == "General":
            src = ref_ws[f"G{donor_row}"] if ref_ws[f"G{donor_row}"].number_format != "General" else src
        copy_style(src, cell)
        if numeric and cell.number_format == "General":
            cell.number_format = ACC_FMT

    for kind, key, *opt in layout:
        o = opt[0] if opt else {}
        row = R(key)
        donor = o.get("donor", key if isinstance(key, int) else None)
        for col in range(1, 20):              # base style of the whole row from the donor
            copy_style(ref_ws.cell(donor, col), ws.cell(row, col))
        if ref_ws.row_dimensions[donor].height:
            ws.row_dimensions[row].height = ref_ws.row_dimensions[donor].height
        label = o.get("label") or (ref_ws[f"F{donor}"].value if kind != "mirror" else None)

        if kind == "copy":
            for col in range(6, 20):
                ws.cell(row, col).value = ref_ws.cell(donor, col).value
        elif kind == "blank":
            continue
        elif kind == "leaf":
            ws[f"F{row}"].value = label
            for col, sec in PODIUM.items():
                put(row, col, leaf.get((key, sec), 0.0), donor)
            for col, sec in TOWER.items():
                put(row, col, leaf.get((key, sec), 0.0), donor)
            put(row, "N", f"=SUM(Q{row}:S{row})", donor)
            put(row, "O", f"=SUM(G{row}:N{row})", donor)
        elif kind == "input":                  # typed by the user; carried over on every rebuild
            ws[f"F{row}"].value = label
            vals = inputs.get(label, {})
            for col in PODIUM_COLS + TOWER_COLS:
                put(row, col, vals.get(col), donor)
            put(row, "N", f"=SUM(Q{row}:S{row})", donor)
            put(row, "O", f"=SUM(G{row}:N{row})", donor)
        elif kind == "mirror":
            t = R(o["target"])
            ws[f"F{row}"].value = f"=F{t}"
            for col in GO_COLS + (TOWER_COLS if o.get("qs") else []):
                put(row, col, f"={col}{t}", donor)
        elif kind in ("sum_range", "sum_list"):
            ws[f"F{row}"].value = label
            if kind == "sum_range":
                a, b = (R(m) for m in o["members"])
                f = lambda col: f"=SUM({col}{a}:{col}{b})"
            else:
                refs = [R(m) for m in o["members"]]
                f = lambda col: "=SUM(%s)" % ",".join(f"{col}{x}" for x in refs)
            for col in GO_COLS + (TOWER_COLS if o.get("qs") else []):
                put(row, col, f(col), donor)
        elif kind == "ratio":
            ws[f"F{row}"].value = label
            n, d = R(o["num"]), R(o["den"])
            for col in GO_COLS:
                put(row, col, f"=IFERROR({col}${n}/{col}{d},0)", donor)
        elif kind == "gfa_total":
            ws[f"F{row}"].value = label
            for col in GO_COLS:
                put(row, col, f"=SUM({col}{R(67)},{col}{R(37)})", donor)
            for col in TOWER_COLS:
                put(row, col, f"=SUM({col}{R(67)},{col}{R(18)})", donor)
        elif kind == "nongfa_total":
            ws[f"F{row}"].value = label
            parts = [R(x) for x in (111, 104, 98, 90, 83, 78)]
            for col in PODIUM_COLS[1:] + ["N"] + TOWER_COLS:
                put(row, col, "=SUM(%s)" % ",".join(f"{col}{x}" for x in parts), donor)
            put(row, "O", f"=SUM(H{row}:N{row})", donor)
        elif kind == "bua_excl":
            ws[f"F{row}"].value = label
            for col in PODIUM_COLS[1:] + ["N"] + TOWER_COLS:
                put(row, col, f"={col}{R(69)}+{col}{R(113)}", donor)
            put(row, "O", f"=SUM(H{row}:N{row})", donor)
        elif kind == "basement_nongfa":
            ws[f"F{row}"].value = label
            put(row, "G", "=SUM(%s)" % ",".join(f"G{R(x)}" for x in (111, 104, 98, 90, 83, 78)), donor)
            put(row, "O", f"=SUM(G{row}:N{row})", donor)
        elif kind == "bua_incl":
            ws[f"F{row}"].value = label
            put(row, "G", f"=SUM(G{R(118)},G{R(117)})", donor)
            for col in PODIUM_COLS[1:] + ["N"] + TOWER_COLS:
                put(row, col, f"=SUM({col}{R(117)},{col}{R(115)})", donor)
            put(row, "O", f"=SUM(O{R(117)},O{R(115)},O{R(118)})", donor)

    for k, dim in ref_ws.column_dimensions.items():
        cd = ws.column_dimensions[k]
        cd.width, cd.min, cd.max = dim.width, dim.min, dim.max
    ws.sheet_view.showGridLines = ref_ws.sheet_view.showGridLines
    ws.sheet_view.zoomScale = ref_ws.sheet_view.zoomScale
    return rownum


# ------------------------------------------------------------------ verify (evaluate the written formulas)
REF_RE = re.compile(r"\$?([A-Z]{1,2})\$?(\d+)")


class Evaluator:
    def __init__(self, ws):
        self.ws, self.memo = ws, {}

    def v(self, ref):
        if ref in self.memo:
            return self.memo[ref]
        val = self.ws[ref].value
        if isinstance(val, str) and val.startswith("="):
            res = self.formula(val[1:])
        elif isinstance(val, (int, float)):
            res = float(val)
        else:
            res = 0.0
        self.memo[ref] = res
        return res

    def rng(self, a, b):
        (ca, ra), (cb, rb) = REF_RE.match(a).groups(), REF_RE.match(b).groups()
        from openpyxl.utils import column_index_from_string as CI
        return [self.v(f"{L(c)}{r}") for c in range(CI(ca), CI(cb) + 1) for r in range(int(ra), int(rb) + 1)]

    def formula(self, f):
        f = re.sub(r"IFERROR\(([^(),]+),([^(),]+)\)", r"_iferror(lambda: \1, \2)", f)
        f = re.sub(r"\$?([A-Z]{1,2})\$?(\d+):\$?([A-Z]{1,2})\$?(\d+)", r'_rng("\1\2","\3\4")', f)
        f = re.sub(r'(?<![A-Za-z"_])\$?([A-Z]{1,2})\$?(\d+)(?![\d"])', r'_v("\1\2")', f)
        f = f.replace("SUM(", "_sum(")

        def _sum(*args):
            return sum(sum(a) if isinstance(a, list) else a for a in args)

        def _iferror(fn, alt):
            try:
                return fn()
            except ZeroDivisionError:
                return alt
        return eval(f, {"_sum": _sum, "_iferror": _iferror, "_v": self.v, "_rng": self.rng})


def verify(path, rownum, rows):
    ws = openpyxl.load_workbook(path)[REF_SHEET]
    ev = Evaluator(ws)
    gfa_row, bua_row = rownum[69], rownum[119]
    data_n = {s: sum(x["N"] for x in rows if x["sec"] == s) for s in ASSETS}
    data_o = {s: sum(x["O"] for x in rows if x["sec"] == s) for s in ASSETS}
    cols = dict(PODIUM, **TOWER)
    checks = [(col, sec, data_n[sec], data_o[sec]) for col, sec in cols.items()]
    checks.append(("N", "Tower Total", sum(data_n[s] for s in TOWER.values()), sum(data_o[s] for s in TOWER.values())))
    checks.append(("O", "GRAND TOTAL", sum(data_n.values()), sum(data_o.values())))
    ok = True
    print("--- written sheet, formulas evaluated ---")
    for col, label, dn, do in checks:
        g, b = ev.v(f"{col}{gfa_row}"), ev.v(f"{col}{bua_row}")
        good = abs(g - dn) < 0.05 and abs(b - do) < 0.05
        ok &= good
        print("  %-20s GFA %12s vs data %12s   BUA %12s vs data %12s   %s" % (
            label, f"{g:,.2f}", f"{dn:,.2f}", f"{b:,.2f}", f"{do:,.2f}", "OK" if good else "*** MISMATCH ***"))
    line = lambda k: "%s %s" % (ws[f"F{rownum[k]}"].value, f"{ev.v(f'O{rownum[k]}'):,.2f}")
    print("  GSA: " + " | ".join(line(k) for k in COMMON_TENANTS))
    print("  Terraces (GSA): " + " | ".join(line(k) for k in (20, "HOTEL_APT_TERR", 81, "OFFICE_TERR", "FB_TERR",
                                                               "RETAIL_TERR")))
    terr_rows = [k for k in rownum if k == "NON_GSA_TERR" or (isinstance(k, tuple) and k[0] == "NON_GSA_TERR")]
    print("  Not in GLA/GSA: " + " | ".join(line(k) for k in ["NON_GSA_GFA", 82] + terr_rows + ["NON_GSA_PLANTER"]))
    gsa_ex, gsa_in = ev.v(f"O{rownum[18]}"), ev.v(f"O{rownum[22]}")
    print("  Total GSA Excl. Terraces %s | Incl. Terraces %s | GFA eff. %.1f%% / %.1f%%" % (
        f"{gsa_ex:,.2f}", f"{gsa_in:,.2f}", 100 * ev.v(f"O{rownum[25]}"), 100 * ev.v(f"O{rownum[26]}")))
    return ok


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workbook", help="dated BUA Option 1 workbook (holds the *_BUA Space Room Split sheet)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference", default=REFERENCE, help="workbook whose 'ProjectA Calculations' sheet is the style template")
    ap.add_argument("--dry-run", action="store_true", help="compute + check coverage, write nothing")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--carry-from", help="ProjectA Calculations workbook to take the manual F&B / Retail Terraces "
                                         "values from (default: the --out workbook being replaced)")
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.workbook)
    data_ws = find_data_sheet(wb)
    rows = load_rows(openpyxl.load_workbook(a.workbook, data_only=True)[data_ws.title])
    leaf, gaps = compute(rows)
    print("data: %s  (%d rows, sheet '%s')" % (a.workbook, len(rows), data_ws.title))
    terr = [x for x in rows if x["cat"] == "Terrace/Balconies"]
    by = defaultdict(float)
    for x in terr:
        by[x["terr"]] += x["O"]
    print("terraces by GLA/GSA Component (BUA): " + " | ".join("%s %s" % (k, f"{v:,.2f}") for k, v in sorted(by.items())))
    print("  %d of %d terrace areas not tagged GLA/GSA (%s m2) - BUA only" % (
        sum(1 for x in terr if not in_gla(x)), len(terr), f"{sum(x['O'] for x in terr if not in_gla(x)):,.2f}"))
    lv = defaultdict(lambda: defaultdict(float))
    for x in terr:
        if x["terr"] == NOT_GSA and x["E"]:
            lv[x["lvl"]][x["sec"]] += x["E"]
    for lvl in sorted(lv, key=level_key):
        print("    Terraces - Not in GLA/GSA - %s: %s" % (lvl, ", ".join("%s %s" % (s, f"{v:,.2f}") for s, v in lv[lvl].items())))
    for x in rows:
        if RULES["NON_GSA_GFA"][0](x) and x["A"]:
            print("  not tagged GLA/GSA -> Usable Areas Not in GLA/GSA (GFA): %s %s %s %s m2" % (
                x["sec"], x["lvl"], x["c"], f"{x['A']:,.2f}"))
    common = defaultdict(float)
    for x in rows:
        if is_common(x):
            common[x["gsa"]] += x["A"]
    print("tagged GLA/GSA services/storage/kitchens/pool... -> Common GLA/GSA to Tenants: " +
          " | ".join("%s %s" % (k, f"{v:,.2f}") for k, v in sorted(common.items())))
    if not [x for x in rows if x["gsa"]]:
        print("  !!! the data sheet has no GLA/GSA Component values (column D) - terraces all sorted by component")
    carry = a.carry_from or (a.out if os.path.exists(a.out) else None)
    inputs = read_inputs(carry) if carry else {}
    for label in INPUT_TERRACES:
        vals = inputs.get(label, {})
        print("%s (manual): %s" % (label, ", ".join("%s=%s" % (k, v) for k, v in vals.items()) or "blank"),
              "- from %s" % carry if vals else "")
    if gaps:
        print("\n*** %d data rows are not placed exactly once on an ProjectA line - nothing written ***" % len(gaps))
        for x, dn, do in gaps:
            print("  row %-4d %-20s %-18s %-34s GFA %+9.2f  BUA %+9.2f" % (x["row"], x["sec"], x["lvl"], x["c"], dn, do))
        sys.exit(1)
    print("coverage: every m2 of GFA and BUA lands on exactly one line")
    if a.dry_run:
        return
    if os.path.exists(a.out) and not a.overwrite:
        sys.exit("exists (use --overwrite): %s" % a.out)

    ref_ws = openpyxl.load_workbook(a.reference)[REF_SHEET]
    import warnings
    with warnings.catch_warnings():          # the temporary "<name> Copy" title can exceed 31 chars
        warnings.simplefilter("ignore")
        detail = wb.copy_worksheet(data_ws)
        detail.title = "Detail Split"
    wb.move_sheet(detail, offset=wb.index(data_ws) + 1 - wb.index(detail))
    if REF_SHEET in wb.sheetnames:
        del wb[REF_SHEET]
    rownum = build_sheet(wb, ref_ws, leaf, inputs)
    wb.calculation.fullCalcOnLoad = True
    try:
        wb.save(a.out)
    except PermissionError:
        sys.exit("SKIPPED - close this workbook in Excel and rerun: %s" % a.out)
    print("saved: %s  (sheets: %s)" % (a.out, ", ".join(wb.sheetnames)))
    ok = verify(a.out, rownum, rows)
    print("\nALL TOTALS TIE OUT - DONE" if ok else "\n*** CHECK MISMATCHES ABOVE ***")


if __name__ == "__main__":
    main()

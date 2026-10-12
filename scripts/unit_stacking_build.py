"""Build the ProjectB "Unit Stacking" sheet (Tower A + Tower B) from a Unit Mix workbook.

Format comes from the 50% SD sample sheet. Data and colour scheme come from the Unit Mix
(per-level counts per unit type). Unit positions within a floor are schematic, grouped by
type in Unit Mix column order. Exec Penthouses are labelled EPH (Unit Mix colour) but are
counted within PH in every total. The floor above each penthouse in DUPLEX_UPPER is drawn as
a white "-" void (double-height penthouse).

    py -3.14 unit_stacking_build.py [--mix X.xlsx] [--out Y.xlsx] [--date YYYY-MM-DD]
                                    [--stage "100% Schematic Design"] [--duplex 75,73,46,44] [--dry-run]

Builds, verifies every level against the Unit Mix, then saves (if the output is open in Excel
it writes "<name>_v2.xlsx"). Preview: unit_stacking_preview.py <xlsx> <png>.
"""
import argparse
import datetime
import os
import sys
import zipfile
from collections import Counter
from fractions import Fraction

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.colors import Color
from openpyxl.utils import get_column_letter as CL
from openpyxl.utils.indexed_list import IndexedList
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

# ================================================================ CONFIG (edit for a new run)
DIR = r"Z:\4. Projects\3470 ProjectA Wadi High Rise\4_Design\4_Architecture\2_Documents\2_Schedules\1_Areas\2_Working\100% SD"
SUB = os.path.join(DIR, "260905_ProjectB_Unit Distribution")
SAMPLE = os.path.join(SUB, "260605_ProjectB_Unit Distribution.xlsx")       # 50% SD format sample (read only)
MIX = os.path.join(SUB, "Copy of 260917_ProjectB_Unit Mix.xlsx")            # latest Unit Mix (read only)
MIX_SHEET = "100% SD_Unit Mix"
STAGE = "100% Schematic Design"
# Upper level of each double-height penthouse ('-' void above the PH/EPH on the level below).
# User-confirmed 2026-10-05: 74 EPH, 72 PH, 45 PH and 43 PH are all double height, both towers.
DUPLEX_UPPER = {75, 73, 46, 44}
# ================================================================

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--mix", default=MIX, help="Unit Mix workbook (default: CONFIG MIX)")
ap.add_argument("--mix-sheet", default=MIX_SHEET)
ap.add_argument("--sample", default=SAMPLE, help="50%% SD sample workbook used for format, theme and Brief values")
ap.add_argument("--out", help="output xlsx (default: <DIR>\\<yymmdd>_ProjectB_Unit Distribution.xlsx)")
ap.add_argument("--date", help="date shown on the sheet and used in the default file name, YYYY-MM-DD (default today)")
ap.add_argument("--stage", default=STAGE, help='title suffix, e.g. "100%% Schematic Design"')
ap.add_argument("--duplex", help="comma list of duplex upper levels (default: CONFIG DUPLEX_UPPER)")
ap.add_argument("--dry-run", action="store_true", help="build and verify, write nothing")
args = ap.parse_args()

MIX, MIX_SHEET, SAMPLE = args.mix, args.mix_sheet, args.sample
DATE = datetime.datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.datetime.combine(
    datetime.date.today(), datetime.time())
if args.duplex is not None:
    DUPLEX_UPPER = {int(x) for x in args.duplex.split(",") if x.strip()}
OUT = args.out or os.path.join(DIR, f"{DATE:%y%m%d}_ProjectB_Unit Distribution.xlsx")
OUT_V2 = os.path.splitext(OUT)[0] + "_v2.xlsx"
DIR = os.path.dirname(os.path.abspath(OUT))

TITLE = f"ProjectB - Tower Unit Stacking - {args.stage}"
_mix_name = os.path.splitext(os.path.basename(MIX))[0].replace("Copy of ", "")
_stage_short = args.stage.replace("Schematic Design", "SD").replace("Design Development", "DD")
NOTE = (f"Source: {_mix_name} ({_stage_short}). Unit positions within each floor are schematic "
        "(grouped by type); per-floor counts match the Unit Mix. Non-unit floors carried over from "
        "50% SD stacking \u2013 confirm.")

# ---------------------------------------------------------------- types
# (mix column, internal key). Label = key; EPH is counted within PH (COMBINE).
TA_COLS = [("B", "SR"), ("C", "FS"), ("D", "ES"), ("E", "KS"), ("F", "PS"),
           ("G", "1B HA"), ("H", "2B HA"), ("I", "3B HA"),
           ("J", "St"), ("K", "1BR"), ("L", "2BR"), ("M", "3BR"), ("N", "PH"), ("O", "EPH")]
TB_COLS = [("R", "St"), ("S", "1BR"), ("T", "2BR"), ("U", "3BR"), ("V", "PH"), ("W", "EPH")]
ORDER = ["SR", "FS", "ES", "KS", "PS", "1B HA", "2B HA", "3B HA", "St", "1BR", "2BR", "3BR", "PH", "EPH"]
WEIGHT = {"SR": Fraction(1), "FS": Fraction(2), "ES": Fraction(3), "KS": Fraction(4), "PS": Fraction(8),
          "1B HA": Fraction(3), "2B HA": Fraction(4), "3B HA": Fraction(5),
          "St": Fraction(3, 2), "1BR": Fraction(2), "2BR": Fraction(3), "3BR": Fraction(4),
          "PH": Fraction(6), "EPH": Fraction(8)}
LABEL = {k: k for k in ORDER}
COMBINE = {k: ("PH" if k == "EPH" else k) for k in ORDER}
DUPLEX_UPPER = {75, 73, 46, 44}
HOTEL = {"SR", "FS", "ES", "KS", "PS"}
HA = {"1B HA", "2B HA", "3B HA"}
RESI = {"St", "1BR", "2BR", "3BR", "PH", "EPH"}
LABELS_A = ["SR", "FS", "ES", "KS", "PS", "1B HA", "2B HA", "3B HA", "St", "1BR", "2BR", "3BR", "PH"]
ALL_LABELS = LABELS_A + ["EPH"]
LABELS_B = ["St", "1BR", "2BR", "3BR", "PH"]

WIDTH = 20
TA_C1, TA_C2 = 4, 23     # D:W
TB_C1, TB_C2 = 28, 47    # AB:AU
GAP_C1, GAP_C2 = 24, 27  # X:AA
COL_A, COL_B, COL_AV = 1, 2, 48
# Typology Split shifted one column right: AX desc, AY abbr, BA brief, BB actual
TS_DESC, TS_ABBR, TS_BRIEF, TS_ACT = 50, 51, 53, 54


def lvl_row(lvl):
    if lvl == "G":
        return 86
    if isinstance(lvl, str) and lvl.startswith("B"):
        return 86 + int(lvl[1:])
    if lvl == 79:
        return 7
    if lvl == 78:
        return 8
    assert 1 <= lvl <= 77, lvl
    return 86 - lvl


# ---------------------------------------------------------------- read inputs
def colour_of(c):
    c = c.fill.fgColor
    return Color(rgb=c.rgb) if c.type == "rgb" else Color(theme=c.theme, tint=c.tint)


def colour_key(c):
    return c.rgb if c.type == "rgb" else (c.theme, round(c.tint, 2))


mwb = load_workbook(MIX)
ms = mwb[MIX_SHEET]
mwv = load_workbook(MIX, data_only=True)[MIX_SHEET]

# The Unit Mix column layout this script reads (row 3 headers, levels in A5:A84 = 79..1, G, totals row 87).
# If this fails the Unit Mix layout changed: update TA_COLS / TB_COLS before running.
hdr = {c: str(ms[f"{c}3"].value).strip() for c, _ in TA_COLS + TB_COLS}
assert [hdr[c] for c, _ in TA_COLS] == ["Standard", "family", "Exec", "King", "Presidential", "1 Bed", "2 Bed",
                                        "3 Bed", "Studio", "1 Bed", "2 Bed", "3 Bed", "Penthouse",
                                        "Exec Penthouse"], ("Unit Mix headers changed", hdr)
assert [hdr[c] for c, _ in TB_COLS] == ["Studio", "1 Bed", "2 Bed", "3 Bed", "Penthouse", "Exec Penthouse"], \
    ("Unit Mix headers changed", hdr)

mix = {"A": {}, "B": {}}           # tower -> level -> Counter(key)
mix_row = {}
for r in range(5, 85):
    a = ms.cell(r, 1).value
    lvl = "G" if str(a).strip().upper() == "G" else int(a)
    mix_row[lvl] = r
    for tower, cols in (("A", TA_COLS), ("B", TB_COLS)):
        cnt = Counter()
        for c, key in cols:
            v = ms[f"{c}{r}"].value
            if v in (None, ""):
                continue
            assert isinstance(v, (int, float)) and v == int(v) and v >= 0, (c, r, v)
            if int(v):
                cnt[key] += int(v)
        mix[tower][lvl] = cnt
assert list(mix_row)[:2] == [79, 78] and mix_row["G"] == 84 and mix_row[1] == 83, mix_row

# source totals (row 87 cached values) vs per-level sums
for tower, cols in (("A", TA_COLS), ("B", TB_COLS)):
    for c, key in cols:
        cached = mwv[f"{c}87"].value
        s = sum(cnt[key] for cnt in mix[tower].values())
        assert cached == s, (tower, c, cached, s)


def label_totals(tower):
    t = Counter()
    for cnt in mix[tower].values():
        for k, v in cnt.items():
            t[COMBINE[k]] += v
    return t


tot_a, tot_b = label_totals("A"), label_totals("B")
assert not (set(tot_b) & (HOTEL | HA)), ("Tower B has hotel / hotel apartment units", tot_b)
keys_total = sum(tot_a[k] for k in HOTEL)
ha_total = sum(tot_a[k] for k in HA)
resi_total = sum(tot_a[k] for k in ("St", "1BR", "2BR", "3BR", "PH")) + sum(tot_b.values())
print(f"Unit Mix totals: keys {keys_total}, hotel apts {ha_total}, residential {resi_total} "
      f"(A {sum(tot_a[k] for k in RESI)}, B {sum(tot_b.values())}), overall {keys_total + ha_total + resi_total}")

# Unit Mix colour scheme (read from the file, checked against the brief)
def first_fill(col, skip_rgb="FFFFFFCC"):
    for r in range(5, 85):
        cell = ms[f"{col}{r}"]
        if cell.value and cell.fill.fill_type:
            fc = cell.fill.fgColor
            if not (fc.type == "rgb" and fc.rgb == skip_rgb):
                return colour_of(cell)
    raise AssertionError(col)


C_HOTEL = colour_of(ms["B87"])
C_HA = colour_of(ms["G87"])
C_RESI = colour_of(ms["K87"])
C_ST = first_fill("J")
C_PH = first_fill("N")
C_EPH = first_fill("O")
C_HDR = colour_of(ms["B1"])
# 2026-10-05 Unit Mix: hotel theme3/0.9, HA theme3/0.75, resi FFFFCC, St FFC000, PH theme5/0.4, EPH 00B0F0
print("Unit Mix colours:", {n: colour_key(c) for n, c in (("hotel", C_HOTEL), ("HA", C_HA), ("resi", C_RESI),
                                                           ("St", C_ST), ("PH", C_PH), ("EPH", C_EPH),
                                                           ("header", C_HDR))})
TYPE_COLOUR = {"SR": C_HOTEL, "FS": C_HOTEL, "ES": C_HOTEL, "KS": C_HOTEL, "PS": C_HOTEL,
               "1B HA": C_HA, "2B HA": C_HA, "3B HA": C_HA,
               "St": C_ST, "1BR": C_RESI, "2BR": C_RESI, "3BR": C_RESI, "PH": C_PH, "EPH": C_EPH}

# sample: theme, fills of the non-unit bands, Typology Split text + Brief values
swb = load_workbook(SAMPLE)
ss = swb["Unit Stacking"]
with zipfile.ZipFile(SAMPLE) as z:
    THEME = z.read("xl/theme/theme1.xml")
SF = {k: colour_of(ss[k]) for k in ("D7", "AB7", "D9", "D34", "D36", "W36", "W38", "AC36", "D82", "D84",
                                    "D86", "D87", "Q90", "A80", "A38", "G40")}
assert ss["A2"].value.startswith("ProjectB - Tower Unit Stacking")
ts_rows = {}
for r in range(15, 37):
    abbr = ss.cell(r, 50).value
    if abbr:
        ts_rows[abbr] = (ss.cell(r, 49).value, ss.cell(r, 52).value)
assert {k: v[1] for k, v in ts_rows.items()} == {"SR": 207, "FS": 20, "ES": 20, "KS": 2, "PS": 1, "1B HA": 15,
                                                 "2B HA": 35, "3B HA": 50, "St": None, "1BR": 300,
                                                 "2BR": 285, "3BR": 65, "PH": None}, ts_rows

# ---------------------------------------------------------------- layout
def allocate(weights, width):
    n = len(weights)
    assert 0 < n <= width, (n, width)
    tot = sum(weights)
    q = [w * width / tot for w in weights]
    a = [max(1, int(x)) for x in q]
    diff = width - sum(a)
    if diff > 0:
        order = sorted(range(n), key=lambda i: (-(q[i] - a[i]), i))
        for k in range(diff):
            a[order[k % n]] += 1
    while diff < 0:
        order = sorted((i for i in range(n) if a[i] > 1), key=lambda i: (q[i] - a[i], i))
        a[order[0]] -= 1
        diff += 1
    assert sum(a) == width and min(a) >= 1
    return a


def units_of(cnt):
    out = []
    for k in ORDER:
        out += [k] * cnt.get(k, 0)
    return out


def tower_layout(tower):
    """level -> list of (label, offset, span); '-' marks the upper level of a duplex PH."""
    levels = [l for l, cnt in mix[tower].items() if sum(cnt.values())]
    lay, reserved = {}, {}
    for lvl in levels:
        units = units_of(mix[tower][lvl])
        if units[-1] in ("PH", "EPH"):
            spans = allocate([WEIGHT[u] for u in units], WIDTH)
            items, off = [], 0
            for u, s in zip(units, spans):
                items.append((LABEL[u], off, s))
                off += s
            lay[lvl] = items
            ph_w = sum(s for u, s in zip(units, spans) if u in ("PH", "EPH"))
            assert all(u in ("PH", "EPH") for u in units[len(units) - sum(1 for x in units if x in ("PH", "EPH")):])
            if lvl + 1 in DUPLEX_UPPER:
                reserved[lvl + 1] = ph_w
    for lvl in levels:
        if lvl in lay:
            continue
        units = units_of(mix[tower][lvl])
        assert not any(u in ("PH", "EPH") for u in units)
        w = WIDTH - reserved.get(lvl, 0)
        spans = allocate([WEIGHT[u] for u in units], w)
        items, off = [], 0
        for u, s in zip(units, spans):
            items.append((LABEL[u], off, s))
            off += s
        if lvl in reserved:
            items.append(("-", off, reserved[lvl]))
        lay[lvl] = items
    for lvl in reserved:
        assert lvl in lay and lay[lvl][-1][0] == "-", ("duplex upper level without units", tower, lvl)
        assert lay[lvl - 1][-1][0] in ("PH", "EPH")
    assert set(reserved) == DUPLEX_UPPER, (tower, reserved)
    assert all(it[0] != "-" for l, its in lay.items() if l not in DUPLEX_UPPER for it in its)
    return lay, reserved


LAY = {}
DUPLEX = {}
for t in ("A", "B"):
    LAY[t], DUPLEX[t] = tower_layout(t)

# deterministic stacking: identical compositions -> identical layouts
for t in ("A", "B"):
    seen = {}
    for lvl, items in LAY[t].items():
        key = (tuple(sorted(mix[t][lvl].items())), DUPLEX[t].get(lvl, 0))
        assert seen.setdefault(key, items) == items

# programme blocks (rows) and the units each one allows - matches the 260917 Unit Mix programme.
# If the programme by level changes, the check below stops the build: update these rows (and BANDS) first.
BLOCKS_A = [(7, 7, None, "empty"), (8, 8, None, "empty"), (9, 10, None, "empty"),
            (11, 33, "Residential", "resi"), (34, 39, "Amenities / MEP", "mep"),
            (40, 43, "Residential", "resi"), (44, 60, "Hotel Apartments", "ha"),
            (61, 62, "MEP", "mep"), (63, 79, "Hotel", "hotel"),
            (80, 86, "Hotel Podium Areas", "podium"), (87, 90, "Basements", "basement")]
BLOCKS_B = [(7, 7, None, "empty"), (8, 8, None, "empty"), (9, 10, None, "empty"),
            (11, 33, "Residential", "resi"), (34, 39, "Amenities / MEP", "mep"),
            (40, 60, "Residential", "resi"), (61, 62, "MEP", "mep"), (63, 79, "Residential", "resi")]
ALLOWED = {"resi": RESI, "ha": HA, "hotel": HOTEL}
row_level = {lvl_row(l): l for l in list(mix_row) + ["B1", "B2", "B3", "B4"]}
for t, blocks in (("A", BLOCKS_A), ("B", BLOCKS_B)):
    for r1, r2, _, kind in blocks:
        for r in range(r1, r2 + 1):
            lvl = row_level[r]
            keys = set(mix[t].get(lvl, Counter()))
            if kind in ALLOWED:
                assert keys and keys <= ALLOWED[kind], (t, lvl, kind, keys)
            else:
                assert not keys, (t, lvl, kind, keys)

# ---------------------------------------------------------------- workbook
wb = Workbook()
base_font = Font(name="Aptos Narrow", sz=11, family=2, scheme="minor", color=Color(theme=1))
wb._fonts = IndexedList([base_font])
wb._named_styles["Normal"].font = base_font
wb.loaded_theme = THEME
ws = wb.active
ws.title = "Unit Stacking"

BLACK = Color(theme=1)


def font(sz=11, b=False, i=False):
    return Font(name="Aptos Narrow", sz=sz, b=b, i=i, family=2, scheme="minor", color=Color(theme=1))


def fill(c):
    return PatternFill(fill_type="solid", fgColor=c, bgColor=Color(indexed=64))


CENTER = Alignment(horizontal="center", vertical="center")
RANK = {None: 0, "thin": 1, "medium": 2}
BD = {}  # (r, c) -> {side: style}


def edge(r, c, side, style):
    opp = {"left": ("right", 0, -1), "right": ("left", 0, 1), "top": ("bottom", -1, 0), "bottom": ("top", 1, 0)}
    for (rr, cc, sd) in ((r, c, side), (r + opp[side][1], c + opp[side][2], opp[side][0])):
        if rr < 1 or cc < 1:
            continue
        d = BD.setdefault((rr, cc), {})
        if RANK[style] > RANK[d.get(sd)]:
            d[sd] = style


def box(r1, c1, r2, c2, style="thin", left=None, right=None, top=None, bottom=None):
    for c in range(c1, c2 + 1):
        edge(r1, c, "top", top or style)
        edge(r2, c, "bottom", bottom or style)
    for r in range(r1, r2 + 1):
        edge(r, c1, "left", left or style)
        edge(r, c2, "right", right or style)


def put(r1, c1, r2, c2, value=None, f=None, fl=None, al=CENTER, nf=None):
    if (r1, c1) != (r2, c2):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    cell = ws.cell(r1, c1)
    if value is not None:
        cell.value = value
    cell.font = f or font()
    if fl is not None:
        cell.fill = fl
    if al is not None:
        cell.alignment = al
    if nf:
        cell.number_format = nf
    return cell


# column widths / row heights
ws.column_dimensions["A"].width = 14
ws.column_dimensions["B"].width = 12.14
for c in range(TA_C1, TB_C2 + 1):
    ws.column_dimensions[CL(c)].width = 5.43
ws.column_dimensions[CL(COL_AV)].width = 14
ws.column_dimensions[CL(TS_DESC)].width = 20
ws.column_dimensions[CL(TS_ABBR)].width = 14.43
for r in range(1, 95):
    h = ss.row_dimensions[r].height
    if 7 <= r <= 85:
        h = 15.75
    if h:
        ws.row_dimensions[r].height = h

# title, note, date
put(2, 1, 2, 1, TITLE, font(18, b=True, i=True), al=None)
put(3, 1, 3, 1, NOTE, font(10, i=True), al=Alignment(vertical="center"))
put(2, 52, 2, 54, DATE, font(), al=Alignment(horizontal="right"), nf="d-mmm-yy")

# headers
put(4, TA_C1, 5, TA_C2, "Tower A", font(20, b=True), fill(C_HDR))
put(4, TB_C1, 5, TB_C2, "Tower B", font(20, b=True), fill(C_HDR))
box(4, TA_C1, 5, TA_C2, "medium")
box(4, TB_C1, 5, TB_C2, "medium")
put(4, COL_B, 4, COL_B, "Level")
WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)
for col in (COL_A, COL_AV):
    put(6, col, 6, col, "Program/Unit Type", al=WRAP)
    box(4, col, 6, col, "medium")
box(4, COL_B, 6, COL_B, "medium", left="thin")

# outer frame D4:AU94 (gap included)
box(4, TA_C1, 94, TB_C2, "medium")
# column A frame to row 94, column B frame to row 90
box(4, COL_A, 94, COL_A, "medium")
box(4, COL_B, 90, COL_B, "medium")
BD_CLEAN_LEFT_B = True

# level numbers
for r in range(7, 91):
    lvl = row_level[r]
    txt = lvl
    if lvl == "G":
        txt = "Ground Floor"
    elif isinstance(lvl, str):
        txt = f"Basement {int(lvl[1:]):02d}"
    c = put(r, COL_B, r, COL_B, txt, al=WRAP if lvl == "G" else CENTER)
GREY = fill(SF["D9"])
for r in list(range(34, 40)) + [61, 62]:
    ws.cell(r, COL_B).fill = GREY

# programme label columns
PROG_FILL = {"resi": fill(C_RESI), "ha": fill(C_HA), "hotel": fill(C_HOTEL), "mep": fill(SF["A38"]),
             "podium": fill(SF["A80"]), "basement": fill(SF["D87"])}


def prog_label(col, r1, r2, text, kind):
    n = r2 - r1 + 1
    box(r1, col, r2, col, "medium")
    if col == COL_A:
        box(r1, COL_B, r2, COL_B, "medium", left="thin")
    if text is None:
        if r1 != r2:
            ws.merge_cells(start_row=r1, start_column=col, end_row=r2, end_column=col)
        return
    if kind in ("podium", "basement"):
        f, al = font(14, b=True, i=True), Alignment(horizontal="center", vertical="center", wrap_text=True, textRotation=90)
    elif kind == "mep" or n <= 4:
        f, al = font(11 if kind == "mep" else 12, i=kind != "mep"), WRAP
    else:
        sz = 36 if len(text) <= 11 else 28
        f, al = font(sz, i=True), Alignment(horizontal="center", vertical="center", textRotation=90)
    put(r1, col, r2, col, text, f, PROG_FILL[kind], al)


for r1, r2, text, kind in BLOCKS_A:
    prog_label(COL_A, r1, r2, text, kind)
for r1, r2, text, kind in BLOCKS_B:
    prog_label(COL_AV, r1, r2, text, kind)

# unit bands
WHITE = fill(SF["G40"])
placed = {"A": {}, "B": {}}   # tower -> level -> Counter(label) read back from what was written
for t, c0, c_end in (("A", TA_C1, TA_C2), ("B", TB_C1, TB_C2)):
    for lvl, items in LAY[t].items():
        r = lvl_row(lvl)
        for label, off, span in items:
            c1, c2 = c0 + off, c0 + off + span - 1
            assert c2 <= c_end
            put(r, c1, r, c2, label, fl=WHITE if label == "-" else None)
            box(r, c1, r, c2, "thin")
        box(r, c0, r, c_end, "thin", left="medium", right="medium")

# non-unit bands (sample texts + fills, adapted to the 20-column bands)
BANDS = [
    (7, 7, TA_C1, TA_C2, "-", "G40", "thin"), (7, 7, TB_C1, TB_C2, "-", "G40", "thin"),
    (8, 8, TA_C1, TA_C2, "ROOFTOP AMENITIES", "D7", "thin"), (8, 8, TB_C1, TB_C2, "ROOFTOP AMENITIES", "AB7", "thin"),
    (9, 10, TA_C1, TA_C2, "MEP", "D9", "thin"), (9, 10, TB_C1, TB_C2, "MEP", "D9", "thin"),
    (34, 35, TA_C1, TB_C2, "SPORTS/GYM/FITNESS", "D34", "medium"),
    (36, 37, TA_C1, TA_C2, "SPA", "D36", "medium"), (36, 37, GAP_C1, GAP_C2, "F&B", "W36", "medium"),
    (36, 37, TB_C1, TB_C2, "SPA", "AC36", "medium"),
    (38, 39, TA_C1, TA_C2, "MEP", "D9", "thin"), (38, 39, GAP_C1, GAP_C2, "AMENITIES", "W38", "medium"),
    (38, 39, TB_C1, TB_C2, "MEP", "D9", "thin"),
    (61, 62, TA_C1, TA_C2, "MEP", "D9", "thin"), (61, 62, TB_C1, TB_C2, "MEP", "D9", "thin"),
    (80, 81, TA_C1, TA_C2, "MEP", "D9", "thin"), (80, 81, TB_C1, TB_C2, "MEP", "D9", "thin"),
    (82, 83, TA_C1, TB_C2, "BALLROOM & MICE FACILITIES", "D82", "medium"),
    (84, 85, TA_C1, TB_C2, "ALL DAY DINING, MAIN KITCHEN AND ADMIN OFFICE", "D84", "medium"),
    (86, 86, TA_C1, TB_C2, "ENTRANCE LOBBIES, RECEPTION, CONCIERGE & F&B", "D86", "medium"),
    (87, 87, TA_C1, TB_C2, "LOADING BAY, LAUNDRY, STAFF FACILITIES, PARKING", "D87", "medium"),
    (88, 88, TA_C1, TB_C2, "PARKING", "D87", "medium"),
    (89, 89, TA_C1, TB_C2, "PARKING", "D87", "medium"),
    (90, 90, 17, 35, "TANKS AND PUMP ROOMS", "Q90", "medium"),
]
band_rows = set()
for r1, r2, c1, c2, text, src, st in BANDS:
    put(r1, c1, r2, c2, text, fl=fill(SF[src]))
    outer_l = "medium" if c1 in (TA_C1, TB_C1, GAP_C1) else st
    outer_r = "medium" if c2 in (TA_C2, TB_C2, GAP_C2) else st
    box(r1, c1, r2, c2, st, left=outer_l if st == "thin" else "medium", right=outer_r if st == "thin" else "medium")
    band_rows.update(range(r1, r2 + 1))
# every level row is either a unit row or a band row
for r in range(7, 91):
    lvl = row_level[r]
    has_units = lvl in LAY["A"] or lvl in LAY["B"]
    assert has_units or r in band_rows, (r, lvl)

# conditional formatting: exact-match rules keyed on the label text
for rng in (f"{CL(TA_C1)}7:{CL(TA_C2)}79", f"{CL(TB_C1)}7:{CL(TB_C2)}79"):
    for lab in ALL_LABELS:
        ws.conditional_formatting.add(
            rng, CellIsRule(operator="equal", formula=[f'"{lab}"'], fill=PatternFill(bgColor=TYPE_COLOUR[lab])))

# bottom rows: type row 92, counts row 94
put(92, COL_A, 92, COL_A, "Program/Unit Type", al=WRAP, fl=WHITE)
put(94, COL_A, 94, COL_A, "Total Counts per Tower", al=WRAP, fl=WHITE)
box(92, COL_A, 92, COL_A, "medium")
box(94, COL_A, 94, COL_A, "medium")
COUNT_CELL = {"A": {}, "B": {}}
for t, labels, c_start, (r_c1, r_c2) in (("A", LABELS_A, TA_C2 - len(LABELS_A) + 1, (TA_C1, TA_C2)),
                                         ("B", LABELS_B, TB_C1, (TB_C1, TB_C2))):
    rng = f"${CL(r_c1)}$7:${CL(r_c2)}$90"
    for k, lab in enumerate(labels):
        c = c_start + k
        put(92, c, 92, c, lab, al=WRAP, fl=fill(TYPE_COLOUR[lab]))
        fx = f'=COUNTIF({rng},"{lab}")' + (f'+COUNTIF({rng},"EPH")' if lab == "PH" else "")
        put(94, c, 94, c, fx, al=WRAP, fl=fill(TYPE_COLOUR[lab]))
        COUNT_CELL[t][lab] = f"{CL(c)}94"
    c_end = c_start + len(labels) - 1
    box(92, c_start, 92, c_end, "medium")
    box(94, c_start, 94, c_end, "medium")

# Typology Split (AX:BB)
put(13, TS_DESC, 13, TS_ACT, "Typology Split", font(12), WHITE, Alignment(horizontal="left"))
box(13, TS_DESC, 13, TS_ACT, "medium")
put(14, TS_BRIEF, 14, TS_BRIEF, "Brief", font(10, b=True, i=True))
put(14, TS_ACT, 14, TS_ACT, "100% SD", font(10, b=True, i=True))
box(13, TS_DESC, 36, TS_ACT, "medium")


def ts_row(r, desc, abbr, brief, actual, colour):
    fl = fill(colour)
    for c in range(TS_DESC, TS_ACT + 1):
        ws.cell(r, c).fill = fl
    put(r, TS_DESC, r, TS_DESC, desc, al=None, fl=fl)
    if abbr:
        put(r, TS_ABBR, r, TS_ABBR, abbr, font(i=True), fl, Alignment(horizontal="right"))
    put(r, TS_BRIEF, r, TS_BRIEF, brief, font(10, b=True, i=True), fl)
    put(r, TS_ACT, r, TS_ACT, actual, font(b=True), fl, Alignment(horizontal="center"))


B_ = CL(TS_BRIEF)
A_ = CL(TS_ACT)
for k, lab in enumerate(["SR", "FS", "ES", "KS", "PS"]):
    ts_row(15 + k, ts_rows[lab][0], lab, ts_rows[lab][1], f"={COUNT_CELL['A'][lab]}", TYPE_COLOUR[lab])
ts_row(21, "Total Guestroom Keys", None, f"=SUM({B_}15:{B_}19)", f"=SUM({A_}15:{A_}19)", C_HOTEL)
box(15, TS_DESC, 21, TS_ACT, "medium")
for k, lab in enumerate(["1B HA", "2B HA", "3B HA"]):
    ts_row(23 + k, ts_rows[lab][0], lab, ts_rows[lab][1], f"={COUNT_CELL['A'][lab]}", TYPE_COLOUR[lab])
ts_row(27, "Total Hotel Apts", None, f"=SUM({B_}23:{B_}25)", f"=SUM({A_}23:{A_}25)", C_HA)
box(23, TS_DESC, 27, TS_ACT, "medium")
for k, lab in enumerate(["St", "1BR", "2BR", "3BR", "PH"]):
    ts_row(30 + k, ts_rows[lab][0], lab, ts_rows[lab][1],
           f"={COUNT_CELL['A'][lab]}+{COUNT_CELL['B'][lab]}", TYPE_COLOUR[lab])
ts_row(36, "Total Residential Units", None, f"=SUM({B_}30:{B_}34)", f"=SUM({A_}30:{A_}34)", C_RESI)
box(30, TS_DESC, 36, TS_ACT, "medium")
# EPH legend
put(38, TS_DESC, 38, TS_DESC, "EPH", font(10, i=True), fill(C_EPH))
box(38, TS_DESC, 38, TS_DESC, "thin")
put(38, TS_ABBR, 38, TS_ABBR, "EPH = Executive Penthouse (shaded blue; counted within PH)", font(10, i=True),
    al=Alignment(vertical="center"))

# apply accumulated borders to every cell (merged cells included)
for (r, c), d in BD.items():
    ws.cell(r, c).border = Border(**{s: Side(style=st) for s, st in d.items()})

# sheet view + page setup (copied from the sample)
ws.freeze_panes = "B7"
ws.sheet_view.zoomScale = 89
ws.sheet_view.zoomScaleNormal = 89
ws.page_setup.orientation = "landscape"
ws.page_setup.paperSize = 304
ws.page_setup.scale = 67
ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
ws.page_margins = PageMargins(left=0.7, right=0.7, top=0.75, bottom=0.75, header=0.3, footer=0.3)

from openpyxl.workbook.properties import CalcProperties
wb.calculation = CalcProperties(fullCalcOnLoad=True)

# ---------------------------------------------------------------- verify before writing
def read_back(sheet, c1, c2):
    out = {}
    for r in range(7, 91):
        cnt = Counter()
        for c in range(c1, c2 + 1):
            v = sheet.cell(r, c).value
            if isinstance(v, str) and v in ALL_LABELS:
                cnt[v] += 1
        out[row_level[r]] = cnt
    return out


def expect_labels(tower, lvl):
    cnt = Counter()
    for k, v in mix[tower].get(lvl, Counter()).items():
        cnt[LABEL[k]] += v
    return cnt


def verify(sheet):
    for t, c1, c2 in (("A", TA_C1, TA_C2), ("B", TB_C1, TB_C2)):
        rb = read_back(sheet, c1, c2)
        for lvl in list(mix_row) + ["B1", "B2", "B3", "B4"]:
            exp = expect_labels(t, lvl)
            got = rb[lvl]
            assert +got == +exp, (t, lvl, dict(got), dict(exp))
            mixc = mix[t].get(lvl, Counter())
            assert got["PH"] + got["EPH"] == mixc["PH"] + mixc["EPH"], (t, lvl)
        tot = Counter()
        for cnt in rb.values():
            for k, v in cnt.items():
                tot[COMBINE[k]] += v
        assert +tot == +(tot_a if t == "A" else tot_b), (t, tot)
    # nothing stray in the gap or outside the bands at unit rows
    for r in range(7, 91):
        for c in range(GAP_C1, GAP_C2 + 1):
            v = sheet.cell(r, c).value
            assert v in (None, "F&B", "AMENITIES", "SPORTS/GYM/FITNESS") or r >= 82, (r, c, v)


verify(ws)
for t in ("A", "B"):
    print("Tower", t, "duplex upper levels (reserved span):", DUPLEX[t])
if args.dry_run:
    print("DRY RUN OK - every level matches the Unit Mix; nothing written. Output would be:", OUT)
    sys.exit(0)

# ---------------------------------------------------------------- save
target = OUT
lock = os.path.join(DIR, "~$" + os.path.basename(OUT))
if os.path.exists(lock):
    target = OUT_V2
elif os.path.exists(OUT):
    try:
        with open(OUT, "r+b"):
            pass
    except PermissionError:
        target = OUT_V2
for p in (SAMPLE, MIX):
    assert os.path.abspath(p) != os.path.abspath(target)
wb.save(target)
print("SAVED", target)

# re-open and verify the saved file
verify(load_workbook(target)["Unit Stacking"])
print("VERIFIED per-level counts for", len(mix_row), "levels; totals A", dict(tot_a), "B", dict(tot_b))

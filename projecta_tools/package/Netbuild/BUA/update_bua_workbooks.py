"""
ProjectB - BUA workbook updater
============================
Re-feeds the raw Revit area export into the formatted BUA workbooks.
Run whenever the raw areas are updated:

    python update_bua_workbooks.py

Produces/overwrites (in this folder):
  1. Option 1 "..._with All Levels.xlsx"      - every sheet shows ALL levels
     (Basement 04 -> 78th) incl. typical expansions as cross-reference rows.
  2. Option 2 "..._Raw Levels Only_Option 2.xlsx" - each sheet shows only its
     own section's levels (+ typical expansions where the base floor has data).

Both files also get their '260622_BUA Space Room Split' sheet re-fed from raw
(template formatting preserved). The 'Roof Areas' sheet is never touched.

Rules encoded (agreed 2026-07-02):
  - Column C kept verbatim from raw (hyphen intact); exact-0 shows as "0".
  - Pivot: GFA components & categories alphabetical; FIXED skeleton = every
    GFA component x the full Space/Room category union, zero-filled (identical
    columns on every reload - other disciplines use this file as a base).
  - Circulation / Services / Storage split into "(GFA)" / "(Non-GFA)" columns;
    all other categories a single BUA column.  GFA = col N (A+B); Non-GFA = O-N.
  - Typical floors (raw stores ONE row already x floor count):
      07th x14 (07-20), 21st x2 (21-22), 27th x10 (27-36), 66th x6 (66-71)
    -> base floor = raw / count, member floors cross-reference the base.
    "27th to 36th Floor" (one combined-range Level) is read as "27th Floor".
  - Raw quirk: col C without a hyphen (e.g. 'Facade Structure') => asset=category.
Requires: openpyxl (pip install openpyxl). Set fullCalcOnLoad so Excel
recalculates all formulas on open.
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, Color
from openpyxl.utils import get_column_letter as L
from collections import OrderedDict, defaultdict
from copy import copy
import os, re, shutil, tempfile

# ------------------------------------------------------------------ config
FOLDER  = os.path.dirname(os.path.abspath(__file__))
RAW     = os.path.join(FOLDER, "Excel - Raw Area from RVT- Overall With Assets For MEP Team.xlsx")
OPTION1 = os.path.join(FOLDER, "260702_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx")
OPTION2 = os.path.join(FOLDER, "260702_ProjectB_Overall BUA_Space_Room Split_Raw Levels Only_Option 2.xlsx")
DATA_SHEET = "260622_BUA Space Room Split"     # template sheet that gets re-fed

ZERO_FMT   = "#,##0.00;-#,##0.00;0"
FN         = "Aptos Narrow"
SPLIT_CATS = {"Circulation", "Services", "Storage"}
# 2026-09-11: ranges updated to match the live model's actual Level set -
# 22nd/28th-36th/67th-71st no longer exist as individual Levels; "27th to
# 36th Floor" is a single combined-range Level (aliased below to the
# ordinal "27th Floor" so it slots into the same base/member mechanism).
TYPICAL    = {"07th Floor": (7, 20, 14), "21st Floor": (21, 22, 2),
              "27th Floor": (27, 36, 10), "66th Floor": (66, 71, 6)}
# Raw Level names that don't match the ordinal(n) convention but should be
# treated as if they did (combined-range Levels named literally in Revit).
LEVEL_ALIASES = {"27th to 36th Floor": "27th Floor"}

# ---------------------------------------------------------- FROZEN format
# The column skeleton is FROZEN so other disciplines can rely on fixed cell
# positions. If a raw export ever contains a NEW component or category, it is
# NOT added silently - the script prints a prominent warning (and totals will
# show a mismatch). To accept a new item, add it to these lists by hand
# (keep alphabetical, case-insensitive) and inform the other disciplines.
FROZEN_COMPONENTS = [
    "Circulation", "Facade Structure", "Hotel", "MEP", "Office",
    "Parking", "Residential", "Retail", "Shared", "Storage",
]
FROZEN_CATS = [
    "Ballroom", "Circulation", "F&B", "F&B Kitchen",
    "F&B Seating / Beach Club Lounge", "Facade Structure", "Gym/Fitness",
    "Hotel Apartments", "Hotel Guest Rooms", "Kitchen", "Meeting Room",
    "MEP Rooms", "Offices", "Parking", "Pool", "Pool Deck",
    "Residential Units", "Restaurant", "Retail", "Roof (Seating Area)",
    "Services", "SPA", "Storage", "Terrace/Balconies",
]

# ------------------------------------------------------------------ helpers
def split_ac(v):  return v.split("-", 1) if "-" in v else (v, v)
def SORT(seq):    return sorted(seq, key=lambda s: s.lower())
def disp(v):      return "0" if abs(v) < 0.005 else f"{v:,.2f}"
def ordinal(n):
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n:02d}{suf} Floor"

def load_raw():
    """Copy raw to temp first - it is often open (locked) in Excel.
    Excel's lock can block Python reads; PowerShell Copy-Item still works."""
    tmp = os.path.join(tempfile.gettempdir(), "_bua_raw_copy.xlsx")
    try:
        shutil.copyfile(RAW, tmp)
    except PermissionError:
        import subprocess
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Copy-Item -LiteralPath "{RAW}" -Destination "{tmp}" -Force'],
            capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(tmp):
            raise PermissionError(f"cannot read raw file (locked): {RAW}\n{res.stderr}")
    return openpyxl.load_workbook(tmp).active

# ------------------------------------------------------------------ parse raw
src = load_raw()
assets, cats, own = OrderedDict(), OrderedDict(), OrderedDict()
SECTIONS, body = [], []                                   # body: for DATA_SHEET re-feed
data    = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # sec -> (lvl,a,y) -> [N,O]
gfatot  = defaultdict(lambda: defaultdict(float))
sec_lv  = defaultdict(set)
present = set()
cur = None
for r in range(4, src.max_row + 1):
    a = src.cell(r, 1).value
    a = LEVEL_ALIASES.get(a, a)
    rest = [src.cell(r, c).value for c in range(2, 16)]
    if a in (None, "") and not [x for x in rest if x not in (None, "")]:
        continue
    if not [x for x in rest if x not in (None, "")]:      # section header row
        cur = a
        if a not in SECTIONS: SECTIONS.append(a)
        body.append(("H", a))
        continue
    body.append(("D", [src.cell(r, c).value for c in range(1, 16)]))
    cval = src.cell(r, 3).value
    if not (isinstance(cval, str) and cval.strip()): continue
    asset, cat = split_ac(cval)
    assets[asset] = cats[cat] = True
    own.setdefault(asset, OrderedDict())[cat] = True
    N = src.cell(r, 14).value or 0; O = src.cell(r, 15).value or 0
    d = data[cur][(a, asset, cat)]; d[0] += N; d[1] += O
    gfatot[cur][a] += N
    present.add(a); sec_lv[cur].add(a)

# FROZEN skeleton: every component x every category (zero-filled) - identical
# columns on every reload. New raw items are flagged, never silently inserted.
ASSETS, CATS = list(FROZEN_COMPONENTS), list(FROZEN_CATS)
NEW_COMPONENTS = SORT(set(assets) - set(FROZEN_COMPONENTS))
NEW_CATS       = SORT(set(cats)   - set(FROZEN_CATS))
UNMAPPED_BUA = sum(v[1] for s in data for (l, a, y), v in data[s].items()
                   if a not in FROZEN_COMPONENTS or y not in FROZEN_CATS)

def warn_new_items():
    if not (NEW_COMPONENTS or NEW_CATS):
        return True
    bar = "!" * 78
    print(f"\n{bar}\n!!!  NEW ITEMS IN RAW THAT ARE *NOT* IN THE FROZEN FORMAT  !!!")
    if NEW_COMPONENTS: print(f"!!!  New GFA Components : {', '.join(NEW_COMPONENTS)}")
    if NEW_CATS:       print(f"!!!  New Space/Room Cats: {', '.join(NEW_CATS)}")
    print(f"!!!  Their area ({UNMAPPED_BUA:,.2f} SQM BUA) is EXCLUDED from the workbooks,")
    print(f"!!!  so totals below will MISMATCH the raw by that amount.")
    print(f"!!!  To accept: add them to FROZEN_COMPONENTS / FROZEN_CATS in this script")
    print(f"!!!  (keep alphabetical) and notify the other disciplines.\n{bar}\n")
    return False

leaf_defs = []
for a in ASSETS:
    for y in CATS:
        if y in SPLIT_CATS: leaf_defs += [(a, y, "GFA"), (a, y, "NonGFA")]
        else:               leaf_defs.append((a, y, "BUA"))
# (new-item detection replaces the old hard assert: warn_new_items() reports
#  anything in raw that has no column in the frozen skeleton)

typ_member = {}
for base, (s, e, fc) in TYPICAL.items():
    for n in range(s, e + 1):
        if ordinal(n) != base: typ_member[ordinal(n)] = base
global_order = [l for l in ["Basement 04", "Basement Mezzanine", "Basement 03", "Basement 02", "Basement 01", "Ground Floor"] if l in present]
for n in range(1, 100):
    fn = ordinal(n)
    if fn in present or fn in typ_member: global_order.append(fn)

def leaf_val(sec, lvl, a, y, kind):
    N, O = data[sec].get((lvl, a, y), (0.0, 0.0))
    return N if kind == "GFA" else (O - N if kind == "NonGFA" else O)

LEAF0 = 2; LEAF1 = 1 + len(leaf_defs); GFA_C = LEAF1 + 1; BUA_C = LEAF1 + 2; NCOLS = BUA_C

# ------------------------------------------------------------------ styles
BLK   = Color(theme=1)
GREY  = PatternFill("solid", fgColor=Color(theme=0, tint=-0.15))
GREY2 = PatternFill("solid", fgColor=Color(theme=0, tint=-0.25))
f_title, f_hdr  = Font(name=FN, sz=20, bold=True, italic=True, color=BLK), Font(name=FN, sz=11, bold=True, italic=True, color=BLK)
f_asset, f_leaf = Font(name=FN, sz=11, bold=True, color=BLK), Font(name=FN, sz=9, italic=True, color=BLK)
f_data, f_tot   = Font(name=FN, sz=11, color=BLK), Font(name=FN, sz=11, bold=True, color=BLK)
a_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
a_leaf   = Alignment(horizontal="center", vertical="bottom", text_rotation=90)
thin, med = Side("thin"), Side("medium")
_bc = {}
def border(l="thin", r="thin", t="thin", b="thin"):
    k = (l, r, t, b)
    if k not in _bc:
        s = {"thin": thin, "medium": med}
        _bc[k] = Border(left=s[l], right=s[r], top=s[t], bottom=s[b])
    return _bc[k]
def leaf_label(y, kind):
    return f"{y} (GFA)" if kind == "GFA" else (f"{y} (Non-GFA)" if kind == "NonGFA" else y)

# ------------------------------------------------------------------ pivot sheet
def build_section(wb, section, mode):
    """mode='all' -> full master level list; mode='own' -> section levels only."""
    if mode == "all":
        master = list(global_order)
    else:
        master = [l for l in global_order
                  if l in sec_lv[section] or (l in typ_member and typ_member[l] in sec_lv[section])]
    if section in wb.sheetnames: del wb[section]
    ws = wb.create_sheet(section)
    R_D0 = 4; R_TOT = R_D0 + len(master)
    base_row = {b: R_D0 + master.index(b) for b in TYPICAL if b in master}

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=NCOLS)
    tc = ws.cell(1, 1, f"ProjectB - {section} - BUA by Asset / Category")
    tc.font = f_title; tc.alignment = Alignment(vertical="center"); tc.border = border(b="medium")
    ws.merge_cells(start_row=2, start_column=1, end_row=3, end_column=1)
    c = ws.cell(2, 1, "Level"); c.font = f_hdr; c.fill = GREY; c.alignment = a_center
    for cc, txt in ((GFA_C, "Gross Floor Area (GFA) (A+B) SQM"), (BUA_C, "Built Up Area (A+B+C+D+E+F+G+H) SQM")):
        ws.merge_cells(start_row=2, start_column=cc, end_row=3, end_column=cc)
        c = ws.cell(2, cc, txt); c.font = f_hdr; c.fill = GREY; c.alignment = a_center

    group_starts = set()
    for i, (a, y, kind) in enumerate(leaf_defs):
        lc = ws.cell(3, LEAF0 + i, leaf_label(y, kind)); lc.font = f_leaf; lc.fill = GREY; lc.alignment = a_leaf
    for a in ASSETS:
        idxs = [LEAF0 + i for i, (aa, _, _) in enumerate(leaf_defs) if aa == a]
        s, e = idxs[0], idxs[-1]; group_starts.add(s)
        if e > s: ws.merge_cells(start_row=2, start_column=s, end_row=2, end_column=e)
        ac = ws.cell(2, s, a); ac.font = f_asset; ac.fill = GREY2; ac.alignment = a_center

    colmax = {c: 1 for c in range(LEAF0, NCOLS + 1)}
    for ri, lvl in enumerate(master):
        r = R_D0 + ri
        lc = ws.cell(r, 1, lvl); lc.font = f_data; lc.alignment = Alignment(vertical="center")
        base = typ_member.get(lvl); is_base = lvl in TYPICAL
        member_ref = base is not None and base in base_row and base in sec_lv[section]
        fc = TYPICAL[lvl][2] if is_base else 1
        rowsum = 0.0
        for i, (a, y, kind) in enumerate(leaf_defs):
            cc = LEAF0 + i
            if base is not None:
                num = leaf_val(section, base, a, y, kind) / TYPICAL[base][2] if member_ref else 0.0
                v = f"={L(cc)}{base_row[base]}" if member_ref else 0
            elif is_base:
                num = v = leaf_val(section, lvl, a, y, kind) / fc
            else:
                num = v = round(leaf_val(section, lvl, a, y, kind), 2)
            rowsum += num
            cell = ws.cell(r, cc, v); cell.font = f_data; cell.number_format = ZERO_FMT
            colmax[cc] = max(colmax[cc], len(disp(num)))
        if base is not None:
            gnum = gfatot[section].get(base, 0) / TYPICAL[base][2] if member_ref else 0.0
            gv = f"={L(GFA_C)}{base_row[base]}" if member_ref else 0
        elif is_base:
            gnum = gv = gfatot[section].get(lvl, 0) / fc
        else:
            gnum = gv = round(gfatot[section].get(lvl, 0), 2)
        gc = ws.cell(r, GFA_C, gv); gc.font = f_data; gc.number_format = ZERO_FMT
        colmax[GFA_C] = max(colmax[GFA_C], len(disp(gnum)))
        bv = f"={L(BUA_C)}{base_row[base]}" if member_ref else f"=SUM({L(LEAF0)}{r}:{L(LEAF1)}{r})"
        bc = ws.cell(r, BUA_C, bv); bc.font = f_data; bc.number_format = ZERO_FMT
        colmax[BUA_C] = max(colmax[BUA_C], len(disp(rowsum)))

    tcell = ws.cell(R_TOT, 1, "Grand Total"); tcell.font = f_tot; tcell.fill = GREY
    for cc in range(LEAF0, NCOLS + 1):
        t = ws.cell(R_TOT, cc, f"=SUM({L(cc)}{R_D0}:{L(cc)}{R_TOT-1})")
        t.font = f_tot; t.fill = GREY; t.number_format = ZERO_FMT
    for i in range(len(leaf_defs)):                        # widths incl. grand totals
        tot = sum(leaf_val(section, lvl, *leaf_defs[i]) for lvl in sec_lv[section])
        colmax[LEAF0 + i] = max(colmax[LEAF0 + i], len(disp(tot)))
    colmax[GFA_C] = max(colmax[GFA_C], len(disp(sum(gfatot[section].values()))))
    colmax[BUA_C] = max(colmax[BUA_C], len(disp(sum(leaf_val(section, lvl, *d) for lvl in sec_lv[section] for d in leaf_defs))))

    for r in range(2, R_TOT + 1):
        for cc in range(1, NCOLS + 1):
            l  = "medium" if (cc in group_starts or cc == GFA_C or cc == 1) else "thin"
            rr = "medium" if cc == NCOLS else "thin"
            t  = "medium" if r in (2, R_TOT) else "thin"
            bb = "medium" if r in (3, R_TOT) else "thin"
            ws.cell(r, cc).border = border(l, rr, t, bb)

    lvl_len = max(len(str(ws.cell(r, 1).value or "")) for r in range(R_D0, R_TOT + 1))
    ws.column_dimensions["A"].width = round(lvl_len * 0.95 + 2, 2)
    for cc in range(LEAF0, LEAF1 + 1):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 4.0), 2)
    for cc in (GFA_C, BUA_C):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 12.0), 2)
    ws.row_dimensions[1].height = 30; ws.row_dimensions[2].height = 30
    ws.row_dimensions[3].height = round(max(len(leaf_label(y, k)) for (_, y, k) in leaf_defs) * 5.0 + 14, 1)
    for r in range(R_D0, R_TOT + 1): ws.row_dimensions[r].height = 15.75
    ws.freeze_panes = ws.cell(R_D0, LEAF0)

# ------------------------------------------------------------------ combined sheet (Option 1)
COMBINED_SHEET = "Overall BUA"

def build_combined(wb):
    """Option 1: one continuous sheet - all sections stacked like the raw layout.
    Col A = Level, col B = Building Asset (section); a section-header row starts
    each block; every block shows ALL levels; a '<Section> Total' subtotal row
    (grand-total style) closes each block; Grand Total row at the very end.
    Terminology: sections = assets, former assets = GFA Components,
    categories = Space/Room Category."""
    for s in SECTIONS:
        if s in wb.sheetnames: del wb[s]
    if COMBINED_SHEET in wb.sheetnames: del wb[COMBINED_SHEET]
    ws = wb.create_sheet(COMBINED_SHEET)
    B_C  = 2
    LF0  = 3; LF1 = 2 + len(leaf_defs)
    G_C  = LF1 + 1; U_C = LF1 + 2; NC = U_C

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=NC)
    tc = ws.cell(1, 1, "ProjectB - Overall BUA - Asset / GFA Component / Space-Room Category")
    tc.font = f_title; tc.alignment = Alignment(vertical="center"); tc.border = border(b="medium")
    for col, txt in ((1, "Level"), (B_C, "Building Asset")):
        ws.merge_cells(start_row=2, start_column=col, end_row=3, end_column=col)
        c = ws.cell(2, col, txt); c.font = f_hdr; c.fill = GREY; c.alignment = a_center
    for cc, txt in ((G_C, "Gross Floor Area (GFA) (A+B) SQM"), (U_C, "Built Up Area (A+B+C+D+E+F+G+H) SQM")):
        ws.merge_cells(start_row=2, start_column=cc, end_row=3, end_column=cc)
        c = ws.cell(2, cc, txt); c.font = f_hdr; c.fill = GREY; c.alignment = a_center
    group_starts = set()
    for i, (a, y, kind) in enumerate(leaf_defs):
        lc = ws.cell(3, LF0 + i, leaf_label(y, kind)); lc.font = f_leaf; lc.fill = GREY; lc.alignment = a_leaf
    for a in ASSETS:
        idxs = [LF0 + i for i, (aa, _, _) in enumerate(leaf_defs) if aa == a]
        s, e = idxs[0], idxs[-1]; group_starts.add(s)
        if e > s: ws.merge_cells(start_row=2, start_column=s, end_row=2, end_column=e)
        ac = ws.cell(2, s, a); ac.font = f_asset; ac.fill = GREY2; ac.alignment = a_center

    colmax = {c: 1 for c in range(LF0, NC + 1)}
    sec_hdr_rows, sub_rows = [], []
    r = 4
    for section in SECTIONS:
        # section-start row (like raw A4/A33/...)
        ws.cell(r, 1, section).font = f_asset
        for c in range(1, NC + 1): ws.cell(r, c).fill = GREY
        sec_hdr_rows.append(r)
        r += 1
        b0 = r
        # levels like the raw: only this section's own levels (+ typical
        # expansion rows where the base floor has data here)
        block_levels = [l for l in global_order
                        if l in sec_lv[section]
                        or (l in typ_member and typ_member[l] in sec_lv[section])]
        base_row = {b: b0 + block_levels.index(b) for b in TYPICAL if b in block_levels}
        for ri, lvl in enumerate(block_levels):
            rr = b0 + ri
            ws.cell(rr, 1, lvl).font = f_data
            ws.cell(rr, B_C, section).font = f_data
            base = typ_member.get(lvl); is_base = lvl in TYPICAL
            member_ref = base is not None and base in sec_lv[section]
            fc = TYPICAL[lvl][2] if is_base else 1
            rowsum = 0.0
            for i, (a, y, kind) in enumerate(leaf_defs):
                cc = LF0 + i
                if base is not None:
                    num = leaf_val(section, base, a, y, kind) / TYPICAL[base][2] if member_ref else 0.0
                    v = f"={L(cc)}{base_row[base]}" if member_ref else 0
                elif is_base:
                    num = v = leaf_val(section, lvl, a, y, kind) / fc
                else:
                    num = v = round(leaf_val(section, lvl, a, y, kind), 2)
                rowsum += num
                cell = ws.cell(rr, cc, v); cell.font = f_data; cell.number_format = ZERO_FMT
                colmax[cc] = max(colmax[cc], len(disp(num)))
            if base is not None:
                gnum = gfatot[section].get(base, 0) / TYPICAL[base][2] if member_ref else 0.0
                gv = f"={L(G_C)}{base_row[base]}" if member_ref else 0
            elif is_base:
                gnum = gv = gfatot[section].get(lvl, 0) / fc
            else:
                gnum = gv = round(gfatot[section].get(lvl, 0), 2)
            gc = ws.cell(rr, G_C, gv); gc.font = f_data; gc.number_format = ZERO_FMT
            colmax[G_C] = max(colmax[G_C], len(disp(gnum)))
            bv = f"={L(U_C)}{base_row[base]}" if member_ref else f"=SUM({L(LF0)}{rr}:{L(LF1)}{rr})"
            bc = ws.cell(rr, U_C, bv); bc.font = f_data; bc.number_format = ZERO_FMT
            colmax[U_C] = max(colmax[U_C], len(disp(rowsum)))
        b1 = b0 + len(block_levels) - 1
        sr = b1 + 1                                   # subtotal row (grand-total style)
        ws.cell(sr, 1, f"{section} Total").font = f_tot
        for c in range(1, NC + 1): ws.cell(sr, c).fill = GREY
        for cc in range(LF0, NC + 1):
            t = ws.cell(sr, cc, f"=SUM({L(cc)}{b0}:{L(cc)}{b1})")
            t.font = f_tot; t.number_format = ZERO_FMT
        # widths incl. section totals
        for i in range(len(leaf_defs)):
            tot = sum(leaf_val(section, lvl, *leaf_defs[i]) for lvl in sec_lv[section])
            colmax[LF0 + i] = max(colmax[LF0 + i], len(disp(tot)))
        colmax[G_C] = max(colmax[G_C], len(disp(sum(gfatot[section].values()))))
        colmax[U_C] = max(colmax[U_C], len(disp(sum(leaf_val(section, lvl, *d) for lvl in sec_lv[section] for d in leaf_defs))))
        sub_rows.append(sr)
        r = sr + 2                                    # +1 blank separator row after each asset

    gr = r                                            # grand total = sum of subtotal rows
    ws.cell(gr, 1, "Grand Total").font = f_tot
    for c in range(1, NC + 1): ws.cell(gr, c).fill = GREY2
    for cc in range(LF0, NC + 1):
        t = ws.cell(gr, cc, "=" + "+".join(f"{L(cc)}{s}" for s in sub_rows))
        t.font = f_tot; t.number_format = ZERO_FMT
    for i in range(len(leaf_defs)):
        tot = sum(leaf_val(sec, lvl, *leaf_defs[i]) for sec in SECTIONS for lvl in sec_lv[sec])
        colmax[LF0 + i] = max(colmax[LF0 + i], len(disp(tot)))
    colmax[G_C] = max(colmax[G_C], len(disp(sum(sum(g.values()) for g in gfatot.values()))))
    colmax[U_C] = max(colmax[U_C], len(disp(sum(v[1] for s in data for v in data[s].values()))))

    special = set(sec_hdr_rows) | set(sub_rows) | {gr}
    blank_rows = {s + 1 for s in sub_rows if s + 1 < gr}   # separator rows stay border-free
    for rr in range(2, gr + 1):
        if rr in blank_rows: continue
        for cc in range(1, NC + 1):
            l  = "medium" if (cc in group_starts or cc == G_C or cc == 1) else "thin"
            rt = "medium" if cc == NC else "thin"
            t  = "medium" if (rr == 2 or rr in special) else "thin"
            bb = "medium" if (rr == 3 or rr in special or rr == gr) else "thin"
            ws.cell(rr, cc).border = border(l, rt, t, bb)

    ws.column_dimensions["A"].width = round(max(len(str(ws.cell(x, 1).value or "")) for x in range(4, gr + 1)) * 0.95 + 2, 2)
    ws.column_dimensions[L(B_C)].width = round(max(len(s) for s in SECTIONS) * 0.95 + 2, 2)
    for cc in range(LF0, LF1 + 1):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 4.0), 2)
    for cc in (G_C, U_C):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 12.0), 2)
    ws.row_dimensions[1].height = 30; ws.row_dimensions[2].height = 30
    ws.row_dimensions[3].height = round(max(len(leaf_label(y, k)) for (_, y, k) in leaf_defs) * 5.0 + 14, 1)
    for rr in range(4, gr + 1): ws.row_dimensions[rr].height = 15.75
    ws.freeze_panes = ws.cell(4, LF0)

def verify_combined(wb, label):
    from openpyxl.utils import column_index_from_string as CI
    ws = wb[COMBINED_SHEET]
    LF0 = 3; LF1 = 2 + len(leaf_defs); G_C = LF1 + 1
    cache = {}
    def num(r, c):
        if (r, c) in cache: return cache[(r, c)]
        v = ws.cell(r, c).value
        if isinstance(v, str) and v.startswith("="):
            m = REFPAT.match(v)
            res = num(int(m.group(2)), CI(m.group(1))) if m else 0.0
        else:
            res = float(v or 0)
        cache[(r, c)] = res
        return res
    print(f"--- {label} ---")
    bysec = defaultdict(lambda: [0.0, 0.0])
    for r in range(4, ws.max_row + 1):
        sec = ws.cell(r, 2).value                    # level rows only (B holds section)
        if sec in data:
            bysec[sec][0] += sum(num(r, c) for c in range(LF0, LF1 + 1))
            bysec[sec][1] += num(r, G_C)
    all_ok = True
    for section in SECTIONS:
        bua, gfa = bysec[section]
        rawO = sum(v[1] for v in data[section].values())
        rawN = sum(v[0] for v in data[section].values())
        ok = abs(bua - rawO) < 0.05 and abs(gfa - rawN) < 0.05
        all_ok &= ok
        print(f"  {section:22} BUA={bua:>11,.2f} vs raw {rawO:>11,.2f}  GFA={gfa:>10,.2f} vs raw {rawN:>10,.2f}  {'OK' if ok else '*** MISMATCH ***'}")
    totO = sum(v[1] for s in data for v in data[s].values())
    totN = sum(v[0] for s in data for v in data[s].values())
    sumB = sum(v[0] for v in bysec.values()); sumG = sum(v[1] for v in bysec.values())
    ok = abs(sumB - totO) < 0.5 and abs(sumG - totN) < 0.5
    all_ok &= ok
    print(f"  {'OVERALL':22} BUA={sumB:>11,.2f} vs raw {totO:>11,.2f}  GFA={sumG:>10,.2f} vs raw {totN:>10,.2f}  {'OK' if ok else '*** MISMATCH ***'}")
    return all_ok

# ------------------------------------------------------------------ re-feed DATA_SHEET
def refeed_data_sheet(wb):
    ws = wb[DATA_SHEET]
    # locate existing grand-total row (col F formula) & repeated header (next row)
    tot_r = next(r for r in range(5, ws.max_row + 1)
                 if isinstance(ws.cell(r, 6).value, str) and ws.cell(r, 6).value.startswith("=SUM("))
    rep_r = tot_r + 1
    data_style = [copy(ws.cell(5, c)._style) for c in range(1, 16)]
    hdr_style  = [copy(ws.cell(4, c)._style) for c in range(1, 16)]
    tot_style  = [copy(ws.cell(tot_r, c)._style) for c in range(1, 16)]
    rep_style  = [copy(ws.cell(rep_r, c)._style) for c in range(1, 16)]
    rep_vals   = [ws.cell(rep_r, c).value for c in range(1, 16)]
    for rr in (tot_r, rep_r):
        if rr in ws.row_dimensions: ws.row_dimensions[rr].height = None

    r = 4
    for kind, payload in body:
        if kind == "H":
            ws.cell(r, 1).value = payload
            for c in range(2, 16): ws.cell(r, c).value = None
            for c in range(1, 16): ws.cell(r, c)._style = copy(hdr_style[c - 1])
        else:
            for c in range(1, 16):
                ws.cell(r, c).value = payload[c - 1]
                ws.cell(r, c)._style = copy(data_style[c - 1])
                if 6 <= c <= 15: ws.cell(r, c).number_format = ZERO_FMT
        r += 1
    last = r - 1
    for c in range(1, 16):
        ws.cell(r, c).value = f"=SUM({L(c)}5:{L(c)}{last})" if c >= 6 else None
        ws.cell(r, c)._style = copy(tot_style[c - 1])
        if c >= 6: ws.cell(r, c).number_format = ZERO_FMT
    ws.row_dimensions[r].height = 15.75
    r += 1
    for c in range(1, 16):
        ws.cell(r, c).value = rep_vals[c - 1]
        ws.cell(r, c)._style = copy(rep_style[c - 1])
    ws.row_dimensions[r].height = 30.75
    for rr in range(r + 1, max(r + 10, tot_r + 10)):        # clear leftovers
        for c in range(1, 16): ws.cell(rr, c).value = None
        if rr in ws.row_dimensions: ws.row_dimensions[rr].height = None

# ------------------------------------------------------------------ verify
REFPAT = re.compile(r"=([A-Z]+)(\d+)$")
def verify(wb, label):
    from openpyxl.utils import column_index_from_string as CI
    print(f"--- {label} ---")
    all_ok = True
    for section in SECTIONS:
        ws = wb[section]
        R_TOT = next(r for r in range(4, ws.max_row + 1) if ws.cell(r, 1).value == "Grand Total")
        cache = {}
        def num(r, c):
            if (r, c) in cache: return cache[(r, c)]
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.startswith("="):
                m = REFPAT.match(v)
                res = num(int(m.group(2)), CI(m.group(1))) if m else 0.0
            else:
                res = float(v or 0)
            cache[(r, c)] = res
            return res
        bua = sum(num(r, c) for r in range(4, R_TOT) for c in range(2, LEAF1 + 1))
        gfa = sum(num(r, GFA_C) for r in range(4, R_TOT))
        rawO = sum(v[1] for v in data[section].values())
        rawN = sum(v[0] for v in data[section].values())
        ok = abs(bua - rawO) < 0.05 and abs(gfa - rawN) < 0.05
        all_ok &= ok
        print(f"  {section:22} rows={R_TOT-4:3}  BUA={bua:>11,.2f} vs raw {rawO:>11,.2f}  "
              f"GFA={gfa:>10,.2f} vs raw {rawN:>10,.2f}  {'OK' if ok else '*** MISMATCH ***'}")
    return all_ok

# ------------------------------------------------------------------ main
if __name__ == "__main__":
    frozen_ok = warn_new_items()
    ok, skipped = True, []
    for path, mode, label in ((OPTION1, "combined", "Option 1 (combined, all levels)"),
                              (OPTION2, "own", "Option 2 (own levels)")):
        try:
            wb = openpyxl.load_workbook(path)
            refeed_data_sheet(wb)
            if mode == "combined":
                build_combined(wb)
            else:
                for section in SECTIONS:
                    build_section(wb, section, mode)
            wb.calculation.fullCalcOnLoad = True
            wb.save(path)
        except PermissionError:
            print(f"\n*** SKIPPED {label}: file is open in Excel - close it and rerun ***\n    {path}")
            skipped.append(label); ok = False
            continue
        wb2 = openpyxl.load_workbook(path)
        ok &= verify_combined(wb2, label) if mode == "combined" else verify(wb2, label)
    if skipped:
        print(f"\n*** {', '.join(skipped)} not updated (file locked) - close in Excel and rerun ***")
    elif not frozen_ok:
        warn_new_items()                              # repeat the highlight at the end
    else:
        print("\nALL TOTALS TIE OUT - DONE" if ok else "\n*** CHECK MISMATCHES ABOVE ***")

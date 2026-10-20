"""Re-feed the raw Revit Area export into the two formatted BUA workbooks, then check every total.

The rules are update_bua_workbooks.py's (ProjectB, agreed 2026-07-02), unchanged:
  - Column C kept verbatim from raw (hyphen intact); exact-0 shows as "0".
  - FROZEN skeleton = every GFA Component x every Space/Room Category, zero-filled (identical columns
    on every reload -- other disciplines use the workbooks as a base). A new component / category is
    reported ("!!!" banner) and its area left out, never added silently.
  - Circulation / Services / Storage split into "(GFA)" / "(Non-GFA)" columns; all other categories a
    single BUA column.  GFA = col N (A+B); Non-GFA = O-N.
  - Typical floors: the raw stores ONE row already x floor count -> base floor = raw / count, member
    floors cross-reference the base.
  - Raw quirk: col C without a hyphen (e.g. 'Facade Structure') => component = category.

Workbooks (in the project folder):
  1. Option 1 "..._with All Levels_Option 1.xlsx" -- one "Overall BUA" sheet, every asset stacked like
     the raw: section row, that asset's own levels (+ typical cross-references), "<Asset> Total", blank.
  2. Option 2 "..._Raw Levels Only_Option 2.xlsx" -- one sheet per asset, its own levels.
Both get their data sheet ("260622_BUA Space Room Split") re-fed from raw, template formatting kept.
Any other sheet ("Roof Areas") is never touched.

What is new compared with the script: the typical-floor set is a profile picked to fit the raw's levels
(the model's Level set changed in 2026-09), a level the set cannot place is reported, both workbooks are
backed up before they are written, a workbook open in Excel is detected before any work, and the result
comes back as a Result the window and the command line report from.

CPython 3 + openpyxl only -- never imported inside Revit.
"""

import datetime as dt
import fnmatch
import os
import re
import shutil
import subprocess
import tempfile
from collections import OrderedDict, defaultdict
from copy import copy

import openpyxl
from openpyxl.styles import Alignment, Border, Color, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string as CI
from openpyxl.utils import get_column_letter as L

# ------------------------------------------------------------------ file names
RAW_NAME = "Excel - Raw Area from RVT- Overall With Assets For MEP Team.xlsx"
OPTION1_PATTERN = "*_with All Levels_Option 1.xlsx"
OPTION2_PATTERN = "*_Raw Levels Only_Option 2.xlsx"
OPTION1_NAME = "260702_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx"   # the script's own
OPTION2_NAME = "260702_ProjectB_Overall BUA_Space_Room Split_Raw Levels Only_Option 2.xlsx"
DATA_SHEET = "260622_BUA Space Room Split"     # template sheet that gets re-fed
DATA_SHEET_HINT = "BUA Space"                  # ... or the sheet named like it (dated copies: "261002_BUA Space ...")
BACKUP_DIR = "Backup"

# ------------------------------------------------------------------ format
ZERO_FMT = "#,##0.00;-#,##0.00;0"
FN = "Aptos Narrow"
SPLIT_CATS = {"Circulation", "Services", "Storage"}
BASEMENT_ORDER = ["Basement 04", "Basement Mezzanine", "Basement 03", "Basement 02", "Basement 01", "Ground Floor"]
MAX_FLOOR = 99                  # ordinal-name scan ceiling ("01st Floor" .. "99th Floor")

# ---------------------------------------------------------- FROZEN format
# The column skeleton is FROZEN so other disciplines can rely on fixed cell positions. If a raw export
# ever contains a NEW component or category, it is NOT added silently -- it is reported (and totals
# mismatch). To accept a new item, add it here by hand (keep alphabetical, case-insensitive) and
# inform the other disciplines.
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

# ---------------------------------------------------------- typical floors
# base floor -> (first, last, floor count). The raw stores the base floor's row already x count.
# "2026-09": the live model's Level set since 2026-09-11 -- 22nd / 28th-36th / 67th-71st no longer
#            exist as Levels; "27th to 36th Floor" is one combined-range Level, read as "27th Floor".
# "2026-07": the Level set of the July 2026 exports (and of the 260702 workbooks).
PROFILES = OrderedDict([
    ("2026-09", {"label": "07-20 / 21-22 / 27-36 / 66-71 (model Levels since 2026-09)",
                 "typical": OrderedDict([("07th Floor", (7, 20, 14)), ("21st Floor", (21, 22, 2)),
                                         ("27th Floor", (27, 36, 10)), ("66th Floor", (66, 71, 6))]),
                 "aliases": {"27th to 36th Floor": "27th Floor"}}),
    ("2026-07", {"label": "07-20 / 26-36 / 65-72 (model Levels of July 2026)",
                 "typical": OrderedDict([("07th Floor", (7, 20, 14)), ("26th Floor", (26, 36, 11)),
                                         ("65th Floor", (65, 72, 8))]),
                 "aliases": {}}),
])
AUTO = "auto"

REFPAT = re.compile(r"=([A-Z]+)(\d+)$")
DONE_LINE = "ALL TOTALS TIE OUT - DONE"
MISMATCH = "*** MISMATCH ***"

# status -> command-line exit code
EXIT = {"done": 0, "mismatch": 1, "new_items": 2, "skipped": 3, "error": 4, "checked": 0}


class UpdateError(Exception):
    """Something wrong with the files themselves -- shown to the user as-is."""


# ------------------------------------------------------------------ helpers
def split_ac(v):
    return v.split("-", 1) if "-" in v else (v, v)


def SORT(seq):
    return sorted(seq, key=lambda s: s.lower())


def disp(v):
    return "0" if abs(v) < 0.005 else "{:,.2f}".format(v)


def ordinal(n):
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%02d%s Floor" % (n, suf)


def leaf_label(y, kind):
    return "%s (GFA)" % y if kind == "GFA" else ("%s (Non-GFA)" % y if kind == "NonGFA" else y)


def copy_to_temp(path):
    """Copy to temp first -- the raw is often open (locked) in Excel. Excel's lock can block Python
    reads; PowerShell Copy-Item still works."""
    if not os.path.isfile(path):
        raise UpdateError("Raw file not found: %s" % path)
    fd, tmp = tempfile.mkstemp(prefix="_bua_raw_copy_", suffix=".xlsx")
    os.close(fd)
    try:
        shutil.copyfile(path, tmp)
    except PermissionError:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Copy-Item -LiteralPath "%s" -Destination "%s" -Force' % (path, tmp)],
            capture_output=True, text=True)
        if res.returncode != 0 or not os.path.getsize(tmp):
            raise UpdateError("Cannot read the raw file (locked?): %s\n%s" % (path, res.stderr))
    return tmp


def read_raw(path):
    """Raw rows from row 4 down: [(row number, [15 cell values])]."""
    tmp = copy_to_temp(path)
    try:
        try:
            ws = openpyxl.load_workbook(tmp).active
        except Exception as e:  # not an .xlsx, damaged, ...
            raise UpdateError("Cannot open the raw file as a workbook: %s (%s)" % (path, e))
        return [(r, [ws.cell(r, c).value for c in range(1, 16)]) for r in range(4, ws.max_row + 1)]
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ------------------------------------------------------------------ parsed raw
class Model(object):
    """The raw export parsed for one typical-floor profile."""

    def __init__(self, rows, profile_key):
        self.profile_key = profile_key
        self.profile = PROFILES[profile_key]
        self.TYPICAL = self.profile["typical"]
        aliases = self.profile["aliases"]
        self.assets, self.cats = OrderedDict(), OrderedDict()
        self.SECTIONS, self.body = [], []                            # body: for the data-sheet re-feed
        self.data = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # sec -> (lvl,a,y) -> [N,O]
        self.gfatot = defaultdict(lambda: defaultdict(float))
        self.sec_lv = defaultdict(set)
        self.present = set()
        self.unmapped = []                                           # raw rows outside the frozen lists
        cur = None
        n_data = 0
        for r, vals in rows:
            a = vals[0]
            a = aliases.get(a, a)
            rest = vals[1:15]
            if a in (None, "") and not [x for x in rest if x not in (None, "")]:
                continue
            if not [x for x in rest if x not in (None, "")]:      # section header row
                cur = a
                if a not in self.SECTIONS:
                    self.SECTIONS.append(a)
                self.body.append(("H", a))
                continue
            n_data += 1
            self.body.append(("D", list(vals)))
            cval = vals[2]
            if not (isinstance(cval, str) and cval.strip()):
                continue
            if cur is None:
                raise UpdateError("Raw row %d has data before the first section row (asset name alone in "
                                  "column A) -- is this the raw Revit Area export?" % r)
            asset, cat = split_ac(cval)
            self.assets[asset] = self.cats[cat] = True
            N = vals[13] or 0
            O = vals[14] or 0
            d = self.data[cur][(a, asset, cat)]
            d[0] += N
            d[1] += O
            self.gfatot[cur][a] += N
            self.present.add(a)
            self.sec_lv[cur].add(a)
            if asset not in FROZEN_COMPONENTS or cat not in FROZEN_CATS:
                self.unmapped.append((r, cur, a, cval, O, N))
        if not n_data or not self.present:
            raise UpdateError("No data rows below row 3 -- is this the raw Revit Area export?")

        self.ASSETS, self.CATS = list(FROZEN_COMPONENTS), list(FROZEN_CATS)
        self.NEW_COMPONENTS = SORT(set(self.assets) - set(FROZEN_COMPONENTS))
        self.NEW_CATS = SORT(set(self.cats) - set(FROZEN_CATS))
        self.UNMAPPED_BUA = sum(v[1] for s in self.data for (l, a, y), v in self.data[s].items()
                                if a not in FROZEN_COMPONENTS or y not in FROZEN_CATS)

        self.leaf_defs = []
        for a in self.ASSETS:
            for y in self.CATS:
                if y in SPLIT_CATS:
                    self.leaf_defs += [(a, y, "GFA"), (a, y, "NonGFA")]
                else:
                    self.leaf_defs.append((a, y, "BUA"))

        self.typ_member = {}
        for base, (s, e, fc) in self.TYPICAL.items():
            for n in range(s, e + 1):
                if ordinal(n) != base:
                    self.typ_member[ordinal(n)] = base
        self.global_order = [l for l in BASEMENT_ORDER if l in self.present]
        for n in range(1, MAX_FLOOR + 1):
            fn = ordinal(n)
            if fn in self.present or fn in self.typ_member:
                self.global_order.append(fn)

        self.LEAF0 = 2
        self.LEAF1 = 1 + len(self.leaf_defs)
        self.GFA_C = self.LEAF1 + 1
        self.BUA_C = self.LEAF1 + 2
        self.NCOLS = self.BUA_C

    # ---------------------------------------------------------- checks
    def leaf_val(self, sec, lvl, a, y, kind):
        N, O = self.data[sec].get((lvl, a, y), (0.0, 0.0))
        return N if kind == "GFA" else (O - N if kind == "NonGFA" else O)

    def level_bua(self, sec, lvl):
        return sum(v[1] for (l, a, y), v in self.data[sec].items() if l == lvl)

    def level_conflicts(self):
        """Levels whose area this profile would leave out: a typical-floor member that has its own rows
        (its rows are replaced by a reference to the base floor), or a name the level order cannot place.
        [(section, level, BUA, reason)]"""
        out = []
        for sec in self.SECTIONS:
            for lvl in sorted(self.sec_lv[sec], key=lambda x: (self.global_order.index(x)
                                                               if x in self.global_order else 999, x)):
                if lvl in self.typ_member:
                    out.append((sec, lvl, self.level_bua(sec, lvl),
                                "has its own rows, but is a typical copy of %s here" % self.typ_member[lvl]))
                elif lvl not in self.global_order:
                    out.append((sec, lvl, self.level_bua(sec, lvl), "is not a level name this order can place"))
        return out

    def bases_present(self):
        return [b for b in self.TYPICAL if b in self.present]

    def raw_totals(self):
        return (sum(v[1] for s in self.data for v in self.data[s].values()),
                sum(v[0] for s in self.data for v in self.data[s].values()))


def choose_profile(rows, key=AUTO):
    """(Model, why). 'auto': the profile that leaves no level out, then the one whose typical base
    floors are all in the raw, then the newer one."""
    if key != AUTO:
        if key not in PROFILES:
            raise UpdateError("Unknown typical-floor set %r (choose %s)" % (key, ", ".join([AUTO] + list(PROFILES))))
        return Model(rows, key), "chosen"
    scored = []
    for i, k in enumerate(PROFILES):
        m = Model(rows, k)
        scored.append(((len(m.level_conflicts()), -len(m.bases_present()) / float(len(m.TYPICAL)), i), m))
    scored.sort(key=lambda x: x[0])
    best = scored[0][1]
    n_conf = scored[0][0][0]
    if n_conf:
        why = "auto: no set fits every level -- the closest one"
    else:
        why = "auto: fits every level of the raw (%d of %d typical base floors present)" % (
            len(best.bases_present()), len(best.TYPICAL))
    return best, why


# ------------------------------------------------------------------ styles
BLK = Color(theme=1)
GREY = PatternFill("solid", fgColor=Color(theme=0, tint=-0.15))
GREY2 = PatternFill("solid", fgColor=Color(theme=0, tint=-0.25))
f_title, f_hdr = Font(name=FN, sz=20, bold=True, italic=True, color=BLK), Font(name=FN, sz=11, bold=True, italic=True, color=BLK)
f_asset, f_leaf = Font(name=FN, sz=11, bold=True, color=BLK), Font(name=FN, sz=9, italic=True, color=BLK)
f_data, f_tot = Font(name=FN, sz=11, color=BLK), Font(name=FN, sz=11, bold=True, color=BLK)
a_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
a_leaf = Alignment(horizontal="center", vertical="bottom", text_rotation=90)
thin, med = Side("thin"), Side("medium")
_bc = {}


def border(l="thin", r="thin", t="thin", b="thin"):
    k = (l, r, t, b)
    if k not in _bc:
        s = {"thin": thin, "medium": med}
        _bc[k] = Border(left=s[l], right=s[r], top=s[t], bottom=s[b])
    return _bc[k]


# ------------------------------------------------------------------ Option 2: one sheet per asset
def build_section(wb, m, section):
    """One asset's sheet: its own levels (+ typical cross-references where the base floor has data)."""
    TYPICAL, typ_member, sec_lv, gfatot, leaf_defs = m.TYPICAL, m.typ_member, m.sec_lv, m.gfatot, m.leaf_defs
    LEAF0, LEAF1, GFA_C, BUA_C, NCOLS = m.LEAF0, m.LEAF1, m.GFA_C, m.BUA_C, m.NCOLS
    master = [l for l in m.global_order
              if l in sec_lv[section] or (l in typ_member and typ_member[l] in sec_lv[section])]
    if section in wb.sheetnames:
        del wb[section]
    ws = wb.create_sheet(section)
    R_D0 = 4
    R_TOT = R_D0 + len(master)
    base_row = {b: R_D0 + master.index(b) for b in TYPICAL if b in master}

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=NCOLS)
    tc = ws.cell(1, 1, "ProjectB - %s - BUA by Asset / Category" % section)
    tc.font = f_title
    tc.alignment = Alignment(vertical="center")
    tc.border = border(b="medium")
    ws.merge_cells(start_row=2, start_column=1, end_row=3, end_column=1)
    c = ws.cell(2, 1, "Level")
    c.font = f_hdr
    c.fill = GREY
    c.alignment = a_center
    for cc, txt in ((GFA_C, "Gross Floor Area (GFA) (A+B) SQM"), (BUA_C, "Built Up Area (A+B+C+D+E+F+G+H) SQM")):
        ws.merge_cells(start_row=2, start_column=cc, end_row=3, end_column=cc)
        c = ws.cell(2, cc, txt)
        c.font = f_hdr
        c.fill = GREY
        c.alignment = a_center

    group_starts = set()
    for i, (a, y, kind) in enumerate(leaf_defs):
        lc = ws.cell(3, LEAF0 + i, leaf_label(y, kind))
        lc.font = f_leaf
        lc.fill = GREY
        lc.alignment = a_leaf
    for a in m.ASSETS:
        idxs = [LEAF0 + i for i, (aa, _, _) in enumerate(leaf_defs) if aa == a]
        s, e = idxs[0], idxs[-1]
        group_starts.add(s)
        if e > s:
            ws.merge_cells(start_row=2, start_column=s, end_row=2, end_column=e)
        ac = ws.cell(2, s, a)
        ac.font = f_asset
        ac.fill = GREY2
        ac.alignment = a_center

    colmax = {c: 1 for c in range(LEAF0, NCOLS + 1)}
    for ri, lvl in enumerate(master):
        r = R_D0 + ri
        lc = ws.cell(r, 1, lvl)
        lc.font = f_data
        lc.alignment = Alignment(vertical="center")
        base = typ_member.get(lvl)
        is_base = lvl in TYPICAL
        member_ref = base is not None and base in base_row and base in sec_lv[section]
        fc = TYPICAL[lvl][2] if is_base else 1
        rowsum = 0.0
        for i, (a, y, kind) in enumerate(leaf_defs):
            cc = LEAF0 + i
            if base is not None:
                num = m.leaf_val(section, base, a, y, kind) / TYPICAL[base][2] if member_ref else 0.0
                v = "=%s%d" % (L(cc), base_row[base]) if member_ref else 0
            elif is_base:
                num = v = m.leaf_val(section, lvl, a, y, kind) / fc
            else:
                num = v = round(m.leaf_val(section, lvl, a, y, kind), 2)
            rowsum += num
            cell = ws.cell(r, cc, v)
            cell.font = f_data
            cell.number_format = ZERO_FMT
            colmax[cc] = max(colmax[cc], len(disp(num)))
        if base is not None:
            gnum = gfatot[section].get(base, 0) / TYPICAL[base][2] if member_ref else 0.0
            gv = "=%s%d" % (L(GFA_C), base_row[base]) if member_ref else 0
        elif is_base:
            gnum = gv = gfatot[section].get(lvl, 0) / fc
        else:
            gnum = gv = round(gfatot[section].get(lvl, 0), 2)
        gc = ws.cell(r, GFA_C, gv)
        gc.font = f_data
        gc.number_format = ZERO_FMT
        colmax[GFA_C] = max(colmax[GFA_C], len(disp(gnum)))
        bv = "=%s%d" % (L(BUA_C), base_row[base]) if member_ref else "=SUM(%s%d:%s%d)" % (L(LEAF0), r, L(LEAF1), r)
        bc = ws.cell(r, BUA_C, bv)
        bc.font = f_data
        bc.number_format = ZERO_FMT
        colmax[BUA_C] = max(colmax[BUA_C], len(disp(rowsum)))

    tcell = ws.cell(R_TOT, 1, "Grand Total")
    tcell.font = f_tot
    tcell.fill = GREY
    for cc in range(LEAF0, NCOLS + 1):
        t = ws.cell(R_TOT, cc, "=SUM(%s%d:%s%d)" % (L(cc), R_D0, L(cc), R_TOT - 1))
        t.font = f_tot
        t.fill = GREY
        t.number_format = ZERO_FMT
    for i in range(len(leaf_defs)):                        # widths incl. grand totals
        tot = sum(m.leaf_val(section, lvl, *leaf_defs[i]) for lvl in sec_lv[section])
        colmax[LEAF0 + i] = max(colmax[LEAF0 + i], len(disp(tot)))
    colmax[GFA_C] = max(colmax[GFA_C], len(disp(sum(gfatot[section].values()))))
    colmax[BUA_C] = max(colmax[BUA_C], len(disp(sum(m.leaf_val(section, lvl, *d)
                                                    for lvl in sec_lv[section] for d in leaf_defs))))

    for r in range(2, R_TOT + 1):
        for cc in range(1, NCOLS + 1):
            l = "medium" if (cc in group_starts or cc == GFA_C or cc == 1) else "thin"
            rr = "medium" if cc == NCOLS else "thin"
            t = "medium" if r in (2, R_TOT) else "thin"
            bb = "medium" if r in (3, R_TOT) else "thin"
            ws.cell(r, cc).border = border(l, rr, t, bb)

    lvl_len = max(len(str(ws.cell(r, 1).value or "")) for r in range(R_D0, R_TOT + 1))
    ws.column_dimensions["A"].width = round(lvl_len * 0.95 + 2, 2)
    for cc in range(LEAF0, LEAF1 + 1):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 4.0), 2)
    for cc in (GFA_C, BUA_C):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 12.0), 2)
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 30
    ws.row_dimensions[3].height = round(max(len(leaf_label(y, k)) for (_, y, k) in leaf_defs) * 5.0 + 14, 1)
    for r in range(R_D0, R_TOT + 1):
        ws.row_dimensions[r].height = 15.75
    ws.freeze_panes = ws.cell(R_D0, LEAF0)


# ------------------------------------------------------------------ Option 1: combined sheet
COMBINED_SHEET = "Overall BUA"


def build_combined(wb, m):
    """One continuous sheet -- all sections stacked like the raw layout. Col A = Level, col B = Building
    Asset (section); a section-header row starts each block; each block shows that asset's own levels;
    a '<Section> Total' subtotal row (grand-total style) closes each block, a blank row follows; Grand
    Total row at the very end. Terminology: sections = assets, former assets = GFA Components,
    categories = Space/Room Category. Returns the Grand Total row."""
    TYPICAL, typ_member, sec_lv, gfatot, leaf_defs, data = (m.TYPICAL, m.typ_member, m.sec_lv, m.gfatot,
                                                            m.leaf_defs, m.data)
    for s in m.SECTIONS:
        if s in wb.sheetnames:
            del wb[s]
    if COMBINED_SHEET in wb.sheetnames:
        del wb[COMBINED_SHEET]
    ws = wb.create_sheet(COMBINED_SHEET)
    B_C = 2
    LF0 = 3
    LF1 = 2 + len(leaf_defs)
    G_C = LF1 + 1
    U_C = LF1 + 2
    NC = U_C

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=NC)
    tc = ws.cell(1, 1, "ProjectB - Overall BUA - Asset / GFA Component / Space-Room Category")
    tc.font = f_title
    tc.alignment = Alignment(vertical="center")
    tc.border = border(b="medium")
    for col, txt in ((1, "Level"), (B_C, "Building Asset")):
        ws.merge_cells(start_row=2, start_column=col, end_row=3, end_column=col)
        c = ws.cell(2, col, txt)
        c.font = f_hdr
        c.fill = GREY
        c.alignment = a_center
    for cc, txt in ((G_C, "Gross Floor Area (GFA) (A+B) SQM"), (U_C, "Built Up Area (A+B+C+D+E+F+G+H) SQM")):
        ws.merge_cells(start_row=2, start_column=cc, end_row=3, end_column=cc)
        c = ws.cell(2, cc, txt)
        c.font = f_hdr
        c.fill = GREY
        c.alignment = a_center
    group_starts = set()
    for i, (a, y, kind) in enumerate(leaf_defs):
        lc = ws.cell(3, LF0 + i, leaf_label(y, kind))
        lc.font = f_leaf
        lc.fill = GREY
        lc.alignment = a_leaf
    for a in m.ASSETS:
        idxs = [LF0 + i for i, (aa, _, _) in enumerate(leaf_defs) if aa == a]
        s, e = idxs[0], idxs[-1]
        group_starts.add(s)
        if e > s:
            ws.merge_cells(start_row=2, start_column=s, end_row=2, end_column=e)
        ac = ws.cell(2, s, a)
        ac.font = f_asset
        ac.fill = GREY2
        ac.alignment = a_center

    colmax = {c: 1 for c in range(LF0, NC + 1)}
    sec_hdr_rows, sub_rows = [], []
    r = 4
    for section in m.SECTIONS:
        # section-start row (like raw A4/A33/...)
        ws.cell(r, 1, section).font = f_asset
        for c in range(1, NC + 1):
            ws.cell(r, c).fill = GREY
        sec_hdr_rows.append(r)
        r += 1
        b0 = r
        # levels like the raw: only this section's own levels (+ typical expansion rows where the base
        # floor has data here)
        block_levels = [l for l in m.global_order
                        if l in sec_lv[section] or (l in typ_member and typ_member[l] in sec_lv[section])]
        base_row = {b: b0 + block_levels.index(b) for b in TYPICAL if b in block_levels}
        for ri, lvl in enumerate(block_levels):
            rr = b0 + ri
            ws.cell(rr, 1, lvl).font = f_data
            ws.cell(rr, B_C, section).font = f_data
            base = typ_member.get(lvl)
            is_base = lvl in TYPICAL
            member_ref = base is not None and base in sec_lv[section]
            fc = TYPICAL[lvl][2] if is_base else 1
            rowsum = 0.0
            for i, (a, y, kind) in enumerate(leaf_defs):
                cc = LF0 + i
                if base is not None:
                    num = m.leaf_val(section, base, a, y, kind) / TYPICAL[base][2] if member_ref else 0.0
                    v = "=%s%d" % (L(cc), base_row[base]) if member_ref else 0
                elif is_base:
                    num = v = m.leaf_val(section, lvl, a, y, kind) / fc
                else:
                    num = v = round(m.leaf_val(section, lvl, a, y, kind), 2)
                rowsum += num
                cell = ws.cell(rr, cc, v)
                cell.font = f_data
                cell.number_format = ZERO_FMT
                colmax[cc] = max(colmax[cc], len(disp(num)))
            if base is not None:
                gnum = gfatot[section].get(base, 0) / TYPICAL[base][2] if member_ref else 0.0
                gv = "=%s%d" % (L(G_C), base_row[base]) if member_ref else 0
            elif is_base:
                gnum = gv = gfatot[section].get(lvl, 0) / fc
            else:
                gnum = gv = round(gfatot[section].get(lvl, 0), 2)
            gc = ws.cell(rr, G_C, gv)
            gc.font = f_data
            gc.number_format = ZERO_FMT
            colmax[G_C] = max(colmax[G_C], len(disp(gnum)))
            bv = "=%s%d" % (L(U_C), base_row[base]) if member_ref else "=SUM(%s%d:%s%d)" % (L(LF0), rr, L(LF1), rr)
            bc = ws.cell(rr, U_C, bv)
            bc.font = f_data
            bc.number_format = ZERO_FMT
            colmax[U_C] = max(colmax[U_C], len(disp(rowsum)))
        b1 = b0 + len(block_levels) - 1
        sr = b1 + 1                                   # subtotal row (grand-total style)
        ws.cell(sr, 1, "%s Total" % section).font = f_tot
        for c in range(1, NC + 1):
            ws.cell(sr, c).fill = GREY
        for cc in range(LF0, NC + 1):
            t = ws.cell(sr, cc, "=SUM(%s%d:%s%d)" % (L(cc), b0, L(cc), b1))
            t.font = f_tot
            t.number_format = ZERO_FMT
        # widths incl. section totals
        for i in range(len(leaf_defs)):
            tot = sum(m.leaf_val(section, lvl, *leaf_defs[i]) for lvl in sec_lv[section])
            colmax[LF0 + i] = max(colmax[LF0 + i], len(disp(tot)))
        colmax[G_C] = max(colmax[G_C], len(disp(sum(gfatot[section].values()))))
        colmax[U_C] = max(colmax[U_C], len(disp(sum(m.leaf_val(section, lvl, *d)
                                                    for lvl in sec_lv[section] for d in leaf_defs))))
        sub_rows.append(sr)
        r = sr + 2                                    # +1 blank separator row after each asset

    gr = r                                            # grand total = sum of subtotal rows
    ws.cell(gr, 1, "Grand Total").font = f_tot
    for c in range(1, NC + 1):
        ws.cell(gr, c).fill = GREY2
    for cc in range(LF0, NC + 1):
        t = ws.cell(gr, cc, "=" + "+".join("%s%d" % (L(cc), s) for s in sub_rows))
        t.font = f_tot
        t.number_format = ZERO_FMT
    for i in range(len(leaf_defs)):
        tot = sum(m.leaf_val(sec, lvl, *leaf_defs[i]) for sec in m.SECTIONS for lvl in sec_lv[sec])
        colmax[LF0 + i] = max(colmax[LF0 + i], len(disp(tot)))
    colmax[G_C] = max(colmax[G_C], len(disp(sum(sum(g.values()) for g in gfatot.values()))))
    colmax[U_C] = max(colmax[U_C], len(disp(sum(v[1] for s in data for v in data[s].values()))))

    special = set(sec_hdr_rows) | set(sub_rows) | {gr}
    blank_rows = {s + 1 for s in sub_rows if s + 1 < gr}   # separator rows stay border-free
    for rr in range(2, gr + 1):
        if rr in blank_rows:
            continue
        for cc in range(1, NC + 1):
            l = "medium" if (cc in group_starts or cc == G_C or cc == 1) else "thin"
            rt = "medium" if cc == NC else "thin"
            t = "medium" if (rr == 2 or rr in special) else "thin"
            bb = "medium" if (rr == 3 or rr in special or rr == gr) else "thin"
            ws.cell(rr, cc).border = border(l, rt, t, bb)

    ws.column_dimensions["A"].width = round(max(len(str(ws.cell(x, 1).value or "")) for x in range(4, gr + 1)) * 0.95 + 2, 2)
    ws.column_dimensions[L(B_C)].width = round(max(len(s) for s in m.SECTIONS) * 0.95 + 2, 2)
    for cc in range(LF0, LF1 + 1):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 4.0), 2)
    for cc in (G_C, U_C):
        ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 12.0), 2)
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 30
    ws.row_dimensions[3].height = round(max(len(leaf_label(y, k)) for (_, y, k) in leaf_defs) * 5.0 + 14, 1)
    for rr in range(4, gr + 1):
        ws.row_dimensions[rr].height = 15.75
    ws.freeze_panes = ws.cell(4, LF0)
    return gr


# ------------------------------------------------------------------ verify
def _resolver(ws):
    """Cell value as a number, following '=A12' cross-references (cached)."""
    cache = {}

    def num(r, c):
        if (r, c) in cache:
            return cache[(r, c)]
        v = ws.cell(r, c).value
        if isinstance(v, str) and v.startswith("="):
            mt = REFPAT.match(v)
            res = num(int(mt.group(2)), CI(mt.group(1))) if mt else 0.0
        else:
            res = float(v or 0)
        cache[(r, c)] = res
        return res
    return num


def _line(name, bua, raw_o, gfa, raw_n, ok, rows=None):
    return "  %-22s %sBUA=%11s vs raw %11s  GFA=%10s vs raw %10s  %s" % (
        name, ("rows=%3d  " % rows) if rows is not None else "", "{:,.2f}".format(bua), "{:,.2f}".format(raw_o),
        "{:,.2f}".format(gfa), "{:,.2f}".format(raw_n), "OK" if ok else MISMATCH)


def verify_combined(wb, m, log):
    """Option 1: per asset + overall BUA / GFA from the sheet's level rows vs raw. (ok, totals)"""
    ws = wb[COMBINED_SHEET]
    LF0 = 3
    LF1 = 2 + len(m.leaf_defs)
    G_C = LF1 + 1
    num = _resolver(ws)
    bysec = defaultdict(lambda: [0.0, 0.0])
    for r in range(4, ws.max_row + 1):
        sec = ws.cell(r, 2).value                    # level rows only (B holds section)
        if sec in m.data:
            bysec[sec][0] += sum(num(r, c) for c in range(LF0, LF1 + 1))
            bysec[sec][1] += num(r, G_C)
    all_ok = True
    for section in m.SECTIONS:
        bua, gfa = bysec[section]
        rawO = sum(v[1] for v in m.data[section].values())
        rawN = sum(v[0] for v in m.data[section].values())
        ok = abs(bua - rawO) < 0.05 and abs(gfa - rawN) < 0.05
        all_ok &= ok
        log(_line(section, bua, rawO, gfa, rawN, ok), "ok" if ok else "fail")
    totO, totN = m.raw_totals()
    sumB = sum(v[0] for v in bysec.values())
    sumG = sum(v[1] for v in bysec.values())
    ok = abs(sumB - totO) < 0.5 and abs(sumG - totN) < 0.5
    all_ok &= ok
    log(_line("OVERALL", sumB, totO, sumG, totN, ok), "ok" if ok else "fail")
    return all_ok, {"bua": sumB, "gfa": sumG, "raw_bua": totO, "raw_gfa": totN}


def verify_sections(wb, m, log):
    """Option 2: each asset sheet's level rows vs raw, then the overall. (ok, totals, {asset: rows})"""
    all_ok = True
    sumB = sumG = 0.0
    rows = OrderedDict()
    for section in m.SECTIONS:
        ws = wb[section]
        R_TOT = next(r for r in range(4, ws.max_row + 1) if ws.cell(r, 1).value == "Grand Total")
        num = _resolver(ws)
        bua = sum(num(r, c) for r in range(4, R_TOT) for c in range(2, m.LEAF1 + 1))
        gfa = sum(num(r, m.GFA_C) for r in range(4, R_TOT))
        rawO = sum(v[1] for v in m.data[section].values())
        rawN = sum(v[0] for v in m.data[section].values())
        ok = abs(bua - rawO) < 0.05 and abs(gfa - rawN) < 0.05
        all_ok &= ok
        sumB += bua
        sumG += gfa
        rows[section] = R_TOT - 4
        log(_line(section, bua, rawO, gfa, rawN, ok, R_TOT - 4), "ok" if ok else "fail")
    totO, totN = m.raw_totals()
    ok = abs(sumB - totO) < 0.5 and abs(sumG - totN) < 0.5
    all_ok &= ok
    log(_line("OVERALL", sumB, totO, sumG, totN, ok, sum(rows.values())), "ok" if ok else "fail")
    return all_ok, {"bua": sumB, "gfa": sumG, "raw_bua": totO, "raw_gfa": totN}, rows


# ------------------------------------------------------------------ re-feed the data sheet
def find_data_sheet(wb):
    """The script's DATA_SHEET, else the one sheet named like it (e.g. '261002_BUA Space Room Split')."""
    if DATA_SHEET in wb.sheetnames:
        return DATA_SHEET
    like = [n for n in wb.sheetnames if DATA_SHEET_HINT.lower() in n.lower()]
    if not like:
        raise UpdateError("No data sheet: neither %r nor a sheet named '...%s...' (sheets: %s)"
                          % (DATA_SHEET, DATA_SHEET_HINT, ", ".join(wb.sheetnames)))
    return like[0]


def refeed_data_sheet(wb, m, name):
    ws = wb[name]
    # locate existing grand-total row (col F formula) & repeated header (next row)
    try:
        tot_r = next(r for r in range(5, ws.max_row + 1)
                     if isinstance(ws.cell(r, 6).value, str) and ws.cell(r, 6).value.startswith("=SUM("))
    except StopIteration:
        raise UpdateError("Sheet %r has no total row (=SUM(...) in column F) -- is it the template data sheet?" % name)
    rep_r = tot_r + 1
    data_style = [copy(ws.cell(5, c)._style) for c in range(1, 16)]
    hdr_style = [copy(ws.cell(4, c)._style) for c in range(1, 16)]
    tot_style = [copy(ws.cell(tot_r, c)._style) for c in range(1, 16)]
    rep_style = [copy(ws.cell(rep_r, c)._style) for c in range(1, 16)]
    rep_vals = [ws.cell(rep_r, c).value for c in range(1, 16)]
    for rr in (tot_r, rep_r):
        if rr in ws.row_dimensions:
            ws.row_dimensions[rr].height = None

    r = 4
    for kind, payload in m.body:
        if kind == "H":
            ws.cell(r, 1).value = payload
            for c in range(2, 16):
                ws.cell(r, c).value = None
            for c in range(1, 16):
                ws.cell(r, c)._style = copy(hdr_style[c - 1])
        else:
            for c in range(1, 16):
                ws.cell(r, c).value = payload[c - 1]
                ws.cell(r, c)._style = copy(data_style[c - 1])
                if 6 <= c <= 15:
                    ws.cell(r, c).number_format = ZERO_FMT
        r += 1
    last = r - 1
    for c in range(1, 16):
        ws.cell(r, c).value = "=SUM(%s5:%s%d)" % (L(c), L(c), last) if c >= 6 else None
        ws.cell(r, c)._style = copy(tot_style[c - 1])
        if c >= 6:
            ws.cell(r, c).number_format = ZERO_FMT
    ws.row_dimensions[r].height = 15.75
    r += 1
    for c in range(1, 16):
        ws.cell(r, c).value = rep_vals[c - 1]
        ws.cell(r, c)._style = copy(rep_style[c - 1])
    ws.row_dimensions[r].height = 30.75
    for rr in range(r + 1, max(r + 10, tot_r + 10)):        # clear leftovers
        for c in range(1, 16):
            ws.cell(rr, c).value = None
        if rr in ws.row_dimensions:
            ws.row_dimensions[rr].height = None


# ------------------------------------------------------------------ files
def _pick(folder, pattern, script_name, what):
    if not os.path.isdir(folder):
        raise UpdateError("Folder not found: %s" % folder)
    found = sorted(n for n in os.listdir(folder)
                   if fnmatch.fnmatch(n.lower(), pattern.lower()) and not n.startswith("~$"))
    if script_name in found:
        return os.path.join(folder, script_name)
    if len(found) == 1:
        return os.path.join(folder, found[0])
    if not found:
        raise UpdateError("No %s workbook ('%s') in %s" % (what, pattern, folder))
    raise UpdateError("More than one %s workbook in %s -- pick one:\n  %s" % (what, folder, "\n  ".join(found)))


def find_files(folder, raw=None, option1=None, option2=None):
    """{'raw', 'option1', 'option2'}: given paths, else the names the script uses, else the one file in
    the folder matching '*_with All Levels_Option 1.xlsx' / '*_Raw Levels Only_Option 2.xlsx'."""
    folder = os.path.abspath(folder or ".")
    out = {"raw": os.path.abspath(raw) if raw else os.path.join(folder, RAW_NAME),
           "option1": os.path.abspath(option1) if option1 else _pick(folder, OPTION1_PATTERN, OPTION1_NAME, "Option 1"),
           "option2": os.path.abspath(option2) if option2 else _pick(folder, OPTION2_PATTERN, OPTION2_NAME, "Option 2")}
    for k in ("raw", "option1", "option2"):
        if not os.path.isfile(out[k]):
            raise UpdateError("%s not found: %s" % ({"raw": "Raw export", "option1": "Option 1 workbook",
                                                     "option2": "Option 2 workbook"}[k], out[k]))
    if len(set(os.path.normcase(p) for p in out.values())) < 3:
        raise UpdateError("The raw export and the two workbooks must be three different files.")
    return out


def check_writable(path):
    """PermissionError when Excel (or anything) holds the file open -- found before any work is done."""
    with open(path, "r+b"):
        pass


def backup(paths, folder, stamp):
    """Copy the workbooks to <folder>/Backup/<stamp>/ before they are overwritten. Returns that folder."""
    dest = os.path.join(folder, BACKUP_DIR, stamp)
    os.makedirs(dest, exist_ok=True)
    for p in paths:
        shutil.copy2(p, os.path.join(dest, os.path.basename(p)))
    return dest


# ------------------------------------------------------------------ result
class Result(object):
    """What one run found. status: done | new_items | mismatch | skipped | error | checked."""

    def __init__(self):
        self.status = "error"
        self.files = {}
        self.profile = None
        self.profile_why = ""
        self.sections = []
        self.new_components, self.new_cats, self.excluded_bua, self.unmapped_rows = [], [], 0.0, []
        self.level_conflicts = []
        self.skipped = []            # [(label, path)]
        self.updated = []            # [(label, path)]
        self.totals = {}             # Option 1 overall: bua, gfa, raw_bua, raw_gfa
        self.option1_rows = 0        # rows of the 'Overall BUA' sheet (to the Grand Total row)
        self.option2_rows = {}       # asset -> level rows
        self.backup_dir = None
        self.error = ""
        self.lines = []

    @property
    def exit_code(self):
        return EXIT[self.status]

    def summary(self):
        """One line for a status bar."""
        if self.status == "done":
            return "%s -- overall BUA %s SQM, GFA %s SQM" % (DONE_LINE, disp(self.totals["bua"]),
                                                              disp(self.totals["gfa"]))
        if self.status == "new_items":
            return "NEW items not in the frozen format -- %s SQM BUA excluded: %s" % (
                disp(self.excluded_bua), ", ".join(self.new_components + self.new_cats))
        if self.status == "skipped":
            return "SKIPPED -- close in Excel, then run again: %s" % ", ".join(
                os.path.basename(p) for _, p in self.skipped)
        if self.status == "mismatch":
            return "*** MISMATCH *** -- totals do not tie out (see the checks)"
        if self.status == "checked":
            return "Check only -- nothing written. Raw OK for the frozen format." if not (
                self.new_components or self.new_cats or self.level_conflicts) else \
                "Check only -- nothing written. See the warnings."
        return "ERROR -- %s" % self.error


def new_items_banner(m, where="below"):
    bar = "!" * 78
    lines = [bar, "!!!  NEW ITEMS IN RAW THAT ARE *NOT* IN THE FROZEN FORMAT  !!!"]
    if m.NEW_COMPONENTS:
        lines.append("!!!  New GFA Components : %s" % ", ".join(m.NEW_COMPONENTS))
    if m.NEW_CATS:
        lines.append("!!!  New Space/Room Cats: %s" % (", ".join(m.NEW_CATS) or "(blank category)"))
    lines += ["!!!  Their area ({:,.2f} SQM BUA) is EXCLUDED from the workbooks,".format(m.UNMAPPED_BUA),
              "!!!  so totals %s will MISMATCH the raw by that amount." % where,
              "!!!  To accept: add them to FROZEN_COMPONENTS / FROZEN_CATS (bua_update/engine.py,",
              "!!!  keep alphabetical) and notify the other disciplines -- or fix the rows in Revit.",
              "!!!  Raw rows behind it:"]
    for r, sec, lvl, cval, bua, gfa in m.unmapped:
        lines.append("!!!    row %-5d %-20s %-20s C=%-34r BUA=%10.2f  GFA=%10.2f" % (r, sec, lvl, cval, bua, gfa))
    lines.append(bar)
    return lines


def levels_banner(m, where="below"):
    bar = "!" * 78
    lines = [bar, "!!!  LEVELS THE TYPICAL-FLOOR SET %s CANNOT PLACE  !!!" % m.profile_key,
             "!!!  (%s)" % m.profile["label"]]
    for sec, lvl, bua, why in m.level_conflicts():
        lines.append("!!!    %-20s %-20s BUA=%10s  %s" % (sec, lvl, disp(bua), why))
    lines += ["!!!  Their area is left out, so the totals %s will MISMATCH. Re-run with the other set" % where,
              "!!!  (%s) or check the Levels in Revit." % ", ".join(k for k in PROFILES if k != m.profile_key),
              bar]
    return lines


# ------------------------------------------------------------------ run
def update(folder=None, raw=None, option1=None, option2=None, typical=AUTO, make_backup=True, write=True,
           log=None):
    """Re-feed the raw into both workbooks (write=False: parse and check only, nothing written).
    log(text, tag) gets every output line; tag is None | 'head' | 'ok' | 'warn' | 'fail'."""
    res = Result()

    def say(text="", tag=None):
        res.lines.append(text)
        if log:
            log(text, tag)
    try:
        files = res.files = find_files(folder, raw, option1, option2)
        say("Raw export: %s" % files["raw"])
        say("Option 1:   %s" % files["option1"])
        say("Option 2:   %s" % files["option2"])
        m, why = choose_profile(read_raw(files["raw"]), typical)
    except UpdateError as e:
        res.error = str(e)
        say("ERROR: %s" % e, "fail")
        return res
    res.profile, res.profile_why, res.sections = m.profile_key, why, list(m.SECTIONS)
    res.new_components, res.new_cats, res.excluded_bua = m.NEW_COMPONENTS, m.NEW_CATS, m.UNMAPPED_BUA
    res.unmapped_rows, res.level_conflicts = list(m.unmapped), m.level_conflicts()
    say("Assets (%d): %s" % (len(m.SECTIONS), ", ".join(m.SECTIONS)))
    say("Typical floors: %s -- %s [%s]" % (m.profile_key, m.profile["label"], why))
    say("Frozen format: %d GFA Components x %d Space/Room Categories = %d columns (Option 1: %d with Level + "
        "Building Asset)" % (len(m.ASSETS), len(m.CATS), m.NCOLS, m.NCOLS + 1))
    frozen_ok = not (m.NEW_COMPONENTS or m.NEW_CATS)
    if not frozen_ok:
        say()
        for line in new_items_banner(m):
            say(line, "warn")
    if res.level_conflicts:
        say()
        for line in levels_banner(m):
            say(line, "warn")
    if not write:
        res.status = "checked"
        say()
        say(res.summary(), "ok" if frozen_ok and not res.level_conflicts else "warn")
        return res

    def skip(label, path):
        say()
        say("*** SKIPPED %s: file is open in Excel - close it and rerun ***" % label, "fail")
        say("    %s" % path, "fail")
        res.skipped.append((label, path))

    # 1. build both in memory: a template problem in either one stops the run before anything is written
    built = []
    say()
    for key, mode, label in (("option1", "combined", "Option 1 (combined 'Overall BUA' sheet)"),
                             ("option2", "own", "Option 2 (one sheet per asset)")):
        path = files[key]
        try:
            check_writable(path)
            try:
                wb = openpyxl.load_workbook(path)
            except PermissionError:
                raise
            except Exception as e:  # damaged / not an .xlsx
                raise UpdateError("Cannot open %s as a workbook (%s)" % (path, e))
            say("Building %s ..." % label)
            refeed_data_sheet(wb, m, find_data_sheet(wb))
            if mode == "combined":
                res.option1_rows = build_combined(wb, m)
            else:
                for section in m.SECTIONS:
                    build_section(wb, m, section)
            wb.calculation.fullCalcOnLoad = True
        except PermissionError:
            skip(label, path)
            continue
        except UpdateError as e:
            res.error = str(e)
            say("ERROR: %s -- nothing was written" % e, "fail")
            return res
        built.append((path, mode, label, wb))

    # 2. back up, save, read back and check against the raw
    ok = not res.skipped
    stamp = dt.datetime.now().strftime("%y%m%d_%H%M%S")
    for path, mode, label, wb in built:
        try:
            if make_backup:
                res.backup_dir = backup([path], os.path.dirname(path), stamp)
            wb.save(path)
        except PermissionError:
            skip(label, path)
            ok = False
            continue
        res.updated.append((label, path))
        say()
        say("--- %s ---" % label, "head")
        wb2 = openpyxl.load_workbook(path)
        if mode == "combined":
            good, res.totals = verify_combined(wb2, m, say)
        else:
            good, totals2, res.option2_rows = verify_sections(wb2, m, say)
            res.totals = res.totals or totals2
        ok &= good

    say()
    if res.backup_dir:
        say("Backup of the workbooks as they were: %s" % res.backup_dir)
    if res.skipped:
        res.status = "skipped"
        say("*** %s not updated (file locked) - close in Excel and rerun ***" % ", ".join(l for l, _ in res.skipped),
            "fail")
    elif not frozen_ok:
        res.status = "new_items"
        for line in new_items_banner(m, "above"):        # repeat the highlight at the end
            say(line, "warn")
    elif ok:
        res.status = "done"
        say(DONE_LINE, "ok")
        say("Overall BUA = %s SQM   GFA = %s SQM   (raw %s / %s)" % (
            "{:,.2f}".format(res.totals["bua"]), "{:,.2f}".format(res.totals["gfa"]),
            "{:,.2f}".format(res.totals["raw_bua"]), "{:,.2f}".format(res.totals["raw_gfa"])), "ok")
    else:
        res.status = "mismatch"
        if res.level_conflicts:
            for line in levels_banner(m, "above"):
                say(line, "warn")
        say("*** CHECK MISMATCHES ABOVE ***", "fail")
    return res

# -*- coding: utf-8 -*-
"""
BUA Workbook Builder - engine
==============================
Parses a raw Area export (Level | Building Asset | GFA Component-Space/Room
Category | ... | GFA (N) SQM | BUA (O) SQM, with section-header rows in
column A grouping the data by Building Asset) and builds the Option 2 pivot
workbook: one sheet per Building Asset section, that section's own levels
only (+ typical-floor cross-reference rows where a base floor's row already
represents several physical floors), a FROZEN GFA-Component x Space/Room
Category column skeleton, and a BUA/GFA tie-out check against the raw
totals.

No GUI/tkinter dependency here - import and call from a script or a
Tk launcher (see BuaWorkbookBuilder_Launcher.pyw).

CONFIG below (TYPICAL / LEVEL_ALIASES / FROZEN_COMPONENTS / FROZEN_CATS) is
project-specific - edit for a different building set. Everything else is
generic to the raw layout.
"""
import os
import re
import shutil
import tempfile
from collections import OrderedDict, defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, Color
from openpyxl.utils import column_index_from_string as CI
from openpyxl.utils import get_column_letter as L

# ---------------------------------------------------------------- CONFIG
ZERO_FMT = "#,##0.00;-#,##0.00;0"
EXCEL_FONT = "Aptos Narrow"
SPLIT_CATS = {"Circulation", "Services", "Storage"}
TYPICAL = {"07th Floor": (7, 20, 14), "21st Floor": (21, 22, 2),
           "27th Floor": (27, 36, 10), "66th Floor": (66, 71, 6)}
LEVEL_ALIASES = {"27th to 36th Floor": "27th Floor"}
BASEMENT_PREFIX = ["Basement 04", "Basement Mezzanine", "Basement 03",
                    "Basement 02", "Basement 01", "Ground Floor"]
FROZEN_COMPONENTS = ["Circulation", "Facade Structure", "Hotel", "MEP", "Office",
                      "Parking", "Residential", "Retail", "Shared", "Storage"]
FROZEN_CATS = ["Ballroom", "Circulation", "F&B", "F&B Kitchen",
               "F&B Seating / Beach Club Lounge", "Facade Structure", "Gym/Fitness",
               "Hotel Apartments", "Hotel Guest Rooms", "Kitchen", "Meeting Room",
               "MEP Rooms", "Offices", "Parking", "Pool", "Pool Deck",
               "Residential Units", "Restaurant", "Retail", "Roof (Seating Area)",
               "Services", "SPA", "Storage", "Terrace/Balconies"]
MAX_FLOOR = 99   # ordinal-name scan ceiling; raise if a raw ever has a higher floor

REFPAT = re.compile(r"=([A-Z]+)(\d+)$")


class RawParseError(Exception):
    """Raised for anything wrong with the raw file itself - shown to the user as-is."""


# ------------------------------------------------------------------ small helpers
def split_ac(v):
    return v.split("-", 1) if "-" in v else (v, v)


def sort_ci(seq):
    return sorted(seq, key=lambda s: s.lower())


def disp(v):
    return "0" if abs(v) < 0.005 else format(v, ",.2f")


def ordinal(n):
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%02d%s Floor" % (n, suf)


def leaf_label(y, kind):
    return "%s (GFA)" % y if kind == "GFA" else ("%s (Non-GFA)" % y if kind == "NonGFA" else y)


def safe_sheet_name(name, wb=None):
    bad = set('[]:*?/\\')
    cleaned = "".join("_" if ch in bad else ch for ch in str(name))[:31] or "Sheet"
    if wb is None:
        return cleaned
    base = cleaned
    n = 1
    while cleaned in wb.sheetnames:
        n += 1
        suffix = " (%d)" % n
        cleaned = base[: 31 - len(suffix)] + suffix
    return cleaned


def load_raw_sheet(path):
    """Copy the raw file to a temp file first - it is often open (locked) in Excel."""
    if not os.path.isfile(path):
        raise RawParseError("Raw file not found: %s" % path)
    tmp = os.path.join(tempfile.gettempdir(), "_bua_raw_copy_%d.xlsx" % os.getpid())
    try:
        shutil.copyfile(path, tmp)
    except PermissionError:
        import subprocess
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Copy-Item -LiteralPath "%s" -Destination "%s" -Force' % (path, tmp)],
            capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(tmp):
            raise RawParseError("Cannot read the raw file (locked?): %s\n%s" % (path, res.stderr))
    try:
        return openpyxl.load_workbook(tmp, data_only=True).active
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ------------------------------------------------------------------ styles
class _Styles:
    def __init__(self):
        blk = Color(theme=1)
        self.GREY = PatternFill("solid", fgColor=Color(theme=0, tint=-0.15))
        self.GREY2 = PatternFill("solid", fgColor=Color(theme=0, tint=-0.25))
        self.f_title = Font(name=EXCEL_FONT, sz=20, bold=True, italic=True, color=blk)
        self.f_hdr = Font(name=EXCEL_FONT, sz=11, bold=True, italic=True, color=blk)
        self.f_asset = Font(name=EXCEL_FONT, sz=11, bold=True, color=blk)
        self.f_leaf = Font(name=EXCEL_FONT, sz=9, italic=True, color=blk)
        self.f_data = Font(name=EXCEL_FONT, sz=11, color=blk)
        self.f_tot = Font(name=EXCEL_FONT, sz=11, bold=True, color=blk)
        self.a_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        self.a_leaf = Alignment(horizontal="center", vertical="bottom", text_rotation=90)
        self._thin, self._med = Side("thin"), Side("medium")
        self._bc = {}

    def border(self, l="thin", r="thin", t="thin", b="thin"):
        k = (l, r, t, b)
        if k not in self._bc:
            sd = {"thin": self._thin, "medium": self._med}
            self._bc[k] = Border(left=sd[l], right=sd[r], top=sd[t], bottom=sd[b])
        return self._bc[k]


# ------------------------------------------------------------------ engine
class BuaEngine:
    """Parses one raw export. build_option2() then writes one sheet per
    Building Asset section into a workbook; verify_option2() checks it ties
    out to the raw totals."""

    def __init__(self, raw_path):
        self.raw_path = raw_path
        self.assets, self.cats = OrderedDict(), OrderedDict()
        self.SECTIONS = []
        self.data = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        self.gfatot = defaultdict(lambda: defaultdict(float))
        self.sec_lv = defaultdict(set)
        self.present = set()
        self._parse()

    # ---------------------------------------------------------- parse
    def _parse(self):
        src = load_raw_sheet(self.raw_path)
        cur = None
        rows_seen = 0
        for r in range(4, src.max_row + 1):
            a = src.cell(r, 1).value
            a = LEVEL_ALIASES.get(a, a)
            rest = [src.cell(r, c).value for c in range(2, 16)]
            if a in (None, "") and not [x for x in rest if x not in (None, "")]:
                continue
            if not [x for x in rest if x not in (None, "")]:      # section header row
                cur = a
                if a not in self.SECTIONS:
                    self.SECTIONS.append(a)
                continue
            rows_seen += 1
            cval = src.cell(r, 3).value
            if not (isinstance(cval, str) and cval.strip()):
                continue
            asset, cat = split_ac(cval)
            self.assets[asset] = self.cats[cat] = True
            n_val = src.cell(r, 14).value or 0
            o_val = src.cell(r, 15).value or 0
            d = self.data[cur][(a, asset, cat)]
            d[0] += n_val
            d[1] += o_val
            self.gfatot[cur][a] += n_val
            self.present.add(a)
            self.sec_lv[cur].add(a)

        if rows_seen == 0:
            raise RawParseError("No data rows found below row 4 - is this the raw area export?")
        if not self.SECTIONS:
            raise RawParseError("No section-header rows found in column A - is this the raw area export?")

        self.ASSETS = list(FROZEN_COMPONENTS)
        self.CATS = list(FROZEN_CATS)
        self.NEW_COMPONENTS = sort_ci(set(self.assets) - set(FROZEN_COMPONENTS))
        self.NEW_CATS = sort_ci(set(self.cats) - set(FROZEN_CATS))
        self.UNMAPPED_BUA = sum(
            v[1] for s in self.data for (l, a, y), v in self.data[s].items()
            if a not in FROZEN_COMPONENTS or y not in FROZEN_CATS)

        self.leaf_defs = []
        for a in self.ASSETS:
            for y in self.CATS:
                if y in SPLIT_CATS:
                    self.leaf_defs += [(a, y, "GFA"), (a, y, "NonGFA")]
                else:
                    self.leaf_defs.append((a, y, "BUA"))

        self.typ_member = {}
        for base, (s, e, fc) in TYPICAL.items():
            for n in range(s, e + 1):
                if ordinal(n) != base:
                    self.typ_member[ordinal(n)] = base

        self.global_order = [l for l in BASEMENT_PREFIX if l in self.present]
        for n in range(1, MAX_FLOOR + 1):
            fn = ordinal(n)
            if fn in self.present or fn in self.typ_member:
                self.global_order.append(fn)

        self.LEAF0 = 2
        self.LEAF1 = 1 + len(self.leaf_defs)
        self.GFA_C = self.LEAF1 + 1
        self.BUA_C = self.LEAF1 + 2
        self.NCOLS = self.BUA_C

    def leaf_val(self, sec, lvl, a, y, kind):
        n_val, o_val = self.data[sec].get((lvl, a, y), (0.0, 0.0))
        return n_val if kind == "GFA" else (o_val - n_val if kind == "NonGFA" else o_val)

    def has_new_items(self):
        return bool(self.NEW_COMPONENTS or self.NEW_CATS)

    def new_items_report(self):
        if not self.has_new_items():
            return []
        lines = ["NEW ITEMS IN RAW THAT ARE NOT IN THE FROZEN FORMAT:"]
        if self.NEW_COMPONENTS:
            lines.append("  New GFA Components : %s" % ", ".join(self.NEW_COMPONENTS))
        if self.NEW_CATS:
            lines.append("  New Space/Room Cats : %s" % (", ".join(self.NEW_CATS) or "(blank category)"))
        lines.append("  Their area (%s SQM BUA) is EXCLUDED from the output -" % disp(self.UNMAPPED_BUA))
        lines.append("  totals will mismatch the raw by that amount unless fixed at the source,")
        lines.append("  or FROZEN_COMPONENTS / FROZEN_CATS is edited in the engine to accept them.")
        return lines

    # ---------------------------------------------------------- build (Option 2 layout)
    def build_option2(self, wb):
        styles = _Styles()
        for section in self.SECTIONS:
            self._build_section(wb, section, styles)

    def _build_section(self, wb, section, s):
        block_levels = [l for l in self.global_order
                        if l in self.sec_lv[section]
                        or (l in self.typ_member and self.typ_member[l] in self.sec_lv[section])]
        ws = wb.create_sheet(safe_sheet_name(section, wb))
        r_d0 = 4
        r_tot = r_d0 + len(block_levels)
        base_row = {b: r_d0 + block_levels.index(b) for b in TYPICAL if b in block_levels}

        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=self.NCOLS)
        tc = ws.cell(1, 1, "%s - BUA by Asset / Category" % section)
        tc.font = s.f_title
        tc.alignment = Alignment(vertical="center")
        tc.border = s.border(b="medium")
        ws.merge_cells(start_row=2, start_column=1, end_row=3, end_column=1)
        c = ws.cell(2, 1, "Level")
        c.font = s.f_hdr
        c.fill = s.GREY
        c.alignment = s.a_center
        for cc, txt in ((self.GFA_C, "Gross Floor Area (GFA) (A+B) SQM"),
                        (self.BUA_C, "Built Up Area (A+B+C+D+E+F+G+H) SQM")):
            ws.merge_cells(start_row=2, start_column=cc, end_row=3, end_column=cc)
            c = ws.cell(2, cc, txt)
            c.font = s.f_hdr
            c.fill = s.GREY
            c.alignment = s.a_center

        group_starts = set()
        for i, (a, y, kind) in enumerate(self.leaf_defs):
            lc = ws.cell(3, self.LEAF0 + i, leaf_label(y, kind))
            lc.font = s.f_leaf
            lc.fill = s.GREY
            lc.alignment = s.a_leaf
        for a in self.ASSETS:
            idxs = [self.LEAF0 + i for i, (aa, _, _) in enumerate(self.leaf_defs) if aa == a]
            s0, e0 = idxs[0], idxs[-1]
            group_starts.add(s0)
            if e0 > s0:
                ws.merge_cells(start_row=2, start_column=s0, end_row=2, end_column=e0)
            ac = ws.cell(2, s0, a)
            ac.font = s.f_asset
            ac.fill = s.GREY2
            ac.alignment = s.a_center

        colmax = {c: 1 for c in range(self.LEAF0, self.NCOLS + 1)}
        for ri, lvl in enumerate(block_levels):
            r = r_d0 + ri
            lc = ws.cell(r, 1, lvl)
            lc.font = s.f_data
            lc.alignment = Alignment(vertical="center")
            base = self.typ_member.get(lvl)
            is_base = lvl in TYPICAL
            member_ref = base is not None and base in base_row and base in self.sec_lv[section]
            fc = TYPICAL[lvl][2] if is_base else 1
            rowsum = 0.0
            for i, (a, y, kind) in enumerate(self.leaf_defs):
                cc = self.LEAF0 + i
                if base is not None:
                    num = self.leaf_val(section, base, a, y, kind) / TYPICAL[base][2] if member_ref else 0.0
                    v = "=%s%d" % (L(cc), base_row[base]) if member_ref else 0
                elif is_base:
                    num = v = self.leaf_val(section, lvl, a, y, kind) / fc
                else:
                    num = v = round(self.leaf_val(section, lvl, a, y, kind), 2)
                rowsum += num
                cell = ws.cell(r, cc, v)
                cell.font = s.f_data
                cell.number_format = ZERO_FMT
                colmax[cc] = max(colmax[cc], len(disp(num)))
            if base is not None:
                gnum = self.gfatot[section].get(base, 0) / TYPICAL[base][2] if member_ref else 0.0
                gv = "=%s%d" % (L(self.GFA_C), base_row[base]) if member_ref else 0
            elif is_base:
                gnum = gv = self.gfatot[section].get(lvl, 0) / fc
            else:
                gnum = gv = round(self.gfatot[section].get(lvl, 0), 2)
            gc = ws.cell(r, self.GFA_C, gv)
            gc.font = s.f_data
            gc.number_format = ZERO_FMT
            colmax[self.GFA_C] = max(colmax[self.GFA_C], len(disp(gnum)))
            bv = ("=%s%d" % (L(self.BUA_C), base_row[base]) if member_ref
                  else "=SUM(%s%d:%s%d)" % (L(self.LEAF0), r, L(self.LEAF1), r))
            bc = ws.cell(r, self.BUA_C, bv)
            bc.font = s.f_data
            bc.number_format = ZERO_FMT
            colmax[self.BUA_C] = max(colmax[self.BUA_C], len(disp(rowsum)))

        tcell = ws.cell(r_tot, 1, "Grand Total")
        tcell.font = s.f_tot
        tcell.fill = s.GREY
        for cc in range(self.LEAF0, self.NCOLS + 1):
            t = ws.cell(r_tot, cc, "=SUM(%s%d:%s%d)" % (L(cc), r_d0, L(cc), r_tot - 1))
            t.font = s.f_tot
            t.fill = s.GREY
            t.number_format = ZERO_FMT
        for i in range(len(self.leaf_defs)):
            tot = sum(self.leaf_val(section, lvl, *self.leaf_defs[i]) for lvl in self.sec_lv[section])
            colmax[self.LEAF0 + i] = max(colmax[self.LEAF0 + i], len(disp(tot)))
        colmax[self.GFA_C] = max(colmax[self.GFA_C], len(disp(sum(self.gfatot[section].values()))))
        colmax[self.BUA_C] = max(colmax[self.BUA_C], len(disp(
            sum(self.leaf_val(section, lvl, *d) for lvl in self.sec_lv[section] for d in self.leaf_defs))))

        for r in range(2, r_tot + 1):
            for cc in range(1, self.NCOLS + 1):
                bl = "medium" if (cc in group_starts or cc == self.GFA_C or cc == 1) else "thin"
                br = "medium" if cc == self.NCOLS else "thin"
                bt = "medium" if r in (2, r_tot) else "thin"
                bb = "medium" if r in (3, r_tot) else "thin"
                ws.cell(r, cc).border = s.border(bl, br, bt, bb)

        lvl_len = max([len(str(ws.cell(r, 1).value or "")) for r in range(r_d0, r_tot + 1)] or [1])
        ws.column_dimensions["A"].width = round(lvl_len * 0.95 + 2, 2)
        for cc in range(self.LEAF0, self.LEAF1 + 1):
            ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 4.0), 2)
        for cc in (self.GFA_C, self.BUA_C):
            ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 12.0), 2)
        ws.row_dimensions[1].height = 30
        ws.row_dimensions[2].height = 30
        ws.row_dimensions[3].height = round(max(len(leaf_label(y, k)) for (_, y, k) in self.leaf_defs) * 5.0 + 14, 1)
        for r in range(r_d0, r_tot + 1):
            ws.row_dimensions[r].height = 15.75
        ws.freeze_panes = ws.cell(r_d0, self.LEAF0)

    # ---------------------------------------------------------- verify
    def verify_option2(self, wb):
        """Returns (all_ok, [report lines]) - per-section + overall BUA/GFA tie-out vs raw."""
        lines = []
        all_ok = True
        tot_bua_all = tot_gfa_all = 0.0
        raw_bua_all = raw_gfa_all = 0.0
        for section in self.SECTIONS:
            name = safe_sheet_name(section, wb) if safe_sheet_name(section) not in wb.sheetnames else safe_sheet_name(section)
            if name not in wb.sheetnames:
                lines.append("  %-24s NO SHEET FOUND (build step skipped it)" % section)
                all_ok = False
                continue
            ws = wb[name]
            try:
                r_tot = next(r for r in range(4, ws.max_row + 1) if ws.cell(r, 1).value == "Grand Total")
            except StopIteration:
                lines.append("  %-24s NO Grand Total row found" % section)
                all_ok = False
                continue
            cache = {}

            def num(r, c):
                if (r, c) in cache:
                    return cache[(r, c)]
                v = ws.cell(r, c).value
                if isinstance(v, str) and v.startswith("="):
                    m = REFPAT.match(v)
                    res = num(int(m.group(2)), CI(m.group(1))) if m else 0.0
                else:
                    res = float(v or 0)
                cache[(r, c)] = res
                return res

            bua = sum(num(r, c) for r in range(4, r_tot) for c in range(2, self.LEAF1 + 1))
            gfa = sum(num(r, self.GFA_C) for r in range(4, r_tot))
            raw_o = sum(v[1] for v in self.data[section].values())
            raw_n = sum(v[0] for v in self.data[section].values())
            ok = abs(bua - raw_o) < 0.05 and abs(gfa - raw_n) < 0.05
            all_ok &= ok
            tot_bua_all += bua
            tot_gfa_all += gfa
            raw_bua_all += raw_o
            raw_gfa_all += raw_n
            lines.append("  %-24s BUA=%12s vs raw %12s   GFA=%12s vs raw %12s   %s" % (
                section, disp(bua), disp(raw_o), disp(gfa), disp(raw_n), "OK" if ok else "*** MISMATCH ***"))
        overall_ok = abs(tot_bua_all - raw_bua_all) < 0.5 and abs(tot_gfa_all - raw_gfa_all) < 0.5
        all_ok &= overall_ok
        lines.append("  %-24s BUA=%12s vs raw %12s   GFA=%12s vs raw %12s   %s" % (
            "OVERALL", disp(tot_bua_all), disp(raw_bua_all), disp(tot_gfa_all), disp(raw_gfa_all),
            "OK" if overall_ok else "*** MISMATCH ***"))
        return all_ok, lines

    # ---------------------------------------------------------- build (Option 1 layout)
    OPTION1_SHEET = "Overall BUA"

    def build_option1(self, wb):
        """One combined sheet - all sections stacked like the raw layout: col A =
        Level, col B = Building Asset; a section-header row starts each block
        (ALL of that section's own levels, same as Option 2); a '<Asset> Total'
        subtotal row (grand-total style) closes each block; a blank separator
        row follows; a Grand Total row (sum of the subtotals) ends the sheet."""
        s = _Styles()
        b_c = 2
        lf0 = 3
        lf1 = 2 + len(self.leaf_defs)
        g_c = lf1 + 1
        u_c = lf1 + 2
        nc = u_c
        self._o1 = {"B_C": b_c, "LF0": lf0, "LF1": lf1, "G_C": g_c, "U_C": u_c, "NC": nc}

        ws = wb.create_sheet(safe_sheet_name(self.OPTION1_SHEET, wb))
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=nc)
        tc = ws.cell(1, 1, "Overall BUA - Asset / GFA Component / Space-Room Category")
        tc.font = s.f_title
        tc.alignment = Alignment(vertical="center")
        tc.border = s.border(b="medium")
        for col, txt in ((1, "Level"), (b_c, "Building Asset")):
            ws.merge_cells(start_row=2, start_column=col, end_row=3, end_column=col)
            c = ws.cell(2, col, txt)
            c.font = s.f_hdr
            c.fill = s.GREY
            c.alignment = s.a_center
        for cc, txt in ((g_c, "Gross Floor Area (GFA) (A+B) SQM"), (u_c, "Built Up Area (A+B+C+D+E+F+G+H) SQM")):
            ws.merge_cells(start_row=2, start_column=cc, end_row=3, end_column=cc)
            c = ws.cell(2, cc, txt)
            c.font = s.f_hdr
            c.fill = s.GREY
            c.alignment = s.a_center

        group_starts = set()
        for i, (a, y, kind) in enumerate(self.leaf_defs):
            lc = ws.cell(3, lf0 + i, leaf_label(y, kind))
            lc.font = s.f_leaf
            lc.fill = s.GREY
            lc.alignment = s.a_leaf
        for a in self.ASSETS:
            idxs = [lf0 + i for i, (aa, _, _) in enumerate(self.leaf_defs) if aa == a]
            s0, e0 = idxs[0], idxs[-1]
            group_starts.add(s0)
            if e0 > s0:
                ws.merge_cells(start_row=2, start_column=s0, end_row=2, end_column=e0)
            ac = ws.cell(2, s0, a)
            ac.font = s.f_asset
            ac.fill = s.GREY2
            ac.alignment = s.a_center

        colmax = {c: 1 for c in range(lf0, nc + 1)}
        sec_hdr_rows, sub_rows = [], []
        r = 4
        for section in self.SECTIONS:
            ws.cell(r, 1, section).font = s.f_asset
            for c in range(1, nc + 1):
                ws.cell(r, c).fill = s.GREY
            sec_hdr_rows.append(r)
            r += 1
            b0 = r
            block_levels = [l for l in self.global_order
                            if l in self.sec_lv[section]
                            or (l in self.typ_member and self.typ_member[l] in self.sec_lv[section])]
            base_row = {b: b0 + block_levels.index(b) for b in TYPICAL if b in block_levels}
            for ri, lvl in enumerate(block_levels):
                rr = b0 + ri
                ws.cell(rr, 1, lvl).font = s.f_data
                ws.cell(rr, b_c, section).font = s.f_data
                base = self.typ_member.get(lvl)
                is_base = lvl in TYPICAL
                member_ref = base is not None and base in self.sec_lv[section]
                fc = TYPICAL[lvl][2] if is_base else 1
                rowsum = 0.0
                for i, (a, y, kind) in enumerate(self.leaf_defs):
                    cc = lf0 + i
                    if base is not None:
                        num = self.leaf_val(section, base, a, y, kind) / TYPICAL[base][2] if member_ref else 0.0
                        v = "=%s%d" % (L(cc), base_row[base]) if member_ref else 0
                    elif is_base:
                        num = v = self.leaf_val(section, lvl, a, y, kind) / fc
                    else:
                        num = v = round(self.leaf_val(section, lvl, a, y, kind), 2)
                    rowsum += num
                    cell = ws.cell(rr, cc, v)
                    cell.font = s.f_data
                    cell.number_format = ZERO_FMT
                    colmax[cc] = max(colmax[cc], len(disp(num)))
                if base is not None:
                    gnum = self.gfatot[section].get(base, 0) / TYPICAL[base][2] if member_ref else 0.0
                    gv = "=%s%d" % (L(g_c), base_row[base]) if member_ref else 0
                elif is_base:
                    gnum = gv = self.gfatot[section].get(lvl, 0) / fc
                else:
                    gnum = gv = round(self.gfatot[section].get(lvl, 0), 2)
                gc = ws.cell(rr, g_c, gv)
                gc.font = s.f_data
                gc.number_format = ZERO_FMT
                colmax[g_c] = max(colmax[g_c], len(disp(gnum)))
                bv = ("=%s%d" % (L(u_c), base_row[base]) if member_ref
                      else "=SUM(%s%d:%s%d)" % (L(lf0), rr, L(lf1), rr))
                bc = ws.cell(rr, u_c, bv)
                bc.font = s.f_data
                bc.number_format = ZERO_FMT
                colmax[u_c] = max(colmax[u_c], len(disp(rowsum)))
            b1 = b0 + len(block_levels) - 1
            sr = b1 + 1
            ws.cell(sr, 1, "%s Total" % section).font = s.f_tot
            for c in range(1, nc + 1):
                ws.cell(sr, c).fill = s.GREY
            for cc in range(lf0, nc + 1):
                t = ws.cell(sr, cc, "=SUM(%s%d:%s%d)" % (L(cc), b0, L(cc), b1))
                t.font = s.f_tot
                t.number_format = ZERO_FMT
            for i in range(len(self.leaf_defs)):
                tot = sum(self.leaf_val(section, lvl, *self.leaf_defs[i]) for lvl in self.sec_lv[section])
                colmax[lf0 + i] = max(colmax[lf0 + i], len(disp(tot)))
            colmax[g_c] = max(colmax[g_c], len(disp(sum(self.gfatot[section].values()))))
            colmax[u_c] = max(colmax[u_c], len(disp(
                sum(self.leaf_val(section, lvl, *d) for lvl in self.sec_lv[section] for d in self.leaf_defs))))
            sub_rows.append(sr)
            r = sr + 2   # +1 blank separator row after each asset

        gr = r
        ws.cell(gr, 1, "Grand Total").font = s.f_tot
        for c in range(1, nc + 1):
            ws.cell(gr, c).fill = s.GREY2
        for cc in range(lf0, nc + 1):
            t = ws.cell(gr, cc, "=" + "+".join("%s%d" % (L(cc), sub) for sub in sub_rows))
            t.font = s.f_tot
            t.number_format = ZERO_FMT
        for i in range(len(self.leaf_defs)):
            tot = sum(self.leaf_val(sec, lvl, *self.leaf_defs[i]) for sec in self.SECTIONS for lvl in self.sec_lv[sec])
            colmax[lf0 + i] = max(colmax[lf0 + i], len(disp(tot)))
        colmax[g_c] = max(colmax[g_c], len(disp(sum(sum(g.values()) for g in self.gfatot.values()))))
        colmax[u_c] = max(colmax[u_c], len(disp(sum(v[1] for sec in self.data for v in self.data[sec].values()))))

        special = set(sec_hdr_rows) | set(sub_rows) | {gr}
        blank_rows = {sub + 1 for sub in sub_rows if sub + 1 < gr}
        for rr in range(2, gr + 1):
            if rr in blank_rows:
                continue
            for cc in range(1, nc + 1):
                bl = "medium" if (cc in group_starts or cc == g_c or cc == 1) else "thin"
                br = "medium" if cc == nc else "thin"
                bt = "medium" if (rr == 2 or rr in special) else "thin"
                bb = "medium" if (rr == 3 or rr in special or rr == gr) else "thin"
                ws.cell(rr, cc).border = s.border(bl, br, bt, bb)

        ws.column_dimensions["A"].width = round(
            max(len(str(ws.cell(x, 1).value or "")) for x in range(4, gr + 1)) * 0.95 + 2, 2)
        ws.column_dimensions[L(b_c)].width = round(max(len(sec) for sec in self.SECTIONS) * 0.95 + 2, 2)
        for cc in range(lf0, lf1 + 1):
            ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 4.0), 2)
        for cc in (g_c, u_c):
            ws.column_dimensions[L(cc)].width = round(max(colmax[cc] * 0.95 + 1.6, 12.0), 2)
        ws.row_dimensions[1].height = 30
        ws.row_dimensions[2].height = 30
        ws.row_dimensions[3].height = round(max(len(leaf_label(y, k)) for (_, y, k) in self.leaf_defs) * 5.0 + 14, 1)
        for rr in range(4, gr + 1):
            ws.row_dimensions[rr].height = 15.75
        ws.freeze_panes = ws.cell(4, lf0)

    def verify_option1(self, wb):
        """Returns (all_ok, [report lines]) - per-section + overall BUA/GFA tie-out vs raw."""
        name = safe_sheet_name(self.OPTION1_SHEET)
        if name not in wb.sheetnames or not hasattr(self, "_o1"):
            return False, ["  NO %r sheet found (build step skipped it)" % self.OPTION1_SHEET]
        ws = wb[name]
        lf0, lf1, g_c = self._o1["LF0"], self._o1["LF1"], self._o1["G_C"]
        cache = {}

        def num(r, c):
            if (r, c) in cache:
                return cache[(r, c)]
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.startswith("="):
                m = REFPAT.match(v)
                res = num(int(m.group(2)), CI(m.group(1))) if m else 0.0
            else:
                res = float(v or 0)
            cache[(r, c)] = res
            return res

        lines = []
        all_ok = True
        bysec = {}
        for r in range(4, ws.max_row + 1):
            sec = ws.cell(r, 2).value        # level rows only (col B holds the section)
            if sec in self.data:
                bs = bysec.setdefault(sec, [0.0, 0.0])
                bs[0] += sum(num(r, c) for c in range(lf0, lf1 + 1))
                bs[1] += num(r, g_c)
        for section in self.SECTIONS:
            bua, gfa = bysec.get(section, [0.0, 0.0])
            raw_o = sum(v[1] for v in self.data[section].values())
            raw_n = sum(v[0] for v in self.data[section].values())
            ok = abs(bua - raw_o) < 0.05 and abs(gfa - raw_n) < 0.05
            all_ok &= ok
            lines.append("  %-24s BUA=%12s vs raw %12s   GFA=%12s vs raw %12s   %s" % (
                section, disp(bua), disp(raw_o), disp(gfa), disp(raw_n), "OK" if ok else "*** MISMATCH ***"))
        tot_o = sum(v[1] for sec in self.data for v in self.data[sec].values())
        tot_n = sum(v[0] for sec in self.data for v in self.data[sec].values())
        sum_b = sum(v[0] for v in bysec.values())
        sum_g = sum(v[1] for v in bysec.values())
        overall_ok = abs(sum_b - tot_o) < 0.5 and abs(sum_g - tot_n) < 0.5
        all_ok &= overall_ok
        lines.append("  %-24s BUA=%12s vs raw %12s   GFA=%12s vs raw %12s   %s" % (
            "OVERALL", disp(sum_b), disp(tot_o), disp(sum_g), disp(tot_n),
            "OK" if overall_ok else "*** MISMATCH ***"))
        return all_ok, lines


# ------------------------------------------------------------------ licence
class LicenceError(RawParseError):
    """Raised when this PC is not licensed, revoked, or the kill switch is on."""

    def __init__(self, state, text):
        RawParseError.__init__(self, text)
        self.state = state


def _require_licence(log):
    """Every run re-checks the licence sheet (kill switch + this PC's row). Enforced in the
    compiled release only - plain source on the developer machine skips it."""
    if "__compiled__" not in globals() and not os.environ.get("BUA_ENFORCE_LICENCE"):
        return
    import bua_license
    log("Checking licence...")
    state, info = bua_license.license_state(retries=2)
    if state != "ok":
        raise LicenceError(state, "Licence: " + bua_license.status_text(state, info))


# ------------------------------------------------------------------ one-shot entry point
def build_and_save(raw_path, out_path, mode="option1", log=None):
    """Full pipeline: parse raw -> build the chosen layout -> save -> verify.
    mode is "option1" (one combined 'Overall BUA' sheet, all assets stacked)
    or "option2" (one sheet per Building Asset). Returns (engine, ok,
    report_lines). Raises RawParseError on a bad raw file or a locked
    output path."""
    if mode not in ("option1", "option2"):
        raise ValueError("mode must be 'option1' or 'option2', got %r" % mode)
    log = log or (lambda *a, **kw: None)
    _require_licence(log)
    log("Reading raw export: %s" % raw_path)
    engine = BuaEngine(raw_path)
    log("Sections found (%d): %s" % (len(engine.SECTIONS), ", ".join(engine.SECTIONS)))
    for line in engine.new_items_report():
        log(line, tag="err")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if mode == "option1":
        log("Building Option 1 workbook (one combined 'Overall BUA' sheet)...")
        engine.build_option1(wb)
    else:
        log("Building Option 2 workbook (one sheet per Building Asset)...")
        engine.build_option2(wb)
    wb.calculation.fullCalcOnLoad = True
    try:
        wb.save(out_path)
    except PermissionError:
        raise RawParseError("Cannot write the output file (open in Excel?): %s" % out_path)
    log("Saved: %s" % out_path)
    log("Verifying BUA/GFA tie-out against the raw totals...")
    wb2 = openpyxl.load_workbook(out_path)
    ok, report = engine.verify_option1(wb2) if mode == "option1" else engine.verify_option2(wb2)
    for line in report:
        log(line, tag=("ok" if "MISMATCH" not in line else "err"))
    return engine, ok, report


if __name__ == "__main__":
    import sys
    if len(sys.argv) not in (3, 4):
        sys.exit("usage: python BuaWorkbookBuilder_Engine.py <raw.xlsx> <output.xlsx> [option1|option2]")
    _mode = sys.argv[3] if len(sys.argv) == 4 else "option1"
    _engine, _ok, _report = build_and_save(sys.argv[1], sys.argv[2], mode=_mode, log=lambda m, tag=None: print(m))
    print("\nALL TOTALS TIE OUT - DONE" if _ok else "\n*** CHECK MISMATCHES ABOVE ***")

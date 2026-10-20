"""BUA Update by Netbuild: product info, the engine on synthetic raw exports / templates (both typical-floor
sets, new items, a locked workbook, check only), the command line, the window and the pyRevit button.

    python -m unittest discover -s BuaUpdate/tests -v
"""

import ast
import filecmp
import io
import os
import runpy
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
EXT = os.path.join(REPO, "LevelShifter", "pyRevit", "Netbuild.extension")
BUTTON = os.path.join(EXT, "Netbuild.tab", "Areas.panel", "BUA Update.pushbutton")
sys.path.insert(0, ROOT)

from bua_update import __version__, about, cli, engine  # noqa: E402
from bua_update import settings as settings_mod  # noqa: E402
from sync_pyrevit_lib import SHARED  # noqa: E402

HEADERS = ["Level", "Building Asset", "GFA Component-Space/Room Category", "GLA/GSA Component", "Floor Count",
           "Usable Area (A) SQM", "Circulation GFA (B) SQM", "Circulation Non-GFA (C) SQM", "Service Area (D) SQM",
           "Terrace Area (E) SQM", "Planter Area (F) SQM", "Parking area (G) SQM", "Structure Area (H) SQM",
           "Gross Floor Area (GFA) (A+B) SQM", "Built Up Area (A+B+C+D+E+F+G+H) SQM"]
OPT1 = "260702_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx"
OPT2 = "260702_ProjectB_Overall BUA_Space_Room Split_Raw Levels Only_Option 2.xlsx"
ROOF = "260622_BUA - Roof Areas (Recrea"

# (section, level, column C, GFA (N), BUA (O)) -- typical base floors already x floor count, as Revit exports them
COMMON = [("Basement", "Basement 01", "Parking-Parking", 0, 500.0),
          ("Basement", "Basement 01", "Circulation-Circulation", 0, 100.0),
          ("Building 1", "01st Floor", "MEP-MEP Rooms", 0, 50.0),
          ("Building 1", "01st Floor", "Facade Structure", 0, 10.0),            # no hyphen: component = category
          ("Tower A", "07th Floor", "Residential-Residential Units", 1400.0, 1540.0),
          ("Tower A", "07th Floor", "Residential-Circulation", 140.0, 168.0),
          ("Tower A", "21st Floor", "Residential-Residential Units", 200.0, 220.0),
          ("Tower A", "37th Floor", "Hotel-Hotel Guest Rooms", 90.0, 99.0)]
JULY = COMMON + [("Tower A", "22nd Floor", "Residential-Residential Units", 100.0, 110.0),
                 ("Tower A", "26th Floor", "Residential-Residential Units", 1100.0, 1210.0),     # x11 (26-36)
                 ("Tower A", "65th Floor", "Hotel-Hotel Apartments", 800.0, 880.0)]              # x8 (65-72)
SEPT = COMMON + [("Tower A", "27th to 36th Floor", "Residential-Residential Units", 1000.0, 1100.0),   # x10
                 ("Tower A", "66th Floor", "Hotel-Hotel Apartments", 600.0, 660.0)]              # x6 (66-71)


def write_rows(ws, rows, first=4):
    """Raw layout from row `first`: a section row (asset name alone in A), then its data rows."""
    r, cur = first, None
    for sec, lvl, cval, n, o in rows:
        if sec != cur:
            ws.cell(r, 1, sec)
            cur = sec
            r += 1
        vals = [lvl, sec, cval, None, 1, n, 0, o - n, 0, 0, 0, 0, 0, n, o]
        for c, v in enumerate(vals, 1):
            ws.cell(r, c, v)
        r += 1
    return r


def make_raw(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Excel - Area - Overall With Ass"
    ws.cell(1, 1, "Excel - Area - Overall With Assets For MEP Team")
    for c, h in enumerate(HEADERS, 1):
        ws.cell(2, c, h)
    write_rows(ws, rows)
    wb.save(path)


def make_template(path, option, data_sheet=engine.DATA_SHEET):
    """A stale template: the data sheet (title, header, rows, =SUM total, repeated header), the Roof Areas sheet
    and old result sheets."""
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = data_sheet
    ws.cell(1, 1, "ProjectB - Area - Overall BUA - Space/Room Split")
    for c, h in enumerate(HEADERS, 1):
        ws.cell(2, c, h)
    last = write_rows(ws, [("Old", "Ground Floor", "Retail-Retail", 5.0, 5.0)] * 3) - 1
    for c in range(1, 16):
        ws.cell(4, c).font = Font(bold=True)
    for c in range(6, 16):
        ws.cell(last + 1, c, "=SUM(%s5:%s%d)" % (openpyxl.utils.get_column_letter(c),
                                                 openpyxl.utils.get_column_letter(c), last))
    for c, h in enumerate(HEADERS, 1):
        ws.cell(last + 2, c, h)
    roof = wb.create_sheet(ROOF)
    roof.cell(1, 1, "Roof Areas")
    roof.cell(2, 2, 123.45)
    if option == 1:
        wb.create_sheet("Overall BUA").cell(1, 1, "stale")
    else:
        wb.create_sheet("Tower A").cell(1, 1, "stale")
    wb.save(path)


def project(rows, folder=None, opt1=OPT1, opt2=OPT2, data_sheet=engine.DATA_SHEET):
    folder = folder or tempfile.mkdtemp()
    make_raw(os.path.join(folder, engine.RAW_NAME), rows)
    make_template(os.path.join(folder, opt1), 1, data_sheet)
    make_template(os.path.join(folder, opt2), 2, data_sheet)
    return folder


def read(path):
    with open(path, "rb") as f:
        return f.read()


class AboutTests(unittest.TestCase):
    def test_product_info_and_license(self):
        with open(os.path.join(REPO, "LICENSE"), encoding="utf-8") as f:
            self.assertEqual(about.LICENSE_TEXT, f.read())            # the About screen shows the real LICENSE
        self.assertEqual((about.OWNER, about.PUBLISHER, about.WEBSITE), ("Netbuild", "Netbuild", "https://skaec.com"))
        self.assertEqual(about.COPYRIGHT, u"© 2026 Netbuild. All rights reserved.")
        self.assertEqual(about.LICENSE_NAME, "Netbuild Software Licence Agreement (proprietary)")
        self.assertEqual(about.PRODUCT, "BUA Update by Netbuild")
        self.assertEqual(about.VERSION, __version__)
        self.assertEqual(about.title("x"), "BUA Update by Netbuild %s -- x" % __version__)
        text = about.about_text()
        for want in ("BUA Update by Netbuild  version " + __version__, "Requirements", "openpyxl", "pyRevit 4.8",
                     "Licence: Netbuild Software Licence Agreement (proprietary) -- owned by Netbuild, "
                     "https://skaec.com", "Netbuild Software Licence Agreement\n\nCopyright"):
            self.assertIn(want, text)
        page = about.licence_text()
        for want in ("Proprietary software -- owned by Netbuild", "Website: https://skaec.com",
                     "No licence key required for this product.", about.LICENSE_TEXT.rstrip()):
            self.assertIn(want, page)

    def test_about_source_is_ironpython_safe(self):
        """about.py runs inside Revit (Netbuild -> About): ASCII, the (c) sign as an escape."""
        with open(os.path.join(ROOT, "bua_update", "about.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertTrue(src.isascii())
        self.assertIn('u"\\u00a9 ', src)

    def test_cli_about_licence_version(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["about"]), 0)
        self.assertIn("Netbuild. All rights reserved.", buf.getvalue())
        for cmd in ("license", "licence"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(cli.main([cmd]), 0)
            self.assertEqual(buf.getvalue(), about.licence_text() + "\n")
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            cli.main(["--version"])
        self.assertEqual(buf.getvalue().strip(), "BUA Update by Netbuild " + __version__)

    def test_exe_version_resource(self):
        import make_version_file
        text = make_version_file.render("BUA Update by Netbuild.exe")
        seen = {}

        def rec(name):
            return lambda *a, **k: seen.setdefault(name, []).append((a, k)) or (name, a, k)
        ns = dict((n, rec(n)) for n in ("VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable",
                                        "StringStruct", "VarFileInfo", "VarStruct"))
        eval(compile(text.split("\n", 1)[1], "version_info", "eval"), ns)  # what PyInstaller does with it
        fields = dict(a for a, k in seen["StringStruct"])
        self.assertEqual(fields["CompanyName"], "Netbuild")
        self.assertEqual(fields["ProductName"], "BUA Update by Netbuild")
        self.assertEqual(fields["LegalCopyright"], "(c) 2026 Netbuild. All rights reserved.")
        self.assertEqual(fields["OriginalFilename"], "BUA Update by Netbuild.exe")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.dirs = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def project(self, rows, **kw):
        d = project(rows, **kw)
        self.dirs.append(d)
        return d

    def run_update(self, folder, **kw):
        lines = []
        res = engine.update(folder, log=lambda t, tag=None: lines.append(t), **kw)
        self.assertEqual(lines, res.lines)
        return res

    def test_july_raw_ties_out(self):
        d = self.project(JULY)
        roof0 = openpyxl.load_workbook(os.path.join(d, OPT1))[ROOF]["B2"].value
        res = self.run_update(d)
        self.assertEqual((res.status, res.exit_code, res.profile), ("done", 0, "2026-07"))
        self.assertIn(engine.DONE_LINE, res.lines)
        self.assertNotIn(engine.MISMATCH, "\n".join(res.lines))
        raw_bua = sum(o for _, _, _, _, o in JULY)
        self.assertAlmostEqual(res.totals["bua"], raw_bua, 2)
        self.assertAlmostEqual(res.totals["gfa"], sum(n for _, _, _, n, _ in JULY), 2)
        self.assertEqual(res.summary(), "ALL TOTALS TIE OUT - DONE -- overall BUA %s SQM, GFA %s SQM" % (
            engine.disp(res.totals["bua"]), engine.disp(res.totals["gfa"])))

        wb = openpyxl.load_workbook(os.path.join(d, OPT1))
        self.assertEqual(wb.sheetnames, [engine.DATA_SHEET, ROOF, "Overall BUA"])
        self.assertEqual(wb[ROOF]["B2"].value, roof0)                       # never touched
        ws = wb["Overall BUA"]
        self.assertEqual(ws.max_column, 274)                                # FROZEN: 10 x 24 (+ splits) + 4
        self.assertEqual(ws.cell(2, 3).value, "Circulation")                # first GFA Component
        self.assertEqual(ws.cell(3, 3).value, "Ballroom")                   # first Space/Room Category
        col_a = [ws.cell(r, 1).value for r in range(1, ws.max_row + 1)]
        self.assertEqual(col_a[-1], "Grand Total")
        self.assertEqual(res.option1_rows, ws.max_row)
        for sec in ("Basement", "Building 1", "Tower A"):
            r = col_a.index(sec + " Total") + 1
            self.assertIsNone(ws.cell(r + 1, 1).value)                      # blank separator after each block
        r07 = col_a.index("07th Floor") + 1
        self.assertEqual(ws.cell(r07 + 1, 1).value, "08th Floor")           # typical cross-reference rows
        self.assertEqual(ws.cell(r07 + 1, 3).value, "=C%d" % r07)
        self.assertIn("22nd Floor", col_a)                                  # its own rows (not a copy of 21st)
        self.assertEqual(col_a.count("72nd Floor"), 1)
        ws2 = openpyxl.load_workbook(os.path.join(d, OPT2))
        self.assertEqual(ws2.sheetnames, [engine.DATA_SHEET, ROOF, "Basement", "Building 1", "Tower A"])
        tower = ws2["Tower A"]
        self.assertEqual(tower.max_column, 273)
        # 07-20 (14) + 21st + 22nd + 26-36 (11) + 37th + 65-72 (8)
        self.assertEqual(res.option2_rows["Tower A"], 14 + 2 + 11 + 1 + 8)
        self.assertEqual(tower.cell(4 + res.option2_rows["Tower A"], 1).value, "Grand Total")
        data = ws2[engine.DATA_SHEET]
        self.assertEqual(data.cell(4, 1).value, "Basement")                 # re-fed from raw, header style kept
        self.assertTrue(data.cell(4, 1).font.b)
        self.assertEqual(data.cell(5, 3).value, "Parking-Parking")
        n = len(JULY) + 3                                                   # rows + 3 section rows
        self.assertEqual(data.cell(4 + n, 6).value, "=SUM(F5:F%d)" % (3 + n))
        self.assertEqual(data.cell(5 + n, 1).value, "Level")                # repeated header
        self.assertEqual(sorted(os.listdir(res.backup_dir)), sorted([OPT1, OPT2]))   # backed up first

    def test_september_raw_picks_the_new_set(self):
        d = self.project(SEPT)
        res = self.run_update(d, make_backup=False)
        self.assertEqual((res.status, res.profile), ("done", "2026-09"))
        self.assertFalse(os.path.exists(os.path.join(d, engine.BACKUP_DIR)))
        col_a = [c.value for c in openpyxl.load_workbook(os.path.join(d, OPT1))["Overall BUA"]["A"]]
        self.assertNotIn("27th to 36th Floor", col_a)                       # read as the 27th base floor
        self.assertIn("27th Floor", col_a)
        self.assertIn("36th Floor", col_a)
        self.assertIn("22nd Floor", col_a)                                  # 21-22 cross-reference

    def test_wrong_set_is_reported_and_mismatches(self):
        d = self.project(JULY)
        res = self.run_update(d, typical="2026-09", make_backup=False)
        self.assertEqual((res.status, res.exit_code), ("mismatch", 1))
        out = "\n".join(res.lines)
        self.assertIn(engine.MISMATCH, out)
        self.assertIn("*** CHECK MISMATCHES ABOVE ***", out)
        self.assertIn("LEVELS THE TYPICAL-FLOOR SET 2026-09 CANNOT PLACE", out)
        self.assertEqual([(s, l) for s, l, _, _ in res.level_conflicts], [("Tower A", "22nd Floor")])
        self.assertAlmostEqual(res.level_conflicts[0][2], 110.0)

    def test_new_items_banner(self):
        rows = JULY + [("Tower A", "37th Floor", "Residential-ser", 30.0, 33.0),     # typo'd Sub-Function
                       ("Building 1", "01st Floor", "Services", 0, 7.0)]           # blank Function
        d = self.project(rows)
        res = self.run_update(d, make_backup=False)
        self.assertEqual((res.status, res.exit_code), ("new_items", 2))
        self.assertEqual(res.new_components, ["Services"])                  # no hyphen: Services-Services
        self.assertEqual(res.new_cats, ["ser"])
        self.assertAlmostEqual(res.excluded_bua, 40.0)
        out = "\n".join(res.lines)
        self.assertIn("!!!  NEW ITEMS IN RAW THAT ARE *NOT* IN THE FROZEN FORMAT  !!!", out)
        self.assertIn("!!!  New Space/Room Cats: ser", out)
        self.assertIn("C='Residential-ser'", out)
        self.assertNotIn(engine.DONE_LINE, out)
        ws = openpyxl.load_workbook(os.path.join(d, OPT1))["Overall BUA"]
        self.assertEqual(ws.max_column, 274)                                # the frozen format did not grow

    def test_new_component(self):
        d = self.project(JULY + [("Tower A", "37th Floor", "Gym-Gym/Fitness", 10.0, 12.0)])
        res = self.run_update(d, make_backup=False, write=False)
        self.assertEqual((res.status, res.new_components, res.new_cats), ("checked", ["Gym"], []))
        self.assertIn("!!!  New GFA Components : Gym", res.lines)

    def test_open_in_excel_is_skipped(self):
        d = self.project(JULY)
        opt2 = os.path.join(d, OPT2)
        before = read(opt2)
        orig = engine.check_writable

        def locked(path):
            if path == opt2:
                raise PermissionError(13, "Permission denied", path)
            return orig(path)
        engine.check_writable = locked
        try:
            res = self.run_update(d, make_backup=False)
        finally:
            engine.check_writable = orig
        self.assertEqual((res.status, res.exit_code), ("skipped", 3))
        self.assertEqual(res.skipped, [("Option 2 (one sheet per asset)", opt2)])
        self.assertIn("*** SKIPPED Option 2 (one sheet per asset): file is open in Excel - close it and rerun ***",
                      res.lines)
        self.assertIn(OPT2, res.summary())
        self.assertEqual(read(opt2), before)                                # untouched
        self.assertEqual([l for l, _ in res.updated], ["Option 1 (combined 'Overall BUA' sheet)"])

    def test_check_writes_nothing(self):
        d = self.project(JULY)
        before = [read(os.path.join(d, n)) for n in (OPT1, OPT2)]
        res = self.run_update(d, write=False)
        self.assertEqual((res.status, res.exit_code), ("checked", 0))
        self.assertEqual([read(os.path.join(d, n)) for n in (OPT1, OPT2)], before)
        self.assertFalse(os.path.exists(os.path.join(d, engine.BACKUP_DIR)))

    def test_template_problem_writes_nothing(self):
        d = self.project(JULY)
        wb = openpyxl.load_workbook(os.path.join(d, OPT2))
        wb[engine.DATA_SHEET].title = "Something else"
        wb.save(os.path.join(d, OPT2))
        before = read(os.path.join(d, OPT1))
        res = self.run_update(d)
        self.assertEqual((res.status, res.exit_code), ("error", 4))
        self.assertIn("No data sheet", res.error)
        self.assertEqual(read(os.path.join(d, OPT1)), before)               # Option 1 was not written either

    def test_dated_workbooks_and_data_sheet(self):
        d = self.project(SEPT, opt1="261002_X_with All Levels_Option 1.xlsx",
                         opt2="261002_X_Raw Levels Only_Option 2.xlsx", data_sheet="261002_BUA Space Room Split")
        res = self.run_update(d, make_backup=False)
        self.assertEqual(res.status, "done")
        self.assertEqual(os.path.basename(res.files["option1"]), "261002_X_with All Levels_Option 1.xlsx")
        make_template(os.path.join(d, "261003_X_with All Levels_Option 1.xlsx"), 1)
        with self.assertRaises(engine.UpdateError) as cm:                   # two candidates: ask which
            engine.find_files(d)
        self.assertIn("More than one Option 1 workbook", str(cm.exception))
        make_template(os.path.join(d, OPT1), 1)                             # the script's own name wins
        self.assertEqual(os.path.basename(engine.find_files(d)["option1"]), OPT1)

    def test_missing_files(self):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        res = self.run_update(d)
        self.assertEqual(res.status, "error")
        self.assertIn("No Option 1 workbook", res.error)
        make_template(os.path.join(d, OPT1), 1)
        make_template(os.path.join(d, OPT2), 2)
        res = self.run_update(d)
        self.assertIn("Raw export not found", res.error)

    def test_not_a_raw_export(self):
        d = self.project(JULY)
        wb = openpyxl.Workbook()
        wb.active.cell(5, 1, "07th Floor")
        wb.active.cell(5, 3, "Residential-Residential Units")               # data before any section row
        wb.save(os.path.join(d, engine.RAW_NAME))
        res = self.run_update(d)
        self.assertEqual(res.status, "error")
        self.assertIn("before the first section row", res.error)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.d = project(JULY)
        self.app = tempfile.mkdtemp()
        self.orig = settings_mod.app_dir
        settings_mod.app_dir = lambda: self.app

    def tearDown(self):
        settings_mod.app_dir = self.orig
        shutil.rmtree(self.d, ignore_errors=True)
        shutil.rmtree(self.app, ignore_errors=True)

    def test_update_and_check(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["check", "--folder", self.d]), 0)
        self.assertIn("Check only -- nothing written.", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["update", "--folder", self.d, "--no-backup"]), 0)
        self.assertIn("ALL TOTALS TIE OUT - DONE", buf.getvalue())
        self.assertIn("Overall BUA = ", buf.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.d, engine.BACKUP_DIR)))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["update", "--folder", self.d, "--typical", "2026-09", "--no-backup"]), 1)
        self.assertIn("*** MISMATCH ***", buf.getvalue())

    def test_unexpected_error_is_exit_4(self):
        orig = engine.backup

        def full(*a):
            raise OSError(28, "No space left on device")
        engine.backup = full
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(cli.main(["update", "--folder", self.d]), 4)
        finally:
            engine.backup = orig
        self.assertIn("ERROR: OSError", buf.getvalue())

    def test_settings_and_default_folder(self):
        s = settings_mod.Settings()
        self.assertEqual(s["typical"], "auto")
        s["folder"] = self.d
        s.save()
        self.assertEqual(settings_mod.Settings().project_folder(), self.d)
        self.assertEqual(settings_mod.default_folder(cwd=self.d, candidates=[]), self.d)      # raw in cwd
        self.assertEqual(settings_mod.default_folder(cwd=self.app, candidates=["/nope", self.app]), self.app)
        self.assertEqual(settings_mod.default_folder(cwd=self.app, candidates=["/nope"]), "")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["update"]), 0)                       # the saved folder
        self.assertIn("ALL TOTALS TIE OUT - DONE", buf.getvalue())


class WindowTests(unittest.TestCase):
    def test_window(self):
        try:
            import tkinter as tk
            from bua_update import gui
            root = tk.Tk()
        except Exception as e:  # no tkinter / no display
            self.skipTest("no window: %s" % e)
        d = project(JULY)
        app_dir = tempfile.mkdtemp()
        orig = settings_mod.app_dir
        settings_mod.app_dir = lambda: app_dir
        try:
            app = gui.App(root)
            self.assertTrue(root.title().startswith("BUA Update by Netbuild 1."))
            tabs = [app.nb.tab(t, "text").strip() for t in app.nb.tabs()]
            self.assertEqual(tabs, ["Update", "About", "Licence"])
            app.vars["folder"].set(d)
            self.assertTrue(app.detect())
            app.run(True)
            deadline = time.time() + 60
            while (app.busy or app.last is None) and time.time() < deadline:
                root.update()
                time.sleep(0.02)
            self.assertEqual(app.last.status, "done")
            self.assertIn("every BUA / GFA total ties out", app.banner.cget("text"))
            self.assertIn("ALL TOTALS TIE OUT - DONE", app.out.get("1.0", "end"))
        finally:
            settings_mod.app_dir = orig
            root.destroy()
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(app_dir, ignore_errors=True)


class PyRevitTests(unittest.TestCase):
    """The ribbon button and the About entry, against LevelShifter's pyRevit stubs."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(REPO, "LevelShifter", "tests"))
        sys.path.append(os.path.join(EXT, "lib"))

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = self.tmp
        os.environ["LOCALAPPDATA"] = self.tmp

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lib_copies_match_the_source(self):
        for name in SHARED:
            self.assertTrue(filecmp.cmp(os.path.join(ROOT, "bua_update", name),
                                        os.path.join(EXT, "lib", "bua_update", name), shallow=False),
                            "%s differs -- run: python BuaUpdate/sync_pyrevit_lib.py" % name)

    def test_button_files(self):
        with open(os.path.join(BUTTON, "icon.png"), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        for name in ("script.py", "config.py"):
            with open(os.path.join(BUTTON, name), encoding="utf-8") as f:
                src = f.read()
            ast.parse(src)
            self.assertIn("netbuild_scripts.run_live(globals())", src)
            if name == "script.py":
                self.assertIn('__author__ = "Netbuild -- skaec.com"', src)
        with open(os.path.join(EXT, "lib", "netbuild_about.py"), encoding="utf-8") as f:
            self.assertIn("bua_update_about", f.read())                     # Netbuild -> About lists it

    def test_button_starts_the_app(self):
        import pyrevit_stubs
        import buaupdate_app
        st = pyrevit_stubs.install(None)
        script = os.path.join(BUTTON, "script.py")
        with self.assertRaises(pyrevit_stubs.ScriptExit):                   # no exe, nothing picked
            runpy.run_path(script, run_name="__main__")
        self.assertIn("BUA Update by Netbuild.exe was not found", st.alerts[0][1])
        self.assertEqual(st.alerts[0][0], "BUA Update by Netbuild")
        exe = os.path.join(self.tmp, "Netbuild", "BuaUpdate", "BUA Update by Netbuild.exe")
        os.makedirs(os.path.dirname(exe))
        open(exe, "w").close()
        self.assertEqual(buaupdate_app.find_exe(""), exe)
        runpy.run_path(script, run_name="__main__")
        self.assertEqual(st.started[-1].FileName, exe)
        st.picked = os.path.join(self.tmp, "Other.exe")
        runpy.run_path(os.path.join(BUTTON, "config.py"), run_name="__main__")     # Shift+Click
        self.assertEqual(st.config.values["exe_path"], st.picked)
        self.assertEqual(buaupdate_app.candidates("", env={})[0], os.path.join(EXT, "bin", buaupdate_app.EXE))


if __name__ == "__main__":
    unittest.main()

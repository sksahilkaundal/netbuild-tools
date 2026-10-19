"""The pyRevit extension: shared-file sync, IronPython-2.7 shape, XAML, and both buttons run end to end
against the stand-in Revit model (stub pyRevit/WPF, see pyrevit_stubs.py).

    python -m unittest discover -s LevelShifter/tests -v
"""

import ast
import filecmp
import os
import runpy
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXT = os.path.join(ROOT, "pyRevit", "Netbuild.extension")
PANEL = os.path.join(EXT, "Netbuild.tab", "Levels.panel")
DIRECT = os.path.join(PANEL, "Level Shift.pushbutton", "script.py")
APP = os.path.join(PANEL, "Level Shift App.pushbutton", "script.py")
APP_CONFIG = os.path.join(PANEL, "Level Shift App.pushbutton", "config.py")
ABOUT = os.path.join(EXT, "Netbuild.tab", "About.panel", "About.pushbutton", "script.py")
LICENCE = os.path.join(EXT, "Netbuild.tab", "About.panel", "Licence.pushbutton", "script.py")
SCRIPTS = os.path.join(EXT, "Netbuild.tab", "Scripts.panel")
FOLDER = os.path.join(SCRIPTS, "Script Folder.pushbutton", "script.py")
UPDATE = os.path.join(SCRIPTS, "Update Scripts.pushbutton", "script.py")
APP_EXE = "Level Shift by Netbuild.exe"
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.append(os.path.join(EXT, "lib"))          # levelshift_ui, levelshift_app

import pyrevit_stubs  # noqa: E402
from fake_revit import FakeRevit  # noqa: E402
from level_shift import core  # noqa: E402
import levelshift_app  # noqa: E402
import levelshift_ui  # noqa: E402

sys.path.insert(0, os.path.join(ROOT))
from sync_pyrevit_lib import SHARED  # noqa: E402

IRONPYTHON_FILES = ([os.path.join(ROOT, "level_shift", n) for n in SHARED] + [DIRECT, APP, APP_CONFIG, ABOUT, LICENCE,
                                                                       FOLDER, UPDATE] +
                    [os.path.join(EXT, "lib", n) for n in ("levelshift_ui.py", "levelshift_app.py",
                                                            "netbuild_about.py", "netbuild_scripts.py",
                                                            "netbuild_roundtrip.py")])
BUTTON_SCRIPTS = sorted(os.path.join(d, n) for d, _, files in os.walk(EXT) for n in files
                        if n in ("script.py", "config.py") and d.endswith(".pushbutton"))
IRONPYTHON_FILES += [p for p in BUTTON_SCRIPTS if p not in IRONPYTHON_FILES]


class ExtensionFileTests(unittest.TestCase):
    def test_lib_copies_match_the_source(self):
        for name in SHARED:
            self.assertTrue(filecmp.cmp(os.path.join(ROOT, "level_shift", name),
                                        os.path.join(EXT, "lib", "level_shift", name), shallow=False),
                            "%s differs -- run: python LevelShifter/sync_pyrevit_lib.py" % name)

    def test_ironpython_27_shape(self):
        """No Python-3-only syntax in anything that runs inside Revit."""
        for path in IRONPYTHON_FILES:
            with open(path, encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src, path)
            for node in ast.walk(tree):
                where = "%s:%s" % (os.path.basename(path), getattr(node, "lineno", "?"))
                self.assertNotIsInstance(node, (ast.JoinedStr, ast.Nonlocal, ast.AsyncFunctionDef,
                                                ast.AnnAssign, ast.YieldFrom), where)
                if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                    self.assertFalse(node.args.kwonlyargs, where)
                    self.assertFalse(getattr(node, "returns", None), where)
                    self.assertFalse([a for a in node.args.args if a.annotation], where)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id == "super":
                        self.assertTrue(node.args, "%s: super() needs arguments on IronPython" % where)
                    if node.func.id == "print":
                        self.assertFalse(node.keywords or len(node.args) > 1, where)
                if isinstance(node, ast.Call):
                    self.assertFalse([k for k in node.keywords if k.arg is None and node.args and
                                      isinstance(node.args[-1], ast.Starred)], where)
            self.assertNotIn("exist_ok", src, path)
            self.assertTrue(src.isascii() or src.startswith("# -*- coding: utf-8 -*-"), path)

    def test_xaml(self):
        win = ET.fromstring(levelshift_ui.window_xaml(core.MAX_LEVELS))
        names = [e.get(pyrevit_stubs.X_NAME) for e in win.iter() if e.get(pyrevit_stubs.X_NAME)]
        self.assertEqual(len(names), len(set(names)))
        for kind in ("lvl", "cur", "new", "by", "dir", "def"):
            self.assertEqual(len([n for n in names if n.startswith(kind + "_")]), 10, kind)
        cur = [e for e in win.iter() if e.get(pyrevit_stubs.X_NAME) == "cur_0"][0]
        self.assertEqual((cur.get("IsReadOnly"), cur.get("Background")), ("True", levelshift_ui.CURRENT_BG))
        dlg = ET.fromstring(levelshift_ui.define_xaml("mm"))
        self.assertIn("New elevation (mm)", ET.tostring(dlg, encoding="unicode"))

    def test_icons_and_titles(self):
        for script_path in (DIRECT, APP, ABOUT, LICENCE, FOLDER, UPDATE):
            with open(os.path.join(os.path.dirname(script_path), "icon.png"), "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
            with open(script_path, encoding="utf-8") as f:
                src = f.read()
            self.assertIn('__author__ = "Netbuild -- skaec.com"', src, script_path)   # every button names its owner
            self.assertNotIn("SKAEC.COM", src, script_path)
            self.assertIn("netbuild_scripts.run_live(globals())", src, script_path)   # every button runs live
        for script_path in BUTTON_SCRIPTS:                      # Netbuild Tools 01 / 02 too
            with open(script_path, encoding="utf-8") as f:
                src = f.read()
            if script_path.endswith("script.py"):
                self.assertIn('__author__ = "Netbuild -- skaec.com"', src, script_path)
            self.assertIn("netbuild_scripts.run_live(globals())", src, script_path)
        self.assertGreater(len(BUTTON_SCRIPTS), 20)
        with open(os.path.join(EXT, "Netbuild.tab", "bundle.yaml")) as f:
            self.assertEqual(f.read().split(), ["layout:", "-", "Levels", "-", "Scripts", "-", "About"])
        with open(os.path.join(EXT, "Netbuild.tab", "About.panel", "bundle.yaml")) as f:
            self.assertEqual(f.read().split(), ["layout:", "-", "About", "-", "Licence"])

    def test_find_exe_and_args(self):
        tmp = tempfile.mkdtemp()
        try:
            old = os.path.join(tmp, "Netbuild", "LevelShifter", "LevelShifter.exe")       # a 1.2 install
            os.makedirs(os.path.dirname(old))
            open(old, "w").close()
            self.assertIsNone(levelshift_app.find_exe("", env={}))
            self.assertEqual(levelshift_app.find_exe("", env={"LOCALAPPDATA": tmp}), old)
            new = os.path.join(tmp, "Netbuild", "LevelShifter", APP_EXE)
            open(new, "w").close()
            self.assertEqual(levelshift_app.find_exe("", env={"LOCALAPPDATA": tmp}), new)     # new name first
            self.assertEqual(levelshift_app.find_exe(old, env={}), old)
            self.assertEqual(levelshift_app.candidates("", env={})[0], os.path.join(EXT, "bin", APP_EXE))
            self.assertEqual(levelshift_app.args_line('Model "A"_user'), '--model "Model A_user"')
            self.assertEqual(levelshift_app.args_line(""), "")
        finally:
            shutil.rmtree(tmp)


class CoreLocalTests(unittest.TestCase):
    """core.run_local: the engine in-process, as the direct button runs it."""

    def setUp(self):
        self.fake = FakeRevit()
        self.doc = self.fake.doc
        self.geo0, self.snap0 = self.doc.geometry(), self.doc.snapshot()

    def tearDown(self):
        self.fake.close()

    def test_levels_plan_trial_apply(self):
        out = core.run_local(self.doc, "levels")
        levels = out["LEVELS"]
        self.assertEqual(out["DOC"]["title"], self.doc.Title)
        moves, checks = core.resolve(levels, [core.MoveSpec("L01", "by", 300), core.MoveSpec("L02", "to", 6850)], "mm")
        self.assertFalse([c for c in checks if c.ok is False])
        out = core.run_local(self.doc, "plan", moves)
        self.assertEqual(out["PLAN"]["compensate"], 20)
        self.assertNotIn("RESULT", out)
        out = core.run_local(self.doc, "trial", moves)
        self.assertEqual(out["RESULT"]["drift"], [])
        self.assertEqual(self.doc.snapshot(), self.snap0)
        out = core.run_local(self.doc, "apply", moves, {"tolerance_mm": 0.5})
        self.assertTrue(out["RESULT"]["committed"])
        self.assertEqual(round(self.fake.lv["L01"].Elevation * 304.8, 6), 3800)
        self.assertEqual(self.doc.geometry(), self.geo0)
        checks, lines = core.result_checks("apply", out["RESULT"], "mm", 0.5)
        self.assertIn("Every element kept its X, Y, Z", [c.label for c in checks])


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRevit()
        self.doc = self.fake.doc
        self.geo0, self.snap0 = self.doc.geometry(), self.doc.snapshot()
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = self.tmp
        os.environ["LOCALAPPDATA"] = self.tmp

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def elev(self, name):
        return round(self.fake.lv[name].Elevation * 304.8, 6)

    def test_direct_button(self):
        st = pyrevit_stubs.install(self.doc)
        runpy.run_path(DIRECT, run_name="__main__")
        win = pyrevit_stubs.WPFWindow.shown[0]
        self.assertIn(self.doc.Title, win.model_tb.Text)
        self.assertIn("Project Base Point", win.base_tb.Text)
        self.assertEqual(win.lvl_0.Items, ["", "B1", "L00 GF", "L01", "L02", "L03", "Roof"])
        # row 1: pick L01, type the new elevation -> current shown read-only, move filled in
        win.lvl_0.SelectedItem = "L01"
        self.assertEqual(win.cur_0.Text, "3,500.0 mm")
        win.new_0.type("3800")
        self.assertEqual((win.by_0.Text, win.dir_0.Text), ("+300.0", "UP"))
        # row 2: pick L02, Define new level... -> move down 150
        win.lvl_1.SelectedItem = "L02"

        def define(dlg):
            self.assertEqual((dlg.name_tb.Text, dlg.cur_tb.Text), ("L02", "7,000.0 mm"))
            dlg.by_rb.IsChecked = True
            dlg.amount_tb.type("150")
            dlg.down_rb.IsChecked = True
            self.assertIn("6,850.0 mm", dlg.result_tb.Text)
            dlg.ok_btn.click()
        pyrevit_stubs.WPFWindow.on_dialog = define
        win.def_1.click()
        self.assertEqual((win.new_1.Text, win.by_1.Text, win.dir_1.Text), ("6850.0", "-150.0", "DOWN"))
        # check -> trial (model untouched) -> apply
        win.check_btn.click()
        report = [i.Content for i in win.report_lb.Items]
        self.assertIn("[OK  ] Elements driven by the moved levels -- 20 to compensate (of 24 model elements)", report)
        win.trial_btn.click()
        self.assertEqual(self.doc.snapshot(), self.snap0)
        self.assertTrue([r for r in (i.Content for i in win.report_lb.Items) if "Trial -- rolled back" in r])
        win.apply_btn.click()
        self.assertEqual((self.elev("L01"), self.elev("L02")), (3800, 6850))
        self.assertEqual(self.doc.geometry(), self.geo0)
        self.assertEqual(win.cur_0.Text, "3,800.0 mm")                 # levels re-read after Apply
        self.assertEqual(win.new_0.Text, "")
        logs = os.listdir(os.path.join(self.tmp, "Netbuild", "LevelShift", "logs"))
        self.assertTrue([n for n in logs if n.endswith("_apply_elements.csv")], logs)
        self.assertEqual(st.alerts[-1][0], "Apply")                     # confirmation asked first

    def test_direct_button_refuses_bad_input(self):
        st = pyrevit_stubs.install(self.doc, answers={"ask": "+250"})
        runpy.run_path(DIRECT, run_name="__main__")
        win = pyrevit_stubs.WPFWindow.shown[0]
        win.check_btn.click()
        self.assertIn("at least one row", st.alerts[-1][1])
        win.lvl_0.SelectedItem = "L01"
        win.lvl_1.SelectedItem = "L03"
        win.same_btn.click()                                           # same move for every row
        self.assertEqual((win.by_0.Text, win.by_1.Text, win.new_1.Text), ("+250.0", "+250.0", "10750.0"))
        win.new_1.type("abc")
        self.assertEqual(win.by_1.Text, "?")
        win.apply_btn.click()
        self.assertIn("not a length", st.alerts[-1][1])
        self.assertEqual(self.doc.snapshot(), self.snap0)
        win.m_rb.IsChecked = True                                       # units -> m, values cleared
        self.assertEqual((win.cur_0.Text, win.by_0.Text), ("3.5000 m", ""))
        self.assertEqual(st.config.values["units"], "m")

    def test_app_button(self):
        st = pyrevit_stubs.install(self.doc)
        with self.assertRaises(pyrevit_stubs.ScriptExit):                # no exe, nothing picked
            runpy.run_path(APP, run_name="__main__")
        self.assertIn("Level Shift by Netbuild.exe was not found", st.alerts[0][1])
        self.assertEqual(st.alerts[0][0], "Level Shift by Netbuild")
        exe = os.path.join(self.tmp, "Netbuild", "LevelShifter", APP_EXE)
        os.makedirs(os.path.dirname(exe))
        open(exe, "w").close()
        runpy.run_path(APP, run_name="__main__")
        psi = st.started[-1]
        self.assertEqual((psi.FileName, psi.Arguments), (exe, '--model "%s"' % self.doc.Title))
        st.picked = os.path.join(self.tmp, "Other.exe")
        runpy.run_path(APP_CONFIG, run_name="__main__")                 # Shift+Click
        self.assertEqual(st.config.values["exe_path"], st.picked)

    def check_about(self, win):
        from level_shift import about
        self.assertEqual(win.Title, "About Level Shift by Netbuild")
        self.assertEqual(win.product_tb.Text, "Level Shift by Netbuild")
        self.assertIn(u"\u00a9 2026 Netbuild. All rights reserved.", win.version_tb.Text)
        self.assertIn(about.VERSION, win.version_tb.Text)
        self.assertIn("Autodesk Revit 2019 - 2026", win.req_tb.Text)
        self.assertIn("pyRevit 4.8", win.req_tb.Text)
        self.assertEqual(win.licence_line_tb.Text, "Licence: Netbuild Software Licence Agreement (proprietary) -- "
                                                   "Proprietary software -- owned by Netbuild. See Licence.")

    def check_licence(self, win):
        from level_shift import about
        self.assertEqual(win.Title, "Licence -- Level Shift by Netbuild")
        self.assertEqual(win.product_tb.Text, "Level Shift by Netbuild  version " + about.VERSION)
        self.assertEqual(win.kind_tb.Text, "Proprietary software -- owned by Netbuild")
        self.assertEqual(win.owner_tb.Text, u"\u00a9 2026 Netbuild. All rights reserved.   |   "
                                            u"Website: https://skaec.com")
        self.assertEqual(win.key_tb.Text, "No licence key required for this product.")
        self.assertEqual(win.license_gb.Header, "Netbuild Software Licence Agreement (proprietary)")
        self.assertEqual(win.license_tb.Text, about.LICENSE_TEXT)

    def test_about_button(self):
        st = pyrevit_stubs.install(self.doc)
        runpy.run_path(ABOUT, run_name="__main__")
        win = pyrevit_stubs.WPFWindow.shown[-1]
        self.check_about(win)
        win.copy_btn.click()
        self.assertIn("Level Shift by Netbuild  version", st.clipboard[-1])
        self.assertIn("Netbuild Software Licence Agreement\n\nCopyright (c) 2026 Netbuild", st.clipboard[-1])
        win.web_btn.click()
        self.assertEqual(st.started[-1], "https://skaec.com")
        win.licence_btn.click()                                           # About -> Licence
        lic = pyrevit_stubs.WPFWindow.shown[-1]
        self.check_licence(lic)
        self.assertIs(lic.Owner, win)

    def test_licence_button(self):
        from level_shift import about
        st = pyrevit_stubs.install(self.doc)
        runpy.run_path(LICENCE, run_name="__main__")
        win = pyrevit_stubs.WPFWindow.shown[-1]
        self.check_licence(win)
        win.copy_btn.click()
        self.assertEqual(st.clipboard[-1], about.LICENSE_TEXT)
        self.assertEqual(win.copy_btn.Content, "Copied")
        win.web_btn.click()
        self.assertEqual(st.started[-1], "https://skaec.com")
        win.close_btn.click()
        self.assertTrue(win.closed)

    def test_level_shift_window_title_and_about(self):
        pyrevit_stubs.install(self.doc)
        runpy.run_path(DIRECT, run_name="__main__")
        win = pyrevit_stubs.WPFWindow.shown[0]
        self.assertTrue(win.Title.startswith("Level Shift by Netbuild 1."), win.Title)
        self.assertTrue(win.Title.endswith(self.doc.Title))
        win.about_btn.click()
        about_win = pyrevit_stubs.WPFWindow.shown[-1]
        self.check_about(about_win)
        self.assertIs(about_win.Owner, win)


if __name__ == "__main__":
    unittest.main()

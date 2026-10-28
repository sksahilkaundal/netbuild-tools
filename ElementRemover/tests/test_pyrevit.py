"""The pyRevit side: shared-file sync, IronPython-2.7 shape, XAML, and the Element Remover button run end to
end against the stand-in Revit model (stub pyRevit/WPF from the shared extension's tests, pyrevit_stubs.py).

    python -m unittest discover -s ElementRemover/tests -v
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
REPO = os.path.dirname(ROOT)
EXT = os.path.join(REPO, "LevelShifter", "pyRevit", "Netbuild.extension")      # the shared Netbuild.extension
BUTTON = os.path.join(EXT, "Netbuild.tab", "Cleanup.panel", "Element Remover.pushbutton", "script.py")
ABOUT = os.path.join(EXT, "Netbuild.tab", "About.panel", "About.pushbutton", "script.py")
LICENCE = os.path.join(EXT, "Netbuild.tab", "About.panel", "Licence.pushbutton", "script.py")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.append(os.path.join(REPO, "LevelShifter", "tests"))     # pyrevit_stubs (shared with Level Shift)
sys.path.append(os.path.join(EXT, "lib"))                         # elementremover_ui, netbuild_about

import pyrevit_stubs  # noqa: E402
from fake_revit import FakeRevit  # noqa: E402
from element_remover import about  # noqa: E402
import elementremover_ui  # noqa: E402
from sync_pyrevit_lib import DST, SHARED, SRC  # noqa: E402

IRONPYTHON_FILES = ([os.path.join(SRC, n) for n in SHARED] + [BUTTON] +
                    [os.path.join(EXT, "lib", n) for n in ("elementremover_ui.py", "netbuild_about.py",
                                                            "netbuild_scripts.py")])


class ExtensionFileTests(unittest.TestCase):
    def test_lib_copies_match_the_source(self):
        self.assertEqual(DST, os.path.join(EXT, "lib", "element_remover"))
        for name in SHARED:
            self.assertTrue(filecmp.cmp(os.path.join(SRC, name), os.path.join(DST, name), shallow=False),
                            "%s differs -- run: python ElementRemover/sync_pyrevit_lib.py" % name)

    def test_ironpython_27_shape(self):
        """No Python-3-only syntax in anything that runs inside Revit (the payload included)."""
        from element_remover.payload import CODE
        sources = [("payload CODE", CODE)]
        for path in IRONPYTHON_FILES:
            with open(path, encoding="utf-8") as f:
                sources.append((path, f.read()))
        for path, src in sources:
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

    def test_xaml_and_labels(self):
        win = ET.fromstring(elementremover_ui.window_xaml())
        names = [e.get(pyrevit_stubs.X_NAME) for e in win.iter() if e.get(pyrevit_stubs.X_NAME)]
        self.assertEqual(len(names), len(set(names)))
        for want in ("ws_lb", "flt_lb", "cat_tb", "any_rb", "all_rb", "groups_cb", "merge_cb", "pinned_cb", "model_cb",
                     "check_btn", "trial_btn", "apply_btn", "about_btn", "licence_btn", "report_lb"):
            self.assertIn(want, names)
        lb = [e for e in win.iter() if e.get(pyrevit_stubs.X_NAME) == "ws_lb"][0]
        self.assertEqual(lb.get("SelectionMode"), "Extended")
        self.assertEqual(elementremover_ui.workset_label({"name": "Site", "elements": 1, "open": False}),
                         "Site   (1 element)   [closed]")
        self.assertEqual(elementremover_ui.filter_label({"name": "Pick", "kind": "selection", "elements": 4}),
                         "Pick   (saved selection, 4 elements)")
        self.assertEqual(elementremover_ui.filter_label({"name": "F", "kind": "rules", "categories": []}),
                         "F   (rules on no categories)")

    def test_icon_title_author_and_layout(self):
        with open(os.path.join(os.path.dirname(BUTTON), "icon.png"), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        with open(BUTTON, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('__author__ = "Netbuild -- skaec.com"', src)
        self.assertIn('__title__ = "Element\\nRemover"', src)
        self.assertIn('__author__ = "Netbuild -- skaec.com"\n\nimport netbuild_scripts\n'
                      'netbuild_scripts.run_live(globals())', src)          # runs from the script folder when set
        with open(os.path.join(EXT, "Netbuild.tab", "bundle.yaml")) as f:
            self.assertEqual(f.read().split(), ["layout:", "-", "Levels", "-", "Models", "-", "Areas", "-", "Sheets", "-", "Stairs",
                                                "-", "Warnings", "-", "Cleanup", "-", "Scripts", "-", "About"])  # About last


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRevit()
        self.doc = self.fake.doc
        self.el = self.fake.el
        self.snap0 = self.doc.snapshot()
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = self.tmp

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open_window(self, answers=None, config=None):
        st = pyrevit_stubs.install(self.doc, answers)
        st.config.values.update(config or {})
        runpy.run_path(BUTTON, run_name="__main__")
        return st, pyrevit_stubs.WPFWindow.shown[0]

    @staticmethod
    def pick(lb, *names):
        lb.SelectedItems.Clear()
        for item in lb.Items:
            if item.split("   (")[0] in names:
                lb.SelectedItems.Add(item)

    @staticmethod
    def report(win):
        return [i.Content for i in win.report_lb.Items]

    def gone(self, *keys):
        return [k for k in keys if not self.doc.alive(self.el[k])]

    def test_window_lists(self):
        st, win = self.open_window()
        self.assertTrue(win.Title.startswith("Element Remover by Netbuild 1."), win.Title)
        self.assertTrue(win.Title.endswith(self.doc.Title))
        self.assertEqual(win.ws_lb.Items, ["Architecture   (16 elements)", "Demolition   (5 elements)",
                                           "Interiors   (9 elements)", "Shared Levels and Grids   (3 elements)",
                                           "Site   (0 elements)   [closed]"])
        self.assertEqual(win.flt_lb.Items, ["All Walls   (rules on Walls)", "Pick list   (saved selection, 4 elements)",
                                            "To Remove   (rules on Doors, Plumbing Fixtures, Walls)"])
        self.assertIn("closed: Site", win.info_tb.Text)
        self.assertEqual((win.groups_cb.IsChecked, win.merge_cb.IsChecked, win.pinned_cb.IsChecked,
                          win.model_cb.IsChecked, win.any_rb.IsChecked), (True, True, False, True, True))
        win.check_btn.click()                                           # nothing picked
        self.assertIn("[FAIL] Targets -- pick at least one workset or filter", self.report(win))
        win.walls_btn.click()
        self.assertEqual(win.cat_tb.Text, "Walls")
        st.answers["pick"] = ["Doors", "Walls"]
        win.cats_btn.click()                                            # Pick... from the categories in use
        self.assertEqual(win.cat_tb.Text, "Doors, Walls")
        self.assertIn("Floors", st.lists[-1][1])
        win.all_cats_btn.click()
        self.assertEqual(win.cat_tb.Text, "")
        self.assertTrue(self.doc.snapshot() == self.snap0)

    def test_check_trial_apply(self):
        st, win = self.open_window()
        self.pick(win.ws_lb, "Demolition")
        win.cat_tb.Text = "Walls"
        win.check_btn.click()
        report = self.report(win)
        self.assertIn("[OK  ] Elements to remove -- 3: 2 standalone, 1 inside model groups", report)
        self.assertTrue([r for r in report if r.startswith("[WARN] Model groups -- 1 group instance(s) (Store)")])
        win.trial_btn.click()
        self.assertTrue(self.doc.snapshot() == self.snap0)
        self.assertTrue([r for r in self.report(win) if "Trial -- rolled back" in r])
        win.apply_btn.click()
        self.assertEqual(st.alerts[-1][0], "Apply")                     # confirmation, with the numbers
        self.assertIn("Remove 3 element(s)", st.alerts[-1][1])
        self.assertEqual(self.gone("demo wall 1", "demo wall 2", "store wall 3", "demo door", "demo slab"),
                         ["demo wall 1", "demo wall 2", "store wall 3", "demo door"])
        self.assertTrue([r for r in self.report(win) if r.startswith("[OK  ] Applied")])
        self.assertIn("Demolition   (2 elements)", win.ws_lb.Items)       # lists re-read after Apply
        self.assertEqual(list(win.ws_lb.SelectedItems), ["Demolition   (2 elements)"])
        logs = os.listdir(os.path.join(self.tmp, "Netbuild", "ElementRemover", "logs"))
        self.assertTrue([n for n in logs if n.endswith("_apply_elements.csv")], logs)
        self.assertTrue([n for n in logs if n.endswith("_apply.log")], logs)
        cfg = st.config.values
        self.assertEqual((cfg["worksets"], cfg["filters"], cfg["categories"], cfg["combine"]),
                         ("Demolition", "", "Walls", "any"))

    def test_apply_declined_or_blocked(self):
        st, win = self.open_window(answers={"alert": False})
        self.pick(win.flt_lb, "To Remove")
        win.apply_btn.click()
        self.assertIn("Remove 5 element(s)", st.alerts[-1][1])
        self.assertIn("share one group type again", st.alerts[-1][1])   # the merge is announced
        self.assertTrue(self.doc.snapshot() == self.snap0)              # "No" -> nothing changed
        self.doc.owners[self.el["wall remove"].Id.Value] = "jane.d"
        win.apply_btn.click()                                           # blocked: no confirmation asked
        self.assertEqual(len(st.alerts), 1)
        self.assertTrue([r for r in self.report(win) if "borrowed by jane.d" in r])
        self.assertTrue(self.doc.snapshot() == self.snap0)

    def test_options_and_both(self):
        st, win = self.open_window(config={"worksets": "Demolition", "filters": "All Walls", "combine": "all",
                                           "skip_pinned": "False", "fix_groups": "false"})
        self.assertEqual(list(win.ws_lb.SelectedItems), ["Demolition   (5 elements)"])   # remembered
        self.assertEqual(list(win.flt_lb.SelectedItems), ["All Walls   (rules on Walls)"])
        self.assertEqual((win.all_rb.IsChecked, win.pinned_cb.IsChecked, win.groups_cb.IsChecked), (True, True, False))
        win.apply_btn.click()
        self.assertEqual(self.gone("demo wall 1", "demo wall 2", "store wall 3", "demo slab"),
                         ["demo wall 1", "demo wall 2"])                # AND walls; group members left alone

    def test_merge_checkbox(self):
        st, win = self.open_window()
        self.pick(win.flt_lb, "To Remove")
        win.merge_cb.IsChecked = False
        win.apply_btn.click()
        self.assertNotIn("share one group type again", st.alerts[-1][1])
        self.assertIs(st.config.values["merge_groups"], False)
        self.assertIn("Toilet Core (2)", self.doc.type_names())         # one type per regrouped instance

    def check_about(self, win):
        self.assertEqual(win.Title, "About Element Remover by Netbuild")
        self.assertEqual(win.product_tb.Text, "Element Remover by Netbuild")
        self.assertIn(u"© 2026 Netbuild. All rights reserved.", win.version_tb.Text)
        self.assertIn(about.VERSION, win.version_tb.Text)
        self.assertIn("Autodesk Revit 2019 - 2026", win.req_tb.Text)
        self.assertEqual(win.licence_line_tb.Text, "Licence: Netbuild Software Licence Agreement (proprietary) -- "
                                                   "Proprietary software -- owned by Netbuild. See Licence.")

    def check_licence(self, win):
        self.assertEqual(win.Title, "Licence -- Element Remover by Netbuild")
        self.assertEqual(win.product_tb.Text, "Element Remover by Netbuild  version " + about.VERSION)
        self.assertEqual(win.kind_tb.Text, "Proprietary software -- owned by Netbuild")
        self.assertEqual(win.owner_tb.Text, u"© 2026 Netbuild. All rights reserved.   |   "
                                            u"Website: https://skaec.com")
        self.assertEqual(win.key_tb.Text, "No licence key required for this product.")
        self.assertEqual(win.license_tb.Text, about.LICENSE_TEXT)

    def test_window_about_and_licence(self):
        st, win = self.open_window()
        win.about_btn.click()
        about_win = pyrevit_stubs.WPFWindow.shown[-1]
        self.check_about(about_win)
        self.assertIs(about_win.Owner, win)
        about_win.licence_btn.click()                                   # About -> Licence
        self.check_licence(pyrevit_stubs.WPFWindow.shown[-1])
        win.licence_btn.click()                                         # the window's own Licence button
        lic = pyrevit_stubs.WPFWindow.shown[-1]
        self.check_licence(lic)
        self.assertIs(lic.Owner, win)
        lic.web_btn.click()
        self.assertEqual(st.started[-1], "https://skaec.com")

    def test_ribbon_about_and_licence_list_this_product(self):
        st = pyrevit_stubs.install(self.doc, answers={"pick": "Element Remover by Netbuild"})
        runpy.run_path(ABOUT, run_name="__main__")
        self.assertIn("Element Remover by Netbuild", st.lists[-1][1])      # listed with every Netbuild product
        self.check_about(pyrevit_stubs.WPFWindow.shown[-1])
        runpy.run_path(LICENCE, run_name="__main__")
        self.check_licence(pyrevit_stubs.WPFWindow.shown[-1])

    def test_refuses_family_and_read_only(self):
        self.doc.IsReadOnly = True
        st = pyrevit_stubs.install(self.doc)
        with self.assertRaises(pyrevit_stubs.ScriptExit):
            runpy.run_path(BUTTON, run_name="__main__")
        self.assertIn("is read-only", st.alerts[-1][1])


if __name__ == "__main__":
    unittest.main()

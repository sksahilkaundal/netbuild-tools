"""Clear Warnings by Netbuild: the engine on a stand-in B001 model (fake_warnings.py), its About / Licence, and
both Warnings-panel buttons run end to end with stub pyRevit / WPF (pyrevit_stubs.py).

    python -m unittest discover -s LevelShifter/tests -v
"""

import ast
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
PANEL = os.path.join(EXT, "Netbuild.tab", "Warnings.panel")
CLEAR = os.path.join(PANEL, "Clear Warnings.pushbutton", "script.py")
SUMMARY = os.path.join(PANEL, "Warnings Summary.pushbutton", "script.py")
ABOUT = os.path.join(EXT, "Netbuild.tab", "About.panel", "About.pushbutton", "script.py")
sys.path.insert(0, HERE)
sys.path.append(os.path.join(EXT, "lib"))

import fake_warnings as fw  # noqa: E402
import pyrevit_stubs  # noqa: E402
from clear_warnings import about, core  # noqa: E402
import clearwarnings_ui  # noqa: E402

DB = fw.DB


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.doc = fw.b001_model()

    def test_summary_and_b001_profile(self):
        s = core.summary(self.doc, DB)
        self.assertEqual(s["total"], 17)
        self.assertEqual(s["groups"][0], (fw.AREA_TEXT, 6))
        self.assertIn((fw.OVERLAP_TEXT, 4), s["groups"])
        self.assertEqual(s["area"], 10)                       # 6 Areas + 4 overlaps of Area Separation Lines
        ok, text = core.profile(s)
        self.assertTrue(ok)
        self.assertIn("10 of 17 warnings (59%)", text)
        self.assertIn("matches the B001 profile", text)
        self.assertEqual(core.profile({"total": 0, "groups": [], "area": 0}), (False, "No warnings in this model."))
        self.assertFalse(core.profile({"total": 10, "groups": [], "area": 2})[0])
        lines = core.summary_lines(s, top=2)
        self.assertEqual(lines[0], ("head", "Warnings: 17"))
        self.assertEqual(lines[-1][1], "       7  ... 4 more group(s)")

    def test_dry_run_changes_nothing(self):
        state = self.doc.state()
        out = core.run(self.doc, DB)
        self.assertEqual(self.doc.state(), state)
        self.assertEqual(self.doc.log, [])                     # no transaction at all
        targeted = dict((s["key"], s["targeted"]) for s in out["steps"])
        self.assertEqual(targeted, {"area_plans": 3, "areas": 6, "area_lines": 8, "matchlines": 1,
                                    "room_tags": 1, "type_marks": 5})
        self.assertIs(out["after"], out["before"])
        report = [t for _, t in core.report_lines(out)]
        self.assertTrue(report[0].startswith("Dry run (nothing changed)"))
        self.assertIn("  4. Delete orphaned Matchlines (no owner view): 1 would be deleted", report)

    def test_run_all_six_steps(self):
        live, placed = self.doc.live_matchline.Id.Value, self.doc.placed_tag.Id.Value
        out = core.run(self.doc, DB, apply=True)
        self.assertTrue(out["committed"])
        self.assertEqual((out["before"]["total"], out["after"]["total"]), (17, 3))
        self.assertEqual(sorted(t for t, _ in out["after"]["groups"]), sorted([fw.WALLS_TEXT, fw.OFF_AXIS_TEXT,
                                                                                fw.TAG_TEXT]))
        steps = dict((s["key"], s) for s in out["steps"])
        self.assertEqual(steps["area_plans"]["done"], 9)        # 2 plans + 1 schedule + 6 Areas with them
        self.assertEqual(steps["areas"]["targeted"], 0)          # already gone with their plans
        self.assertEqual(steps["area_lines"]["done"], 8)
        self.assertEqual(steps["type_marks"]["done"], 5)
        names = [e.Name for e in self.doc.of(lambda e: isinstance(e, (fw.ViewPlan, fw.ViewSchedule)))]
        self.assertEqual(names, ["L01 GA Plan", "Area Plan template", "Door Schedule", "Revision Schedule"])
        marks = dict((t.Name, t.params["ALL_MODEL_TYPE_MARK"]) for t in self.doc.of(lambda e: e.is_type))
        self.assertEqual(marks, {"Wall 200mm": "W1-200", "Wall 100mm": "W1-100", "Ritz Door 900": "RITZ-D1",
                                 "Double Door": "D1b", "Single Door": "D1c", "Existing": "D1a"})
        # one Undo entry: every step's transaction inside one assimilated group
        self.assertEqual(self.doc.log[0], ("group", "Clear Warnings by Netbuild"))
        self.assertEqual(self.doc.log[-1], ("assimilate", "Clear Warnings by Netbuild"))
        self.assertEqual(len([e for e in self.doc.log if e[0] == "commit"]), 5)    # step 2 had nothing left
        # what the script leaves alone on purpose is listed for review, by Id
        review = core.review_items(out)
        self.assertEqual(len(review), 2)
        self.assertIn("Matchline [%d] in view 'L01 GA Plan' is live" % live, review[0])
        self.assertIn("Room Tag [%d] in view 'L01 GA Plan' (room L01-001 [%d]) has a valid room" % (
            placed, self.doc.placed_tag.Room.Id.Value), review[1])
        self.assertIn("2 live Matchline(s) left untouched", steps["matchlines"]["lines"][0])   # 1 in a warning
        report = [t for _, t in core.report_lines(out)]
        self.assertIn("Warnings: 17 before -> 3 after (-14)", report)
        self.assertIn("       6 -> 0      " + fw.AREA_TEXT, report)
        self.assertIn("Manual review: 2 item(s) -- left alone on purpose", report)

    def test_active_area_plan_is_kept_for_review(self):
        plan = self.doc.of(lambda e: isinstance(e, fw.ViewPlan) and e.Name == "L01 Area Plan GFA")[0]
        self.doc.ActiveView = plan
        out = core.run(self.doc, DB, ["area_plans"], apply=True)
        self.assertIsNotNone(self.doc.GetElement(plan.Id))
        self.assertIn("is the active view", core.review_items(out)[0])

    def test_a_revit_error_rolls_everything_back(self):
        state = self.doc.state()
        self.doc.fail_on_commit = "Delete all Area Separation Lines"
        with self.assertRaises(Exception):
            core.run(self.doc, DB, apply=True)
        self.assertEqual(self.doc.state(), state)
        self.assertEqual(self.doc.log[-1], ("group rollback", "Clear Warnings by Netbuild"))

    def test_chosen_steps_only(self):
        out = core.run(self.doc, DB, ["matchlines", "room_tags"], apply=True)
        self.assertEqual([s["key"] for s in out["steps"]], ["matchlines", "room_tags"])
        self.assertEqual(out["after"]["total"], 15)

    def test_type_mark_rules_and_helpers(self):
        self.assertEqual(core.parse_rules(core.DEFAULT_RULES), [("ritz", "RITZ-"), ("dormakaba", "DK-")])
        self.assertEqual(core.parse_rules(" Kaba = K- ;\n"), [("kaba", "K-")])
        self.assertEqual(core.parse_rules(""), [])
        for bad in ("ritz", "a=b=c", "=X-"):
            with self.assertRaises(ValueError):
                core.parse_rules(bad)
        self.assertEqual(core.numeric_token("Wall 200mm Red"), "200R")
        self.assertEqual(core.numeric_token("Glazing 12"), "12")
        self.assertIsNone(core.numeric_token("Glazing"))
        info = [(1, "Doors", "Ritz 900", "D1"), (2, "Doors", "Ritz 1000", "D1"), (3, "Doors", "Plain", "D1")]
        self.assertEqual(core.plan_group(info, [("ritz", "RITZ-")]),
                         {1: "RITZ-D1", 2: "RITZ-D1-1000", 3: "D1a"})
        self.assertEqual(core.int_id(fw.OldElementId(42)), 42)          # Revit 2023 and older
        self.assertEqual(core.int_id(fw.ElementId(43)), 43)


class AboutTests(unittest.TestCase):
    def test_product_info_and_license(self):
        with open(os.path.join(os.path.dirname(ROOT), "LICENSE"), encoding="utf-8") as f:
            self.assertEqual(about.LICENSE_TEXT, f.read())
        self.assertEqual(about.PRODUCT, "Clear Warnings by Netbuild")
        self.assertEqual((about.OWNER, about.PUBLISHER, about.WEBSITE), ("Netbuild", "Netbuild", "https://skaec.com"))
        self.assertEqual(about.COPYRIGHT, u"© 2026 Netbuild. All rights reserved.")
        self.assertEqual(about.LICENSE_NAME, "Netbuild Software Licence Agreement (proprietary)")
        self.assertEqual(about.LICENCE_KEY, "No licence key required for this product.")
        self.assertEqual(about.title("B002"), "Clear Warnings by Netbuild %s -- B002" % about.VERSION)
        self.assertEqual(core.UNDO_NAME, about.PRODUCT)
        text = about.about_text()
        for want in ("Autodesk Revit 2019 - 2026", "pyRevit 4.8", "Licence: Netbuild Software Licence Agreement",
                     about.LICENSE_TEXT.rstrip()):
            self.assertIn(want, text)
        self.assertIn(about.LICENSE_TEXT.rstrip(), about.licence_text())

    def test_listed_with_the_netbuild_products(self):
        pyrevit_stubs.install(fw.b001_model())
        import netbuild_about
        self.assertIn(about, netbuild_about.PRODUCTS)


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.doc = fw.b001_model("ProjectC-Studio-BIM-B002-ZZZ-BM-950001")
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = self.tmp

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self, **answers):
        st = pyrevit_stubs.install(self.doc, answers=answers)
        sys.modules["pyrevit"].DB = DB
        return st

    def test_files(self):
        for path in (CLEAR, SUMMARY):
            with open(os.path.join(os.path.dirname(path), "icon.png"), "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        for path in [CLEAR, SUMMARY, os.path.join(EXT, "lib", "clearwarnings_ui.py")] + [
                os.path.join(EXT, "lib", "clear_warnings", n) for n in ("__init__.py", "about.py", "core.py")]:
            with open(path, encoding="utf-8") as f:
                src = f.read()
            self.assertTrue(src.isascii(), path)                       # IronPython reads it
            for node in ast.walk(ast.parse(src)):
                self.assertNotIsInstance(node, ast.JoinedStr, path)
        with open(os.path.join(PANEL, "bundle.yaml")) as f:
            self.assertEqual(f.read().split(), ["layout:", "-", "Warnings", "Summary", "-", "Clear", "Warnings"])
        win = ET.fromstring(clearwarnings_ui.window_xaml())
        names = [e.get(pyrevit_stubs.X_NAME) for e in win.iter() if e.get(pyrevit_stubs.X_NAME)]
        self.assertEqual([n for n in names if n.startswith("step_")], ["step_%d" % i for i in range(6)])

    def test_clear_warnings_window(self):
        st = self.install()
        runpy.run_path(CLEAR, run_name="__main__")
        win = pyrevit_stubs.WPFWindow.shown[0]
        self.assertEqual(win.Title, "Clear Warnings by Netbuild %s -- %s" % (about.VERSION, self.doc.Title))
        self.assertIn("ProjectC-Studio-BIM-B002-ZZZ-BM-950001", win.model_tb.Text)
        self.assertIn("17 warnings.", win.profile_tb.Text)
        self.assertIn("matches the B001 profile", win.profile_tb.Text)
        self.assertEqual(win.report_lb.Items[0].Content, "Warnings now: 17")
        self.assertEqual(win.rules_tb.Text, core.DEFAULT_RULES)
        state = self.doc.state()
        win.dry_btn.click()
        self.assertEqual(self.doc.state(), state)
        self.assertIn("Dry run: nothing changed. 2 item(s)", win.status_tb.Text)
        win.rules_tb.Text = "ritz"                                     # a bad rule stops before anything runs
        win.run_btn.click()
        self.assertIn("write keyword=PREFIX", st.alerts[-1][1])
        win.rules_tb.Text = core.DEFAULT_RULES
        win.step_0.IsChecked = False                                   # keep the Area Plans this time
        win.run_btn.click()
        self.assertEqual(st.alerts[-1][0], "Run")                       # confirmation asked first
        self.assertIn("Run these steps on ProjectC-Studio-BIM-B002", st.alerts[-1][1])
        self.assertNotIn("1. Delete Area Plan", st.alerts[-1][1])
        self.assertEqual(len(self.doc.of(lambda e: isinstance(e, fw.ViewPlan))), 4)
        self.assertIn("Done: 17 -> 3 warnings, 2 item(s) for manual review", win.status_tb.Text)
        report = [i.Content for i in win.report_lb.Items]
        self.assertIn("Warnings: 17 before -> 3 after (-14)", report)
        self.assertTrue([r for r in report if "Room Tag [" in r and "move it into its room by hand" in r])
        self.assertEqual(st.config.values["steps_off"], "area_plans")
        logs = os.listdir(os.path.join(self.tmp, "Netbuild", "ClearWarnings", "logs"))
        self.assertEqual(sorted(n.split("_", 2)[-1] for n in logs), ["dry_run.log", "run.log"])
        win.copy_btn.click()
        self.assertIn("Manual review: 2 item(s)", st.clipboard[-1])
        win.about_btn.click()
        about_win = pyrevit_stubs.WPFWindow.shown[-1]
        self.assertEqual(about_win.Title, "About Clear Warnings by Netbuild")
        self.assertIs(about_win.Owner, win)

    def test_run_cancelled_or_failing(self):
        st = self.install(alert=False)
        runpy.run_path(CLEAR, run_name="__main__")
        win = pyrevit_stubs.WPFWindow.shown[0]
        state = self.doc.state()
        win.run_btn.click()                                            # "No" at the confirmation
        self.assertEqual(self.doc.state(), state)
        st.answers["alert"] = True
        self.doc.fail_on_commit = "Delete orphaned Room Tags (dangling room reference)"
        win.run_btn.click()
        self.assertEqual(self.doc.state(), state)
        self.assertIn("Run stopped -- nothing was changed", win.report_lb.Items[0].Content)

    def test_read_only_model(self):
        self.doc.IsReadOnly = True
        st = self.install()
        with self.assertRaises(pyrevit_stubs.ScriptExit):
            runpy.run_path(CLEAR, run_name="__main__")
        self.assertIn("is read-only", st.alerts[-1][1])

    def test_warnings_summary_button(self):
        st = self.install()
        runpy.run_path(SUMMARY, run_name="__main__")
        self.assertEqual(st.printed[0], "## Warnings: 17 -- ProjectC-Studio-BIM-B002-ZZZ-BM-950001")
        self.assertIn("matches the B001 profile", st.printed[1])
        self.assertIn("| 6 | %s |" % fw.AREA_TEXT, st.printed[2])
        self.assertEqual(self.doc.log, [])                              # read-only

    def test_netbuild_about_button_lists_every_product(self):
        st = self.install(pick="Clear Warnings by Netbuild")
        runpy.run_path(ABOUT, run_name="__main__")
        self.assertEqual(st.lists[-1][1], ["Level Shift by Netbuild", "BUA Update by Netbuild",
                                           "Clear Warnings by Netbuild"])
        self.assertEqual(pyrevit_stubs.WPFWindow.shown[-1].Title, "About Clear Warnings by Netbuild")


if __name__ == "__main__":
    unittest.main()

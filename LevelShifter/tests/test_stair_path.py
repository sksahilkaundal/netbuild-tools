"""Stair Path by Netbuild: the office-standard rules, the engine (Check / Trial run / Apply) against the stand-in
model (fake_stairs.py), and the ribbon button end to end (stub pyRevit, see pyrevit_stubs.py).

    python -m unittest discover -s LevelShifter/tests -v
"""

import io
import json
import os
import runpy
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXT = os.path.join(ROOT, "pyRevit", "Netbuild.extension")
BUTTON = os.path.join(EXT, "Netbuild.tab", "Stairs.panel", "Stair Path.pushbutton", "script.py")
sys.path.insert(0, HERE)
sys.path.append(os.path.join(EXT, "lib"))

import fake_stairs  # noqa: E402
import pyrevit_stubs  # noqa: E402
from stair_path import about, rules  # noqa: E402

FIXED, AUTO = rules.FIXED, rules.AUTO


def mm(v):
    return round(v * 304.8, 3)


def stair(box, run):
    return {"id": 1, "box": box, "run": run}


class RulesTests(unittest.TestCase):
    def test_type_names_are_matched_loosely(self):
        for name, scale in (("Standard 1-500", 500), ("Standard 1:200", 200), ("1/100 Standard", 100),
                            ("Standard 1 - 100 (Studio)", 100), ("Standard_1_200", 200), ("Standard 200", 200),
                            ("Standard", None), ("Standard 1-1000", 1000)):
            self.assertEqual(rules.type_scale(name), scale, name)
        self.assertEqual(rules.family_kind("Fixed Up Direction"), FIXED)
        self.assertEqual(rules.family_kind("automatic up-down direction"), AUTO)
        self.assertIsNone(rules.family_kind("Stair Path"))
        types = [{"id": 1, "family": AUTO, "name": "Studio 1-100 bold"}, {"id": 2, "family": AUTO, "name": "Standard 1-100"},
                 {"id": 3, "family": FIXED, "name": "Standard 1-100"}, {"id": 4, "family": AUTO, "name": "Standard"}]
        self.assertEqual(rules.pick_type(types, AUTO, 100)["id"], 2)            # 'Standard' first
        self.assertEqual(rules.pick_type(types, FIXED, 100)["id"], 3)
        self.assertIsNone(rules.pick_type(types, FIXED, 200))
        self.assertEqual(rules.missing_types(types, [500, 100, 100]), [(AUTO, 500)])
        self.assertEqual(rules.missing_types(types, [200]), [(FIXED, 200), (AUTO, 200)])
        src, new = rules.type_to_create(types, AUTO, 500)
        self.assertEqual((src["id"], new), (4, "Standard 1-500"))                # duplicated from plain 'Standard'

    def test_style_per_scale_and_case(self):
        self.assertEqual(rules.style(500, "up"), (AUTO, False, False, ()))       # arrows only
        self.assertEqual(rules.style(500, "down"), (AUTO, False, False, ()))
        self.assertEqual(rules.style(200, "up"), (FIXED, True, None, ("up",)))   # no Show Down Text on Fixed
        self.assertEqual(rules.style(100, "down"), (AUTO, False, True, ("down",)))
        self.assertEqual(rules.style(100, "through"), (AUTO, True, True, ("up", "down")))
        self.assertEqual(rules.style(200, "sweep"), (AUTO, True, True, ("up", "down")))

    def test_text_offset_away_from_the_run(self):
        s = rules.settings({"dir_x_mm": 300, "dir_y_mm": 250})
        along_x, along_y = (0, 0, 6, 2), (0, 0, 2, 6)                            # length > width / width > length
        self.assertEqual(rules.text_offset(stair(along_x, (5, 0)), 200, s), (-300.0, 0.0))   # +X run -> -X side
        self.assertEqual(rules.text_offset(stair(along_x, (-5, 0)), 200, s), (600.0, 0.0))   # -X run -> std +X
        self.assertEqual(rules.text_offset(stair(along_x, (-5, 0)), 100, s), (400.0, 0.0))
        self.assertEqual(rules.text_offset(stair(along_y, (0, 5)), 100, s), (0.0, -250.0))   # +Y run -> -Y
        self.assertEqual(rules.text_offset(stair(along_y, (0, -5)), 100, s), (0.0, 250.0))   # -Y run -> +Y
        self.assertEqual(rules.text_offset(stair(along_y, (0, 0)), 200, s), (0.0, 200.0))    # unknown -> std
        self.assertEqual(rules.text_offset(stair((0, 0, 4, 4), (5, 0)), 200, s), (-300.0, 0.0))  # square -> X
        self.assertEqual(rules.text_offset(stair(along_x, (5, 0)), 500, s), (0.0, 0.0))
        flat = rules.settings({"directional": False})
        self.assertEqual(rules.text_offset(stair(along_x, (5, 0)), 200, flat), (600.0, 0.0))
        self.assertEqual(rules.text_offset(stair(along_y, (0, 5)), 200, flat), (0.0, 200.0))

    def test_settings(self):
        s = rules.settings({"dir_x_mm": "450", "sweep": "false", "views": "bogus", "nope": 1, "dir_y_mm": "x"})
        self.assertEqual((s["dir_x_mm"], s["sweep"], s["views"], s["dir_y_mm"]), (450.0, False, "open", 300.0))
        self.assertNotIn("nope", s)
        bad = rules.check_settings(rules.settings({"core_tol_mm": 0, "tag_nudge_mm": -5, "views": "name",
                                                   "name_filter": " "}))
        self.assertEqual(sorted(c.label for c in bad), ["Setting core_tol_mm", "Setting tag_nudge_mm", "Views"])

    def test_cores_levels_and_pass_through(self):
        f = 1 / 304.8
        levels = [{"id": i, "name": n, "elev": e * f} for i, (n, e) in enumerate(
            (("GF", 0), ("L01", 3500), ("L02", 7000), ("L03", 10500)))]
        a, b = (0, 0, 2500 * f, 6000 * f), (20000 * f, 0, 26000 * f, 2500 * f)
        stairs = [
            {"id": 11, "base": "GF", "top": "L01", "base_elev": 0, "top_elev": 3500 * f, "box": a},
            {"id": 12, "base": "GF", "top": "L02", "base_elev": 3510 * f, "top_elev": 7000 * f, "box": a},  # offset
            {"id": 9, "base": "L01", "top": "L02", "base_elev": 3500 * f, "top_elev": 7000 * f, "box": a},  # older
            {"id": 20, "base": "GF", "top": "L03", "base_elev": 0, "top_elev": 10500 * f, "box": b},
            {"id": 30, "base": "L01", "top": "L01", "base_elev": 3500 * f, "top_elev": 3500 * f, "box": a},
        ]
        cores, skipped, notes = rules.build_cores(stairs, levels, rules.settings())
        self.assertEqual([c["name"] for c in cores], ["Core A", "Core B"])
        self.assertEqual([(x["id"], x["base"], x["top"]) for x in cores[0]["flights"]],
                         [(11, "GF", "L01"), (9, "L01", "L02"), (12, "L01", "L02")])
        self.assertEqual(skipped[0][0], 30)
        self.assertEqual(notes, [(12, "base L01 (parameter: GF)")])
        ups, downs = rules.up_down(cores)
        self.assertEqual(ups["L01"], [("Core A", 12)])                         # newest duplicate wins
        self.assertEqual(downs["L02"], [("Core A", 12)])
        self.assertEqual(rules.pass_through(cores, levels, "L01"), {"Core B": 20})
        self.assertEqual(rules.pass_through(cores, levels, "L02"), {"Core B": 20})
        self.assertEqual(rules.pass_through(cores, levels, "GF"), {})
        self.assertEqual(rules.snap_level(levels, 3700 * f, 300 * f), "L01")
        self.assertIsNone(rules.snap_level(levels, 5000 * f, 300 * f))


class EngineTests(unittest.TestCase):
    def setUp(self):
        fake_stairs.install_stubs()
        from stair_path import engine
        self.engine = engine
        self.m = fake_stairs.Model()
        self.doc = self.m.doc

    def run_engine(self, action, **values):
        r = self.engine.Run(self.doc, self.m.uidoc, values)
        r.run(action)
        return r

    def text(self, r):
        return "\n".join([str(c) for c in r.checks] + r.lines)

    def by_view(self):
        out = {}
        for p in self.doc.paths():
            out.setdefault(self.doc.by_id[p.OwnerViewId.Value].Name, []).append(p)
        return out

    def find(self, view, sid):
        hits = [p for p in self.by_view()[view] if p.StairsId.HostElementId.Value == sid]
        self.assertEqual(len(hits), 1, (view, sid))
        return hits[0]

    def type_of(self, p):
        t = self.doc.by_id[p.GetTypeId().Value]
        return (t.family, t.Name)

    def test_check_changes_nothing(self):
        before = [p.Id.Value for p in self.doc.paths()]
        r = self.run_engine("plan")
        self.assertTrue(r.ok(), self.text(r))
        self.assertEqual([p.Id.Value for p in self.doc.paths()], before)
        self.assertEqual((self.doc.names, self.doc.groups), ([], []))           # no transaction at all
        out = self.text(r)
        self.assertIn("[OK  ] Target views -- 5 open plan views", out)
        self.assertIn("[WARN] Views at other scales -- skipped", out)
        self.assertIn("L01 Stair Detail (1:50)", out)
        self.assertIn("[OK  ] Stair cores -- 2 core(s), 6 flight(s) of 7 stairs", out)
        self.assertIn("Core A: 4 flight(s) GF -> L03", out)
        self.assertIn("300 does not climb", out)
        self.assertIn("102 base L01 (parameter: GF)", out)
        self.assertIn("L02 GA Plan (1:100, L02): Up x2, Down x2", out)
        self.assertIn("L03 Part Plan 01: Core B Down (stair 202) is outside the crop region -- skipped", out)

    def test_apply(self):
        r = self.run_engine("apply")
        self.assertTrue(r.ok(), self.text(r))
        self.assertEqual(self.doc.groups, ["Stair Path by Netbuild"])          # one Undo entry
        self.assertEqual(self.doc.group_result, "assimilated")
        views = self.by_view()
        self.assertNotIn(self.m.old.Id.Value, self.doc.by_id)                   # cleared in the target views
        self.assertIn(self.m.kept.Id.Value, self.doc.by_id)                     # the detail view is not a target
        # 1:500 -- Automatic Up/Down, arrows only (Up of each core + the bystander flight 101)
        self.assertEqual(sorted(p.StairsId.HostElementId.Value for p in views["GF GA Plan"]), [101, 150, 201])
        for p in views["GF GA Plan"]:
            self.assertEqual(self.type_of(p), (AUTO, "Standard 1-500"))
            self.assertEqual((p.ShowUpText, p.ShowDownText), (False, False))
        # 1:200 at L01 -- Up: Fixed Up, text against its -Y run; Down: Automatic, Down text only
        up = self.find("L01 GA Plan", 102)
        self.assertEqual(self.type_of(up), (FIXED, "Standard 1-200"))
        self.assertTrue(up.ShowUpText)
        self.assertEqual((mm(up.UpTextOffset.X), mm(up.UpTextOffset.Y)), (0, 300))
        with self.assertRaises(ValueError):
            up.ShowDownText                                                     # Fixed Up has none -- never set
        down = self.find("L01 GA Plan", 101)
        self.assertEqual(self.type_of(down), (AUTO, "Standard 1-200"))
        self.assertEqual((down.ShowUpText, down.ShowDownText), (False, True))
        self.assertEqual((mm(down.DownTextOffset.X), mm(down.DownTextOffset.Y)), (0, -300))
        # sweep at L01: the flight passing through, the newer duplicate and the stub -- both texts
        for sid in (150, 201, 300):
            p = self.find("L01 GA Plan", sid)
            self.assertEqual((self.type_of(p), p.ShowUpText, p.ShowDownText),
                             ((AUTO, "Standard 1-200"), True, True), sid)
        p201 = self.find("L01 GA Plan", 201)
        self.assertEqual((mm(p201.UpTextOffset.X), mm(p201.DownTextOffset.X)), (-300, -300))   # +X run
        # 1:100 at L02 -- Up x2; Down of core A via the flight passing through (102 hidden); core B is a gap
        self.assertEqual(self.type_of(self.find("L02 GA Plan", 103)), (FIXED, "Standard 1:100"))
        b_up = self.find("L02 GA Plan", 202)
        self.assertEqual((mm(b_up.UpTextOffset.X), mm(b_up.UpTextOffset.Y)), (400, 0))    # -X run: std +X
        through = self.find("L02 GA Plan", 150)
        self.assertEqual((self.type_of(through), through.ShowUpText, through.ShowDownText),
                         ((AUTO, "Standard 1-100"), True, True))
        self.assertEqual(len(views["L02 GA Plan"]), 3)
        # part plan at L03: only core A is inside the crop
        self.assertEqual(sorted(p.StairsId.HostElementId.Value for p in views["L03 Part Plan 01"]), [103, 150])
        self.assertEqual([p.Id.Value for p in views["L01 Stair Detail"]], [self.m.kept.Id.Value])   # 1:50: untouched
        out = self.text(r)
        self.assertIn("[OK  ] Up / Down placed -- 8 (1 Down via a flight passing through the level)", out)
        self.assertIn("[OK  ] Other visible stairs tagged -- 5", out)
        self.assertIn("[OK  ] Cleared -- 1 existing stair path(s) in the target views", out)
        self.assertIn("[WARN] Down gaps -- 1 level(s) without Down", out)
        self.assertIn("GAP L02 GA Plan (L02): Core B Down -- stair 201 is not visible in this view and no flight "
                      "of Core B passes through L02. View Range is set by view template 'GA 1-100'", out)
        self.assertIn("[WARN] Dimension strings -- 1 overlap(s)", out)
        self.assertIn("[OK  ] Room tags -- 1 nudged off a stair path, 1 Staircase tag(s) moved back", out)
        # room tags: the one on core A moved up 300, the Staircase tag back to its room's centre, the free one kept
        self.assertEqual((mm(self.m.office_tag.Location.Point.X), mm(self.m.office_tag.Location.Point.Y)),
                         (2400, 3300))
        self.assertEqual((mm(self.m.stair_tag.Location.Point.X), mm(self.m.stair_tag.Location.Point.Y)),
                         (1250, 3000))
        self.assertEqual(mm(self.m.free_tag.Location.Point.Y), 5000)
        rows = dict(((x["view"], x["stair"], x["kind"]), x["result"]) for x in r.rows)
        self.assertEqual(rows[("L02 GA Plan", 150, "down")], "through")
        self.assertEqual(rows[("L02 GA Plan", 201, "down")], "gap")

    def test_trial_rolls_back(self):
        before = [(p.Id.Value, p.OwnerViewId.Value) for p in self.doc.paths()]
        tag = self.m.office_tag.Location.Point
        r = self.run_engine("trial")
        self.assertTrue(r.ok(), self.text(r))
        self.assertIn("[OK  ] Trial -- rolled back -- the model is unchanged", self.text(r))
        self.assertEqual([(p.Id.Value, p.OwnerViewId.Value) for p in self.doc.paths()], before)
        self.assertIs(self.m.office_tag.Location.Point, tag)
        self.assertEqual(self.doc.group_result, "rolled back")
        self.assertEqual(len([x for x in r.rows if x["result"] in ("placed", "through")]), 13)

    def test_missing_types(self):
        self.m = fake_stairs.Model(drop_types=[(FIXED, "Standard 1:100"), (AUTO, "Standard 1-500")])
        self.doc = self.m.doc
        r = self.run_engine("apply")
        self.assertFalse(r.ok())
        out = self.text(r)
        self.assertIn("[FAIL] Stair path type Fixed Up Direction : 1-100 -- not in the model", out)
        self.assertIn("[FAIL] Not run -- fix the FAIL lines first", out)
        self.assertEqual(self.doc.groups, [])
        r = self.run_engine("apply", create_types=True)
        self.assertTrue(r.ok(), self.text(r))
        self.assertIn("[OK  ] Stair path types created -- Automatic Up/Down Direction : Standard 1-500, "
                      "Fixed Up Direction : Standard 1-100", self.text(r))
        self.assertEqual(self.type_of(self.find("L02 GA Plan", 103)), (FIXED, "Standard 1-100"))

    def test_views_by_name_and_clear_whole_model(self):
        r = self.run_engine("apply", views="name", name_filter="ga plan", clear="model", room_tags=False,
                            sweep=False)
        self.assertTrue(r.ok(), self.text(r))
        self.assertIn("Target views -- 4 plan views named '*ga plan*'", self.text(r))
        self.assertNotIn(self.m.kept.Id.Value, self.doc.by_id)                  # whole model cleared
        views = self.by_view()
        self.assertEqual(sorted(views), ["GF GA Plan", "L01 GA Plan", "L02 GA Plan"])   # Roof: nothing up / down
        self.assertEqual(mm(self.m.office_tag.Location.Point.Y), 3000)          # room tags left alone

    def test_nothing_to_do(self):
        self.m.open = []
        r = self.run_engine("trial")
        self.assertIn("[FAIL] Target views -- no open plan views", self.text(r))


class ButtonTests(unittest.TestCase):
    def setUp(self):
        fake_stairs.install_stubs()
        self.m = fake_stairs.Model()
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = self.tmp

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, answers=None, config=None):
        st = pyrevit_stubs.install(self.m.doc, answers)
        st.config = config or st.config                     # the button's saved pyRevit config
        sys.modules["pyrevit.revit"].uidoc = self.m.uidoc
        runpy.run_path(BUTTON, run_name="__main__")
        return st, pyrevit_stubs.WPFWindow.shown[0]

    def test_window_runs_and_keeps_settings_per_model(self):
        st, win = self.start()
        self.assertEqual(win.Title, "Stair Path by Netbuild %s -- Tower_B001" % about.VERSION)
        self.assertEqual((win.dir_x_mm_tb.Text, win.std_x_100_tb.Text, win.open_rb.IsChecked,
                          win.clear_views_rb.IsChecked, win.sweep_cb.IsChecked), ("300", "400", True, True, True))
        win.check_btn.click()
        report = [i.Content for i in win.report_lb.Items]
        self.assertEqual(report[0], "Check")
        self.assertIn("[OK  ] Stair cores -- 2 core(s), 6 flight(s) of 7 stairs", report)
        self.assertEqual(self.m.doc.groups, [])
        win.dir_y_mm_tb.type("350")
        win.apply_btn.click()
        self.assertEqual(st.alerts[-1][0], "Apply")                             # confirmation asked first
        self.assertEqual(self.m.doc.group_result, "assimilated")
        down = [p for p in self.m.doc.paths() if p.OwnerViewId == self.m.v["L01"].Id and
                p.StairsId.HostElementId.Value == 101][0]
        self.assertEqual(mm(down.DownTextOffset.Y), -350)
        self.assertIn("Apply: OK", win.status_tb.Text)
        logs = os.listdir(os.path.join(self.tmp, "Netbuild", "StairPath", "logs"))
        csv_name = [n for n in logs if n.endswith("_apply_stair_paths.csv")][0]
        with io.open(os.path.join(self.tmp, "Netbuild", "StairPath", "logs", csv_name), encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], "view,scale,level,core,kind,stair,result,path,offset_mm,why")
        self.assertTrue([l for l in lines if l.startswith("L02 GA Plan,100,L02,Core A,down,150,through,")])
        saved = json.loads(st.config.values["models"])
        self.assertEqual(saved["Tower_B001"]["dir_y_mm"], 350.0)                # kept for this model only
        _, win2 = self.start(config=st.config)
        self.assertEqual(win2.dir_y_mm_tb.Text, "350")
        win2.defaults_btn.click()
        self.assertEqual(win2.dir_y_mm_tb.Text, "300")

    def test_bad_number_and_about(self):
        st, win = self.start()
        win.core_tol_mm_tb.type("abc")
        win.trial_btn.click()
        self.assertIn("'abc' is not a number", st.alerts[-1][1])
        self.assertEqual(self.m.doc.groups, [])
        win.about_btn.click()
        ab = pyrevit_stubs.WPFWindow.shown[-1]
        self.assertEqual(ab.Title, "About Stair Path by Netbuild")
        self.assertIs(ab.Owner, win)
        self.assertIn("Autodesk Revit 2019 - 2026", ab.req_tb.Text)
        ab.licence_btn.click()
        lic = pyrevit_stubs.WPFWindow.shown[-1]
        self.assertEqual(lic.key_tb.Text, "No licence key required for this product.")
        self.assertEqual(lic.license_tb.Text, about.LICENSE_TEXT)

    def test_ribbon_about_lists_every_product(self):
        st = pyrevit_stubs.install(self.m.doc, {"pick": "Stair Path by Netbuild"})
        runpy.run_path(os.path.join(EXT, "Netbuild.tab", "About.panel", "About.pushbutton", "script.py"),
                       run_name="__main__")
        self.assertEqual(st.lists[-1][1], ["Level Shift by Netbuild", "BUA Update by Netbuild",
                                            "Clear Warnings by Netbuild", "Stair Path by Netbuild",
                                            "Align Viewports by Netbuild", "Element Remover by Netbuild"])
        self.assertEqual(pyrevit_stubs.WPFWindow.shown[-1].product_tb.Text, "Stair Path by Netbuild")


class AboutTests(unittest.TestCase):
    def test_product_info_and_license(self):
        with io.open(os.path.join(os.path.dirname(ROOT), "LICENSE"), encoding="utf-8") as f:
            self.assertEqual(about.LICENSE_TEXT, f.read())
        self.assertEqual((about.PRODUCT, about.PUBLISHER, about.OWNER, about.WEBSITE),
                         ("Stair Path by Netbuild", "Netbuild", "Netbuild", "https://skaec.com"))
        self.assertEqual(about.COPYRIGHT, u"\u00a9 2026 Netbuild. All rights reserved.")
        self.assertEqual(about.LICENSE_NAME, "Netbuild Software Licence Agreement (proprietary)")
        with io.open(os.path.join(EXT, "lib", "stair_path", "about.py"), encoding="utf-8") as f:
            self.assertIn('u"\\u00a9 %s %s. All rights reserved."', f.read())      # the escape, for IronPython
        text = about.licence_text()
        for part in ("Stair Path by Netbuild  version", "Proprietary software -- owned by Netbuild",
                     "Website: https://skaec.com", "No licence key required for this product."):
            self.assertIn(part, text)
        self.assertIn("Features", about.about_text(license=False))


if __name__ == "__main__":
    unittest.main()

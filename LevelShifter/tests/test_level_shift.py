"""Tests against a stand-in Revit listener (no Revit needed).

    python -m unittest discover -s LevelShifter/tests -v
"""

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_revit import FakeRevit, mm  # noqa: E402
from level_shift import cli, revit  # noqa: E402
from level_shift.payload import CODE  # noqa: E402
from level_shift.runner import MoveSpec, Runner, resolve  # noqa: E402
from level_shift.settings import Settings  # noqa: E402
from level_shift.units import fmt, parse_length  # noqa: E402

TOL = 1e-6


class UnitTests(unittest.TestCase):
    def test_parse_length(self):
        for text, want in (("3500", 3500), ("+300", 300), ("-150", -150), ("3,500", 3500), ("-1,200.5", -1200.5),
                           ("3.5m", 3500), ("3,5 m", 3500), ("10500 mm", 10500), (" .5 m", 500)):
            self.assertAlmostEqual(parse_length(text, "mm"), want, msg=text)
        self.assertAlmostEqual(parse_length("300mm", "m"), 0.3)
        for bad in ("", "abc", "3500x", "1..2", "+-3"):
            with self.assertRaises(ValueError, msg=bad):
                parse_length(bad, "mm")
        self.assertEqual(fmt(3500, "mm"), "3,500.0 mm")
        self.assertEqual(fmt(-150, "mm", signed=True), "-150.0 mm")

    def test_move_spec(self):
        sp = MoveSpec.parse("Level 01 = A=+300", "by", "mm")      # the last '=' splits
        self.assertEqual((sp.level, sp.mode, sp.value), ("Level 01 = A", "by", 300))
        self.assertEqual(MoveSpec.parse("L03=10.5m", "to", "mm").value, 10500)
        with self.assertRaises(ValueError):
            MoveSpec.parse("L03", "to", "mm")

    def test_payload_is_py2_shaped_and_compiles(self):
        code = revit.action_code("n", "plan", ["T00O"], [{"id": 5, "name": u"Lével", "delta": 1.0}])
        compile(code, "<revit>", "exec")
        self.assertIn("u'L\u00e9vel'", code)
        self.assertNotIn('f"', CODE)
        self.assertNotIn("f'", CODE)


LEVELS = [{"id": 1, "name": "L00", "elev": 0.0}, {"id": 2, "name": "L01", "elev": mm(3500)},
          {"id": 3, "name": "L02", "elev": mm(7000)}, {"id": 4, "name": "L03", "elev": mm(10500)}]


class ResolveTests(unittest.TestCase):
    def labels(self, checks, ok):
        return [c.label for c in checks if c.ok is ok]

    def test_to_and_by(self):
        moves, checks = resolve(LEVELS, [MoveSpec("L01", "by", 300), MoveSpec("l02", "to", 6850)], "mm")
        self.assertEqual([round(m["delta"] * 304.8, 6) for m in moves], [300, -150])
        self.assertEqual(round(moves[1]["new"] * 304.8, 6), 6850)
        self.assertFalse(self.labels(checks, False))

    def test_problems(self):
        _, checks = resolve(LEVELS, [MoveSpec("L09", "by", 1), MoveSpec("L01", "by", 1), MoveSpec("2", "by", 2)], "mm")
        self.assertEqual(self.labels(checks, False), ["Level 'L09'", "L01"])          # unknown; id 2 = L01 twice
        _, checks = resolve(LEVELS, [MoveSpec("L01", "by", 1)] * 11, "mm")
        self.assertIn("Levels", self.labels(checks, False))
        moves, checks = resolve(LEVELS, [MoveSpec("L01", "to", 3500)], "mm")
        self.assertEqual(moves, [])
        self.assertIn("L01", self.labels(checks, None))                              # no change -> skipped
        self.assertIn("Levels", self.labels(checks, False))                          # nothing to move

    def test_warnings_same_elevation_and_order(self):
        _, checks = resolve(LEVELS, [MoveSpec("L01", "to", 7000)], "mm")
        self.assertIn("L01 elevation", self.labels(checks, None))
        _, checks = resolve(LEVELS, [MoveSpec("L01", "to", 8000)], "mm")
        order = [c for c in checks if c.label == "Level order"]
        self.assertEqual(order[0].detail, "the stacking order changes: L01 / L02")
        _, checks = resolve(LEVELS, [MoveSpec("L01", "to", 8000), MoveSpec("L02", "to", 9000)], "mm")
        self.assertFalse([c for c in checks if c.label == "Level order"])            # moved together


class Fixture(unittest.TestCase):
    extra = ()

    def setUp(self):
        self.fake = FakeRevit(self.extra)
        self.doc = self.fake.doc
        self.tmp = tempfile.mkdtemp()
        self.s = Settings(self.tmp)
        self.s.update({"revit_url": self.fake.url})
        self.lines = []
        self.r = Runner(self.s, on_line=self.lines.append)
        self.geo0 = self.doc.geometry()
        self.params0 = self.doc.snapshot()

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def explain(self, res):
        return "\n".join(map(str, res.checks)) + "\n" + "\n".join(self.lines[-40:])

    def moved(self):
        g1 = self.doc.geometry()
        return dict((self.doc.by_id[i].Name, (round((g1[i][0] - z[0]) * 304.8, 3), round((g1[i][1] - z[1]) * 304.8, 3)))
                    for i, z in self.geo0.items() if abs(g1[i][0] - z[0]) > TOL or abs(g1[i][1] - z[1]) > TOL)

    def elev(self, name):
        return round(self.fake.lv[name].Elevation * 304.8, 6)

    def unchanged(self):
        return self.doc.snapshot() == self.params0

    def off(self, key, param):
        return round(self.fake.el[key].v(param) * 304.8, 6)


class WorkflowTests(Fixture):
    def test_levels(self):
        res = self.r.read_levels()
        self.assertTrue(res.ok, self.explain(res))
        names = [lv["name"] for lv in res.info["levels"]]
        self.assertEqual(names, ["B1", "L00 GF", "L01", "L02", "L03", "Roof"])         # by elevation
        self.assertEqual(round(res.info["levels"][2]["elev"] * 304.8, 6), 3500)
        self.assertIn("Elevation Base: Project Base Point", str(res.checks[-1]))

    def test_plan_changes_nothing(self):
        res = self.r.run("plan", None, [MoveSpec("L01", "by", 300)])
        self.assertTrue(res.ok, self.explain(res))
        self.assertTrue(self.unchanged())
        plan = res.info["plan"]
        cats = dict((c, n) for lid, c, n in plan["counts"])
        self.assertEqual(cats["Walls"], 3)                  # base L01 x2 + top L01 x1; group member excluded
        for c in ("Doors", "Furniture", "StructuralColumns", "Stairs", "Rooms", "PipeCurves", "Ceilings",
                  "IOSModelGroups", "GenericModel"):
            self.assertIn(c, cats)
        self.assertNotIn("PipeFitting", cats)               # follows the pipe
        self.assertNotIn("LightingFixtures", cats)          # hosted on the L02 slab
        self.assertEqual([r["name"] for r in plan["no_offset"]], ["In-place plinth"])
        self.assertEqual(plan["group_members"], 1)
        self.assertTrue([c for c in res.checks if c.label == "Model groups" and c.ok is None])

    def test_trial_rolls_back(self):
        res = self.r.run("trial", None, [MoveSpec("L01", "by", 300), MoveSpec("L02", "to", 6850)])
        self.assertTrue(res.ok, self.explain(res))
        self.assertTrue(self.unchanged())
        self.assertEqual(self.doc.groups, [("Netbuild Level Shift", "rolled back")])
        self.assertIn("Every element kept its X, Y, Z", [c.label for c in res.checks])
        self.assertEqual([lv["name"] for lv in res.info["result"]["levels_after"]], ["L01", "L02"])
        self.assertTrue(os.path.isfile(res.info["rows_csv"]))

    def test_apply_two_levels_everything_stays(self):
        res = self.r.run("apply", None, [MoveSpec("L01", "by", 300), MoveSpec("L02", "to", 6850)])
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual((self.elev("L01"), self.elev("L02")), (3800, 6850))
        self.assertEqual(self.moved(), {})
        self.assertEqual(self.doc.groups, [("Netbuild Level Shift", "assimilated")])
        # the offsets carry the opposite of each level's move
        self.assertEqual(self.off("wall L01-L02", "WALL_BASE_OFFSET"), -300)
        self.assertEqual(self.off("wall L01-L02", "WALL_TOP_OFFSET"), 150)
        self.assertEqual(self.off("wall L00-L01", "WALL_TOP_OFFSET"), -300)
        self.assertEqual(self.off("wall L01 unconnected", "WALL_BASE_OFFSET"), -300)
        self.assertEqual(self.off("door", "INSTANCE_SILL_HEIGHT_PARAM"), -300)
        self.assertEqual(self.off("desk", "INSTANCE_ELEVATION_PARAM"), -300)
        self.assertEqual(self.off("floor L02", "FLOOR_HEIGHTABOVELEVEL_PARAM"), 150)
        self.assertEqual(self.off("beam", "STRUCTURAL_BEAM_END0_ELEVATION"), 150)
        self.assertEqual(self.off("beam", "STRUCTURAL_BEAM_END1_ELEVATION"), 150)
        self.assertEqual(self.off("room", "ROOM_UPPER_OFFSET"), 150)
        self.assertEqual(self.off("group", "GROUP_OFFSET_FROM_LEVEL"), -300)
        self.assertEqual(self.off("pipe", "RBS_OFFSET_PARAM"), 2500)
        # followers untouched: the fitting, the face-hosted light, the group member
        self.assertEqual(self.off("elbow", "INSTANCE_ELEVATION_PARAM"), 2800)
        self.assertEqual(self.off("light", "INSTANCE_FREE_HOST_OFFSET_PARAM"), 0)
        self.assertEqual(self.off("group member", "WALL_BASE_OFFSET"), 0)
        # no offset parameter: measured, then moved back
        self.assertEqual(round(self.fake.el["generic"].free * 304.8, 6), -300)
        self.assertEqual(self.fake.el["wall L03-Roof"].p, self.params0[self.fake.el["wall L03-Roof"].Id.Value][0])
        rows = dict((r["name"], r) for r in res.info["result"]["rows"])
        self.assertEqual(rows["In-place plinth"]["method"], "moved")
        self.assertEqual(rows["Basic Wall 200"]["rule"], "WALL_BASE_CONSTRAINT+WALL_HEIGHT_TYPE")

    def test_apply_down_by_metres(self):
        self.s["units"] = "m"
        res = self.r.run("apply", None, [MoveSpec("L00 GF", "by", -0.45)])
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual(self.elev("L00 GF"), -450)
        self.assertEqual(self.moved(), {})
        self.assertEqual(self.off("stair", "STAIRS_BASE_OFFSET"), 450)

    def test_borrowed_element_blocks_apply(self):
        self.doc.owners[self.fake.el["door"].Id.Value] = "jane.d"
        res = self.r.run("plan", None, [MoveSpec("L01", "by", 300)])
        self.assertFalse(res.ok)
        self.assertTrue([c for c in res.checks if "Doors" in c.label and "jane.d" in c.detail], self.explain(res))
        res = self.r.run("apply", None, [MoveSpec("L01", "by", 300)])
        self.assertFalse(res.ok)
        self.assertTrue(self.unchanged())
        self.assertIn("Not applied", [c.label for c in res.checks])

    def test_revit_warnings_dismissed_errors_roll_back(self):
        self.doc.commit_warnings = ["Highlighted walls overlap."]
        res = self.r.run("apply", None, [MoveSpec("L01", "by", 300)])
        self.assertTrue(res.ok, self.explain(res))
        self.assertTrue([c for c in res.checks if c.label == "Revit warnings (dismissed)" and "overlap" in c.detail])
        self.doc.commit_warnings, self.doc.commit_errors = [], ["Element cannot be modified."]
        snap = self.doc.snapshot()
        res = self.r.run("apply", None, [MoveSpec("L01", "by", 100)])
        self.assertFalse(res.ok)
        self.assertEqual(self.doc.snapshot(), snap)
        self.assertTrue([c for c in res.checks if "cannot be modified" in c.detail], self.explain(res))

    def test_model_binding(self):
        self.s["model_match"] = "T00O-ZZZ-BM-950001"
        self.assertTrue(self.r.read_levels().ok)
        self.s["model_match"] = "B001"
        res = self.r.read_levels()
        self.assertFalse(res.ok)
        self.assertIn("0 open model(s) match", self.explain(res))

    def test_revit_down_paused_or_stale(self):
        self.fake.paused = True
        res = self.r.read_levels()
        self.assertFalse(res.ok)
        self.assertIn("manually stopped", self.explain(res))
        self.fake.paused = False
        self.fake.stale_calls = {self.fake.calls + 1}
        self.r.read_levels()
        res = self.r.read_levels()
        self.assertFalse(res.ok)
        self.assertIn("stale echo", self.explain(res))
        self.s["revit_url"] = "http://127.0.0.1:9/revit_mcp/execute_code/"
        res = self.r.read_levels()
        self.assertIn("not reachable", self.explain(res))


class DriftTests(Fixture):
    extra = ("sloped",)

    def test_shape_change_rolls_back_unless_kept(self):
        res = self.r.run("trial", None, [MoveSpec("L01", "by", 300)])
        self.assertFalse(res.ok)
        drift = res.info["result"]["drift"]
        self.assertEqual([(d["name"], d["status"]) for d in drift], [("Sloped roof", "changed shape")])
        self.assertTrue(self.unchanged())
        res = self.r.run("apply", None, [MoveSpec("L01", "by", 300)])
        self.assertFalse(res.ok)
        self.assertTrue(self.unchanged())
        self.assertIn("rolled back", str([c for c in res.checks if c.label == "Applied"][0]))
        self.s["rollback_on_drift"] = False
        res = self.r.run("apply", None, [MoveSpec("L01", "by", 300)])
        self.assertTrue(res.info["result"]["committed"])
        self.assertEqual(self.moved(), {"Sloped roof": (300.0, 0.0)})            # reported, kept as asked
        self.assertEqual(self.elev("L01"), 3800)


class CliTests(Fixture):
    def cli(self, *args):
        import level_shift.settings as st
        orig = st.app_dir
        st.app_dir = lambda: self.tmp
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = cli.main(list(args))
        finally:
            st.app_dir = orig
        return rc, buf.getvalue()

    def test_cli(self):
        self.s.save()
        rc, out = self.cli("levels")
        self.assertEqual(rc, 0, out)
        self.assertIn("L01", out)
        rc, out = self.cli("models")
        self.assertIn("950001_user   [active]", out)
        rc, out = self.cli("trial", "--by", "L01=+300", "--to", "Roof=14.2m")
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.unchanged())
        rc, out = self.cli("apply", "--by", "L01=+300", "--to", "Roof=14.2m")
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.elev("L01"), self.elev("Roof")), (3800, 14200))
        self.assertEqual(self.moved(), {})
        rc, out = self.cli("plan", "--by", "L09=+300")
        self.assertEqual(rc, 1)
        self.assertIn("not found in the model", out)
        rc, out = self.cli("setup", "--set", "tolerance_mm=0.5", "--set", "move_fallback=false")
        self.assertEqual(Settings(self.tmp)["tolerance_mm"], 0.5)
        self.assertIs(Settings(self.tmp)["move_fallback"], False)


class GuiTests(Fixture):
    def test_window(self):
        try:
            import tkinter as tk
            from level_shift import gui
            root = tk.Tk()
        except Exception as e:  # no tkinter / no display
            self.skipTest("no window: %s" % e)
        import level_shift.settings as st
        self.s.save()
        orig = st.app_dir
        st.app_dir = lambda: self.tmp
        try:
            app = gui.App(root)
            gui.messagebox.askyesno = lambda *a, **k: True

            def wait():
                deadline = time.time() + 30
                while app.busy and time.time() < deadline:
                    root.update()
                    time.sleep(0.02)
                root.update()
            app.do_levels()
            wait()
            self.assertEqual(len(app.levels), 6, app.checks.get("1.0", "end"))
            r1, r2 = app.rows[0], app.rows[1]
            r1.level.set("L01")
            r1.on_level()
            self.assertEqual(r1.current.get(), "3,500.0 mm")              # read-only, highlighted
            r1.new.set("3800")
            r1.on_edit("to")
            self.assertEqual(r1.delta.get(), "+300.0")
            r2.level.set("L02")
            r2.on_level()
            dlg = gui.DefineDialog(r2)
            dlg.how.set("by")
            dlg.amount.set("150")
            dlg.dir.set("down")
            self.assertIn("6,850.0 mm", dlg.result.cget("text"))
            dlg.ok()
            self.assertEqual((r2.new.get(), r2.delta.get()), ("6850.0", "-150.0"))
            app.do_run("trial")
            wait()
            self.assertTrue(self.unchanged(), app.checks.get("1.0", "end"))
            app.do_run("apply")
            wait()
            wait()                                                    # levels reload after a kept Apply
            self.assertEqual((self.elev("L01"), self.elev("L02")), (3800, 6850))
            self.assertEqual(self.moved(), {})
            self.assertEqual(r1.current.get(), "3,800.0 mm")
            self.assertEqual(r1.new.get(), "")
        finally:
            root.destroy()
            st.app_dir = orig


if __name__ == "__main__":
    unittest.main()

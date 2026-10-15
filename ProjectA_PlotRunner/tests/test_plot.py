"""Tests against a stand-in Revit listener and copies of the real export scripts (no Revit needed).

    python -m unittest discover -s ProjectA_PlotRunner/tests -v
"""

import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_revit import FakeRevit  # noqa: E402
from projecta_plot import patch  # noqa: E402
from projecta_plot.runner import Job, Runner, static_checks  # noqa: E402
from projecta_plot.settings import Settings  # noqa: E402
from projecta_plot.sheets import (SheetSpecError, parse_sheet_spec, pick_date_filter,  # noqa: E402
                             select)

FIXTURES = os.path.join(HERE, "fixtures")
MASTER = os.path.join(FIXTURES, "export_master_ga_sheets_by_browser_filter.py")
PODIUM = os.path.join(FIXTURES, "export_podium_sheets_by_revision.py")
SITE = "01_GA Plans (1-500) - Site"
B2B5 = "02_GA Plans B2 B5 (1-200)"
PLANS = "03_Podium Building Part Plans (1-100)"
ELEV = "04_Podium Building Elevations (1-100)"
SECT = "05_Podium Building Sections (1-100)"


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


SCRIPT_HASHES = None


def before_after_scripts_unchanged():
    return SCRIPT_HASHES == (sha(MASTER), sha(PODIUM))


def tree(root):
    out = set()
    for d, _, files in os.walk(root):
        for f in files:
            out.add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    return out


SCRIPT_HASHES = (sha(MASTER), sha(PODIUM))


class PatchTests(unittest.TestCase):
    def test_real_scripts_patch_and_compile(self):
        for path in (MASTER, PODIUM):
            with open(path, "rb") as f:
                src = f.read()
            code, hits = patch.patch_source(
                src, {"BASE_OUTPUT_FOLDER": r"C:\Users\user\OneDrive - Studio\Projects\ProjectA\Plot\20261015",
                      "REVISION_DATE_FILTER": None, "EXPORT_PDF": True, "EXPORT_CAD": False,
                      "DRY_RUN": False, "doc": patch.Expr("_projecta_pick_doc(_ProjectA_MATCH)")},
                insert_after_loop="candidates = _projecta_filter(candidates)", prepend="# pre", append="# post")
            compile(code, path, "exec")
            self.assertTrue(all(n == 1 for n in hits.values()), hits)
            self.assertIn(r"BASE_OUTPUT_FOLDER = 'C:\\Users\\user\\OneDrive - Studio", code)
            self.assertIn("doc = _projecta_pick_doc(_ProjectA_MATCH)", code)
            self.assertIn("REVISION_DATE_FILTER = None", code)
            # everything else is byte-identical: same lines, minus the edited ones
            orig = src.decode("utf-8").splitlines()
            new = code.splitlines()
            self.assertEqual(len(new), len(orig) + 3)
            self.assertIn(sum(1 for line in orig if line not in new), (4, 5))
            i = new.index("candidates = _projecta_filter(candidates)")
            self.assertTrue(new[i - 1].startswith("    candidates.append("))

    def test_literals_are_py2_safe(self):
        self.assertEqual(patch.py_literal("caf\u00e9"), "u'caf\u00e9'")
        self.assertEqual(patch.py_literal([True, None, 3]), "[True, None, 3]")

    def test_missing_global_is_refused(self):
        with self.assertRaises(patch.PatchError):
            patch.patch_source("A = 1\n", {"NOPE": 2})

    def test_static_checks_on_real_scripts(self):
        for path, kind in ((MASTER, "master"), (PODIUM, "podium")):
            bad = [str(c) for c in static_checks(path, kind) if c.ok is not True]
            self.assertEqual(bad, [])

    def test_static_checks_flag_routing_drift(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "m.py")
            with open(MASTER, encoding="utf-8") as f:
                src = f.read().replace('"Studio_03 - Browser Filter"', '"Browser Filter"')
            with open(p, "w", encoding="utf-8") as f:
                f.write(src)
            warn = [c for c in static_checks(p, "master") if c.ok is None]
            self.assertTrue(any("BROWSER_FILTER_PARAM" in c.label for c in warn))
        finally:
            shutil.rmtree(tmp)


class SheetSpecTests(unittest.TestCase):
    CANDS = [{"sheet": "B001-AR-%s" % n, "fname": "ProjectC-Studio-DWG-B001-GFL-AR-%s_D" % n, "subfolder": "x"}
             for n in ("210001", "210002", "210003", "210010", "220001")]

    def texts(self, spec):
        return [s.text for s in parse_sheet_spec(spec)]

    def test_single_list_series(self):
        self.assertEqual(self.texts("210001"), ["210001"])
        self.assertEqual(self.texts("210001, 210002;210003\n220001 | 230001\t1 2"),
                         ["210001", "210002", "210003", "220001", "230001", "1", "2"])
        self.assertEqual(self.texts("210001 to 210012, 220001..220003, 230001-230004"),
                         ["210001 to 210012", "220001..220003", "230001-230004"])
        self.assertEqual(self.texts(""), [])

    def test_drawing_number_is_not_a_series(self):
        self.assertEqual(self.texts("ProjectC-Studio-DWG-B001-GFL-AR-210001"), ["ProjectC-Studio-DWG-B001-GFL-AR-210001"])

    def test_bad_series(self):
        for bad in ("210012 to 210001", "A-101 to B-110", "abc to def"):
            with self.assertRaises(SheetSpecError):
                parse_sheet_spec(bad)

    def test_select_by_any_name(self):
        chosen, unmatched = select(self.CANDS, parse_sheet_spec(
            "210001 to 210003, ProjectC-Studio-DWG-B001-GFL-AR-220001_D, b001-ar-210010, 999999"))
        self.assertEqual([c["sheet"][-6:] for c in chosen], ["210001", "210002", "210003", "210010", "220001"])
        self.assertEqual(unmatched, ["999999"])
        chosen, _ = select(self.CANDS, parse_sheet_spec("B001-AR-210002 to B001-AR-210010"))
        self.assertEqual(len(chosen), 3)

    def test_date_format_found_live(self):
        flt, _, _ = pick_date_filter("06-Sep-2026", {"06/09/2026": 7, "16/09/2026": 1})
        self.assertEqual(flt, "06/09/2026")
        flt, _, _ = pick_date_filter("6/9/2026", {"06-Sep-2026": 3, "20-Aug-2026": 1})
        self.assertEqual(flt, "06-Sep-2026")
        flt, counts, msg = pick_date_filter("07-Sep-2026", {"06-Sep-2026": 3})
        self.assertIsNone(flt)
        self.assertIn("no sheet", msg)
        self.assertEqual(pick_date_filter("", {})[0], None)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRevit()
        self.tmp = tempfile.mkdtemp()
        self.plot = os.path.join(self.tmp, "Plot")
        os.makedirs(self.plot)
        self.app = os.path.join(self.tmp, "app")
        os.makedirs(self.app)
        self.s = Settings(self.app)
        self.s.update({"netbuild_root": FIXTURES, "master_script": os.path.basename(MASTER),
                       "podium_script": os.path.basename(PODIUM), "plot_root": self.plot,
                       "revit_url": self.fake.url, "poll_seconds": 0.05, "settle_seconds": 0.3,
                       "stall_seconds": 1.0, "sheet_timeout_seconds": 10,
                       "time_saved_log": os.path.join(self.tmp, "time.csv")})
        self.lines = []
        self.r = Runner(self.s, on_line=self.lines.append)
        self.out = os.path.join(self.plot, "20261015")

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def job(self, date="06-Sep-2026", mode="pdf", sheets=""):
        return Job(self.plot, "20261015", date, mode, sheets)

    def explain(self, res):
        return "\n".join(map(str, res.checks)) + "\n" + "\n".join(self.lines[-40:])


class WorkflowTests(Fixture):
    def test_check_model(self):
        res = self.r.check_model(self.s.model("B001"))
        self.assertTrue(res.ok, self.explain(res))
        self.assertIsNone([c for c in res.checks if c.label == "Active window"][0].ok)
        res = self.r.check_model(self.s.model("B003"))
        self.assertFalse(res.ok)
        self.assertIn("no open model", str(res.checks[0]))

    def test_master_pdf_and_cad(self):
        before = (sha(MASTER), sha(PODIUM))
        res = self.r.export(self.s.model("SW00"), self.job(mode="pdf+cad"))
        self.assertTrue(res.ok, self.explain(res))
        stem = "ProjectC-Studio-DWG-SW0O-ZZZ-AR-1000%02d_C"
        want = set()
        for kind, ext in (("PDF", "pdf"), ("CAD", "dwg")):
            want |= {"%s/%s/%s.%s" % (kind, SITE, stem % n, ext) for n in (1, 2)}
            want |= {"%s/%s/%s.%s" % (kind, B2B5, stem % n, ext) for n in (5, 6)}
        self.assertEqual(tree(self.out), want)  # Solar Shading, Site Plan, old date, 'Other' all left out
        kinds = [k for k, _ in self.fake.exports]
        self.assertEqual(kinds, ["PDF"] * 4 + ["CAD"] * 4)  # all PDFs first, then all DWGs
        self.assertEqual(before, (sha(MASTER), sha(PODIUM)))
        date = [c for c in res.checks if c.label == "Revision-date filter"][0]
        self.assertIn("'06/09/2026'", date.detail)  # typed DD-Mon-YYYY, model uses DD/MM/YYYY
        self.assertTrue(os.path.isfile(res.info["summary_csv"]))

    def test_podium_routing_and_superseded_duplicate(self):
        res = self.r.export(self.s.model("B001"), self.job(date="06/09/2026"))
        self.assertTrue(res.ok, self.explain(res))
        files = tree(self.out)
        self.assertEqual(len([f for f in files if f.startswith("PDF/%s/" % PLANS)]), 4)
        self.assertEqual(len([f for f in files if f.startswith("PDF/%s/" % ELEV)]), 2)
        self.assertEqual(len([f for f in files if f.startswith("PDF/%s/" % SECT)]), 1)
        self.assertIn("PDF/%s/ProjectC-Studio-DWG-B001-GFL-AR-210003_E.pdf" % PLANS, files)  # its own revision
        self.assertNotIn("B001-AR-210001(1)", [s for _, s in self.fake.exports])
        self.assertFalse(os.path.isdir(os.path.join(self.out, "CAD")))

    def test_sheet_list_cad_only(self):
        res = self.r.export(self.s.model("B001"), self.job(mode="cad", sheets="210001 to 210003\n230001"))
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual(sorted(s[-6:] for _, s in self.fake.exports), ["210001", "210002", "210003", "230001"])
        self.assertEqual({k for k, _ in self.fake.exports}, {"CAD"})
        self.assertFalse(os.path.isdir(os.path.join(self.out, "PDF")))
        self.assertEqual({f.rsplit(".", 1)[1] for f in tree(self.out)}, {"dwg"})  # byproducts swept

    def test_single_sheet_without_date(self):
        res = self.r.export(self.s.model("B001"), self.job(date="", sheets="ProjectC-Studio-DWG-B001-GFL-AR-220002"))
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual(tree(self.out), {"PDF/%s/ProjectC-Studio-DWG-B001-GFL-AR-220002_D.pdf" % ELEV})

    def test_unlisted_sheet_stops_before_export(self):
        res = self.r.export(self.s.model("B001"), self.job(sheets="210001, 299999"))
        self.assertFalse(res.ok)
        self.assertEqual(res.info["unmatched"], ["299999"])
        self.assertEqual(self.fake.exports, [])
        res = self.r.export(self.s.model("B001"), self.job(sheets="210001, 299999"), allow_unmatched=True)
        self.assertEqual(len(self.fake.exports), 1)

    def test_superseded_duplicate_without_date_is_refused(self):
        res = self.r.dry_run(self.s.model("B001"), self.job(date="", sheets="210001"))
        dup = [c for c in res.checks if c.label == "Duplicate filenames"]
        self.assertTrue(dup and dup[0].ok is False, self.explain(res))
        res = self.r.export(self.s.model("B001"), self.job(date="", sheets="210001"))
        self.assertFalse(res.ok)
        self.assertEqual(self.fake.exports, [])

    def test_wrong_date_lists_real_values(self):
        res = self.r.dry_run(self.s.model("SW00"), self.job(date="07-Sep-2026"))
        self.assertFalse(res.ok)
        self.assertIn("'06/09/2026'", "\n".join(map(str, res.checks)))

    def test_wrong_model_open_is_explained(self):
        # Field case 2026-10-15: the Tower plans model (T00O) was bound as SW00; every sheet's
        # "Studio_03 - Browser Filter" is 'Tower'/'Other', so the master script routes nothing.
        self.s.model("SW00")["match"] = ["T00O-ZZZ-BM-950001"]
        res = self.r.export(self.s.model("SW00"), self.job(mode="pdf+cad"))
        self.assertFalse(res.ok)
        self.assertEqual(self.fake.exports, [])
        checks = dict((c.label, c) for c in res.checks)
        self.assertIsNone(checks["Bound to model"].ok)
        self.assertIn("expected ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001", checks["Bound to model"].detail)
        self.assertIn("'Tower' x4", checks["Why 0 sheets"].detail)
        self.assertIn("different model", checks["Why 0 sheets"].detail)
        self.assertIn("[runner] SW00: NOTHING EXPORTED", self.lines)

    def test_master_and_areas_models_do_not_collide(self):
        # SW0O-...-BM-950001 (master) and SW00-...-AR-970002 (Areas) are open together
        self.assertTrue(self.r.check_model(self.s.model("SW00")).ok)
        self.assertTrue(self.r.check_model(self.s.model("AREAS")).ok)
        self.assertTrue(self.r.check_model(self.s.model("TOWER-PLANS")).ok)
        self.assertTrue(self.r.check_model(self.s.model("TOWER-ELEV-SEC")).ok)

    def test_tower_and_areas_models(self):
        res = self.r.export(self.s.model("TOWER-PLANS"), self.job(mode="pdf+cad"))
        self.assertTrue(res.ok, self.explain(res))
        res = self.r.export(self.s.model("TOWER-ELEV-SEC"), self.job(mode="pdf"))
        self.assertTrue(res.ok, self.explain(res))
        res = self.r.export(self.s.model("AREAS"), self.job(date="06/09/2026", mode="pdf", sheets="600001 to 600002"))
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual(tree(self.out), {
            "PDF/06_Tower Plans/ProjectC-Studio-DWG-T00O-L10-AR-400001_B.pdf",
            "PDF/06_Tower Plans/ProjectC-Studio-DWG-T00O-L11-AR-400002_B.pdf",
            "PDF/06_Tower Plans/ProjectC-Studio-DWG-T00O-L12-AR-400003_B.pdf",
            "CAD/06_Tower Plans/ProjectC-Studio-DWG-T00O-L10-AR-400001_B.dwg",
            "CAD/06_Tower Plans/ProjectC-Studio-DWG-T00O-L11-AR-400002_B.dwg",
            "CAD/06_Tower Plans/ProjectC-Studio-DWG-T00O-L12-AR-400003_B.dwg",
            "PDF/07_Tower Elevations/ProjectC-Studio-DWG-T00O-ZZZ-AR-500001_B.pdf",
            "PDF/07_Tower Elevations/ProjectC-Studio-DWG-T00O-ZZZ-AR-500002_B.pdf",
            "PDF/08_Tower Sections/ProjectC-Studio-DWG-T00O-ZZZ-AR-500003_B.pdf",
            "PDF/08_Tower Sections/ProjectC-Studio-DWG-T00O-ZZZ-AR-500004_B.pdf",
            "PDF/09_Area Plans/ProjectC-Studio-DWG-SW00-L00-AR-600001_A.pdf",
            "PDF/09_Area Plans/ProjectC-Studio-DWG-SW00-L01-AR-600002_A.pdf",
        })  # Tower CeilingPlan + Legend sheets are not routed
        self.assertEqual(before_after_scripts_unchanged(), True)

    def test_old_settings_get_the_new_model_list(self):
        import json
        with open(self.s.path, "w") as f:
            json.dump({"plot_root": self.plot, "models": [{"name": "SW00", "kind": "master",
                                                           "match": ["-T00O-"]}]}, f)
        s2 = Settings(self.app)
        self.assertEqual([m["name"] for m in s2["models"]][-3:], ["TOWER-PLANS", "TOWER-ELEV-SEC", "AREAS"])
        self.assertEqual(s2.model("SW00")["match"][0], "SW0O-ZZZ-BM-950001")
        self.assertEqual(s2["plot_root"], self.plot)

    def test_stalled_batch_falls_back_to_one_sheet_per_call(self):
        self.fake.delay["B001-AR-210002"] = 2.5   # longer than stall_seconds
        res = self.r.export(self.s.model("B001"), self.job())
        self.assertTrue(res.ok, self.explain(res))
        rows = res.info["files"]
        self.assertTrue(all(r["status"] == "OK" for r in rows))
        self.assertTrue(any(r["via"] == "single" for r in rows), self.explain(res))
        self.assertTrue(any("one sheet per call" in line for line in self.lines))

    def test_stale_echo_is_ignored_disk_decides(self):
        self.fake.stale_calls = {2}  # 0 probe, 1 dry run, 2 first batch -> previous call's output
        res = self.r.export(self.s.model("SW00"), self.job())
        self.assertTrue(res.ok, self.explain(res))
        self.assertTrue(any("stale echo" in line for line in self.lines))

    def test_failed_sheet_with_old_file_is_not_counted(self):
        old = os.path.join(self.out, "PDF", SECT)
        os.makedirs(old)
        path = os.path.join(old, "ProjectC-Studio-DWG-B001-GFL-AR-230001_D.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF old")
        os.utime(path, (time.time() - 3600, time.time() - 3600))
        self.fake.fail.add("B001-AR-230001")
        res = self.r.export(self.s.model("B001"), self.job())
        self.assertFalse(res.ok)
        bad = [r for r in res.info["files"] if r["status"] != "OK"]
        self.assertEqual([r["sheet"] for r in bad], ["B001-AR-230001"])
        self.assertIn("NOT REWRITTEN", bad[0]["status"])

    def test_revit_down_or_paused(self):
        self.fake.paused = True
        res = self.r.export(self.s.model("SW00"), self.job())
        self.assertFalse(res.ok)
        self.assertIn("stopped", "\n".join(map(str, res.checks)))
        self.s["revit_url"] = "http://127.0.0.1:9/revit_mcp/execute_code/"
        res = self.r.check_model(self.s.model("SW00"))
        self.assertIn("not reachable", "\n".join(map(str, res.checks)))

    def test_verify_output_pairs(self):
        res = self.r.export(self.s.model("SW00"), self.job(mode="pdf+cad"))
        os.remove(os.path.join(self.out, "CAD", SITE, "ProjectC-Studio-DWG-SW0O-ZZZ-AR-100001_C.dwg"))
        ver = self.r.verify_output(self.out, "pdf+cad", res.info["files"])
        text = "\n".join(map(str, ver.checks))
        self.assertIn("PDF only: projectc-studio-dwg-sw0o-zzz-ar-100001_c", text)
        self.assertFalse(ver.ok)


class CliTests(Fixture):
    def test_cli_commands(self):
        from projecta_plot import cli
        import projecta_plot.settings as st
        orig = st.app_dir
        self.s.save()
        st.app_dir = lambda: self.app
        try:
            self.assertEqual(cli.main(["setup"]), 0)
            self.assertEqual(cli.main(["models"]), 0)
            self.assertEqual(cli.main(["check", "SW00"]), 0)
            self.assertEqual(cli.main(["dry", "B001", "--date", "06-Sep-2026", "--out", "20261015"]), 0)
            self.assertEqual(cli.main(["export", "B001", "--date", "06-Sep-2026", "--out", "20261015",
                                       "--mode", "pdf+cad", "--sheets", "220001;220002"]), 0)
            self.assertEqual(cli.main(["verify", "--out", "20261015", "--mode", "pdf+cad"]), 0)
            self.assertEqual(cli.main(["export", "B001", "--out", "20261015"]), 2)  # no date, no sheets
            self.assertEqual(cli.main(["log-time", "--actual", "20", "--sheets", "2"]), 0)
        finally:
            st.app_dir = orig


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "needs a display")
class GuiTests(Fixture):
    def test_window_runs_a_model(self):
        try:
            import tkinter as tk
            from projecta_plot import gui
        except ImportError:
            self.skipTest("no tkinter")
        import projecta_plot.settings as st
        self.s.save()
        orig = st.app_dir
        st.app_dir = lambda: self.app
        root = tk.Tk()
        try:
            app = gui.App(root)
            gui.messagebox.askyesno = lambda *a, **k: True
            app.date.set("06-Sep-2026")
            app.out_date.set("20261015")
            app.mode.set("pdf+cad")
            dlg = gui.SheetDialog(app)
            dlg.single.set("230001")
            dlg.add_single()
            dlg.s_from.set("210001")
            dlg.s_to.set("210002")
            dlg.add_series()
            dlg.paste.insert("1.0", "220001; 220002")
            dlg.add_list()
            dlg.ok()
            self.assertEqual(app.sheet_mode.get(), "list")
            self.assertEqual(app.sheet_text().splitlines(), ["230001", "210001 to 210002", "220001", "220002"])
            app.tree.selection_set("B001")
            app.do_export()
            deadline = time.time() + 30
            while (app.busy or app.tree.set("B001", "result") == "") and time.time() < deadline:
                root.update()
                time.sleep(0.02)
            self.assertEqual(app.tree.set("B001", "result"), "OK", app.checks.get("1.0", "end"))
            self.assertEqual(app.tree.set("B001", "pdf"), "5/5")
            self.assertEqual(app.tree.set("B001", "dwg"), "5/5")
            app.do_next()
            self.assertEqual(app.tree.selection()[0], "B002")
        finally:
            root.destroy()
            st.app_dir = orig


if __name__ == "__main__":
    unittest.main()

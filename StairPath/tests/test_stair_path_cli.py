"""StairPath command line and exe, against the stand-in pyRevit MCP listener (fake_listener.py) and model
(LevelShifter/tests/fake_stairs.py). The engine itself (rules, Check / Trial / Apply in-process, the ribbon button)
is tested in LevelShifter/tests/test_stair_path.py.

    python -m unittest discover -s StairPath/tests -v
"""

import ast
import filecmp
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from fake_listener import FakeListener, fake_stairs  # noqa: E402
from stair_path import about, cli, revit, rules  # noqa: E402
from stair_path.runner import Aborted, Runner, pick_model  # noqa: E402
from stair_path.settings import Settings  # noqa: E402
import sync_pyrevit_lib  # noqa: E402


def text(res):
    return "\n".join([str(c) for c in res.checks] + res.lines)


class FileTests(unittest.TestCase):
    def test_lib_copies_and_payload_are_current(self):
        self.assertEqual(sync_pyrevit_lib.DST, os.path.join(os.path.dirname(ROOT), "LevelShifter", "pyRevit",
                                                            "Netbuild.extension", "lib", "stair_path"))
        for name in sync_pyrevit_lib.SHARED:
            self.assertTrue(filecmp.cmp(os.path.join(sync_pyrevit_lib.SRC, name),
                                        os.path.join(sync_pyrevit_lib.DST, name), shallow=False),
                            "%s differs -- run: python StairPath/sync_pyrevit_lib.py" % name)
        with io.open(sync_pyrevit_lib.PAYLOAD, encoding="utf-8") as f:
            self.assertEqual(f.read(), sync_pyrevit_lib.payload_source(),
                             "payload.py is stale -- run: python StairPath/sync_pyrevit_lib.py")

    def test_code_sent_to_revit_is_ironpython_27_shaped(self):
        code = revit.action_code("n", "apply", [u"Tower B\u00f6"], rules.settings({"name_filter": u"GA Pl\u00e4n"}))
        sources = [("action code", code), ("list docs", revit.list_docs_code("n")), ("rules", revit.RULES)]
        for name in ("about.py", "rules.py", "engine.py", "__init__.py"):
            with io.open(os.path.join(ROOT, "stair_path", name), encoding="utf-8") as f:
                sources.append((name, f.read()))
        for where, src in sources:
            tree = ast.parse(src, where)
            for node in ast.walk(tree):
                at = "%s:%s" % (where, getattr(node, "lineno", "?"))
                self.assertNotIsInstance(node, (ast.JoinedStr, ast.Nonlocal, ast.AsyncFunctionDef, ast.AnnAssign,
                                                ast.YieldFrom), at)
                if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                    self.assertFalse(node.args.kwonlyargs, at)
                    self.assertFalse([a for a in node.args.args if a.annotation], at)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id == "super":
                        self.assertTrue(node.args, at)
                    if node.func.id == "print":
                        self.assertFalse(node.keywords or len(node.args) > 1, at)
            self.assertTrue(src.isascii() or where == "action code", where)        # only the u'' literals
        self.assertIn(u"'match': [u'Tower B\u00f6']", code)                       # unicode literals for IronPython
        with self.assertRaises(ValueError):
            revit.action_code("n", "delete", [], {})

    def test_exe_version_resource(self):
        import make_version_file
        txt = make_version_file.render("StairPath.exe")
        seen = {}

        def rec(name):
            return lambda *a, **k: seen.setdefault(name, []).append((a, k)) or (name, a, k)
        ns = dict((n, rec(n)) for n in ("VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable",
                                        "StringStruct", "VarFileInfo", "VarStruct"))
        eval(compile(txt.split("\n", 1)[1], "version_info", "eval"), ns)     # what PyInstaller does with it
        fields = dict(a for a, k in seen["StringStruct"])
        self.assertEqual(fields["CompanyName"], "Netbuild")
        self.assertEqual(fields["ProductName"], "Stair Path by Netbuild")
        self.assertEqual(fields["ProductVersion"], about.VERSION)
        self.assertEqual(fields["OriginalFilename"], "StairPath.exe")
        self.assertEqual(fields["LegalCopyright"], "(c) 2026 Netbuild. All rights reserved.")
        self.assertEqual(fields["Comments"], "https://skaec.com")
        self.assertEqual(seen["FixedFileInfo"][0][1]["filevers"], (1, 1, 0, 0))

    def test_about_names_the_command_line(self):
        req = about.requirements_text()
        self.assertIn("StairPath command line (StairPath.exe)", req)
        self.assertIn("http://127.0.0.1:48884", req)
        self.assertIn("Python 3.9 or later", req)


class UnitTests(unittest.TestCase):
    def test_parse_sets(self):
        self.assertEqual(cli.parse_sets(["dir_x_mm=250", "sweep=off", "views=name", "name_filter=GA = Plan"],
                                        rules.DEFAULTS),
                         {"dir_x_mm": 250.0, "sweep": False, "views": "name", "name_filter": "GA = Plan"})
        for bad in (["nope=1"], ["dir_x_mm"], ["dir_x_mm=wide"], ["sweep=maybe"]):
            with self.assertRaises(ValueError):
                cli.parse_sets(bad, rules.DEFAULTS)

    def test_pick_model(self):
        docs = [{"title": "Tower_B001", "active": True}, {"title": "Tower_B002"},
                {"title": "Tower_B002 link", "linked": True}, {"title": "Door", "family": True}]
        self.assertEqual(pick_model(docs, [])["title"], "Tower_B001")
        self.assertEqual(pick_model(docs, ["b002"])["title"], "Tower_B002")         # the link is not a project
        with self.assertRaises(Aborted):
            pick_model(docs, ["Tower"])
        with self.assertRaises(Aborted):
            pick_model(docs, ["B009"])


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeListener()
        self.tmp = tempfile.mkdtemp()
        self.s = Settings(self.tmp)
        self.s["revit_url"] = self.fake.url
        self.lines = []
        self.r = Runner(self.s, on_line=self.lines.append)

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def paths(self):
        return [(p.OwnerViewId.Value, p.StairsId.HostElementId.Value) for p in self.fake.doc.paths()]

    def explain(self, res):
        return text(res) + "\n" + "\n".join(self.lines)

    def test_plan_trial_apply(self):
        before = self.paths()
        res = self.r.run("plan")
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual(self.paths(), before)
        self.assertIn("[OK  ] Stair cores -- 2 core(s), 6 flight(s) of 7 stairs", text(res))
        self.assertIn("  L02 GA Plan (1:100, L02): Up x2, Down x2", self.lines)
        self.assertEqual(res.info["doc"]["title"], "Tower_B001")
        res = self.r.run("trial")
        self.assertTrue(res.ok, self.explain(res))
        self.assertIn("[OK  ] Trial -- rolled back -- the model is unchanged", text(res))
        self.assertEqual(self.paths(), before)
        self.assertEqual(self.fake.doc.group_result, "rolled back")
        res = self.r.run("apply", {"dir_y_mm": 350.0})
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual(self.fake.doc.groups[-1], "Stair Path by Netbuild")       # one Undo entry
        self.assertEqual(self.fake.doc.group_result, "assimilated")
        self.assertIn("[OK  ] Up / Down placed -- 8 (1 Down via a flight passing through the level)", text(res))
        self.assertIn("[WARN] Down gaps -- 1 level(s) without Down", text(res))
        self.assertTrue([l for l in self.lines if l.startswith("  GAP L02 GA Plan (L02): Core B Down")])
        down = [p for p in self.fake.doc.paths() if p.OwnerViewId == self.fake.m.v["L01"].Id and
                p.StairsId.HostElementId.Value == 101][0]
        self.assertEqual(round(down.DownTextOffset.Y * 304.8, 3), -350)
        with open(res.info["rows_csv"], encoding="utf-8-sig", newline="") as f:
            csv_lines = f.read().splitlines()
        self.assertEqual(csv_lines[0], ",".join(rules.CSV_FIELDS))
        self.assertTrue([l for l in csv_lines if l.startswith("L02 GA Plan,100,L02,Core A,down,150,through,")])
        self.assertTrue(os.path.isfile(res.log_path))

    def test_settings_are_kept_per_model(self):
        self.r.run("plan", {"dir_x_mm": 450.0, "sweep": False})
        saved = Settings(self.tmp)
        self.assertEqual((saved.models["Tower_B001"]["dir_x_mm"], saved.models["Tower_B001"]["sweep"]), (450.0, False))
        res = self.r.run("plan")                                                  # kept for the next run
        self.assertEqual((res.info["settings"]["dir_x_mm"], res.info["settings"]["sweep"]), (450.0, False))
        res = self.r.run("plan", reset=True)
        self.assertEqual(res.info["settings"]["dir_x_mm"], 300.0)
        res = self.r.run("plan", {"core_tol_mm": 0.0})
        self.assertFalse(res.ok)
        self.assertIn("[FAIL] Setting core_tol_mm -- must be more than 0", text(res))
        self.assertEqual(Settings(self.tmp).models["Tower_B001"]["core_tol_mm"], 1500.0)   # a bad value is not kept

    def test_other_model_read_only_and_listener_down(self):
        other = fake_stairs.Model()
        other.doc.Title, other.doc.PathName = "Tower_B002", "C:\\Revit_Local\\Tower_B002.rvt"
        self.fake.doc.Application.Documents.append(other.doc)
        self.s["model_match"] = "B002"
        res = self.r.run("trial")                                                 # B002 is not the active window
        self.assertFalse(res.ok)
        self.assertIn("[FAIL] Open views -- Tower_B002 is not the active window in Revit", text(res))
        res = self.r.run("apply", {"views": "name", "name_filter": "GA Plan"})
        self.assertTrue(res.ok, self.explain(res))
        self.assertIn("(not the active window)", text(res))
        self.assertEqual(other.doc.group_result, "assimilated")
        self.assertIsNone(self.fake.doc.group_result)                             # the active model untouched
        self.s["model_match"] = "B00"
        self.assertIn("2 open model(s) match", text(self.r.run("plan")))
        self.s["model_match"] = ""
        self.fake.doc.IsReadOnly = True
        self.assertTrue(self.r.run("plan").ok)
        res = self.r.run("apply")
        self.assertIn("[FAIL] Model is read-only", text(res))
        self.assertIsNone(self.fake.doc.group_result)
        self.fake.paused = True
        self.assertIn("manually stopped", text(self.r.run("apply")))
        self.s["revit_url"] = "http://127.0.0.1:9/revit_mcp/execute_code/"
        self.assertIn("not reachable", text(self.r.run("plan")))

    def cli(self, *args):
        import stair_path.settings as st
        orig = st.app_dir
        st.app_dir = lambda: self.tmp
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    rc = cli.main(list(args))
                except SystemExit as e:
                    rc = e.code
        finally:
            st.app_dir = orig
        return rc, out.getvalue() + err.getvalue()

    def test_cli(self):
        self.s.save()
        rc, out = self.cli("models")
        self.assertEqual(rc, 0, out)
        self.assertIn("Tower_B001   [active]", out)
        rc, out = self.cli("plan")
        self.assertEqual(rc, 0, out)
        self.assertIn("[stair path] plan on Tower_B001", out)
        self.assertIn("settings: open plan views; clear in the target views; directional on (X 300, Y 300 mm)", out)
        rc, out = self.cli("trial", "--views-named", "GA Plan", "--clear-model", "--set", "sweep=false")
        self.assertEqual(rc, 0, out)
        self.assertIn("Target views -- 4 plan views named '*GA Plan*'", out)
        self.assertNotIn("Other visible stairs tagged", out)
        self.assertEqual(self.fake.doc.group_result, "rolled back")
        rc, out = self.cli("apply", "--open-views", "--clear-views", "--create-types")
        self.assertEqual(rc, 0, out)
        self.assertIn("annotation list:", out)
        self.assertEqual(self.fake.doc.group_result, "assimilated")
        rc, out = self.cli("setup", "--set", "apply_timeout_seconds=7200")
        self.assertEqual(rc, 0, out)
        self.assertIn("apply_timeout_seconds    7200", out)
        self.assertIn("  Tower_B001: create_types=True, sweep=False", out)            # kept from the runs above
        with open(os.path.join(self.tmp, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["apply_timeout_seconds"], 7200)
        rc, out = self.cli("plan", "--set", "dir_x_mm=wide")
        self.assertEqual(rc, 2)
        self.assertIn("dir_x_mm: 'wide' is not a float", out)
        rc, out = self.cli("setup", "--set", "dir_x_mm=1")
        self.assertEqual(rc, 2)
        rc, out = self.cli("--model", "B009", "plan")
        self.assertEqual(rc, 1)
        self.assertIn("0 open model(s) match ['B009']", out)

    def test_cli_about_licence_and_version(self):
        rc, out = self.cli("about")
        self.assertEqual(rc, 0)
        self.assertIn("Stair Path by Netbuild  version " + about.VERSION, out)
        self.assertIn("StairPath command line (StairPath.exe)", out)
        for cmd in ("license", "licence"):
            rc, out = self.cli(cmd)
            self.assertEqual((rc, out), (0, about.licence_text() + "\n"))
        rc, out = self.cli("--version")
        self.assertEqual((rc, out.strip()), (0, "Stair Path by Netbuild " + about.VERSION))
        self.assertEqual(self.fake.calls, 0)                                       # no Revit needed


if __name__ == "__main__":
    unittest.main()

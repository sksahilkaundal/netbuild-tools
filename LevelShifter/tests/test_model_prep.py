"""Model Prep by Netbuild: the rules engine, the .xlsx register reader, the rules file, Apply against a stand-in
model (fake_links.py) and both buttons end to end (stub pyRevit / WPF, see pyrevit_stubs.py).

    python -m unittest discover -s LevelShifter/tests -v
"""

import io
import os
import runpy
import shutil
import sys
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXT = os.path.join(ROOT, "pyRevit", "Netbuild.extension")
MODELS = os.path.join(EXT, "Netbuild.tab", "Models.panel")
MODEL_PREP = os.path.join(MODELS, "Model Prep.pushbutton", "script.py")
PLACE_LINKS = os.path.join(MODELS, "Place Links.pushbutton", "script.py")
sys.path.insert(0, HERE)
sys.path.append(os.path.join(EXT, "lib"))

import fake_links  # noqa: E402
import pyrevit_stubs  # noqa: E402
from model_prep import about, core, xlsx  # noqa: E402
from model_prep import revit as prep  # noqa: E402
from model_prep import rules as rules_mod  # noqa: E402
import modelprep_ui  # noqa: E402

RULES = rules_mod.DEFAULT_RULES
REGISTER = RULES["worksets"]
B = {  # the B001 BM host's links (fake_links.b001_bm)
    "AR": "ProjectC-Studio-BIM-B001-ZZZ-AR-900001.rvt", "ST": "ProjectC-DEC-BIM-B001-ZZZ-ST-400001.rvt",
    "EL": "ProjectC-DEC-BIM-B001-ZZZ-EL-400001.rvt", "PL": "ProjectC-DEC-BIM-B001-ZZZ-PL-400001.rvt",
    "FF": "ProjectC-DEC-BIM-B001-ZZZ-FF-400001.rvt", "HV": "ProjectC-DEC-BIM-B001-ZZZ-HV-400001.rvt",
    "LA": "ProjectC-Studio-BIM-SW00-ZZZ-LA-300001.rvt", "BM": "ProjectC-Studio-BIM-SW00-ZZZ-BM-925001.rvt",
    "T00O": "ProjectC-Studio-BIM-T00O-ZZZ-AR-900001.rvt", "TO": "ProjectC-Studio-BIM-TO-ZZZ-AR-900003.rvt",
    "B005": "ProjectC-Studio-BIM-B005-ZZZ-AR-900001.rvt", "OLD": "Old survey.rvt"}


def make_xlsx(path, sheets):
    """A minimal .xlsx: sheets = [(tab, rows)], a row = [cell, ...]; str -> shared string ('inline:' prefix -> inline
    string, 'rich:a|b' -> a rich-text shared string a+b), number -> number, None -> no cell."""
    shared, idx = [], {}

    def sst(text):
        if text not in idx:
            idx[text] = len(shared)
            shared.append(text)
        return idx[text]

    parts = {}
    for n, (tab, rows) in enumerate(sheets, 1):
        xml_rows = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, v in enumerate(row):
                ref = "%s%d" % (chr(65 + c), r)
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    cells.append('<c r="%s"><v>%s</v></c>' % (ref, v))
                elif v.startswith("inline:"):
                    cells.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (
                        ref, escape(v[7:])))
                else:
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, sst(v)))
            xml_rows.append('<row r="%d">%s</row>' % (r, "".join(cells)))
        parts["xl/worksheets/sheet%d.xml" % n] = (
            '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % "".join(xml_rows))
    sis = []
    for text in shared:
        if text.startswith("rich:"):
            sis.append("<si>%s</si>" % "".join('<r><t xml:space="preserve">%s</t></r>' % escape(t)
                                               for t in text[5:].split("|")))
        else:
            sis.append('<si><t xml:space="preserve">%s</t></si>' % escape(text))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    parts["xl/sharedStrings.xml"] = '<?xml version="1.0" encoding="UTF-8"?><sst %s>%s</sst>' % (ns, "".join(sis))
    parts["xl/workbook.xml"] = '<?xml version="1.0" encoding="UTF-8"?><workbook %s %s><sheets>%s</sheets></workbook>' % (
        ns, rel_ns, "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(t, {'"': "&quot;"}), n, n)
                            for n, (t, _) in enumerate(sheets, 1)))
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">%s</Relationships>' % "".join(
            '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'worksheet" Target="%s"/>' % (n, "worksheets/sheet%d.xml" % n if n % 2 else "/xl/worksheets/sheet%d.xml" % n)
            for n in range(1, len(sheets) + 1)))
    with zipfile.ZipFile(path, "w") as z:
        for name, text in parts.items():
            z.writestr(name, text.encode("utf-8"))
    return path


def b001_snapshot():
    fake_links.install()
    doc = fake_links.b001_bm()
    return doc, prep.snapshot(doc)


def rows_by_name(plan):
    return dict((r["name"], r) for r in plan["step03"])


class NameRuleTests(unittest.TestCase):
    def test_parse_and_host(self):
        self.assertEqual(core.parse(B["PL"], RULES), ("B001", "PL"))
        self.assertEqual(core.parse("projectc-studio-bim-b002-zzz-ar-900001.rvt", RULES), ("B002", "AR"))
        self.assertEqual(core.parse("Old survey.rvt", RULES), (None, None))
        self.assertEqual(core.host("ProjectC-Studio-BIM-B003-ZZZ-BM-950001_user", RULES),
                         {"building": "B003", "disc": "BM"})

    def test_look_alike_worksets(self):
        live = ["Studio_AR-00 Link-EL", "Studio_AR-00 Link-PL", "Studio_AR-Wall Fixtures", "Studio_AR-00 Link-Studio-AR-Facade",
                "Studio_AR-Ceiling", "Studio_AR-ID Placeholder", "Workset1", "Studio_AR-00 Link-STR"]
        pairs = dict((p["old"], p["new"]) for p in core.suggest_pairs(live, REGISTER))
        self.assertEqual(pairs, {"Studio_AR-00 Link-EL": "Studio_AR-00 Link-ELE",
                                 "Studio_AR-00 Link-PL": "Studio_AR-00 Link-PLB",
                                 "Studio_AR-Wall Fixtures": "Studio_AR-Walls Fixtures",      # not "Studio_AR-Fixtures"
                                 "Studio_AR-00 Link-Studio-AR-Facade": "Studio_AR-00 Link-Facade",
                                 "Studio_AR-Ceiling": "Studio_AR-Ceiling "})                 # trailing space only
        self.assertLess(core.similarity("Studio_AR-00 Link-EL", "Studio_AR-00 Link-Levels "), 0.85)
        both = core.suggest_pairs(["Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE"], REGISTER)
        self.assertEqual([(p["old"], p["both"]) for p in both], [("Studio_AR-00 Link-EL", True)])

    def test_register_tab_choice(self):
        tabs = [("Archive", ["Old A", "Old B"]), ("Sheet Model ", REGISTER), ("Empty", [])]
        live = ["Studio_AR-Walls ", "Old A"]
        self.assertEqual(core.best_tab(tabs, live, "Sheet Model "), "Sheet Model ")
        self.assertEqual(core.best_tab(tabs, ["Old A", "Old B"], "Missing tab"), "Archive")
        self.assertIsNone(core.best_tab([("Empty", [])], live))
        self.assertEqual(core.check_register(REGISTER, live), (56, 1, 1 / 56.0))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.snap = b001_snapshot()

    def test_step01_links(self):
        s1 = core.step01(self.snap["links"], RULES, "B001")
        self.assertEqual(sorted(d for d, _ in s1["ok"]), ["EL", "FF", "HV", "PL", "ST"])
        self.assertEqual([(w["kind"], w["disc"], w["code"]) for w in s1["wrong"]], [("WRONG SCOPE", "LA", "SW00")])
        self.assertEqual([(m["disc"], bool(m["expected"])) for m in s1["missing"]],
                         [("ID", True), ("LA", False), ("WS", False), ("TC", True), ("AV", False)])
        self.assertEqual(s1["others"], 6)                    # context links of other disciplines: left alone
        self.assertNotIn("nested", " ".join(l["name"] for l in self.snap["links"]))
        lines = core.link_instructions(s1["missing"][1:2], RULES, "B001")
        self.assertEqual(lines[0], "[LA] Insert > Link Revit > Autodesk Docs > <project> > A.WIP > 01.Architecture > "
                                   "Consumed > 03_LA_LANDSCAPE -- pick the B001 file only (ProjectC-*-BIM-B001-ZZZ-LA-*.rvt), "
                                   "Positioning: Auto - By Shared Coordinates")

    def test_another_buildings_discipline_link_is_flagged_not_removed_by_default(self):
        self.doc.link("ProjectC-DEC-BIM-B005-ZZZ-PL-400001.rvt", "Studio_AR-Walls ")     # a one-row-off click
        plan = core.make_plan(prep.snapshot(self.doc), RULES, "B001", REGISTER)
        self.assertEqual(sorted(w["kind"] for w in plan["step01"]["wrong"]), ["OTHER BUILDING", "WRONG SCOPE"])
        self.assertEqual([w["link"]["name"] for w in plan["remove"]], [B["LA"]])

    def test_step02_worksets(self):
        live = [w["name"] for w in self.snap["worksets"]]
        s2 = core.step02(live, REGISTER, [("Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE")])
        self.assertEqual((len(s2["matched"]), len(s2["missing"]), len(s2["create"])), (7, 49, 48))
        self.assertEqual(s2["extra"], ["Studio_AR-00 Link-EL", "Studio_AR-00 Link-PL", "Studio_AR-ID Placeholder",
                                       "Studio_AR-Wall Fixtures", "Workset1"])
        self.assertEqual(s2["renames"], [{"old": "Studio_AR-00 Link-EL", "new": "Studio_AR-00 Link-ELE", "delete_new": False}])
        self.assertNotIn("Studio_AR-00 Link-ELE", s2["create"])
        self.assertIn("Workset1", s2["final"])                 # never deleted
        self.assertNotIn("Studio_AR-00 Link-EL", s2["final"])
        bad = core.step02(live + ["Studio_AR-00 Link-ELE"], REGISTER + REGISTER[:1],
                          [("Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE"), ("Studio_AR-Walls ", "Studio_AR-Rooms "),
                           ("Workset1", "Not in register")], {"Studio_AR-00 Link-ELE": 4})
        self.assertEqual(bad["renames"], [])
        self.assertEqual(len(bad["problems"]), 3)
        self.assertEqual(bad["dupes"], [REGISTER[0]])
        merge = core.step02(live + ["Studio_AR-00 Link-ELE"], REGISTER, [("Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE")],
                            {"Studio_AR-00 Link-ELE": 0})
        self.assertEqual(merge["renames"][0]["delete_new"], True)

    def test_step03_rules(self):
        plan = core.make_plan(self.snap, RULES, "B001", REGISTER)
        rows = rows_by_name(plan)
        want = {"AR": "Studio_AR-00 Link-Podium Buildings", "ST": "Studio_AR-00 Link-STR", "EL": "Studio_AR-00 Link-ELE",
                "PL": "Studio_AR-00 Link-PLB", "FF": "Studio_AR-00 Link-FF", "HV": "Studio_AR-00 Link-MEC",
                "BM": "Studio_AR-00 Link-Levels ", "T00O": "Studio_AR-00 Link-Core", "TO": "Studio_AR-00 Link-Tower (T3)"}
        self.assertEqual(dict((k, rows[B[k]]["target"]) for k in want), want)
        self.assertNotIn(B["LA"], rows)                         # removed in Step 01, not placed
        status = dict((k, rows[B[k]]["status"]) for k in want)
        self.assertEqual(status, {"AR": "MOVE", "ST": "OK", "EL": "MOVE", "PL": "MOVE", "FF": "MOVE", "HV": "OK",
                                  "BM": "MOVE", "T00O": "MOVE", "TO": "MOVE"})
        self.assertEqual((rows[B["PL"]]["moves"], rows[B["FF"]]["moves"]), (3, 1))   # type + 2 instances; 1 instance
        self.assertEqual(rows[B["B005"]]["status"], "ASK")
        self.assertIn("cross-building AR link: B005's model inside B001", rows[B["B005"]]["question"]["why"])
        self.assertEqual(rows[B["B005"]]["question"]["suggest"], "Studio_AR-00 Link-Podium Buildings")
        self.assertEqual(rows[B["OLD"]]["question"]["why"], "file name does not follow the naming rule")
        self.assertEqual(core.actions(plan), {"remove": 1, "create": 49, "rename": 0, "move": 14})

    def test_ar_host_does_not_use_the_bm_rule_and_answers_win(self):
        plan = core.make_plan(self.snap, RULES, "B001", REGISTER, host_disc="AR")
        self.assertEqual(rows_by_name(plan)[B["AR"]]["status"], "ASK")
        plan = core.make_plan(self.snap, RULES, "B001", REGISTER,
                              {"answers": {B["B005"]: "Studio_AR-00 Link-Podium Buildings", B["OLD"]: ""}})
        rows = rows_by_name(plan)
        self.assertEqual((rows[B["B005"]]["status"], rows[B["B005"]]["rule"]), ("MOVE", "your answer"))
        self.assertEqual(rows[B["OLD"]]["status"], "LEAVE")

    def test_steps_off(self):
        plan = core.make_plan(self.snap, RULES, "B001", REGISTER, {"steps": set([3])})
        rows = rows_by_name(plan)
        self.assertIsNone(plan["step01"])
        self.assertEqual(rows[B["LA"]]["target"], None)           # not removed: Step 01 is off; LA has no workset yet
        self.assertIn("not created by Step 02", rows[B["PL"]]["question"]["why"])
        self.assertEqual(rows[B["ST"]]["status"], "OK")
        self.assertEqual(core.actions(plan)["create"], 0)
        plan = core.make_plan(self.snap, RULES, "B001", None, {"steps": set([2])})
        self.assertIn((core.FAIL, "No workset register list -- pick the register file and tab"),
                      core.preflight(plan, RULES))

    def test_report(self):
        plan = core.make_plan(self.snap, RULES, "B001", REGISTER)
        text = "\n".join("[%s] %s" % l for l in core.report(plan, RULES, ("Register tab 'Sheet Model ': 56", core.OK)))
        for line in ("[OK  ] Open model is B001 -- BM host (ProjectC-Studio-BIM-B001-ZZZ-BM-950001_user)",
                     "WRONG SCOPE [LA] %s -- a SW00 file, not B001's own  -> REMOVE on Apply" % B["LA"],
                     "MISSING [ID] link by hand from Consumed > 02_ID_INTERIORS  (expected: no building-specific "
                     "Interiors model exists yet)",
                     "[WARN] MISSING [WS] link by hand from Consumed > 08_WS_WAYFINDING & SIGNAGE",
                     "CREATE 'Studio_AR-Ceiling '",                     # the trailing space shows
                     "LOOKS ALIKE 'Studio_AR-00 Link-EL' ~ register 'Studio_AR-00 Link-ELE'",
                     "EXTRA 'Workset1' -- in the model, not in the register: left alone",
                     "MOVE %s: type 'Studio_AR-00 Link-FF' / instances 'Studio_AR-Walls ' -> 'Studio_AR-00 Link-FF'" % B["FF"],
                     "ASK %s on 'Studio_AR-Walls ' -- cross-building AR link" % B["B005"],
                     "Apply would: remove 1 link(s), create 49 workset(s), rename 0, set 14 link placement(s)"):
            self.assertIn(line, text)
        self.assertIn((core.WARN, "The open model looks like B001 (%s) -- you set the host building to B002" %
                       self.doc.Title), core.preflight(core.make_plan(self.snap, RULES, "B002", REGISTER), RULES))
        self.assertEqual(core.preflight(core.make_plan(self.snap, RULES, "", REGISTER), RULES)[0][0], core.FAIL)


class XlsxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_read_register(self):
        path = make_xlsx(os.path.join(self.tmp, "Worksets.xlsx"), [
            ("Archive", [["Old A", 1], ["Old B"]]),
            ("Sheet Model ", [["Studio_AR-Walls ", "note"], [None, "B only"], ["inline:Studio_AR-Rooms "],
                              ["rich:Studio_AR-00 |Link-Tower (PO)"], ["   "], [42], ["Studio_AR-Doors (BOH) & Co"]])])
        tabs = xlsx.read_register(path)
        self.assertEqual(tabs, [("Archive", ["Old A", "Old B"]),
                                ("Sheet Model ", ["Studio_AR-Walls ", "Studio_AR-Rooms ", "Studio_AR-00 Link-Tower (PO)", "42",
                                                  "Studio_AR-Doors (BOH) & Co"])])
        self.assertEqual(xlsx.read_register(path, "B", 1)[1][1], ["B only"])

    def test_bad_files(self):
        with self.assertRaises(xlsx.RegisterError):
            xlsx.read_register(os.path.join(self.tmp, "none.xlsx"))
        bad = os.path.join(self.tmp, "bad.xlsx")
        with io.open(bad, "w") as f:
            f.write(u"not a zip")
        with self.assertRaises(xlsx.RegisterError):
            xlsx.read_register(bad)
        with self.assertRaises(xlsx.RegisterError):
            xlsx.read_register(bad, "1")


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = {"APPDATA": self.tmp}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_defaults_user_file_and_remember(self):
        r = rules_mod.load(self.env)
        self.assertEqual((r["register_sheet"], r["_errors"]), ("Sheet Model ", []))
        path = rules_mod.user_path(self.env)
        os.makedirs(os.path.dirname(path))
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(u'{"register_sheet": "Worksets", "typo_key": 1}')
        r = rules_mod.load(self.env)
        self.assertEqual(r["register_sheet"], "Worksets")
        self.assertEqual(r["_errors"], ["unknown key in rules.json: typo_key"])
        rules_mod.remember({B["B005"]: "Studio_AR-00 Link-Podium Buildings"}, self.env)
        r = rules_mod.load(self.env)
        self.assertEqual(r["manual_overrides"][B["B005"]], "Studio_AR-00 Link-Podium Buildings")
        self.assertEqual(r["manual_overrides"][B["BM"]], "Studio_AR-00 Link-Levels ")     # the default one kept
        with io.open(path, encoding="utf-8") as f:
            self.assertNotIn("worksets", f.read())               # only the user's own keys are written
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(u"[1, 2]")
        self.assertIn("could not be read", rules_mod.load(self.env)["_errors"][0])
        os.remove(path)
        self.assertTrue(os.path.isfile(rules_mod.ensure_user_file(self.env)))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.snap = b001_snapshot()

    def plan(self, **decisions):
        return core.make_plan(prep.snapshot(self.doc), RULES, "B001", REGISTER, decisions,
                              dict((n, prep.count_elements(self.doc, n)) for _, n in decisions.get("pairs", [])
                                   if n in self.doc.names()))

    def test_apply_and_verify(self):
        plan = self.plan(pairs=[("Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE")],
                         answers={B["B005"]: "Studio_AR-00 Link-Podium Buildings"})
        log = []
        done = prep.apply(self.doc, plan, log)
        self.assertEqual(done, {"removed": 1, "created": 48, "renamed": 1, "set": 14, "skipped": []})
        self.assertEqual(self.doc.undo, ["Model Prep by Netbuild"])          # one Undo entry
        placed = self.doc.placed()
        self.assertNotIn(B["LA"], placed)
        self.assertEqual(placed[B["PL"]], ("Studio_AR-00 Link-PLB", ["Studio_AR-00 Link-PLB"] * 2))
        self.assertEqual(placed[B["FF"]], ("Studio_AR-00 Link-FF", ["Studio_AR-00 Link-FF"]))
        self.assertEqual(placed[B["EL"]], ("Studio_AR-00 Link-ELE", ["Studio_AR-00 Link-ELE"]))   # renamed, not moved
        self.assertEqual(placed[B["B005"]][0], "Studio_AR-00 Link-Podium Buildings")
        self.assertEqual(placed[B["OLD"]][0], "Studio_AR-Walls ")                # asked, not answered: left
        self.assertEqual(prep.count_elements(self.doc, "Studio_AR-00 Link-ELE"), 5)  # 3 elements + the EL link
        self.assertIn("Workset1", self.doc.names())
        self.assertEqual(len([n for n in REGISTER if n not in self.doc.names()]), 0)
        self.assertTrue([l for l in log if l.startswith("renamed workset 'Studio_AR-00 Link-EL'")])
        checks = core.verify(plan, prep.snapshot(self.doc))
        self.assertEqual([c[0] for c in checks], [core.OK] * 3, checks)
        again = self.plan()
        self.assertEqual(core.actions(again), {"remove": 0, "create": 0, "rename": 0, "move": 0})

    def test_merge_into_an_empty_register_workset(self):
        self.doc.workset("Studio_AR-00 Link-ELE")
        plan = self.plan(pairs=[("Studio_AR-00 Link-EL", "Studio_AR-00 Link-ELE")])
        self.assertTrue(plan["step02"]["renames"][0]["delete_new"])
        prep.apply(self.doc, plan)
        self.assertEqual(self.doc.names().count("Studio_AR-00 Link-ELE"), 1)
        self.assertEqual(prep.count_elements(self.doc, "Studio_AR-00 Link-ELE"), 5)   # 3 + the EL link's type + instance

    def test_failure_rolls_everything_back(self):
        before = (self.doc.names(), self.doc.placed())
        self.doc.fail_on = "Step 03: link worksets"
        with self.assertRaises(RuntimeError):
            prep.apply(self.doc, self.plan())
        self.assertEqual((self.doc.names(), self.doc.placed()), before)
        self.assertEqual(self.doc.undo, [])
        self.assertIsNone(self.doc.tx)

    def test_borrowed_and_read_only(self):
        lt = [e for e in self.doc.elements.values() if getattr(e, "type_name", None) == B["T00O"]][0]
        self.doc.owners[lt.Id.Value] = "maria.k"
        hv = [e for e in self.doc.elements.values() if getattr(e, "type_name", None) == B["AR"]][0]
        hv.ws_locked = True
        plan = self.plan()
        self.assertEqual(rows_by_name(plan)[B["T00O"]]["status"], "BORROWED")
        done = prep.apply(self.doc, plan)
        self.assertEqual(self.doc.placed()[B["T00O"]][0], "Studio_AR-Walls ")
        self.assertEqual(len(done["skipped"]), 1)
        self.assertIn("read-only", done["skipped"][0])

    def test_model_problem(self):
        self.assertIsNone(prep.model_problem(self.doc))
        self.doc.IsWorkshared = False
        self.assertIn("not workshared", prep.model_problem(self.doc))
        self.assertEqual(prep.model_problem(None), "Open a project model first.")


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = self.tmp
        self.doc, _ = b001_snapshot()
        self.register = make_xlsx(os.path.join(self.tmp, "3470 ProjectA Wadi High Rise - Worksets.xlsx"),
                                  [("Archive", [["Old A"]]), ("Sheet Model ", [[n] for n in REGISTER])])

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open_window(self, **answers):
        st = pyrevit_stubs.install(self.doc, answers=answers)
        st.config.values["register_path"] = self.register
        fake_links.install()
        runpy.run_path(MODEL_PREP, run_name="__main__")
        return st, pyrevit_stubs.WPFWindow.shown[0]

    def report(self, win):
        return "\n".join(i.Content for i in win.report_lb.Items)

    def test_check_decide_apply(self):
        st, win = self.open_window()
        self.assertEqual(win.Title, "Model Prep by Netbuild %s -- %s" % (about.VERSION, self.doc.Title))
        self.assertEqual(win.building_tb.Text, "B001")
        self.assertIn("B001, BM host", win.host_tb.Text)
        self.assertEqual(win.sheet_cb.Items, ["Archive", "Sheet Model ", "(the list saved in the rules)"])
        self.assertEqual(win.sheet_cb.SelectedItem, "Sheet Model ")
        self.assertEqual(win.register_info_tb.Text,
                         "Register tab 'Sheet Model ': 56 names, 7 already in this model (12%) -- few match: check "
                         "this tab belongs to this model before trusting it")
        self.assertFalse(win.apply_btn.IsEnabled)
        snap0 = (self.doc.names(), self.doc.placed())
        win.check_btn.click()                                             # dry run: nothing changes
        self.assertEqual((self.doc.names(), self.doc.placed()), snap0)
        self.assertTrue(win.apply_btn.IsEnabled)
        self.assertIn("5 item(s) to decide first", win.status_tb.Text)  # 2 links to ask + 3 look-alikes
        text = self.report(win)
        self.assertIn("== STEP 01 -- discipline links (B001-specific only; never adds a link)", text)
        self.assertIn("[FAIL] WRONG SCOPE [LA]", text)
        win.building_tb.type("B002")                                      # any change: Check again first
        self.assertFalse(win.apply_btn.IsEnabled)
        win.building_tb.type("B001")
        win.check_btn.click()

        def decide(dlg):
            self.assertEqual(dlg.rm_0.IsChecked, True)
            self.assertIn("WRONG SCOPE [LA]", dlg.rm_0.Content)
            pairs = [dlg.FindName("pair_%d" % i).Content for i in range(len(dlg.pairs))]
            self.assertEqual(len(pairs), 3)
            self.assertIn("'Studio__AR-00 Link-EL'  ->  register 'Studio__AR-00 Link-ELE'", pairs[0])   # WPF access keys
            self.assertFalse([i for i in range(3) if dlg.FindName("pair_%d" % i).IsChecked])   # never pre-ticked
            for i, p in enumerate(dlg.pairs):
                if p["old"] in ("Studio_AR-00 Link-EL", "Studio_AR-00 Link-PL"):
                    dlg.FindName("pair_%d" % i).IsChecked = True
            names = [dlg.FindName("ask_name_%d" % i).Text.split("\n")[0] for i in range(len(dlg.asks))]
            self.assertEqual(sorted(names), sorted([B["B005"], B["OLD"]]))
            i = names.index(B["B005"])
            combo = dlg.FindName("ask_ws_%d" % i)
            self.assertEqual(combo.SelectedItem, modelprep_ui.LEAVE)      # suggested, not chosen for the user
            self.assertEqual(combo.Items[1], "Studio_AR-00 Link-Podium Buildings")
            combo.SelectedItem = "Studio_AR-00 Link-Podium Buildings"
            dlg.remember_cb.IsChecked = True
            dlg.ok_btn.click()
        pyrevit_stubs.WPFWindow.on_dialog = decide
        win.decide_btn.click()
        pyrevit_stubs.WPFWindow.on_dialog = None
        self.assertEqual(rules_mod.load()["manual_overrides"][B["B005"]], "Studio_AR-00 Link-Podium Buildings")
        text = self.report(win)
        self.assertIn("RENAME 'Studio_AR-00 Link-EL' -> 'Studio_AR-00 Link-ELE'", text)
        self.assertIn("LOOKS ALIKE 'Studio_AR-Wall Fixtures' ~ register 'Studio_AR-Walls Fixtures'", text)
        win.apply_btn.click()
        self.assertEqual(st.alerts[-1][0], "Apply")                       # asked first
        self.assertIn("Remove 1 link(s): %s" % B["LA"], st.alerts[-1][1])
        self.assertEqual(self.doc.undo, ["Model Prep by Netbuild"])
        placed = self.doc.placed()
        self.assertEqual(placed[B["PL"]], ("Studio_AR-00 Link-PLB", ["Studio_AR-00 Link-PLB"] * 2))
        self.assertEqual(placed[B["B005"]][0], "Studio_AR-00 Link-Podium Buildings")
        self.assertNotIn("Studio_AR-00 Link-EL", self.doc.names())
        self.assertIn("Studio_AR-Wall Fixtures", self.doc.names())           # unticked: left alone
        text = self.report(win)
        self.assertIn("== VERIFY -- the model read back", text)
        self.assertNotIn("[FAIL]", text.split("== VERIFY")[1].split("== Model Prep")[0])
        self.assertIn("Apply would: remove 0 link(s), create 0 workset(s), rename 0, set 0 link placement(s)", text)
        logs = os.listdir(os.path.join(self.tmp, "Netbuild", "ModelPrep", "logs"))
        self.assertTrue([n for n in logs if n.endswith("_B001.log")], logs)
        self.assertIn("Applied -- Ctrl+Z", win.status_tb.Text)

    def test_apply_needs_a_fresh_check_and_paths_about(self):
        st, win = self.open_window()
        win.apply_btn.click()
        self.assertIn("Check first", st.alerts[-1][1])
        win.check_btn.click()
        self.doc.link("ProjectC-DEC-BIM-B001-ZZZ-WS-400001.rvt", "Studio_AR-Walls ")    # model changed after Check
        win.apply_btn.click()
        self.assertIn("The model changed since Check", win.status_tb.Text)
        self.assertEqual(self.doc.undo, [])
        win.paths_btn.click()
        self.assertIn("[AV] Insert > Link Revit > Autodesk Docs", st.clipboard[-1])
        self.assertNotIn("[WS]", st.clipboard[-1])                         # just linked
        win.about_btn.click()
        about_win = pyrevit_stubs.WPFWindow.shown[-1]
        self.assertEqual(about_win.product_tb.Text, "Model Prep by Netbuild")
        self.assertIn("Autodesk Revit 2019 - 2026", about_win.req_tb.Text)
        about_win.licence_btn.click()
        lic = pyrevit_stubs.WPFWindow.shown[-1]
        self.assertEqual(lic.license_tb.Text, about.LICENSE_TEXT)
        self.assertEqual(lic.key_tb.Text, "No licence key required for this product.")

    def test_unreadable_register_uses_the_saved_list(self):
        os.remove(self.register)
        st, win = self.open_window()
        self.assertEqual(win.sheet_cb.SelectedItem, "(the list saved in the rules)")
        self.assertIn("Register not read: not found:", win.register_info_tb.Text)
        win.step1_cb.IsChecked = False
        win.check_btn.click()
        self.assertIn("Register 56", self.report(win))
        self.assertNotIn("STEP 01", self.report(win))

    def test_refuses_a_model_without_worksets(self):
        self.doc.IsWorkshared = False
        st = pyrevit_stubs.install(self.doc)
        fake_links.install()
        with self.assertRaises(pyrevit_stubs.ScriptExit):
            runpy.run_path(MODEL_PREP, run_name="__main__")
        self.assertIn("not workshared", st.alerts[-1][1])

    def test_place_links(self):
        st = pyrevit_stubs.install(self.doc)
        fake_links.install()
        runpy.run_path(PLACE_LINKS, run_name="__main__")                  # asks, then places
        ask, result = st.alerts[-2], st.alerts[-1]
        self.assertIn("Put these links on their worksets", ask[1])
        self.assertIn("%s: 'Studio_AR-Walls ' -> 'Studio_AR-00 Link-Core'" % B["T00O"], ask[1])
        self.assertIn("Not placed -- no confident rule", ask[1])
        self.assertIn("Placed", result[1])
        placed = self.doc.placed()
        self.assertEqual(placed[B["T00O"]][0], "Studio_AR-00 Link-Core")
        self.assertEqual(placed[B["PL"]][0], "Studio_AR-00 Link-MEC")        # Link-PLB not created yet: left
        self.assertEqual(placed[B["LA"]][0], "Studio_AR-Walls ")             # Place Links never removes a link
        self.assertEqual(self.doc.undo, ["Model Prep by Netbuild"])
        with self.assertRaises(pyrevit_stubs.ScriptExit):                  # second run: nothing to move
            runpy.run_path(PLACE_LINKS, run_name="__main__")
        self.assertIn("none to move", st.alerts[-1][1])

    def test_xaml(self):
        import xml.etree.ElementTree as ET
        ET.fromstring(modelprep_ui.window_xaml())
        dlg = ET.fromstring(modelprep_ui.decisions_xaml(2, 1, 3))
        names = [e.get(pyrevit_stubs.X_NAME) for e in dlg.iter() if e.get(pyrevit_stubs.X_NAME)]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len([n for n in names if n.startswith("ask_ws_")]), 3)
        ET.fromstring(modelprep_ui.decisions_xaml(0, 0, 0))


class AboutTests(unittest.TestCase):
    def test_about(self):
        with io.open(os.path.join(os.path.dirname(ROOT), "LICENSE"), encoding="utf-8") as f:
            self.assertEqual(about.LICENSE_TEXT, f.read())
        self.assertEqual(about.PRODUCT, "Model Prep by Netbuild")
        self.assertEqual((about.PUBLISHER, about.OWNER, about.WEBSITE), ("Netbuild", "Netbuild", "https://skaec.com"))
        self.assertEqual(about.COPYRIGHT, u"© 2026 Netbuild. All rights reserved.")
        self.assertIn("Licence: Netbuild Software Licence Agreement (proprietary) -- owned by Netbuild",
                      about.about_text())
        self.assertTrue(about.licence_text().startswith("Model Prep by Netbuild  version " + about.VERSION))
        pyrevit_stubs.install(None)
        import netbuild_about
        self.assertIn(about, netbuild_about.PRODUCTS)


if __name__ == "__main__":
    unittest.main()

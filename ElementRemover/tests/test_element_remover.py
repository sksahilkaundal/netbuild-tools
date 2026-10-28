"""Tests against a stand-in Revit (no Revit needed): the engine in-process and through the listener, the CLI.

    python -m unittest discover -s ElementRemover/tests -v
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_revit import FakeRevit, Group, SketchPlane, WorksetId  # noqa: E402
from element_remover import about, cli, core, revit  # noqa: E402
from element_remover.core import Targets  # noqa: E402
from element_remover.payload import CODE  # noqa: E402
from element_remover.runner import Runner  # noqa: E402
from element_remover.settings import Settings  # noqa: E402


class UnitTests(unittest.TestCase):
    def test_split_names_and_targets(self):
        self.assertEqual(core.split_names(" Walls, Doors;Walls\nFloors ,"), ["Walls", "Doors", "Floors"])
        self.assertEqual(core.split_names(""), [])
        t = Targets(["Demolition"], ["To Remove"], ["Walls"], "all")
        self.assertEqual(t.describe(), "worksets: Demolition AND filters: To Remove  (categories: Walls)")
        self.assertEqual(t.checks(), [])
        self.assertEqual([c.ok for c in Targets().checks()], [False])
        self.assertEqual([c.ok for c in Targets(["Demolition"], combine="all").checks()], [None])
        with self.assertRaises(ValueError):
            Targets(combine="some")

    def test_payload_is_py2_shaped_and_compiles(self):
        code = revit.action_code("n", "plan", ["B003"], Targets([u"Démolition"], ["To Remove"]))
        compile(code, "<revit>", "exec")
        self.assertIn(u"u'D\u00e9molition'", code)
        self.assertNotIn('f"', CODE)
        self.assertNotIn("f'", CODE)
        cfg = core.config("n", "apply", (), Targets(["A"]), {"skip_pinned": False})
        self.assertEqual((cfg["skip_pinned"], cfg["fix_groups"], cfg["model_only"]), (False, True, True))


class AboutTests(unittest.TestCase):
    def test_product_info_and_license(self):
        from element_remover import __version__
        with open(os.path.join(os.path.dirname(os.path.dirname(HERE)), "LICENSE"), encoding="utf-8") as f:
            self.assertEqual(about.LICENSE_TEXT, f.read())            # the About screen shows the real LICENSE
        self.assertEqual((about.OWNER, about.PUBLISHER, about.WEBSITE), ("Netbuild", "Netbuild", "https://skaec.com"))
        self.assertEqual(about.COPYRIGHT, u"© 2026 Netbuild. All rights reserved.")
        self.assertEqual(about.LICENSE_NAME, "Netbuild Software Licence Agreement (proprietary)")
        self.assertEqual(about.LICENSE_KIND, "Proprietary software -- owned by Netbuild")
        self.assertEqual(about.LICENCE_KEY, "No licence key required for this product.")
        self.assertEqual(about.PRODUCT, "Element Remover by Netbuild")
        self.assertEqual(about.title("B003"), "Element Remover by Netbuild %s -- B003" % __version__)
        text = about.about_text()
        for want in ("Element Remover by Netbuild  version " + __version__, u"© 2026 Netbuild. All rights reserved.",
                     "Requirements", "Autodesk Revit 2019 - 2026", "pyRevit 4.8", "Python 3.9",
                     "Licence: Netbuild Software Licence Agreement (proprietary) -- owned by Netbuild, "
                     "https://skaec.com", "Netbuild Software Licence Agreement\n\nCopyright"):
            self.assertIn(want, text)
        for gone in ("SKAEC.COM", "MIT"):
            self.assertNotIn(gone, text)
        page = about.licence_text()
        for want in ("Proprietary software -- owned by Netbuild", "Website: https://skaec.com",
                     "No licence key required", about.LICENSE_TEXT.rstrip()):
            self.assertIn(want, page)

    def test_cli_about_licence_and_version(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["about"]), 0)
        self.assertIn("Netbuild. All rights reserved.", buf.getvalue())
        self.assertIn("Requirements", buf.getvalue())
        for cmd in ("license", "licence"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(cli.main([cmd]), 0)
            self.assertEqual(buf.getvalue(), about.licence_text() + "\n")
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            cli.main(["--version"])
        self.assertEqual(buf.getvalue().strip(), "Element Remover by Netbuild " + about.VERSION)

    def test_exe_version_resource(self):
        import make_version_file
        text = make_version_file.render("ElementRemover.exe")
        seen = {}

        def rec(name):
            return lambda *a, **k: seen.setdefault(name, []).append((a, k)) or (name, a, k)
        ns = dict((n, rec(n)) for n in ("VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable",
                                        "StringStruct", "VarFileInfo", "VarStruct"))
        eval(compile(text.split("\n", 1)[1], "version_info", "eval"), ns)  # what PyInstaller does with it
        fields = dict(a for a, k in seen["StringStruct"])
        self.assertEqual(fields["CompanyName"], "Netbuild")
        self.assertEqual(fields["ProductName"], "Element Remover by Netbuild")
        self.assertEqual(fields["LegalCopyright"], "(c) 2026 Netbuild. All rights reserved.")
        self.assertEqual(fields["Comments"], "https://skaec.com")
        self.assertEqual(fields["OriginalFilename"], "ElementRemover.exe")
        self.assertEqual(seen["FixedFileInfo"][0][1]["filevers"], (1, 0, 0, 0))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRevit()
        self.doc = self.fake.doc
        self.el = self.fake.el
        self.snap0 = self.doc.snapshot()

    def tearDown(self):
        self.fake.close()

    def run_(self, action, worksets=(), filters=(), t=None, **options):
        """The engine in-process; ``t``: more Targets fields, ``options``: engine settings."""
        return core.run_local(self.doc, action, Targets(worksets, filters, **(t or {})), options or None)

    def gone(self, *keys):
        return [k for k in keys if not self.doc.alive(self.el[k])]

    def unchanged(self):
        return self.doc.snapshot() == self.snap0

    def grouped_with(self, key):
        """(type name, sorted member names) of the group that now holds an element."""
        g = self.doc.group_of(self.el[key])
        return g.GroupType.Name, sorted(m.Name for m in g.member_els())

    def instances(self, type_name):
        """The group instances of a type, as {instance id: sorted [(member name, position, mirrored)]}."""
        return dict((g.Id.Value, sorted((m.Name, m.pos, m.mirrored) for m in g.member_els()))
                    for g in self.doc.by_id.values() if isinstance(g, Group) and g.GroupType.Name == type_name)

    def status(self, out, key):
        return [r["status"] for r in out["RESULT"]["rows"] if r["id"] == self.el[key].Id.Value][0]


class SourcesTests(Fixture):
    def test_sources(self):
        out = core.run_local(self.doc, "sources")
        self.assertEqual(out["DOC"]["title"], self.doc.Title)
        src = out["SOURCES"]
        self.assertEqual([(w["name"], w["elements"], w["open"]) for w in src["worksets"]], [
            ("Architecture", 16, True), ("Demolition", 5, True), ("Interiors", 9, True),
            ("Shared Levels and Grids", 3, True), ("Site", 0, False)])                    # view worksets left out
        self.assertEqual([(f["name"], f["kind"], f["categories"], f["elements"]) for f in src["filters"]], [
            ("All Walls", "rules", ["Walls"], None), ("Pick list", "selection", [], 4),
            ("To Remove", "rules", ["Doors", "Plumbing Fixtures", "Walls"], None)])
        self.assertEqual(src["categories"], ["Doors", "Floors", "Furniture", "Model Groups", "Plumbing Fixtures",
                                             "Walls"])                                   # no levels / grids / tags
        lines = core.sources_lines(src)
        self.assertIn("[closed]", [l for l in lines if "Site" in l][0])
        self.assertTrue(self.unchanged())


class WorksetTests(Fixture):
    def test_plan_changes_nothing(self):
        out = self.run_("plan", ["Demolition"])
        plan = out["PLAN"]
        self.assertNotIn("RESULT", out)
        self.assertEqual((plan["targets"], plan["standalone"], plan["in_groups"], plan["groups"]), (3, 2, 1, 1))
        self.assertEqual(plan["group_types"], ["Store"])
        self.assertEqual(plan["skipped_why"], [["pinned", 1], ["protected: Grids", 1]])
        self.assertEqual(plan["by_category"], [["Walls", 3]])
        rows = dict((r["id"], r) for r in plan["rows"])
        self.assertEqual(rows[self.el["store wall 3"].Id.Value]["status"], "to remove (taken out of its group)")
        self.assertIn("Store (id ", rows[self.el["store wall 3"].Id.Value]["group"])
        self.assertEqual(rows[self.el["demo slab"].Id.Value]["status"][:15], "skipped: pinned")
        self.assertEqual(rows[self.el["demo wall 1"].Id.Value]["workset"], "Demolition")
        checks, lines = core.plan_checks(plan)
        self.assertEqual([c.ok for c in checks], [True, None, None])
        self.assertTrue(self.unchanged())

    def test_trial_rolls_back(self):
        out = self.run_("trial", ["Demolition"])
        r = out["RESULT"]
        self.assertFalse(r["committed"])
        self.assertEqual((r["requested"], r["deleted"], r["left"]), (3, 3, []))
        self.assertEqual(r["dependents"], [["Doors", 1], ["Wall Tags", 1]])
        self.assertTrue(self.unchanged())
        self.assertEqual(self.doc.groups, [("Element Remover by Netbuild", "rolled back")])
        checks, _ = core.result_checks("trial", r)
        self.assertEqual(checks[-1].label, "Trial")
        self.assertIn("rolled back", str(checks[-1]))

    def test_apply_standalone_and_grouped(self):
        out = self.run_("apply", ["Demolition"])
        r = out["RESULT"]
        self.assertTrue(r["committed"], r)
        self.assertEqual(self.doc.groups, [("Element Remover by Netbuild", "assimilated")])  # one Undo entry
        self.assertEqual(self.gone("demo wall 1", "demo wall 2", "store wall 3", "demo door", "demo tag"),
                         ["demo wall 1", "demo wall 2", "store wall 3", "demo door", "demo tag"])
        self.assertEqual(self.gone("demo slab", "grid B", "wall keep", "store shelf 3"), [])   # pinned / protected
        # G3 regrouped without its wall; G4 still uses 'Store', so the new type is renamed
        self.assertEqual(self.grouped_with("store shelf 3"), ("Store (elements removed)", ["Shelf"]))
        self.assertEqual(self.grouped_with("store wall 4"), ("Store", ["Shelf", "Store partition"]))
        self.assertEqual(self.status(out, "store wall 3"), "deleted (taken out of its group)")
        self.assertEqual(self.status(out, "demo door"), "deleted with a removed element")
        self.assertEqual(r["total"], 5)
        checks, lines = core.result_checks("apply", r)
        self.assertEqual([c.label for c in checks], ["Removed", "Deleted with them by Revit", "Groups regrouped",
                                                     "Applied"])
        self.assertIn("'Store' -> 'Store (elements removed)'", str(checks[2]))

    def test_categories_and_pinned(self):
        out = self.run_("plan", ["Demolition"], t={"categories": ["floors"]})
        self.assertEqual((out["PLAN"]["targets"], out["PLAN"]["skipped_why"]), (0, [["pinned", 1]]))
        out = self.run_("apply", ["Demolition"], t={"categories": ["Floors"]})
        self.assertEqual(out["RESULT"]["stopped"], "nothing to remove")
        self.assertTrue(self.unchanged())
        out = self.run_("apply", ["Demolition"], t={"categories": ["Floors"]}, skip_pinned=False)
        self.assertTrue(out["RESULT"]["committed"])
        self.assertEqual(self.gone("demo slab", "demo wall 1"), ["demo slab"])            # unpinned, removed

    def test_walls_only(self):
        out = self.run_("apply", ["Demolition", "Architecture"], t={"categories": ["Walls"]})
        self.assertTrue(out["RESULT"]["committed"])
        self.assertEqual(out["RESULT"]["requested"], 9)
        # every wall on both worksets, standalone or grouped; doors / WCs / shelves stay (unless hosted)
        self.assertEqual(self.gone("wall keep", "wall remove", "core wall 1", "core wall 2", "apt wall",
                                   "store wall 3", "store wall 4"),
                         ["wall keep", "wall remove", "core wall 1", "core wall 2", "apt wall", "store wall 3",
                          "store wall 4"])
        self.assertEqual(self.gone("core door 1", "core wc 1", "store shelf 3"), ["core door 1"])  # door was hosted
        self.assertEqual(self.grouped_with("core wc 1"), ("Toilet Core", ["WC"]))
        # both Store instances lost their wall and are alike: they share one type again
        self.assertEqual(self.grouped_with("store shelf 3"), ("Store", ["Shelf"]))
        self.assertEqual(sorted(self.instances("Store").values()),
                         [[("Shelf", (102.0, 4.0, 0.0), False)], [("Shelf", (132.0, 4.0, 0.0), False)]])
        self.assertNotIn("Store (2)", self.doc.type_names())


class FilterTests(Fixture):
    def test_rule_filter_nested_and_repeated_groups(self):
        out = self.run_("apply", filters=["To Remove"])
        r = out["RESULT"]
        self.assertTrue(r["committed"], r)
        self.assertEqual(self.gone("wall remove", "core door 1", "core door 2", "basin 6", "basin 7"),
                         ["wall remove", "core door 1", "core door 2", "basin 6", "basin 7"])
        # no instance of the old types is left: the new types keep the names (old types deleted)
        # no instance of the old types is left: the new types keep the names (old types deleted). The two
        # Toilet Cores are alike again and share one type; a nested Bath Pod is never switched
        self.assertEqual(self.doc.type_names(), ["Apartment", "Bath Pod", "Bath Pod (2)", "Store", "Toilet Core"])
        self.assertEqual(self.grouped_with("core wall 1"), ("Toilet Core", ["Partition 100", "WC"]))
        self.assertEqual(sorted(self.instances("Toilet Core").values()), [
            [("Partition 100", (0.0, 0.0, 0.0), False), ("WC", (5.0, 3.0, 0.0), False)],
            [("Partition 100", (40.0, 0.0, 0.0), False), ("WC", (45.0, 3.0, 0.0), False)]])   # nothing moved
        self.assertEqual(self.gone("core wall 2", "core wc 2"), ["core wall 2", "core wc 2"])  # rebuilt: new ids
        self.assertEqual([g["merged"] for g in sorted(r["groups"], key=lambda g: g["old_id"])],
                         [False, True, False, False, False])
        # the nested Bath Pod is regrouped first, then the Apartment around it
        pod = self.doc.group_of(self.el["bath 6"])
        self.assertEqual(sorted(m.Name for m in pod.member_els()), ["Bath"])
        apt = self.doc.group_of(pod)
        self.assertEqual(apt.GroupType.Name, "Apartment")
        self.assertEqual(sorted(m.Name for m in apt.member_els()), ["Apartment Wall 150", "Bath Pod"])
        self.assertEqual(len(r["groups"]), 5)
        self.assertEqual(self.gone("core wall 1", "bath 6", "apt wall", "wall keep"), [])

    def test_merge_checks_every_member(self):
        before = self.instances("Toilet Core")
        out = self.run_("trial", filters=["To Remove"])                 # the merge is rolled back with the rest
        self.assertEqual(len([g for g in out["RESULT"]["groups"] if g["merged"]]), 1)
        self.assertTrue(self.unchanged())
        # a mirrored instance: switching it to the other one's type would mirror its members -> not merged
        for k in ("core wall 2", "core door 2", "core wc 2"):
            self.el[k].mirrored = True
        out = self.run_("apply", filters=["To Remove"])
        r = out["RESULT"]
        self.assertTrue(r["committed"], r)
        self.assertEqual(r["errors"], [])                                # a refused merge is not an error
        self.assertIn("Toilet Core (2)", self.doc.type_names())
        self.assertEqual(self.gone("core wall 2", "core wc 2"), [])      # its members kept their Element Ids
        self.assertEqual([m[2] for m in self.instances("Toilet Core (2)").popitem()[1]], [True, True])
        kept = [g for g in r["groups"] if g["merge"].startswith("kept")]
        self.assertEqual(len(kept), 1)
        self.assertIn("would not match", kept[0]["merge"])
        checks, lines = core.result_checks("apply", r)
        self.assertIn("Group types not merged", [c.label for c in checks])
        self.assertNotIn("Group types merged", [c.label for c in checks])
        self.assertTrue([l for l in lines if "kept 'Toilet Core (2)'" in l], lines)
        self.assertTrue(len(before) == 2 and [x for x in before.values() if len(x) == 3])

    def test_merge_keeps_member_data(self):
        """Marks differ between the instances: a merge would copy one's Marks onto the other -> not merged."""
        self.el["core wc 1"].mark, self.el["core wc 2"].mark = "WC-101", "WC-201"
        out = self.run_("apply", filters=["To Remove"])
        self.assertTrue(out["RESULT"]["committed"])
        self.assertIn("Toilet Core (2)", self.doc.type_names())
        self.assertEqual((self.el["core wc 2"].mark, self.gone("core wc 2")), ("WC-201", []))
        self.assertIn("would not match", [g for g in out["RESULT"]["groups"] if g["merge"]][0]["merge"])

    def test_merge_option_off(self):
        plan, _ = core.plan_checks(self.run_("plan", filters=["To Remove"], merge_groups=False)["PLAN"])
        self.assertNotIn("share one group type", str([c for c in plan if c.label == "Model groups"][0]))
        out = self.run_("apply", filters=["To Remove"], merge_groups=False)
        self.assertTrue(out["RESULT"]["committed"])
        self.assertEqual(self.doc.type_names(), ["Apartment", "Bath Pod", "Bath Pod (2)", "Store", "Toilet Core",
                                                 "Toilet Core (2)"])
        self.assertEqual(self.gone("core wall 2", "core wc 2"), [])      # Element Ids kept
        self.assertEqual([g["merge"] for g in out["RESULT"]["groups"]], [""] * 5)

    def test_merged_report(self):
        plan, _ = core.plan_checks(self.run_("plan", filters=["To Remove"])["PLAN"])
        self.assertIn("share one group type again", str([c for c in plan if c.label == "Model groups"][0]))
        out = self.run_("apply", filters=["To Remove"])
        checks, lines = core.result_checks("apply", out["RESULT"])
        merged = [c for c in checks if c.label == "Group types merged"][0]
        self.assertIn("1 regrouped instance(s) now share the type", str(merged))
        self.assertIn("new Element Ids", str(merged))
        self.assertTrue([l for l in lines if "merged into 'Toilet Core'" in l], lines)

    def test_workset_and_filter(self):
        out = self.run_("plan", ["Demolition"], ["All Walls"], t={"combine": "all"})
        self.assertEqual(out["PLAN"]["targets"], 3)
        self.assertEqual(out["PLAN"]["by_source"], [["filter All Walls", 3], ["workset Demolition", 3]])
        out = self.run_("plan", ["Demolition"], ["To Remove"], t={"combine": "all"})
        self.assertEqual(out["PLAN"]["targets"], 0)
        out = self.run_("plan", ["Demolition"], ["To Remove"])                       # either
        self.assertEqual(out["PLAN"]["targets"], 8)

    def test_selection_filter_whole_group(self):
        out = self.run_("plan", filters=["Pick list"])
        plan = out["PLAN"]
        self.assertEqual((plan["targets"], plan["whole_groups"], plan["with_group"]), (2, 1, 1))
        self.assertEqual(plan["skipped_why"], [["protected: Levels", 1]])
        out = self.run_("apply", filters=["Pick list"])
        self.assertTrue(out["RESULT"]["committed"])
        self.assertEqual(self.gone("store 4", "store wall 4", "store shelf 4", "sofa", "L02"),
                         ["store 4", "store wall 4", "store shelf 4", "sofa"])
        self.assertEqual(self.status(out, "store wall 4"), "deleted with its group")
        self.assertEqual(self.grouped_with("store wall 3"), ("Store", ["Shelf", "Store partition"]))
        self.assertEqual(out["RESULT"]["groups"], [])                                 # nothing ungrouped

    def test_groups_option_off(self):
        out = self.run_("apply", ["Demolition"], fix_groups=False)
        self.assertTrue(out["RESULT"]["committed"])
        self.assertEqual(self.gone("demo wall 1", "demo wall 2", "store wall 3"), ["demo wall 1", "demo wall 2"])
        self.assertTrue(self.status(out, "store wall 3").startswith("skipped: inside model group 'Store'"))
        self.assertEqual(self.grouped_with("store wall 3")[0], "Store")

    def test_pinned_group(self):
        self.el["store 3"]._pinned = True
        out = self.run_("plan", ["Demolition"])
        self.assertIn(["inside a pinned model group", 1], out["PLAN"]["skipped_why"])
        out = self.run_("apply", ["Demolition"], skip_pinned=False)
        self.assertTrue(out["RESULT"]["committed"])
        self.assertEqual(self.gone("store wall 3", "demo slab"), ["store wall 3", "demo slab"])
        self.assertEqual(self.grouped_with("store shelf 3")[0], "Store (elements removed)")


class WorksetDeleteTests(Fixture):
    """--delete-worksets: a picked workset is deleted once nothing but internal elements is left on it."""

    def emptiable(self):
        """Demolition, with its grid moved away and a sketch plane Revit keeps there."""
        self.el["grid B"].WorksetId = WorksetId(1)
        self.el["sketch plane"] = SketchPlane(self.doc, 3)
        self.snap0 = self.doc.snapshot()

    def names(self):
        return [w.Name for w in self.doc.worksets]

    def test_plan_says_what_stays(self):
        out = self.run_("plan", ["Demolition"], delete_worksets=True)
        self.assertEqual(out["PLAN"]["worksets"], [{"name": "Demolition", "blocked": "", "stay": 2,
                                                    "stay_cats": [["Floors", 1], ["Grids", 1]]}])
        checks, _ = core.plan_checks(out["PLAN"])
        kept = [c for c in checks if c.label == "Workset 'Demolition' kept"][0]
        self.assertEqual((kept.ok, kept.detail), (None, "2 element(s) on it are not removed: Floors x1, Grids x1"))
        out = self.run_("apply", ["Demolition"], delete_worksets=True)  # pinned slab + protected grid stay
        self.assertTrue(out["RESULT"]["committed"])
        self.assertIn("Demolition", self.names())
        self.assertEqual(out["RESULT"]["worksets"][0]["why"], "2 element(s) left on it")

    def test_deleted_once_empty(self):
        self.emptiable()
        plan = self.run_("plan", ["Demolition"], skip_pinned=False, delete_worksets=True)["PLAN"]
        self.assertEqual(plan["worksets"][0]["stay"], 0)
        out = self.run_("trial", ["Demolition"], skip_pinned=False, delete_worksets=True)
        self.assertTrue(out["RESULT"]["worksets"][0]["deleted"])
        self.assertTrue(self.unchanged())                               # trial: the workset is back
        self.assertIn("Demolition", self.names())
        out = self.run_("apply", ["Demolition"], skip_pinned=False, delete_worksets=True)
        r = out["RESULT"]
        self.assertTrue(r["committed"], r)
        self.assertNotIn("Demolition", self.names())
        self.assertEqual(r["worksets"], [{"name": "Demolition", "deleted": True, "moved": 1, "why": "",
                                          "stay_cats": []}])
        self.assertEqual(self.el["sketch plane"].WorksetId, WorksetId(2))   # moved to the active workset
        self.assertTrue(self.doc.alive(self.el["sketch plane"]))
        checks, _ = core.result_checks("apply", r)
        self.assertIn("[OK  ] Workset deleted -- 'Demolition' (1 internal element(s) moved to the active workset)",
                      [str(c) for c in checks])
        self.assertEqual(self.doc.groups[-1], ("Element Remover by Netbuild", "assimilated"))   # one Undo entry

    def test_kept_when_active_borrowed_or_old_revit(self):
        self.emptiable()
        cases = []

        def active():
            self.doc.active_ws = WorksetId(3)

        def borrowed():
            [w for w in self.doc.worksets if w.Name == "Demolition"][0].Owner = "jane.d"

        def old_revit():
            import sys
            del sys.modules["Autodesk.Revit.DB"].WorksetTable          # Revit 2019 - 2021 have no DeleteWorkset
        for setup, want in ((active, "it is the active workset"), (borrowed, "borrowed by jane.d"),
                            (old_revit, "deleting a workset needs Revit 2022 or later")):
            self.fake.close()
            Fixture.setUp(self)
            self.emptiable()
            setup()
            plan = self.run_("plan", ["Demolition"], skip_pinned=False, delete_worksets=True)["PLAN"]
            self.assertTrue(plan["worksets"][0]["blocked"].startswith(want), plan["worksets"])
            out = self.run_("apply", ["Demolition"], skip_pinned=False, delete_worksets=True)
            r = out["RESULT"]
            self.assertTrue(r["committed"], r)                         # the removal itself goes ahead
            self.assertEqual(r["errors"], [])
            self.assertIn("Demolition", self.names())
            self.assertTrue(r["worksets"][0]["why"].startswith(want))
            cases.append(want)
        self.assertEqual(len(cases), 3)

    def test_off_by_default(self):
        self.emptiable()
        out = self.run_("apply", ["Demolition"], skip_pinned=False)
        self.assertTrue(out["RESULT"]["committed"])
        self.assertIn("Demolition", self.names())
        self.assertEqual((out["PLAN"]["worksets"], out["RESULT"]["worksets"]), ([], []))
        self.assertIs(core.config("n", "apply")["delete_worksets"], False)


class SafetyTests(Fixture):
    def test_borrowed_element_blocks_apply(self):
        self.doc.owners[self.el["demo wall 2"].Id.Value] = "jane.d"
        out = self.run_("plan", ["Demolition"])
        self.assertEqual(out["PLAN"]["blockers"][0]["why"], "borrowed by jane.d")
        out = self.run_("apply", ["Demolition"])
        self.assertIn("borrowed by other users", out["RESULT"]["stopped"])
        self.assertTrue(self.unchanged())
        with self.assertRaises(Exception) as cm:                     # trial: Revit refuses at commit
            self.run_("trial", ["Demolition"])
        self.assertIn("jane.d", str(cm.exception))
        self.assertTrue(self.unchanged())

    def test_not_found_and_closed(self):
        out = self.run_("apply", ["Site", "Nope"], ["Missing filter"], t={"categories": ["Wals"]})
        plan = out["PLAN"]
        self.assertEqual(plan["closed"], ["Site"])
        self.assertEqual([m.split(" (")[0] for m in plan["missing"]],
                         ["workset 'Nope'", "filter 'Missing filter'", "category 'wals'"])
        self.assertTrue(out["RESULT"]["stopped"].startswith("not found in the model"))
        checks, _ = core.plan_checks(plan)
        self.assertEqual([c.label for c in checks if c.ok is False], ["Not found", "Not found", "Not found",
                                                                      "Workset closed"])
        self.assertTrue(self.unchanged())

    def test_not_workshared(self):
        self.doc.IsWorkshared = False
        self.assertEqual(core.run_local(self.doc, "sources")["SOURCES"]["worksets"], [])
        out = self.run_("plan", ["Demolition"])
        self.assertIn("the model is not workshared", out["PLAN"]["missing"][0])

    def test_warnings_dismissed_errors_roll_back(self):
        self.doc.commit_warnings = ["Highlighted walls are attached to, but miss, the highlighted targets."]
        out = self.run_("apply", filters=["To Remove"])
        self.assertTrue(out["RESULT"]["committed"])
        self.assertIn("Highlighted walls are attached to", out["RESULT"]["warnings"][0])
        self.fake.close()
        self.setUp()
        self.doc.commit_errors = ["Can't keep elements joined."]
        with self.assertRaises(Exception) as cm:
            self.run_("apply", filters=["To Remove"])
        self.assertIn("Can't keep elements joined.", str(cm.exception))
        self.assertTrue(self.unchanged())

    def test_read_only(self):
        self.doc.IsReadOnly = True
        self.assertTrue(self.run_("plan", ["Demolition"])["PLAN"]["targets"])
        with self.assertRaises(Exception):
            self.run_("apply", ["Demolition"])
        self.assertTrue(self.unchanged())

    def test_annotation_kept_unless_asked(self):
        sel = self.el["Pick list"]
        sel.ids.append(self.el["demo tag"].Id)
        out = self.run_("plan", filters=["Pick list"])
        self.assertIn(["annotation / view-specific", 1], out["PLAN"]["skipped_why"])
        out = self.run_("plan", filters=["Pick list"], model_only=False)
        self.assertEqual(out["PLAN"]["targets"], 3)


class ListenerTests(Fixture):
    """The same engine through the MCP listener route, as the exe runs it."""

    def setUp(self):
        Fixture.setUp(self)
        self.tmp = tempfile.mkdtemp()
        self.s = Settings(self.tmp)
        self.s.update({"revit_url": self.fake.url})
        self.lines = []
        self.r = Runner(self.s, on_line=self.lines.append)

    def tearDown(self):
        Fixture.tearDown(self)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def explain(self, res):
        return "\n".join(map(str, res.checks)) + "\n" + "\n".join(self.lines[-40:])

    def test_runner(self):
        res = self.r.read_sources()
        self.assertTrue(res.ok, self.explain(res))
        self.assertIn("  Worksets:", self.lines)
        res = self.r.run("plan", Targets(["Demolition"]))
        self.assertTrue(res.ok, self.explain(res))
        self.assertTrue(os.path.isfile(res.info["rows_csv"]))
        res = self.r.run("trial", Targets(["Demolition"]))
        self.assertTrue(res.ok, self.explain(res))
        self.assertTrue(self.unchanged())
        res = self.r.run("apply", Targets(["Demolition"]))
        self.assertTrue(res.ok, self.explain(res))
        self.assertEqual(self.gone("demo wall 1", "store wall 3"), ["demo wall 1", "store wall 3"])
        with open(res.info["rows_csv"], encoding="utf-8-sig", newline="") as f:
            csv = f.read()
        self.assertTrue(csv.startswith("id,category,name,workset,group,matched,status\r\n"))
        self.assertIn("deleted (taken out of its group)", csv)
        res = self.r.run("plan", Targets())
        self.assertFalse(res.ok)

    def test_model_binding_and_listener_down(self):
        self.s["model_match"] = "B001"
        res = self.r.read_sources()
        self.assertIn("0 open model(s) match", self.explain(res))
        self.s["model_match"] = "B003"
        self.assertTrue(self.r.read_sources().ok)
        self.fake.paused = True
        res = self.r.run("apply", Targets(["Demolition"]))
        self.assertIn("manually stopped", self.explain(res))
        self.s["revit_url"] = "http://127.0.0.1:9/revit_mcp/execute_code/"
        res = self.r.read_sources()
        self.assertIn("not reachable", self.explain(res))
        self.assertTrue(self.unchanged())

    def cli(self, *args):
        import element_remover.settings as st
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
        rc, out = self.cli("sources")
        self.assertEqual(rc, 0, out)
        self.assertIn("Demolition", out)
        rc, out = self.cli("models")
        self.assertIn("0001_user   [active]", out)
        rc, out = self.cli("trial", "--workset", "Demolition", "--category", "Walls, Floors")
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.unchanged())
        rc, out = self.cli("plan", "--workset", "Nope")
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] Not found -- workset 'Nope'", out)
        rc, out = self.cli("apply", "--workset", "Demolition", "--filter", "All Walls", "--both", "--no-groups")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.gone("demo wall 1", "demo wall 2", "store wall 3"), ["demo wall 1", "demo wall 2"])
        rc, out = self.cli("apply", "--filter", "To Remove", "--no-merge")
        self.assertEqual(rc, 0, out)
        self.assertIn("Toilet Core (2)", self.doc.type_names())
        rc, out = self.cli("plan", "--workset", "Demolition", "--delete-worksets")
        self.assertIn("[WARN] Workset 'Demolition' kept", out)
        rc, out = self.cli("apply", "--workset", "Demolition", "--include-pinned")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.gone("demo slab", "store wall 3"), ["demo slab", "store wall 3"])
        rc, out = self.cli("setup", "--set", "skip_pinned=false")
        self.assertIs(Settings(self.tmp)["skip_pinned"], False)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("plan")                                          # no --workset / --filter
        self.assertTrue(isinstance(self.doc.group_of(self.el["store shelf 3"]), Group))


if __name__ == "__main__":
    unittest.main()

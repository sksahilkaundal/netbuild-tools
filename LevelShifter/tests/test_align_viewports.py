"""Align Viewports by Netbuild: the engine on a stand-in sheet set, and the ribbon button end to end
(stub pyRevit / WPF, see pyrevit_stubs.py).

    python -m unittest discover -s LevelShifter/tests -v
"""

import io
import os
import runpy
import shutil
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
EXT = os.path.join(ROOT, "pyRevit", "Netbuild.extension")
BUTTON = os.path.join(EXT, "Netbuild.tab", "Sheets.panel", "Align Viewports.pushbutton", "script.py")
sys.path.insert(0, HERE)
sys.path.append(os.path.join(EXT, "lib"))

import pyrevit_stubs  # noqa: E402
from align_viewports import about, core  # noqa: E402
import alignviewports_ui  # noqa: E402

MM = 304.8
TITLE_GAP = (2.0 / MM, -6.0 / MM)       # the title family's own offset from (box min + LabelOffset)


def mm(v):
    return v / MM


# ------------------------------------------------------------ a stand-in Revit sheet set

class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def __add__(self, o):
        return XYZ(self.X + o.X, self.Y + o.Y, self.Z + o.Z)

    def __sub__(self, o):
        return XYZ(self.X - o.X, self.Y - o.Y, self.Z - o.Z)

    def mm(self):
        return (round(self.X * MM, 6), round(self.Y * MM, 6))


def xy(x_mm, y_mm):
    return XYZ(mm(x_mm), mm(y_mm))


class ElementId(object):
    def __init__(self, n):
        self.IntegerValue = self.Value = n

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class View(object):
    def __init__(self, doc, name, view_type):
        self.Id, self.Name, self.ViewType = doc.new_id(self), name, view_type


class Viewport(object):
    """A viewport whose projection origin sits ``k`` from its box centre (the crop is not centred on it)."""

    def __init__(self, doc, view, center, half, k, offset=None, length=mm(60)):
        self.doc, self.Id, self.ViewId = doc, doc.new_id(self), view.Id
        self.center, self.half, self.k = center, half, k
        self._offset, self._length = offset or xy(5, -8), length
        self.locked = False

    def GetBoxCenter(self):
        return XYZ(self.center.X, self.center.Y)

    def SetBoxCenter(self, p):
        self.doc.require_transaction()
        if self.locked:
            raise Exception("The element is borrowed by another user.")
        self.center = XYZ(p.X, p.Y)

    def GetBoxOutline(self):
        return types.SimpleNamespace(MinimumPoint=self.center - self.half, MaximumPoint=self.center + self.half)

    def GetProjectionToSheetTransform(self):
        return types.SimpleNamespace(Origin=self.center + self.k)

    @property
    def LabelOffset(self):
        return XYZ(self._offset.X, self._offset.Y)

    @LabelOffset.setter
    def LabelOffset(self, v):
        self.doc.require_transaction()
        self._offset = XYZ(v.X, v.Y)

    @property
    def LabelLineLength(self):
        return self._length

    @LabelLineLength.setter
    def LabelLineLength(self, v):
        self.doc.require_transaction()
        self._length = v

    def title_at(self):
        """Where Revit draws the title: box min + LabelOffset + the title family's own gap."""
        p = self.center - self.half + self._offset
        return (round((p.X + TITLE_GAP[0]) * MM, 6), round((p.Y + TITLE_GAP[1]) * MM, 6))


class ViewSheet(object):
    def __init__(self, doc, number, name, placeholder=False):
        self.Id, self.SheetNumber, self.Name, self.IsPlaceholder = doc.new_id(self), number, name, placeholder
        self.vps = []

    def GetAllViewports(self):
        return [vp.Id for vp in self.vps]


class Doc(object):
    def __init__(self, title):
        self.Title, self.IsFamilyDocument, self.IsReadOnly = title, False, False
        self.by_id, self.sheets, self.open_tx, self.groups, self.exported = {}, [], 0, [], []
        self._next = 1000

    def new_id(self, el):
        self._next += 1
        self.by_id[self._next] = el
        return ElementId(self._next)

    def GetElement(self, eid):
        return self.by_id.get(eid.Value)

    def require_transaction(self):
        if not self.open_tx:
            raise Exception("Modifying is forbidden because the document has no open transaction.")

    def viewports(self):
        return [e for e in self.by_id.values() if isinstance(e, Viewport)]

    def snapshot(self):
        return dict((vp.Id.Value, (vp.center.mm(), vp._offset.mm(), round(vp._length * MM, 6)))
                    for vp in self.viewports())

    def restore(self, snap):
        for vp in self.viewports():
            c, o, l = snap[vp.Id.Value]
            vp.center, vp._offset, vp._length = xy(*c), xy(*o), mm(l)

    def ExportImage(self, opts):
        self.exported.append(opts)
        for eid in opts.ids:
            s = self.GetElement(eid)
            with open("%s - Sheet - %s - %s.png" % (opts.FilePath, s.SheetNumber, s.Name), "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")

    # -------------------------------------------------- building the model
    def sheet(self, number, name, *vps, **kw):
        s = ViewSheet(self, number, name, kw.get("placeholder", False))
        for view_type, name_, cx, cy, hw, hh, kx, ky in vps:
            v = View(self, name_, view_type)
            s.vps.append(Viewport(self, v, xy(cx, cy), xy(hw, hh), xy(kx, ky), kw.get("offset"),
                                  mm(kw.get("length", 60))))
        self.sheets.append(s)
        return s


class Status(object):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


class Transaction(object):
    def __init__(self, doc, name):
        self.doc, self.name, self.started, self.ended = doc, name, False, False

    def Start(self):
        self.snap, self.started = self.doc.snapshot(), True
        self.doc.open_tx += 1

    def Commit(self):
        self.doc.open_tx -= 1
        self.ended = True
        return Status("Committed")

    def RollBack(self):
        self.doc.restore(self.snap)
        self.doc.open_tx -= 1
        self.ended = True

    def HasStarted(self):
        return self.started

    def HasEnded(self):
        return self.ended


class TransactionGroup(object):
    def __init__(self, doc, name):
        self.doc, self.name = doc, name

    def Start(self):
        self.snap = self.doc.snapshot()

    def RollBack(self):
        self.doc.restore(self.snap)
        self.doc.groups.append((self.name, "rolled back"))

    def Assimilate(self):
        self.doc.groups.append((self.name, "assimilated"))


class Collector(object):
    def __init__(self, doc):
        self.doc = doc

    def OfClass(self, cls):
        return [e for e in self.doc.by_id.values() if isinstance(e, cls)]


class ImageExportOptions(object):
    def SetViewsAndSheets(self, ids):
        self.ids = list(ids)


def install_revit(doc):
    """Autodesk.Revit.DB / System.Collections.Generic stubs. Returns the sys.modules entries they replaced."""
    db = types.ModuleType("Autodesk.Revit.DB")
    db.FilteredElementCollector, db.ViewSheet = Collector, ViewSheet
    db.Transaction, db.TransactionGroup, db.ElementId = Transaction, TransactionGroup, ElementId
    db.ImageExportOptions = ImageExportOptions
    db.ExportRange = types.SimpleNamespace(SetOfViews="SetOfViews")
    db.ImageFileType = types.SimpleNamespace(PNG="PNG")
    db.ImageResolution = types.SimpleNamespace(DPI_150="DPI_150")
    db.ZoomFitType = types.SimpleNamespace(FitToPage="FitToPage")
    revit_mod = types.ModuleType("Autodesk.Revit")
    revit_mod.DB = db
    autodesk = types.ModuleType("Autodesk")
    autodesk.Revit = revit_mod
    generic = types.ModuleType("System.Collections.Generic")
    generic.List = {ElementId: list}
    collections = types.ModuleType("System.Collections")
    collections.Generic = generic
    new = {"Autodesk": autodesk, "Autodesk.Revit": revit_mod, "Autodesk.Revit.DB": db,
           "System.Collections": collections, "System.Collections.Generic": generic}
    old = dict((k, sys.modules.get(k)) for k in new)
    sys.modules.update(new)
    return old


def restore_modules(old):
    for k, v in old.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def model():
    """Reference 10023 (two plans + a legend) and targets with other crops, positions and title offsets."""
    doc = Doc("3505-ProjectG-Studio-ARC-RVT-00010")
    plan, legend = "FloorPlan", "Legend"
    doc.sheet("10023", "LEVEL 23 GA PLAN",
              (plan, "L23 GA", 420, 380, 300, 180, 12, -4),
              (plan, "L23 KEY", 420, 120, 150, 60, 0, 0),
              (legend, "LEGEND", 760, 300, 40, 200, 0, 0), offset=xy(10, -14), length=95)
    doc.sheet("10001", "LEVEL 01 GA PLAN",                 # bottom viewport listed first (detail numbers differ)
              (plan, "L01 KEY", 430, 110, 160, 70, 3, 1),
              (plan, "L01 GA", 400, 390, 320, 170, -20, 9),
              (legend, "LEGEND", 700, 280, 40, 200, 0, 0))
    doc.sheet("10002", "LEVEL 02 GA PLAN",
              (plan, "L02 GA", 415, 375, 290, 185, 15, -2),
              (plan, "L02 KEY", 421, 121, 150, 60, 0, 0), length=40)
    doc.sheet("10003", "LEVEL 03 GA PLAN",                 # three plans -> skipped
              (plan, "L03 GA", 420, 380, 300, 180, 0, 0),
              (plan, "L03 KEY", 420, 120, 150, 60, 0, 0),
              (plan, "L03 PART", 700, 120, 50, 50, 0, 0))
    doc.sheet("10004", "LEVEL 04 GA PLAN", (plan, "L04 GA", 380, 400, 280, 160, 7, 7))      # fewer -> top slot
    doc.sheet("10005", "LEVEL 05 NOTES", (legend, "LEGEND", 300, 300, 40, 200, 0, 0))       # nothing to align
    doc.sheet("10B01", "BASEMENT 01 GA PLAN",
              (plan, "B01 GA", 410, 385, 305, 175, -6, 3),
              (plan, "B01 KEY", 418, 118, 150, 60, 0, 0))
    doc.sheet("10099", "SITE PLAN", (plan, "SITE", 400, 300, 300, 200, 0, 0))
    doc.sheet("10050", "PLACEHOLDER", placeholder=True)
    return doc


def plans(doc, number):
    s = [x for x in doc.sheets if x.SheetNumber == number][0]
    vps = [vp for vp in s.vps if doc.GetElement(vp.ViewId).ViewType == "FloorPlan"]
    return sorted(vps, key=lambda vp: -vp.center.Y)


def legend(doc, number):
    s = [x for x in doc.sheets if x.SheetNumber == number][0]
    return [vp for vp in s.vps if doc.GetElement(vp.ViewId).ViewType == "Legend"][0]


# ------------------------------------------------------------ tests

class ChoosingTests(unittest.TestCase):
    def test_targets(self):
        numbers = ["10001", "10002", "10023", "10039", "10040", "10B01", "A101"]
        self.assertEqual(core.pick_targets(numbers, "10023", (10001, 10039), ["10B01", "X9"]),
                         (["10B01", "10001", "10002", "10039"], ["X9"]))
        self.assertEqual(core.pick_targets(numbers, "10023", None, ["A101", "10023"]), (["A101"], []))
        self.assertEqual(core.parse_range(" 10039", "10001 "), (10001, 10039))
        self.assertIsNone(core.parse_range("", " "))
        with self.assertRaises(ValueError):
            core.parse_range("10001", "")
        self.assertEqual(core.split_numbers("10B01, 10B02;10B03  A1"), ["10B01", "10B02", "10B03", "A1"])
        self.assertEqual(sorted(["10010", "10B01", "10002", "9"], key=core.natural_key),
                         ["9", "10B01", "10002", "10010"])
        self.assertEqual(core.check_image_sheets(["1", "2", "3", "4", "5"]), ["1", "3", "5"])
        self.assertEqual(core.check_image_sheets(["1", "2"]), ["1", "2"])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.doc = model()
        self.old = install_revit(self.doc)
        self.snap0 = self.doc.snapshot()

    def tearDown(self):
        restore_modules(self.old)

    def plan(self, targets=("10001", "10002", "10003", "10004", "10005", "10B01", "10023", "NOPE")):
        return core.make_plan(self.doc, "10023", list(targets), ["FloorPlan"])

    def test_plan_pairs_by_slot_and_reports(self):
        p = self.plan()
        self.assertEqual([(m.sheet, m.slot, m.name) for m in p["moves"]],
                         [("10001", 0, "L01 GA"), ("10001", 1, "L01 KEY"), ("10002", 0, "L02 GA"),
                          ("10002", 1, "L02 KEY"), ("10004", 0, "L04 GA"), ("10B01", 0, "B01 GA"),
                          ("10B01", 1, "B01 KEY")])
        self.assertEqual(p["skipped"], [("10003", "3 viewports, the reference has 2")])
        self.assertEqual(p["fewer"], [("10004", 1)])
        self.assertEqual((p["empty"], p["missing"]), (["10005"], ["NOPE"]))
        self.assertNotIn("10023", p["targets"])
        checks, lines = core.plan_checks(p)
        text = "\n".join(str(c) for c in checks)
        self.assertIn("[OK  ] Reference sheet 10023 -- 2 slot(s), top -> bottom: 0 L23 GA; 1 L23 KEY", text)
        self.assertIn("[OK  ] To align -- 7 viewport(s) on 4 sheet(s)", text)
        self.assertIn("[WARN] Skipped sheet 10003", text)
        self.assertIn("[WARN] Fewer viewports -- aligned to the reference's top slots: 10004 (1)", text)
        self.assertIn("[WARN] Nothing to align -- no floor plans viewport on 10005", text)
        self.assertIn("[WARN] Not in the model -- NOPE", text)
        # L01 GA: origin (380, 399) -> reference origin (432, 376)
        self.assertIn("10001 slot 0  L01 GA", lines[0])
        self.assertIn("move (+52.0, -23.0) mm", lines[0])
        self.assertIn("line 60.0 -> 95.0 mm", lines[0])
        self.assertEqual(self.doc.snapshot(), self.snap0)              # a plan changes nothing

    def test_reference_problems(self):
        with self.assertRaises(ValueError) as e:
            core.make_plan(self.doc, "99999", ["10001"], ["FloorPlan"])
        self.assertIn("not in", str(e.exception))
        with self.assertRaises(ValueError) as e:
            core.make_plan(self.doc, "10023", ["10001"], ["CeilingPlan"])
        self.assertIn("no ceiling plans viewport", str(e.exception))

    def test_trial_rolls_back(self):
        p = self.plan()
        r = core.run(self.doc, p, commit=False)
        self.assertFalse(r["committed"])
        self.assertEqual(r["moved"], 7)
        self.assertEqual([v[3] for v in r["verify"]], [0.0] * 7)       # origins re-read inside the trial
        self.assertEqual(self.doc.snapshot(), self.snap0)
        self.assertEqual(self.doc.groups, [("Align Viewports by Netbuild", "rolled back")])
        checks, _ = core.result_checks("trial", p, r)
        self.assertIn("[OK  ] Trial -- rolled back -- the model is unchanged", [str(c) for c in checks])

    def test_apply_aligns_plans_and_titles(self):
        p = self.plan()
        r = core.run(self.doc, p, commit=True)
        self.assertTrue(r["committed"])
        self.assertEqual(self.doc.groups, [("Align Viewports by Netbuild", "assimilated")])
        self.assertEqual(self.doc.open_tx, 0)
        ref = plans(self.doc, "10023")
        for n in ("10001", "10002", "10004", "10B01"):
            for slot, vp in enumerate(plans(self.doc, n)):
                o, ro = vp.GetProjectionToSheetTransform().Origin, ref[slot].GetProjectionToSheetTransform().Origin
                self.assertEqual(o.mm(), ro.mm(), (n, slot))                         # plans + grids line up
                self.assertEqual(vp.title_at(), ref[slot].title_at(), (n, slot))     # title drawn at the same spot
                self.assertAlmostEqual(vp.LabelLineLength, ref[slot].LabelLineLength)
        # box centres differ (the crops differ) -- matching centres would have been wrong
        self.assertNotEqual(plans(self.doc, "10001")[0].center.mm(), ref[0].center.mm())
        # legends, the skipped sheet and the reference are untouched
        after = self.doc.snapshot()
        for vp in [legend(self.doc, "10001"), legend(self.doc, "10023")] + plans(self.doc, "10003") + ref:
            self.assertEqual(after[vp.Id.Value], self.snap0[vp.Id.Value])
        checks, _ = core.result_checks("apply", p, r)
        text = [str(c) for c in checks]
        self.assertIn("[OK  ] Projection origins re-read -- 7 viewport(s), every one 0.0 mm off its reference slot",
                      text)
        self.assertIn("[OK  ] Applied -- 7 viewport(s), one Undo entry in Revit: 'Align Viewports by Netbuild'. "
                      "Save / Synchronize when happy", text)

    def test_titles_left_alone(self):
        before = dict((vp.Id.Value, vp.title_at()) for vp in plans(self.doc, "10002"))
        r = core.run(self.doc, self.plan(["10002"]), commit=True, titles=False)
        self.assertTrue(r["committed"])
        for vp in plans(self.doc, "10002"):
            self.assertAlmostEqual(vp.LabelLineLength, mm(40))
            self.assertNotEqual(vp.title_at(), before[vp.Id.Value])    # the title rides along with its box

    def test_a_failure_changes_nothing(self):
        plans(self.doc, "10B01")[1].locked = True
        p = self.plan()
        r = core.run(self.doc, p, commit=True)
        self.assertFalse(r["committed"])
        self.assertEqual(r["fails"], [("10B01", 1, "The element is borrowed by another user.")])
        self.assertEqual(self.doc.snapshot(), self.snap0)
        self.assertEqual(self.doc.open_tx, 0)
        checks, _ = core.result_checks("apply", p, r)
        self.assertEqual(str(checks[0]), "[FAIL] Not changed -- rolled back -- 1 viewport(s) could not be changed")

    def test_revit_error_rolls_back(self):
        p = self.plan()

        def boom(doc, plan):
            raise RuntimeError("regeneration failed")
        real, core.verify = core.verify, boom
        try:
            with self.assertRaises(RuntimeError):
                core.run(self.doc, p, commit=True)
        finally:
            core.verify = real
        self.assertEqual(self.doc.snapshot(), self.snap0)
        self.assertEqual(self.doc.groups, [("Align Viewports by Netbuild", "rolled back")])

    def test_needs_revit_2022(self):
        vp = plans(self.doc, "10023")[0]
        real = Viewport.GetProjectionToSheetTransform
        try:
            del Viewport.GetProjectionToSheetTransform
            with self.assertRaises(ValueError) as e:
                core.make_plan(self.doc, "10023", ["10001"], ["FloorPlan"])
            self.assertIn("Revit 2022", str(e.exception))
        finally:
            Viewport.GetProjectionToSheetTransform = real
        self.assertTrue(vp.GetProjectionToSheetTransform())

    def test_logs(self):
        tmp = tempfile.mkdtemp()
        try:
            p = self.plan(["10001"])
            r = core.run(self.doc, p, commit=False)
            path = core.write_moves_csv(os.path.join(tmp, "moves.csv"), p, r)
            with io.open(path, encoding="utf-8-sig") as f:
                rows = f.read().splitlines()
            self.assertEqual(rows[0].split(",")[:3], ["sheet", "slot", "view"])
            self.assertTrue(rows[1].startswith('10001,0,L01 GA,52.0,-23.0,"(5.0, -8.0)",'), rows[1])
            self.assertTrue(rows[1].endswith(",60.0,95.0,0.00"), rows[1])
            # time-saved log: new file gets the standard header ...
            log = os.path.join(tmp, "sub", "time_saved_log.csv")
            row = {"date": "2026-10-20", "task": core.TIME_LOG_TASK, "project": "P", "export": "reference 10023",
                   "issues": "4 sheets / 7 viewports", "manual_minutes": 14.0, "actual_minutes": 3.0,
                   "minutes_saved": 11.0, "notes": "a, b"}
            core.log_time_saved(log, row)
            with io.open(log, encoding="utf-8") as f:
                self.assertEqual(f.read().splitlines(), [",".join(core.TIME_LOG_FIELDS),
                                                         '2026-10-20,Align viewports to reference sheet,P,'
                                                         'reference 10023,4 sheets / 7 viewports,14.0,3.0,11.0,'
                                                         '"a, b"'])
            # ... an existing one keeps its own columns (any order / case), even without a final newline
            with io.open(log, "w", encoding="utf-8-sig") as f:
                f.write(u'Task,"Minutes_Saved",Other,DATE')
            core.log_time_saved(log, row)
            with io.open(log, encoding="utf-8-sig") as f:
                self.assertEqual(f.read().splitlines()[1], "Align viewports to reference sheet,11.0,,2026-10-20")
            with io.open(log, "w", encoding="utf-8") as f:
                f.write(u"a,b\n")
            with self.assertRaises(ValueError):
                core.log_time_saved(log, row)
        finally:
            shutil.rmtree(tmp)

    def test_export_images(self):
        tmp = tempfile.mkdtemp()
        try:
            sheets = core.read_sheets(self.doc)
            files = core.export_images(self.doc, [sheets["10023"], sheets["10001"]], os.path.join(tmp, "img"))
            self.assertEqual([os.path.basename(f) for f in files],
                             ["check - Sheet - 10001 - LEVEL 01 GA PLAN.png",
                              "check - Sheet - 10023 - LEVEL 23 GA PLAN.png"])
            opts = self.doc.exported[0]
            self.assertEqual((opts.ExportRange, opts.HLRandWFViewsFileType, opts.ZoomType),
                             ("SetOfViews", "PNG", "FitToPage"))
            self.assertNotIn("10050", sheets)                           # placeholders are not sheets to align
        finally:
            shutil.rmtree(tmp)


class AboutTests(unittest.TestCase):
    def test_about(self):
        with io.open(os.path.join(REPO, "LICENSE"), encoding="utf-8") as f:
            self.assertEqual(about.LICENSE_TEXT, f.read())
        self.assertEqual(about.PRODUCT, "Align Viewports by Netbuild")
        self.assertEqual((about.OWNER, about.PUBLISHER, about.WEBSITE), ("Netbuild", "Netbuild", "https://skaec.com"))
        self.assertEqual(about.COPYRIGHT, u"\u00a9 2026 Netbuild. All rights reserved.")
        self.assertEqual(about.LICENSE_NAME, "Netbuild Software Licence Agreement (proprietary)")
        self.assertEqual(about.LICENCE_KEY, "No licence key required for this product.")
        self.assertTrue(about.title("M").startswith("Align Viewports by Netbuild 1."))
        self.assertIn("Autodesk Revit 2022 - 2026", about.about_text())
        self.assertTrue(about.licence_text().endswith(about.LICENSE_TEXT.rstrip()))
        with io.open(os.path.join(EXT, "lib", "align_viewports", "about.py"), encoding="utf-8") as f:
            self.assertTrue(f.read().isascii())                        # the (c) sign is written as \u00a9

    def test_xaml(self):
        win = ET.fromstring(alignviewports_ui.window_xaml())
        names = [e.get(pyrevit_stubs.X_NAME) for e in win.iter() if e.get(pyrevit_stubs.X_NAME)]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual([n[3:] for n in names if n.startswith("vt_")], [k for k, _ in core.VIEW_TYPES])
        for n in ("ref_cb", "tgt_lb", "check_btn", "trial_btn", "apply_btn", "images_btn", "about_btn",
                  "licence_btn", "log_tb", "minutes_tb", "report_lb"):
            self.assertIn(n, names)


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.doc = model()
        self.snap0 = self.doc.snapshot()
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = os.environ["USERPROFILE"] = self.tmp
        os.environ.pop("NETBUILD_SCRIPT_SOURCE", None)
        self.st = pyrevit_stubs.install(self.doc)
        self.old = install_revit(self.doc)

    def tearDown(self):
        restore_modules(self.old)
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self):
        runpy.run_path(BUTTON, run_name="__main__")
        return pyrevit_stubs.WPFWindow.shown[0]

    def report(self, win):
        return [i.Content for i in win.report_lb.Items]

    def test_check_trial_apply(self):
        log = os.path.join(self.tmp, "time_saved_log.csv")
        win = self.open()
        self.assertTrue(win.Title.startswith("Align Viewports by Netbuild 1."))
        self.assertTrue(win.Title.endswith(self.doc.Title))
        self.assertEqual(win.ref_cb.Items[:2], ["10B01 - BASEMENT 01 GA PLAN", "10001 - LEVEL 01 GA PLAN"])
        self.assertNotIn("10050 - PLACEHOLDER", win.ref_cb.Items)
        self.assertEqual([k for k, _ in core.VIEW_TYPES if getattr(win, "vt_" + k).IsChecked], ["FloorPlan"])
        self.assertTrue(win.titles_cb.IsChecked)
        win.check_btn.click()
        self.assertEqual(self.st.alerts[-1], ("Check", "Pick the reference sheet."))
        win.ref_cb.SelectedItem = "10023 - LEVEL 23 GA PLAN"
        self.assertEqual(win.ref_info_tb.Text, "2 viewport slots, top -> bottom: L23 GA; L23 KEY")
        win.from_tb.type("10001")
        win.to_tb.type("10039")
        win.extra_tb.type("10B01, ZZ1")
        win.range_btn.click()
        self.assertEqual(self.st.alerts[-1], ("Target sheets", "Not in this model: ZZ1"))
        self.assertEqual(win.count_tb.Text, "6 target sheets picked")      # 10001-10005 + 10B01, not 10023
        win.log_tb.Text = log
        win.minutes_tb.Text = "3"
        win.check_btn.click()
        report = self.report(win)
        self.assertEqual(report[0], "Check")
        self.assertIn("[OK  ] To align -- 7 viewport(s) on 4 sheet(s) -- 0 already in place, largest move 56.9 mm",
                      report)
        self.assertEqual(self.doc.snapshot(), self.snap0)
        win.trial_btn.click()
        self.assertTrue([r for r in self.report(win) if r.startswith("[OK  ] Trial -- rolled back")])
        self.assertEqual(self.doc.snapshot(), self.snap0)
        win.apply_btn.click()
        self.assertEqual(self.st.alerts[-1][0], "Apply")                    # confirmation asked first
        self.assertIn("Align 7 viewport(s) on 4 sheet(s)", self.st.alerts[-1][1])
        report = self.report(win)
        self.assertTrue([r for r in report if r.startswith("[OK  ] Applied -- 7 viewport(s)")], report)
        self.assertTrue([r for r in report if r.startswith("[OK  ] Time-saved log -- ")], report)
        ref = plans(self.doc, "10023")
        for slot, vp in enumerate(plans(self.doc, "10B01")):
            self.assertEqual(vp.GetProjectionToSheetTransform().Origin.mm(),
                             ref[slot].GetProjectionToSheetTransform().Origin.mm())
            self.assertEqual(vp.title_at(), ref[slot].title_at())
        with io.open(log, encoding="utf-8") as f:
            rows = f.read().splitlines()
        self.assertEqual(rows[0], ",".join(core.TIME_LOG_FIELDS))
        self.assertIn(",Align viewports to reference sheet,3505-ProjectG-Studio-ARC-RVT-00010,reference 10023,"
                      "4 sheets / 7 viewports,21.0,", rows[1])
        logs = os.listdir(os.path.join(self.tmp, "Netbuild", "AlignViewports", "logs"))
        self.assertTrue([n for n in logs if n.endswith("_apply_viewports.csv")], logs)
        self.assertTrue([n for n in logs if n.endswith("_apply.log")], logs)
        self.assertEqual((self.st.config.values["reference"], self.st.config.values["range_from"],
                          self.st.config.values["view_types"]), ("10023", "10001", "FloorPlan"))
        # check images: the reference and the first / middle / last aligned sheet
        win.images_btn.click()
        report = self.report(win)
        self.assertTrue(report[1].startswith("[OK  ] Check images -- 4 PNG file(s)"), report)
        self.assertEqual([self.doc.GetElement(i).SheetNumber for i in self.doc.exported[-1].ids],
                         ["10023", "10B01", "10002", "10004"])     # aligned sheets: first, middle, last
        self.assertTrue(os.path.isdir(self.st.started[-1]))

    def test_remembers_and_declines(self):
        self.st.config.values.update(reference="10023", range_from="10001", range_to="10002", extra="",
                                     view_types="FloorPlan,Section", titles=False)
        self.st.answers["alert"] = False                                   # "No" to Apply
        win = self.open()
        self.assertEqual(win.ref_cb.SelectedItem, "10023 - LEVEL 23 GA PLAN")
        self.assertEqual(list(win.tgt_lb.SelectedItems), ["10001 - LEVEL 01 GA PLAN", "10002 - LEVEL 02 GA PLAN"])
        self.assertTrue(win.vt_Section.IsChecked)
        self.assertFalse(win.titles_cb.IsChecked)
        win.apply_btn.click()
        self.assertEqual(self.doc.snapshot(), self.snap0)
        self.assertIn("View titles are left as they are.", self.st.alerts[-1][1])
        win.vt_FloorPlan.IsChecked = False
        win.vt_Section.IsChecked = False
        win.vt_Section.click()
        self.assertEqual(win.ref_info_tb.Text, "No viewport of the ticked kinds on this sheet.")
        win.check_btn.click()
        self.assertEqual(self.st.alerts[-1], ("Check", "Tick at least one kind of viewport to align."))
        win.vt_CeilingPlan.IsChecked = True
        win.check_btn.click()
        self.assertIn("[FAIL] Stopped -- Reference sheet 10023 has no ceiling plans viewport.", self.report(win))
        win.none_btn.click()
        self.assertEqual(win.count_tb.Text, "0 target sheets picked")
        win.about_btn.click()
        self.assertEqual(pyrevit_stubs.WPFWindow.shown[-1].Title, "About Align Viewports by Netbuild")
        self.assertIs(pyrevit_stubs.WPFWindow.shown[-1].Owner, win)
        win.licence_btn.click()
        lic = pyrevit_stubs.WPFWindow.shown[-1]
        self.assertEqual(lic.Title, "Licence -- Align Viewports by Netbuild")
        self.assertEqual(lic.key_tb.Text, "No licence key required for this product.")
        self.assertEqual(lic.license_tb.Text, about.LICENSE_TEXT)

    def test_refuses_read_only(self):
        self.doc.IsReadOnly = True
        with self.assertRaises(pyrevit_stubs.ScriptExit):
            runpy.run_path(BUTTON, run_name="__main__")
        self.assertIn("read-only", self.st.alerts[-1][1])


if __name__ == "__main__":
    unittest.main()

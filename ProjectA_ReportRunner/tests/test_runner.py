"""End-to-end tests against stand-in Netbuild scripts (no Revit/ACC needed).

    python -m unittest discover -s ProjectA_ReportRunner/tests -t ProjectA_ReportRunner
"""

import hashlib
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from projecta_runner import overrides  # noqa: E402
from projecta_runner.runner import (Runner, RunInputs, check_extract_log, guess_previous,  # noqa: E402
                               log_time_saved, today)
from projecta_runner.settings import Settings  # noqa: E402

FAKE_PIPELINE = '''
import datetime, os, zipfile
from pathlib import Path

# ---- CONFIG
BASE = Path(r"C:\\SK\\Projects\\ProjectA\\Issues\\260914")
EXPORT_SUBDIR = "20260101"
ACC_PDF = "Issue detail-old.pdf"
BCF_FILE = ["old Issues.bcf"]
MAX_ISSUE_ID = None
PREVIOUS_EXPORT_SUBDIR = None
RUN_EXTRACT = True
RUN_BUILD = True
BY_MODEL = False

def topics():
    n = 0
    for b in BCF_FILE:
        with zipfile.ZipFile(BASE / EXPORT_SUBDIR / b) as z:
            n += sum(1 for x in z.namelist() if x.endswith("/markup.bcf"))
    return n

def main():
    assert isinstance(BASE, Path), type(BASE)
    n = topics()
    if MAX_ISSUE_ID:
        n = min(n, MAX_ISSUE_ID)
    if RUN_EXTRACT:
        print("pin snapshots: %d from BCF, 0 from PDF" % n)
        print("ACC links: %d of %d issues" % (n, n))
    if RUN_BUILD:
        if os.environ.get("FAKE_LOCKED"):
            raise PermissionError("[WinError 32] The process cannot access the file because it is being used by another process")
        out = BASE / ("%s_ProjectA_ACC Issue detail (Issues 1-%d)" % (datetime.date.today().strftime("%Y%m%d"), n))
        out.mkdir(exist_ok=True)
        stem = "%s_ProjectA_ACC Issue detail (Updated with Current Status)" % out.name[:8]
        files = [stem + ".pdf"] + ([stem + " - by Tier-Model.pdf"] if BY_MODEL else [])
        for f in files:
            try:
                import pypdf
                w = pypdf.PdfWriter()
                for _ in range(n + 1):
                    w.add_blank_page(100, 100)
                w.write(str(out / f))
            except ImportError:
                (out / f).write_bytes(b"%PDF-1.4")
        print("wrote", out)

if __name__ == "__main__":
    main()
'''

FAKE_VERIFY = '''
import os, sys
pdfs = [f for f in os.listdir(sys.argv[1]) if f.endswith(".pdf")]
print("reports:", len(pdfs))
print("ALL CHECKS PASSED" if len(pdfs) == 2 else "1 CHECK FAILED")
'''

FAKE_WALK = '''
import sys
print("walkthrough", " ".join(sys.argv[1:]))
'''


def make_bcf(path, guids):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("bcf.version", "<Version/>")
        for g in guids:
            z.writestr("%s/markup.bcf" % g, "<Markup/>")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "Netbuild")
        os.makedirs(os.path.join(self.root, "scripts"))
        for name, src in (("scripts/ProjectA_IssueReport_Pipeline.py", FAKE_PIPELINE),
                          ("scripts/ProjectA_IssueReport_Verify.py", FAKE_VERIFY),
                          ("scripts/ProjectA_IssueWalkthrough.py", FAKE_WALK),
                          ("ProjectA_IssueExport_Extract.py", ""), ("ProjectA_IssueDetailReport_Build.py", "")):
            with open(os.path.join(self.root, name), "w") as f:
                f.write(textwrap.dedent(src))
        self.base = os.path.join(self.tmp, "Issues")
        for d in ("20261001", "20261009"):
            os.makedirs(os.path.join(self.base, d))
        open(os.path.join(self.base, "20261009", "Issue detail-x.pdf"), "wb").close()
        make_bcf(os.path.join(self.base, "20261009", "A Issues.bcf"), ["g1", "g2", "g3"])
        make_bcf(os.path.join(self.base, "20261009", "B Issues.bcf"), ["g4"])
        make_bcf(os.path.join(self.base, "20261001", "old Issues.bcf"), ["g1", "g9"])

        self.app = os.path.join(self.tmp, "app")
        os.makedirs(self.app)
        self.s = Settings(self.app)
        self.s.update({"netbuild_root": self.root, "python_exe": sys.executable,
                       "pipeline_script": os.path.join("scripts", "ProjectA_IssueReport_Pipeline.py"),
                       "verify_script": os.path.join("scripts", "ProjectA_IssueReport_Verify.py"),
                       "walkthrough_script": os.path.join("scripts", "ProjectA_IssueWalkthrough.py"),
                       "base_dir": self.base,
                       "time_saved_log": os.path.join(self.tmp, "time.csv")})
        self.lines = []
        self.r = Runner(self.s, on_line=self.lines.append)
        self.pipeline = os.path.join(self.root, "scripts", "ProjectA_IssueReport_Pipeline.py")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def inputs(self, prev="20261001", max_id=None):
        return RunInputs(self.base, "20261009", "Issue detail-x.pdf", ["A Issues.bcf", "B Issues.bcf"],
                         max_id, prev)


class OverrideTests(unittest.TestCase):
    def test_keeps_form_of_original(self):
        src = 'from pathlib import Path\nA = Path("x")\nB = "y"\nC = ["z"]\nD = None\nE: int = 3\n'
        code, hits = overrides.patch_source(src, {"A": "p", "B": ["q"], "C": "r", "D": 5, "E": 7})
        g = {}
        exec(code, g)
        self.assertEqual((str(g["A"]), g["B"], g["C"], g["D"], g["E"]), ("p", "q", ["r"], 5, 7))
        self.assertEqual(type(g["A"]).__name__.endswith("Path"), True)

    def test_list_into_single_value_is_refused(self):
        with self.assertRaises(overrides.OverrideError):
            overrides.patch_source('B = "a.bcf"\n', {"B": ["a.bcf", "b.bcf"]})

    def test_missing_global_is_refused(self):
        with self.assertRaises(overrides.OverrideError):
            overrides.patch_source("A = 1\n", {"NOPE": 2})

    def test_only_top_level(self):
        code, _ = overrides.patch_source("A = 1\ndef f():\n    A = 9\n    return A\n", {"A": 2})
        g = {}
        exec(code, g)
        self.assertEqual((g["A"], g["f"]()), (2, 9))


class WorkflowTests(Fixture):
    def test_extract_checks_pass_and_file_untouched(self):
        before = hashlib.sha256(open(self.pipeline, "rb").read()).hexdigest()
        res = self.r.extract(self.inputs())
        self.assertTrue(res.ok, "\n".join(map(str, res.checks)) + "\n" + res.text)
        self.assertIn("pin snapshots: 4 from BCF, 0 from PDF", res.text)
        self.assertIn("ACC links: 4 of 4 issues", res.text)
        self.assertEqual(res.info["issues"], 4)
        overlap = [c for c in res.checks if c.label.startswith("Previous")][0]
        self.assertTrue(overlap.ok)
        self.assertIn("1 of 4", overlap.detail)
        self.assertEqual(before, hashlib.sha256(open(self.pipeline, "rb").read()).hexdigest())
        self.assertFalse(any(n.startswith(today()) for n in os.listdir(self.base)))  # no build

    def test_previous_sharing_nothing_is_flagged(self):
        make_bcf(os.path.join(self.base, "20261001", "old Issues.bcf"), ["zz"])
        overlap = self.r.previous_overlap(self.inputs())
        self.assertIsNone(overlap.ok)
        self.assertIn("shares NO issues", overlap.detail)

    def test_build_then_verify(self):
        res = self.r.build(self.inputs(max_id=3))
        self.assertTrue(res.ok, "\n".join(map(str, res.checks)) + "\n" + res.text)
        folder = res.info["output_folder"]
        self.assertTrue(os.path.basename(folder).startswith(today() + "_ProjectA_ACC Issue detail (Issues 1-3)"))
        ver = self.r.verify(folder)
        self.assertTrue(ver.ok, "\n".join(map(str, ver.checks)))
        pages = sorted(p["pages"] for p in ver.info["pdfs"])
        self.assertEqual(len(pages), 2)

    def test_locked_pdf_reported_not_forced(self):
        os.environ["FAKE_LOCKED"] = "1"
        try:
            res = self.r.build(self.inputs())
        finally:
            del os.environ["FAKE_LOCKED"]
        self.assertTrue(res.info.get("locked"))
        self.assertFalse(res.ok)

    def test_walkthrough_and_pending(self):
        self.assertIn("walkthrough pending", self.r.pending().text)
        self.assertIn("walkthrough note 12 a b", self.r.walkthrough(["note", "12", "a b"]).text)

    def test_input_problems(self):
        bad = RunInputs(self.base, "20261009", "missing.pdf", [], None, "20261009")
        msgs = " | ".join(bad.problems())
        self.assertIn("ACC PDF not in the export folder", msgs)
        self.assertIn("No BCF selected", msgs)
        self.assertIn("same as the new one", msgs)
        self.assertEqual(guess_previous(self.base, "20261009"), "20261001")

    def test_setup_check_paths(self):
        rows = dict((l, ok) for l, _, ok in self.s.check_paths())
        self.assertTrue(all(rows.values()), rows)

    def test_time_log_respects_existing_header(self):
        path = self.s["time_saved_log"]
        with open(path, "w") as f:
            f.write("Date,Task,Minutes_Saved\n")
        log_time_saved(path, {"date": "20261013", "task": "ProjectA", "minutes_saved": 200})
        self.assertEqual(open(path).read().splitlines()[-1], "20261013,ProjectA,200")


class LogParseTests(unittest.TestCase):
    def test_pdf_pins_fail(self):
        checks = check_extract_log("pin snapshots: 10 from BCF, 2 from PDF\nACC links: 12 of 12 issues")
        self.assertEqual([c.ok for c in checks], [True, False])

    def test_missing_links(self):
        checks = check_extract_log("ACC links: 11 of 12 issues")
        self.assertFalse(checks[0].ok)


if __name__ == "__main__":
    unittest.main()

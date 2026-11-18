"""The ProjectA issue-report workflow, step by step, independent of the GUI/CLI.

Every step runs the user's own scripts with the user's Python and streams
their output line by line to ``on_line``. Nothing here edits a script,
closes a viewer or deletes a file.
"""

import csv
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import zipfile

from .settings import resource_path

DATED = re.compile(r"^\d{8}$")
PIN_RE = re.compile(r"pin snapshots:\s*(\d+)\s*from BCF,\s*(\d+)\s*from PDF", re.I)
LINKS_RE = re.compile(r"ACC links:\s*(\d+)\s*of\s*(\d+)\s*issues", re.I)
LOCKED_RE = re.compile(r"PermissionError|WinError 32|WinError 5\b|being used by another process", re.I)
PASSED = "ALL CHECKS PASSED"
REPORT_FULL = "%s_ProjectA_ACC Issue detail (Updated with Current Status).pdf"
REPORT_BY_MODEL = "%s_ProjectA_ACC Issue detail (Updated with Current Status) - by Tier-Model.pdf"


def today():
    return datetime.date.today().strftime("%Y%m%d")


class Check(object):
    def __init__(self, label, ok, detail=""):
        self.label, self.ok, self.detail = label, ok, detail

    def __str__(self):
        mark = "OK  " if self.ok is True else ("WARN" if self.ok is None else "FAIL")
        return "[%s] %s%s" % (mark, self.label, (" -- " + self.detail) if self.detail else "")


class StepResult(object):
    def __init__(self, name, returncode, lines, log_path):
        self.name, self.returncode, self.lines, self.log_path = name, returncode, lines, log_path
        self.checks = []
        self.info = {}

    @property
    def ok(self):
        return self.returncode == 0 and all(c.ok is not False for c in self.checks)

    @property
    def text(self):
        return "\n".join(self.lines)


# ---------------------------------------------------------------- inputs

class RunInputs(object):
    """What the prompt asks for: BASE, export folder, ACC PDF, BCF(s), issue cap, previous export."""

    def __init__(self, base, export_subdir, acc_pdf, bcf_files, max_issue_id=None,
                 previous_subdir=None):
        self.base = base
        self.export_subdir = export_subdir
        self.acc_pdf = os.path.basename(acc_pdf)
        self.bcf_files = [os.path.basename(b) for b in bcf_files]
        self.max_issue_id = int(max_issue_id) if max_issue_id not in (None, "", "all") else None
        prev = (previous_subdir or "").strip()
        self.previous_subdir = None if prev.lower() in ("", "none") else prev

    @property
    def export_dir(self):
        return os.path.join(self.base, self.export_subdir)

    def pipeline_globals(self, run_extract, run_build, extra=None):
        g = dict(extra or {})
        g.update({
            "BASE": self.base,
            "EXPORT_SUBDIR": self.export_subdir,
            "ACC_PDF": self.acc_pdf,
            "BCF_FILE": self.bcf_files if len(self.bcf_files) > 1 else self.bcf_files[0],
            "MAX_ISSUE_ID": self.max_issue_id,
            "PREVIOUS_EXPORT_SUBDIR": self.previous_subdir,
            "RUN_EXTRACT": run_extract,
            "RUN_BUILD": run_build,
        })
        return g

    def problems(self):
        p = []
        if not os.path.isdir(self.base):
            p.append("BASE folder not found: %s" % self.base)
        if not DATED.match(self.export_subdir or ""):
            p.append("Export folder should be a YYYYMMDD name, got %r" % self.export_subdir)
        elif not os.path.isdir(self.export_dir):
            p.append("Export folder not found: %s" % self.export_dir)
        if not self.acc_pdf:
            p.append("No ACC PDF selected")
        elif not os.path.isfile(os.path.join(self.export_dir, self.acc_pdf)):
            p.append("ACC PDF not in the export folder: %s" % self.acc_pdf)
        if not self.bcf_files:
            p.append("No BCF selected (list every BCF -- ACC caps a BCF at 250 issues)")
        for b in self.bcf_files:
            if not os.path.isfile(os.path.join(self.export_dir, b)):
                p.append("BCF not in the export folder: %s" % b)
        if self.previous_subdir:
            if self.previous_subdir == self.export_subdir:
                p.append("Previous export folder is the same as the new one")
            elif not os.path.isdir(os.path.join(self.base, self.previous_subdir)):
                p.append("Previous export folder not found: %s" % self.previous_subdir)
        return p

    def as_dict(self):
        return {"base": self.base, "export_subdir": self.export_subdir, "acc_pdf": self.acc_pdf,
                "bcf_files": self.bcf_files, "max_issue_id": self.max_issue_id,
                "previous_subdir": self.previous_subdir}


def dated_folders(base):
    """YYYYMMDD sub-folders of BASE, newest first."""
    try:
        names = [n for n in os.listdir(base)
                 if DATED.match(n) and os.path.isdir(os.path.join(base, n))]
    except OSError:
        return []
    return sorted(names, reverse=True)


def guess_previous(base, export_subdir):
    older = [n for n in dated_folders(base) if n < export_subdir]
    return older[0] if older else None


def export_files(export_dir):
    """(pdfs, bcfs) in an export folder; the ACC 'Issue detail' PDF first."""
    try:
        names = sorted(os.listdir(export_dir))
    except OSError:
        return [], []
    pdfs = [n for n in names if n.lower().endswith(".pdf")]
    pdfs.sort(key=lambda n: (not n.lower().startswith("issue detail"), n))
    bcfs = [n for n in names if n.lower().endswith((".bcf", ".bcfzip"))]
    return pdfs, bcfs


# ---------------------------------------------------------------- process

def stream(cmd, cwd, on_line, log_path):
    """Run cmd, echo each output line to on_line, keep a log file. -> (rc, lines)"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    lines = []
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("$ %s\n(cwd %s)\n\n" % (subprocess.list2cmdline(cmd), cwd))
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as e:
            msg = "[runner] could not start %s: %s" % (cmd[0], e)
            on_line(msg)
            log.write(msg + "\n")
            return 127, [msg]
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            lines.append(line)
            log.write(line + "\n")
            log.flush()
            on_line(line)
        proc.stdout.close()
        rc = proc.wait()
        log.write("\n[exit %d]\n" % rc)
    return rc, lines


class Runner(object):
    def __init__(self, settings, on_line=None):
        self.s = settings
        self.on_line = on_line or (lambda line: print(line, flush=True))

    def _log_path(self, step):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.s.logs_dir(), "%s_%s.log" % (stamp, step))

    def _run_script(self, step, script_key, args=None, overrides=None):
        script = self.s.script(script_key)
        if not os.path.isfile(script):
            msg = "[runner] script not found: %s (link it on the Setup tab)" % script
            self.on_line(msg)
            return StepResult(step, 127, [msg], None)
        cmd = list(self.s.python_cmd()) + ["-u"]
        if overrides is not None:
            cmd += [resource_path("projecta_runner", "overrides.py"), script]
            for k, v in overrides.items():
                cmd += ["--set", "%s=%s" % (k, json.dumps(v))]
            if args:
                cmd += ["--"] + list(args)
        else:
            cmd += [script] + list(args or [])
        log_path = self._log_path(step)
        self.on_line("[runner] %s: %s" % (step, os.path.basename(script)))
        rc, lines = stream(cmd, self.s["netbuild_root"], self.on_line, log_path)
        res = StepResult(step, rc, lines, log_path)
        if rc != 0:
            res.checks.append(Check("%s exited with code %d" % (os.path.basename(script), rc), False,
                                    "see log %s" % log_path))
        return res

    # ---- step 1: extract only
    def extract(self, inputs):
        g = inputs.pipeline_globals(True, False, self.s["extra_globals"])
        res = self._run_script("extract", "pipeline_script", overrides=g)
        res.checks.extend(check_extract_log(res.text))
        m = LINKS_RE.search(res.text)
        if m:
            res.info["issues"] = int(m.group(2))
        res.checks.append(self.previous_overlap(inputs))
        return res

    def previous_overlap(self, inputs):
        if not inputs.previous_subdir:
            return Check("Previous export", None, "none given -- no movement-since table")
        cur = bcf_topics([os.path.join(inputs.export_dir, b) for b in inputs.bcf_files])
        prev_dir = os.path.join(inputs.base, inputs.previous_subdir)
        prev = bcf_topics([os.path.join(prev_dir, b) for b in export_files(prev_dir)[1]])
        if not prev:
            return Check("Previous export overlap", None,
                         "no BCF in %s to compare -- check the pipeline log" % inputs.previous_subdir)
        shared = len(cur & prev)
        if shared == 0:
            return Check("Previous export overlap", None,
                         "%s shares NO issues with this export (BCF topics)" % inputs.previous_subdir)
        return Check("Previous export overlap", True,
                     "%d of %d issues also in %s (BCF topics)" % (shared, len(cur), inputs.previous_subdir))

    # ---- Studio notes
    def pending(self):
        return self._run_script("pending", "walkthrough_script", self.s["walkthrough_pending_args"])

    def walkthrough(self, args):
        return self._run_script("walkthrough", "walkthrough_script", args)

    # ---- step 2: build only
    def locked_pdfs(self, base):
        """PDFs in report folders under BASE that another program holds open."""
        locked = []
        for folder in glob.glob(os.path.join(base, self.s["report_folder_glob"])):
            for pdf in glob.glob(os.path.join(folder, "*.pdf")):
                try:
                    with open(pdf, "r+b"):  # opened, never written
                        pass
                except PermissionError:
                    locked.append(pdf)
                except OSError:
                    pass
        return locked

    def build(self, inputs):
        g = inputs.pipeline_globals(False, True, self.s["extra_globals"])
        res = self._run_script("build", "pipeline_script", overrides=g)
        if LOCKED_RE.search(res.text):
            res.info["locked"] = True
            res.checks.append(Check(
                "Move to %s stopped" % self.s["superseded_dir"], False,
                "a PDF is open in your viewer -- close it, then run Build again"))
        folder = self.output_folder(inputs.base)
        res.info["output_folder"] = folder
        res.checks.extend(check_output_folder(folder))
        return res

    def output_folder(self, base, date=None):
        pattern = (date or today()) + self.s["report_folder_glob"].lstrip("*")
        hits = [p for p in glob.glob(os.path.join(base, pattern)) if os.path.isdir(p)]
        return max(hits, key=os.path.getmtime) if hits else None

    # ---- step 4: verify
    def verify(self, folder):
        res = self._run_script("verify", "verify_script", [folder])
        tail = [l for l in res.lines if l.strip()][-1:] or [""]
        res.checks.append(Check("Verify ends \"%s\"" % PASSED, PASSED in tail[0], tail[0].strip()))
        res.info["pdfs"] = self.pdf_stats(folder)
        for st in res.info["pdfs"]:
            res.checks.append(Check(st["name"], True, "%s pages, %.1f MB" % (st["pages"], st["mb"])))
        return res

    def pdf_stats(self, folder):
        pdfs = sorted(glob.glob(os.path.join(folder or "", "*.pdf")))
        if not pdfs:
            return []
        code = ("import json,sys\n"
                "def n(p):\n"
                " try:\n  import fitz; d=fitz.open(p); c=d.page_count; d.close(); return c\n"
                " except Exception: pass\n"
                " try:\n  import pypdf; return len(pypdf.PdfReader(p).pages)\n"
                " except Exception: return None\n"
                "print(json.dumps([n(p) for p in sys.argv[1:]]))\n")
        try:
            out = subprocess.run(list(self.s.python_cmd()) + ["-c", code] + pdfs,
                                 capture_output=True, timeout=300,
                                 creationflags=0x08000000 if os.name == "nt" else 0)
            pages = json.loads(out.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except Exception:
            pages = [None] * len(pdfs)
        return [{"name": os.path.basename(p), "pages": n if n is not None else "?",
                 "mb": os.path.getsize(p) / 1048576.0} for p, n in zip(pdfs, pages)]


# ---------------------------------------------------------------- checks

def check_extract_log(text):
    checks = []
    links = LINKS_RE.findall(text)
    n = None
    if links:
        got, total = map(int, links[-1])
        n = total
        checks.append(Check("ACC links: %d of %d issues" % (got, total), got == total))
    else:
        checks.append(Check("ACC links line", False, "\"ACC links: N of N issues\" not in the log"))
    pins = PIN_RE.findall(text)
    if pins:
        bcf, pdf = map(int, pins[-1])
        ok = pdf == 0 and (n is None or bcf == n)
        checks.append(Check("pin snapshots: %d from BCF, %d from PDF" % (bcf, pdf), ok,
                            "" if ok else "expected N from BCF, 0 from PDF"))
    else:
        checks.append(Check("pin snapshots line", False,
                            "\"pin snapshots: N from BCF, 0 from PDF\" not in the log"))
    return checks


def check_output_folder(folder):
    if not folder:
        return [Check("Output folder", False, "no %s_ProjectA_ACC Issue detail (Issues ...) folder in BASE" % today())]
    date = os.path.basename(folder)[:8]
    checks = [Check("Output folder", True, folder)]
    for tmpl in (REPORT_FULL, REPORT_BY_MODEL):
        name = tmpl % date
        checks.append(Check(name, os.path.isfile(os.path.join(folder, name)),
                            "" if os.path.isfile(os.path.join(folder, name)) else "missing"))
    return checks


def bcf_topics(paths):
    """Topic GUIDs (one per issue) across BCF zips."""
    topics = set()
    for p in paths or []:
        try:
            with zipfile.ZipFile(p) as z:
                for name in z.namelist():
                    parts = name.replace("\\", "/").split("/")
                    if len(parts) == 2 and parts[1].lower() == "markup.bcf":
                        topics.add(parts[0].lower())
        except (OSError, zipfile.BadZipFile):
            pass
    return topics


# ---------------------------------------------------------------- time log

TIME_LOG_FIELDS = ["date", "task", "project", "export", "issues", "manual_minutes",
                   "actual_minutes", "minutes_saved", "notes"]


def log_time_saved(path, row):
    """Append one row; follow the existing header if the file already has one."""
    exists = os.path.isfile(path) and os.path.getsize(path) > 0
    if exists:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), [])
        lookup = dict((k.lower(), v) for k, v in row.items())
        out = [lookup.get(h.strip().lower(), "") for h in header]
        if not any(out):
            raise ValueError("%s has columns %s -- none match %s"
                             % (path, header, ", ".join(TIME_LOG_FIELDS)))
    else:
        header = TIME_LOG_FIELDS
        out = [row.get(h, "") for h in header]
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(header)
        w.writerow(out)
    return header, out


def open_folder(path):
    """Open a folder in Explorer (never a PDF -- an open PDF blocks the next build's move)."""
    if os.name == "nt":
        os.startfile(path)  # noqa: pylint: disable=no-member
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

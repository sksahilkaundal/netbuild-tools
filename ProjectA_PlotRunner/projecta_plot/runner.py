"""The ProjectA Plot GA export pass, model by model, independent of the GUI/CLI.

Per model:  check (is it open?)  ->  probe (real "Current Revision Date"
format)  ->  dry run (exact sheet list + filenames)  ->  PDF pass  ->  CAD pass.

Each pass is batched by category (output subfolder). While Revit works, the
runner watches the output folder: a file counts only when it is on disk,
written during this pass, non-empty, not still growing, and has the right
header. Printed results are never trusted on their own. If a batch stops
producing files for ``stall_seconds`` the remaining sheets go one per call.

The export scripts are read, never edited (see patch.py).
"""

import csv
import datetime
import fnmatch
import glob
import os
import re
import subprocess
import sys
import threading
import time

from . import revit
from .patch import Expr, PatchError, find_candidates_loop, parse, patch_source, top_level_values
from .sheets import parse_sheet_spec, pick_date_filter, select

DATED = re.compile(r"^\d{8}$")
MODES = {"pdf": ("PDF",), "cad": ("CAD",), "pdf+cad": ("PDF", "CAD")}
MODE_LABELS = {"pdf": "PDF only", "cad": "CAD (DWG) only", "pdf+cad": "PDF + CAD (DWG)"}
EXT = {"PDF": ".pdf", "CAD": ".dwg"}
HEADER = {"PDF": b"%PDF", "CAD": b"AC"}
CONFIG_NAMES = ["BASE_OUTPUT_FOLDER", "REVISION_DATE_FILTER", "EXPORT_PDF", "EXPORT_CAD", "DRY_RUN", "doc"]

# What the ProjectA Plot GA prompt asks for; Setup compares each script against it.
EXPECTED = {
    "master": {
        "BROWSER_FILTER_PARAM": "Studio_03 - Browser Filter",
        "SUBFOLDER_BY_BROWSER_FILTER": {"B2 B5_1-200": "02_GA Plans B2 B5 (1-200)",
                                        "Site": "01_GA Plans (1-500) - Site"},
        "EXCLUDE_SHEET_NAMES": {"Solar Shading 01", "Solar Shading 02", "Site Plan"},
    },
    "podium": {
        "SUBFOLDER_BY_VIEWTYPE": {"FloorPlan": "03_Podium Building Part Plans (1-100)",
                                  "Elevation": "04_Podium Building Elevations (1-100)",
                                  "Section": "05_Podium Building Sections (1-100)"},
    },
}
PAPER = [("ISO_A0", "A0"), ("PaperPlacementType.Center", "Center placement"),
         ("ZoomPercentage = 100", "100% scale")]


def today():
    return datetime.date.today().strftime("%Y%m%d")


class Check(object):
    def __init__(self, label, ok, detail=""):
        self.label, self.ok, self.detail = label, ok, detail

    def __str__(self):
        mark = "OK  " if self.ok is True else ("WARN" if self.ok is None else "FAIL")
        return "[%s] %s%s" % (mark, self.label, (" -- " + self.detail) if self.detail else "")


class StepResult(object):
    def __init__(self, name, log_path=None):
        self.name, self.log_path = name, log_path
        self.checks = []
        self.info = {}
        self.aborted = False

    @property
    def ok(self):
        return not self.aborted and all(c.ok is not False for c in self.checks)

    def add(self, label, ok, detail=""):
        self.checks.append(Check(label, ok, detail))


class Job(object):
    """What the prompt asks for: output folder, revision date, PDF/CAD, and (optionally) which sheets."""

    def __init__(self, plot_root, out_date, date_text, mode="pdf", sheet_spec=""):
        self.plot_root = plot_root
        self.out_date = (out_date or "").strip() or today()
        self.date_text = (date_text or "").strip()
        self.mode = mode
        self.sheet_spec = sheet_spec or ""
        self.selectors = parse_sheet_spec(self.sheet_spec)  # raises SheetSpecError

    @property
    def out_dir(self):
        return os.path.join(self.plot_root, self.out_date)

    @property
    def kinds(self):
        return MODES[self.mode]

    def problems(self):
        p = []
        if self.mode not in MODES:
            p.append("Export must be one of: %s" % ", ".join(MODES))
        if not DATED.match(self.out_date):
            p.append("Output folder should be a YYYYMMDD name, got %r" % self.out_date)
        if not os.path.isdir(self.plot_root):
            p.append("Plot root folder not found: %s" % self.plot_root)
        if not self.date_text and not self.selectors:
            p.append("Give a revision date, a sheet list, or both "
                     "(with neither, every routed sheet in the model would be exported)")
        return p

    def as_dict(self):
        return {"plot_root": self.plot_root, "out_date": self.out_date, "date_text": self.date_text,
                "mode": self.mode, "sheet_spec": self.sheet_spec}


# ------------------------------------------------------------ static checks

def static_checks(path, kind):
    """What can be checked without Revit: CONFIG names, the candidates loop, A0/Center/100%, routing."""
    checks = []
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            src = f.read().decode("utf-8-sig")
        tree = parse(src, name)
    except (OSError, PatchError) as e:
        return [Check(name, False, str(e))]
    have = top_level_values(src, CONFIG_NAMES + ["SBFX_PARAM_NAMES"] + list(EXPECTED[kind]))
    missing = [n for n in CONFIG_NAMES if n not in have]
    checks.append(Check("%s: CONFIG globals" % name, not missing,
                        "missing: " + ", ".join(missing) if missing else ", ".join(CONFIG_NAMES)))
    checks.append(Check("%s: candidates loop" % name, find_candidates_loop(tree) is not None,
                        "" if find_candidates_loop(tree) else "no top-level loop that appends to `candidates`"))
    sbfx = have.get("SBFX_PARAM_NAMES")
    checks.append(Check("%s: SBFX_SHEET_01..07" % name, isinstance(sbfx, list) and len(sbfx) == 7,
                        "%s names" % (len(sbfx) if isinstance(sbfx, list) else "no")))
    lacking = [label for needle, label in PAPER if needle not in src]
    checks.append(Check("%s: A0 / Center / 100%%" % name, None if lacking else True,
                        ("not found in the script: " + ", ".join(lacking)) if lacking else ""))
    for key, want in EXPECTED[kind].items():
        got = have.get(key)
        if isinstance(want, set):
            ok = isinstance(got, (set, list, tuple)) and want <= set(got)
        elif isinstance(want, dict):
            ok = isinstance(got, dict) and all(got.get(k) == v for k, v in want.items())
        else:
            ok = got == want
        checks.append(Check("%s: %s" % (name, key), True if ok else None,
                            "as the prompt asks" if ok else "script has %r, prompt says %r" % (got, want)))
    return checks


# ------------------------------------------------------------ helpers

class Call(object):
    """One POST to Revit on a background thread, so the disk can be watched meanwhile."""

    def __init__(self, url, code, timeout, description):
        self.reply = None
        self.done = threading.Event()

        def work():
            try:
                self.reply = revit.post(url, code, timeout, description)
            except Exception as e:  # never lose the thread silently
                self.reply = revit.Reply(error="%s: %s" % (type(e).__name__, e))
            self.done.set()
        threading.Thread(target=work, daemon=True).start()


def file_state(path, t0):
    """None (absent) | ('old'|'new', size)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return ("new" if st.st_mtime >= t0 - 2 else "old", st.st_size)


def header_ok(path, kind):
    try:
        with open(path, "rb") as f:
            return f.read(4).startswith(HEADER[kind])
    except OSError:
        return False


class Aborted(Exception):
    pass


# ------------------------------------------------------------ runner

class Runner(object):
    def __init__(self, settings, on_line=None, cancel=None):
        self.s = settings
        self.on_line = on_line or (lambda line: print(line, flush=True))
        self.cancel = cancel or threading.Event()
        self._log = None

    # ---- logging
    def _begin(self, step, model=None):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = ("%s_%s" % (model["name"], step)) if model else step
        path = os.path.join(self.s.logs_dir(), "%s_%s.log" % (stamp, tag))
        self._log = open(path, "w", encoding="utf-8")
        return StepResult(tag, path)

    def _end(self, res):
        if self._log:
            for c in res.checks:
                self._log.write(str(c) + "\n")
            self._log.close()
            self._log = None
        return res

    def say(self, line):
        if self._log:
            self._log.write(line + "\n")
            self._log.flush()
        self.on_line(line)

    def _float(self, key):
        return float(self.s[key])

    # ---- Revit calls
    def _call(self, code, timeout, description):
        call = Call(self.s["revit_url"], code, timeout, description)
        while not call.done.wait(0.25):
            if self.cancel.is_set():
                break
        return call.reply

    def _need_reply(self, reply, nonce, what):
        """Raise Aborted unless this is this call's own reply and the model was bound."""
        if reply is None:
            raise Aborted("%s: cancelled" % what)
        if reply.unreachable or reply.paused or reply.timed_out:
            raise Aborted("%s: %s" % (what, reply.error))
        if not reply.has("BEGIN", nonce) and not reply.has("DOCS", nonce):
            raise Aborted("%s: Revit's answer did not carry this call's nonce (stale echo of an earlier "
                          "call) -- run it again%s" % (what, ("; error: " + reply.error) if reply.error else ""))
        return reply

    def list_docs(self):
        nonce = revit.new_nonce()
        reply = self._call(revit.list_docs_code(nonce), self._float("probe_timeout_seconds"), "ProjectA: list models")
        self._need_reply(reply, nonce, "List open models")
        docs = reply.marker("DOCS", nonce)
        if docs is None:
            raise Aborted("List open models: %s" % (reply.error or "no answer"))
        return docs

    def _script(self, model):
        path = self.s.model_script(model)
        if not os.path.isfile(path):
            raise Aborted("script not found: %s (link it on the Setup tab)" % path)
        with open(path, "rb") as f:
            return path, f.read()

    def build_code(self, model, overrides, nonce, subfolder=None, sheets=None):
        path, src = self._script(model)
        ov = dict(overrides)
        ov["doc"] = Expr("_projecta_pick_doc(_ProjectA_MATCH)")
        try:
            code, _ = patch_source(src, ov, insert_after_loop=revit.FILTER_LINE,
                                   prepend=revit.preamble(nonce, model["match"], subfolder, sheets),
                                   append=revit.END_LINE, filename=os.path.basename(path))
        except PatchError as e:
            raise Aborted(str(e))
        return code

    # ---- step: is the model open?
    def check_model(self, model):
        res = self._begin("check", model)
        try:
            docs = self.list_docs()
        except Aborted as e:
            res.add("Revit", False, str(e))
            res.aborted = True
            return self._end(res)
        open_docs = [d for d in docs if not d.get("linked") and not d.get("family")]
        for d in open_docs:
            self.say("  open: %s%s" % (d["title"], "   (active window)" if d.get("active") else ""))
        want = [m.lower() for m in model["match"]]
        hits = [d for d in open_docs if any(w in d["title"].lower() for w in want)]
        if len(hits) == 1:
            d = hits[0]
            res.info["doc"] = d
            res.add("%s is open" % model["name"], True, d["title"])
            res.add("Active window", True if d.get("active") else None,
                    "yes" if d.get("active") else
                    "another model is active -- fine, every call binds to %s by title" % model["name"])
        elif not hits:
            res.add("%s is open" % model["name"], False,
                    "no open model title contains %s" % " / ".join(model["match"]))
        else:
            res.add("%s is open" % model["name"], False, "ambiguous -- %d models match: %s"
                    % (len(hits), ", ".join(d["title"] for d in hits)))
        return self._end(res)

    # ---- step: real date format
    def _probe(self, model, job, res):
        path, src = self._script(model)
        vals = top_level_values(src, ["SBFX_PARAM_NAMES", "BROWSER_FILTER_PARAM"])
        params = list(vals.get("SBFX_PARAM_NAMES") or []) + ["Current Revision Date", "Current Revision"]
        group = vals.get("BROWSER_FILTER_PARAM") if model["kind"] == "master" else None
        if group:
            params.append(group)
        nonce = revit.new_nonce()
        self.say("[runner] %s: reading sheet parameters live ..." % model["name"])
        reply = self._call(revit.probe_code(nonce, model["match"], params, group),
                           self._float("probe_timeout_seconds"), "ProjectA: probe %s" % model["name"])
        self._need_reply(reply, nonce, "Probe")
        doc = reply.marker("DOC", nonce)
        data = reply.marker("PROBE", nonce)
        if doc is None or data is None:
            raise Aborted("Probe: %s" % (reply.error or "no result"))
        res.info["doc"] = doc
        res.add("Bound to model", True, doc["title"] + ("" if doc.get("active") else "  (not the active window)"))
        dates = data["dates"]
        top = sorted(dates.items(), key=lambda kv: -kv[1])[:8]
        self.say("  %d sheets; \"Current Revision Date\" values: %s" % (
            data["sheets"], ", ".join("%r x%d" % kv for kv in top)))
        if data.get("groups"):
            self.say("  %s values: %s" % (group, ", ".join("%r x%d" % kv for kv in sorted(data["groups"].items()))))
        for pname, n in sorted(data["missing"].items()):
            res.add("Parameter %r" % pname, False if n == data["sheets"] else None,
                    "missing on %d of %d sheets" % (n, data["sheets"]))
        flt, counts, msg = pick_date_filter(job.date_text, dates)
        res.info["date_filter"] = flt
        if job.date_text and flt is None:
            res.add("Revision date %r" % job.date_text, False, msg + ". Values in this model: "
                    + ", ".join(repr(v) for v, _ in top))
            raise Aborted("revision date not found in %s" % model["name"])
        res.add("Revision-date filter", True if flt or not job.date_text else False, msg)
        return flt

    # ---- step: dry run
    def _dry(self, model, job, res):
        flt = self._probe(model, job, res) if job.date_text else None
        if not job.date_text:
            res.add("Revision-date filter", None, "none -- the sheet list alone decides")
        nonce = revit.new_nonce()
        code = self.build_code(model, {"BASE_OUTPUT_FOLDER": job.out_dir, "REVISION_DATE_FILTER": flt,
                                       "EXPORT_PDF": "PDF" in job.kinds, "EXPORT_CAD": "CAD" in job.kinds,
                                       "DRY_RUN": True}, nonce)
        reply = self._call(code, self._float("probe_timeout_seconds"), "ProjectA: dry run %s" % model["name"])
        self._need_reply(reply, nonce, "Dry run")
        for line in reply.text_lines():
            self.say("  | " + line)
        found = reply.marker("CANDIDATES", nonce)
        if found is None or not reply.has("END", nonce):
            raise Aborted("Dry run: script did not finish -- %s" % (reply.error or "no candidate list"))
        chosen, unmatched = select(found, job.selectors)
        res.info.update({"date_filter": flt, "routed": found, "chosen": chosen, "unmatched": unmatched})

        res.add("Sheets matched by the script", bool(found), "%d (date %r)" % (len(found), flt))
        if job.selectors:
            res.add("Sheets you listed", not unmatched,
                    "%d sheet(s) selected%s" % (len(chosen), ("; NOT found among routed sheets%s: %s" % (
                        " with that date" if flt else "", ", ".join(unmatched))) if unmatched else ""))
        cats = {}
        for c in chosen:
            cats[c["subfolder"]] = cats.get(c["subfolder"], 0) + 1
        for cat in sorted(cats):
            res.add(cat, True, "%d sheet(s)" % cats[cat])
        names = {}
        for c in chosen:  # same drawing number twice = a superseded duplicate sheet, whatever its revision
            names.setdefault(c["fname"].rsplit("_", 1)[0].lower(), []).append(c["sheet"])
        dups = dict((k, v) for k, v in names.items() if len(v) > 1)
        if dups:
            res.add("Duplicate filenames", False, "; ".join("%s <- %s" % (k, ", ".join(v)) for k, v in dups.items())
                    + " (superseded duplicate sheet? narrow by revision date, or list the Sheet Number)")
        odd = [c["sheet"] for c in chosen if "--" in c["fname"] or c["fname"].startswith("-")
               or "_" not in c["fname"]]
        if odd:
            res.add("Filename fields", None, "empty SBFX field or no _<revision> on: " + ", ".join(odd))
        sup = [c["sheet"] for c in chosen if c["sheet"].rstrip().endswith(")")]
        if sup:
            res.add("Possible superseded duplicates", None, "sheet numbers ending '(n)': " + ", ".join(sup))
        self.say("")
        for c in chosen:
            self.say("  %-22s %-42s %s" % (c["sheet"], c["subfolder"], c["fname"]))
        return chosen

    def dry_run(self, model, job):
        res = self._begin("dryrun", model)
        try:
            self._dry(model, job, res)
        except Aborted as e:
            res.add("Stopped", False, str(e))
            res.aborted = True
        return self._end(res)

    # ---- step: export
    def export(self, model, job, allow_unmatched=False):
        res = self._begin("export", model)
        rows = []
        res.info["files"] = rows
        try:
            chosen = self._dry(model, job, res)
            if res.info["unmatched"] and not allow_unmatched:
                raise Aborted("some listed sheets were not found -- fix the list, or allow exporting the rest")
            if not chosen:
                raise Aborted("nothing to export")
            if not all(c.ok is not False for c in res.checks if c.label != "Sheets you listed"):
                raise Aborted("fix the FAIL lines above first")
            only = [c["sheet"] for c in chosen] if job.selectors else None
            base = {"BASE_OUTPUT_FOLDER": job.out_dir, "REVISION_DATE_FILTER": res.info["date_filter"],
                    "DRY_RUN": False}
            for kind in job.kinds:  # ALL PDFs first, then ALL DWGs
                for cat in sorted(set(c["subfolder"] for c in chosen)):
                    items = [c for c in chosen if c["subfolder"] == cat]
                    rows.extend(self._pass(model, kind, cat, items, base, only, job.out_dir))
                    if self.cancel.is_set():
                        raise Aborted("cancelled -- Revit may still finish the call it is on")
        except Aborted as e:
            res.add("Stopped", False, str(e))
            res.aborted = True
        for kind in ("PDF", "CAD"):
            mine = [r for r in rows if r["kind"] == kind]
            if mine:
                good = sum(1 for r in mine if r["status"] == "OK")
                single = sum(1 for r in mine if r["via"] == "single")
                res.add("%s on disk" % kind, good == len(mine), "%d of %d verified%s" % (
                    good, len(mine), (", %d needed one-sheet-per-call" % single) if single else ""))
        for r in rows:
            if r["status"] != "OK":
                res.add("%s %s" % (r["kind"], r["fname"]), False, r["status"])
        res.info["summary_csv"] = self._write_summary(model, rows)
        return self._end(res)

    def _overrides(self, base, kind):
        o = dict(base)
        o["EXPORT_PDF"], o["EXPORT_CAD"] = kind == "PDF", kind == "CAD"
        return o

    def _pass(self, model, kind, cat, items, base, only, out_dir):
        folder = os.path.join(out_dir, kind, cat)
        expected = dict((c["sheet"], os.path.join(folder, c["fname"] + EXT[kind])) for c in items)
        via = dict((c["sheet"], "batch") for c in items)
        t0 = time.time()
        self.say("[runner] %s %s: batch of %d -> %s" % (model["name"], kind, len(items), folder))
        nonce = revit.new_nonce()
        code = self.build_code(model, self._overrides(base, kind), nonce, subfolder=cat, sheets=only)
        call = Call(self.s["revit_url"], code, self._float("batch_timeout_seconds"),
                    "ProjectA: %s %s %s" % (model["name"], kind, cat))
        outcome = self._watch(expected, t0, call, kind, cat, self._float("stall_seconds"))
        self._after_call(call, nonce, outcome)

        missing = [sh for sh, p in expected.items() if not self._good(p, t0, kind)]
        if missing and not self.cancel.is_set():
            self.say("[runner] %d of %d %s not on disk after the batch -- one sheet per call"
                     % (len(missing), len(expected), kind))
            for sh in missing:
                if self.cancel.is_set():
                    break
                if self._good(expected[sh], t0, kind):
                    continue  # the stalled batch caught up
                via[sh] = "single"
                n2 = revit.new_nonce()
                code = self.build_code(model, self._overrides(base, kind), n2, sheets=[sh])
                call = Call(self.s["revit_url"], code, self._float("sheet_timeout_seconds"),
                            "ProjectA: %s %s %s" % (model["name"], kind, sh))
                out = self._watch({sh: expected[sh]}, t0, call, kind, sh, self._float("sheet_timeout_seconds"))
                self._after_call(call, n2, out)

        if kind == "CAD" and self.s["sweep_byproducts"]:
            self._sweep(folder, t0)
        rows = []
        for c in items:
            p = expected[c["sheet"]]
            st = file_state(p, t0)
            if st is None:
                status = "MISSING"
            elif st[0] == "old":
                status = "NOT REWRITTEN (file is from an earlier export)"
            elif st[1] == 0:
                status = "EMPTY FILE"
            elif not header_ok(p, kind):
                status = "NOT A VALID %s" % kind
            else:
                status = "OK"
            rows.append({"model": model["name"], "kind": kind, "subfolder": cat, "sheet": c["sheet"],
                         "fname": c["fname"] + EXT[kind], "path": p, "status": status, "via": via[c["sheet"]],
                         "bytes": st[1] if st else 0})
        good = sum(1 for r in rows if r["status"] == "OK")
        self.say("[runner] %s %s %s: %d of %d verified on disk" % (model["name"], kind, cat, good, len(rows)))
        return rows

    def _good(self, path, t0, kind):
        st = file_state(path, t0)
        return bool(st) and st[0] == "new" and st[1] > 0 and header_ok(path, kind)

    def _watch(self, expected, t0, call, kind, label, stall_s):
        """Poll the disk until every file is in and stable, Revit answered, or nothing moved for stall_s."""
        poll, settle = self._float("poll_seconds"), self._float("settle_seconds")
        prev_sig, prev_n = None, -1
        last_change = time.time()
        answered = None
        while True:
            if self.cancel.is_set():
                return "cancelled"
            fresh = {}
            for sh, p in expected.items():
                st = file_state(p, t0)
                if st and st[0] == "new":
                    fresh[sh] = st[1]
            sig = tuple(sorted(fresh.items()))
            n = sum(1 for v in fresh.values() if v > 0)
            now = time.time()
            if sig != prev_sig:
                last_change = now
                if n != prev_n:
                    self.say("  %s %s: %d/%d on disk" % (kind, label, n, len(expected)))
                    prev_n = n
            stable = sig == prev_sig
            if n == len(expected) and stable:
                return "complete"
            if call.done.is_set():
                answered = answered or now
                if stable and now - answered >= settle:
                    return "answered"
            elif now - last_change >= stall_s:
                self.say("  %s %s: nothing new on disk for %ds -- batch looks stalled" % (kind, label, stall_s))
                return "stalled"
            prev_sig = sig
            time.sleep(poll)

    def _after_call(self, call, nonce, outcome):
        """Log what Revit printed -- for the record only; the disk is what counts."""
        reply = call.reply if call.done.is_set() else None
        if reply is None:
            self.say("  (Revit has not answered yet -- %s; carrying on from what is on disk)" % outcome)
            return
        if reply.unreachable or reply.paused:
            raise Aborted(reply.error)
        if reply.timed_out:
            self.say("  (%s -- ignored, the files on disk decide)" % reply.error)
            return
        if not reply.has("BEGIN", nonce):
            self.say("  (answer did not carry this call's nonce -- stale echo, ignored)")
            return
        if not reply.has("DOC", nonce):
            raise Aborted("model binding failed: %s" % reply.error)
        for line in reply.text_lines():
            self.say("  | " + line)
        if reply.error:
            self.say("  Revit reported: %s" % reply.error.splitlines()[0])

    def _sweep(self, folder, t0):
        swept = []
        for pat in self.s["byproduct_patterns"]:
            for p in glob.glob(os.path.join(folder, pat)):
                if os.path.splitext(p)[1].lower() == ".dwg":
                    continue
                try:
                    if os.path.getmtime(p) >= t0 - 2:
                        os.remove(p)
                        swept.append(os.path.basename(p))
                except OSError:
                    pass
        if swept:
            self.say("  swept %d DWG byproduct(s): %s" % (len(swept), ", ".join(sorted(swept))))

    def _write_summary(self, model, rows):
        if not rows:
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.s.logs_dir(), "%s_%s_files.csv" % (stamp, model["name"]))
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, ["model", "kind", "subfolder", "sheet", "fname", "status", "via", "bytes", "path"])
            w.writeheader()
            w.writerows(rows)
        return path

    # ---- final check over the whole output folder
    def verify_output(self, out_dir, mode, expected_rows=None):
        res = self._begin("verify")
        if not os.path.isdir(out_dir):
            res.add("Output folder", False, "not found: %s" % out_dir)
            return self._end(res)
        res.add("Output folder", True, out_dir)
        stems = {}
        for kind in MODES.get(mode, ("PDF", "CAD")):
            root = os.path.join(out_dir, kind)
            if not os.path.isdir(root):
                res.add(kind, False, "no %s folder" % kind)
                continue
            for cat in sorted(os.listdir(root)):
                folder = os.path.join(root, cat)
                if not os.path.isdir(folder):
                    continue
                files = sorted(os.listdir(folder))
                mine = [f for f in files if f.lower().endswith(EXT[kind])]
                stems[(kind, cat)] = set(os.path.splitext(f)[0].lower() for f in mine)
                empty = [f for f in mine if os.path.getsize(os.path.join(folder, f)) == 0]
                bad = [f for f in mine if not header_ok(os.path.join(folder, f), kind)]
                junk = [f for f in files if any(fnmatch.fnmatch(f.lower(), p.lower())
                                                for p in self.s["byproduct_patterns"])]
                res.add("%s\\%s" % (kind, cat), not empty and not bad,
                        "%d %s file(s)%s%s" % (len(mine), EXT[kind], ("; empty: " + ", ".join(empty)) if empty else "",
                                               ("; not valid: " + ", ".join(bad)) if bad else ""))
                if junk:
                    res.add("%s\\%s byproducts" % (kind, cat), None, ", ".join(junk))
        if mode == "pdf+cad":
            for (kind, cat), names in stems.items():
                if kind != "PDF":
                    continue
                other = stems.get(("CAD", cat), set())
                if names != other:
                    res.add("PDF/DWG pairs in %s" % cat, None, "PDF only: %s | DWG only: %s" % (
                        ", ".join(sorted(names - other)) or "-", ", ".join(sorted(other - names)) or "-"))
                else:
                    res.add("PDF/DWG pairs in %s" % cat, True, "%d pairs" % len(names))
        if expected_rows:
            gone = [r for r in expected_rows if not os.path.isfile(r["path"])]
            res.add("Files exported this session", not gone, "%d of %d still on disk%s" % (
                len(expected_rows) - len(gone), len(expected_rows),
                ("; missing: " + ", ".join(r["fname"] for r in gone)) if gone else ""))
        return self._end(res)


# ------------------------------------------------------------ time log

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
            raise ValueError("%s has columns %s -- none match %s" % (path, header, ", ".join(TIME_LOG_FIELDS)))
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
    if os.name == "nt":
        os.startfile(path)  # noqa: pylint: disable=no-member
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

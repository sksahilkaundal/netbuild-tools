"""Level Shift, independent of the GUI/CLI.

Steps:  levels (read)  ->  plan (who is driven by the moved levels; nothing changed)
        ->  trial (the whole move, measured, then rolled back)  ->  apply (the same, kept).

Revit's answer is trusted only through what it measured: every model element's bounding box
before and after.  An element that still moved is reported by Id, never hidden.
"""

import datetime
import os
import subprocess
import sys
import threading

from . import revit
from .core import Check, plan_checks, resolve, result_checks, write_rows_csv
from .units import FEET, fmt_ft


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


class Aborted(Exception):
    pass


class Call(object):
    """One POST to Revit on a background thread, so Cancel stays responsive."""

    def __init__(self, url, code, timeout, description):
        self.reply = None
        self.done = threading.Event()

        def work():
            try:
                self.reply = revit.post(url, code, timeout, description)
            except Exception as e:
                self.reply = revit.Reply(error="%s: %s" % (type(e).__name__, e))
            self.done.set()
        threading.Thread(target=work, daemon=True).start()


class Runner(object):
    def __init__(self, settings, on_line=None, cancel=None):
        self.s = settings
        self.on_line = on_line or (lambda line: print(line, flush=True))
        self.cancel = cancel or threading.Event()
        self._log = None

    @property
    def units(self):
        return self.s["units"] if self.s["units"] in FEET else "mm"

    # ---- logging
    def _begin(self, step):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.s.logs_dir(), "%s_%s.log" % (stamp, step))
        self._log = open(path, "w", encoding="utf-8")
        return StepResult(step, path)

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

    # ---- Revit calls
    def _call(self, code, timeout, description):
        call = Call(self.s["revit_url"], code, timeout, description)
        while not call.done.wait(0.25):
            if self.cancel.is_set():
                break
        return call.reply

    def _need(self, reply, nonce, what, tag="BEGIN"):
        if reply is None:
            raise Aborted("%s: cancelled -- Revit may still be working on it" % what)
        if reply.unreachable or reply.paused or reply.timed_out:
            raise Aborted("%s: %s" % (what, reply.error))
        if not reply.has(tag, nonce):
            raise Aborted("%s: Revit's answer did not carry this call's nonce (stale echo of an earlier "
                          "call) -- run it again%s" % (what, ("; error: " + reply.error) if reply.error else ""))
        return reply

    def list_docs(self):
        nonce = revit.new_nonce()
        reply = self._call(revit.list_docs_code(nonce), float(self.s["probe_timeout_seconds"]), "LS: list models")
        self._need(reply, nonce, "List open models", "DOCS")
        return reply.marker("DOCS", nonce) or []

    def _action(self, action, moves=(), timeout=None):
        nonce = revit.new_nonce()
        code = revit.action_code(nonce, action, self.s.match(),
                                 [{"id": m["id"], "name": m["name"], "delta": m["delta"]} for m in moves], self.s)
        reply = self._call(code, timeout or float(self.s["probe_timeout_seconds"]), "LS: %s" % action)
        self._need(reply, nonce, action.capitalize())
        for line in reply.text_lines():
            self.say("  | " + line)
        return reply, nonce

    def _bind(self, reply, nonce, res):
        doc = reply.marker("DOC", nonce)
        if doc is None:
            raise Aborted("model binding failed: %s" % (reply.error or "no answer"))
        res.info["doc"] = doc
        res.add("Model", True, doc["title"] + ("" if doc.get("active") else "  (not the active window)"))
        if doc.get("readonly"):
            res.add("Model is read-only", False, "open it editable (detach / local copy) to move levels")
        return doc

    # ---- step: levels
    def read_levels(self):
        res = self._begin("levels")
        try:
            reply, nonce = self._action("levels")
            self._bind(reply, nonce, res)
            levels = reply.marker("LEVELS", nonce)
            if levels is None:
                raise Aborted("Levels: %s" % (reply.error or "no answer"))
            res.info["levels"] = levels
            bases = sorted(set(lv.get("base") or "?" for lv in levels))
            res.add("Levels", bool(levels), "%d level(s); Elevation Base: %s" % (len(levels), ", ".join(bases)))
            for lv in levels:
                self.say("  %-30s %18s%s" % (lv["name"], fmt_ft(lv["elev"], self.units),
                                            "   [pinned]" if lv.get("pinned") else ""))
        except Aborted as e:
            res.add("Stopped", False, str(e))
            res.aborted = True
        return self._end(res)

    # ---- step: plan / trial / apply
    def run(self, action, levels, specs):
        """action: plan | trial | apply.  ``levels`` from read_levels (re-read if None)."""
        res = self._begin(action)
        try:
            if levels is None:
                reply, nonce = self._action("levels")
                levels = reply.marker("LEVELS", nonce) or []
            moves, checks = resolve(levels, specs, self.units, float(self.s["tolerance_mm"]))
            res.checks.extend(checks)
            res.info["moves"] = moves
            if not res.ok:
                raise Aborted("fix the FAIL lines above first")
            timeout = float(self.s["apply_timeout_seconds"]) if action != "plan" else None
            self.say("[level shift] %s: %s" % (action, "; ".join("%s %s" % (
                m["name"], fmt_ft(m["delta"], self.units, signed=True)) for m in moves)))
            reply, nonce = self._action(action, moves, timeout)
            self._bind(reply, nonce, res)
            self._report_plan(reply.marker("PLAN", nonce), moves, res)
            if action != "plan":
                result = reply.marker("RESULT", nonce)
                if result is None:
                    raise Aborted("%s did not finish -- %s" % (action, reply.error or "no result"))
                self._report_result(action, result, res)
            elif reply.error:
                res.add("Revit reported", False, reply.error.splitlines()[0])
        except Aborted as e:
            res.add("Stopped", False, str(e))
            res.aborted = True
        self._say_failures(res)
        return self._end(res)

    def _report_plan(self, plan, moves, res):
        if plan is None:
            raise Aborted("Plan: no answer")
        res.info["plan"] = plan
        checks, lines = plan_checks(plan, moves)
        res.checks.extend(checks)
        for line in lines:
            self.say(line)

    def _report_result(self, action, r, res):
        res.info["result"] = r
        checks, lines = result_checks(action, r, self.units, self.s["tolerance_mm"])
        res.checks.extend(checks)
        for line in lines:
            self.say(line)
        if not r.get("stopped"):
            res.info["rows_csv"] = self._write_rows(action, r.get("rows") or [])

    def _say_failures(self, res):
        for c in res.checks:
            if c.ok is not True:
                self.say("  %s" % c)

    def _write_rows(self, action, rows):
        if not rows:
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return write_rows_csv(os.path.join(self.s.logs_dir(), "%s_%s_elements.csv" % (stamp, action)),
                              rows, self.units)


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)  # noqa: pylint: disable=no-member
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

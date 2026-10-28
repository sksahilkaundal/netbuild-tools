"""Element Remover, independent of the command line.

Steps:  sources (read)  ->  plan (what matches, what is skipped, what blocks; nothing changed)
        ->  trial (the whole removal, checked, then rolled back)  ->  apply (the same, kept).

Revit's answer is trusted only through what it reports back: every target is looked up again after
the deletion, and anything still in the model is listed by Id, never hidden.
"""

import datetime
import os
import threading

from . import revit
from .core import Check, plan_checks, result_checks, sources_lines, write_rows_csv


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
    """One POST to Revit on a background thread, so Ctrl+C / cancel stays responsive."""

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
        reply = self._call(revit.list_docs_code(nonce), float(self.s["probe_timeout_seconds"]), "ER: list models")
        self._need(reply, nonce, "List open models", "DOCS")
        return reply.marker("DOCS", nonce) or []

    def _action(self, action, targets=None, timeout=None):
        nonce = revit.new_nonce()
        code = revit.action_code(nonce, action, self.s.match(), targets, self.s)
        reply = self._call(code, timeout or float(self.s["probe_timeout_seconds"]), "ER: %s" % action)
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
            res.add("Model is read-only", False, "open it editable (detach / local copy) to remove elements")
        return doc

    # ---- step: sources
    def read_sources(self):
        res = self._begin("sources")
        try:
            reply, nonce = self._action("sources")
            self._bind(reply, nonce, res)
            src = reply.marker("SOURCES", nonce)
            if src is None:
                raise Aborted("Sources: %s" % (reply.error or "no answer"))
            res.info["sources"] = src
            res.add("Worksets / filters", True, "%d user workset(s), %d filter(s)" % (
                len(src["worksets"]), len(src["filters"])))
            for line in sources_lines(src):
                self.say("  " + line)
        except Aborted as e:
            res.add("Stopped", False, str(e))
            res.aborted = True
        return self._end(res)

    # ---- step: plan / trial / apply
    def run(self, action, targets):
        """action: plan | trial | apply; ``targets``: core.Targets."""
        res = self._begin(action)
        try:
            res.checks.extend(targets.checks())
            if not res.ok:
                raise Aborted("fix the FAIL lines above first")
            timeout = float(self.s["apply_timeout_seconds"]) if action != "plan" else None
            self.say("[element remover] %s: %s" % (action, targets.describe()))
            reply, nonce = self._action(action, targets, timeout)
            self._bind(reply, nonce, res)
            plan = reply.marker("PLAN", nonce)
            if plan is None:
                raise Aborted("Plan: %s" % (reply.error or "no answer"))
            res.info["plan"] = plan
            checks, lines = plan_checks(plan)
            res.checks.extend(checks)
            for line in lines:
                self.say(line)
            if action == "plan":
                res.info["rows_csv"] = self._write_rows(action, plan.get("rows") or [])
                if reply.error:
                    res.add("Revit reported", False, reply.error.splitlines()[0])
            else:
                result = reply.marker("RESULT", nonce)
                if result is None:
                    raise Aborted("%s did not finish -- %s" % (action, reply.error or "no result"))
                res.info["result"] = result
                checks, lines = result_checks(action, result)
                res.checks.extend(checks)
                for line in lines:
                    self.say(line)
                res.info["rows_csv"] = self._write_rows(action, result.get("rows") or [])
        except Aborted as e:
            res.add("Stopped", False, str(e))
            res.aborted = True
        for c in res.checks:
            if c.ok is not True:
                self.say("  %s" % c)
        return self._end(res)

    def _write_rows(self, action, rows):
        if not rows:
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return write_rows_csv(os.path.join(self.s.logs_dir(), "%s_%s_elements.csv" % (stamp, action)), rows)

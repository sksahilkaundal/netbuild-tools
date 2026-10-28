"""Stair Path through the pyRevit MCP listener, independent of the command line.

Steps:  plan (cores, flights, what each view gets; nothing changed)  ->  trial (everything placed, reported,
        then rolled back)  ->  apply (the same, kept: one Undo entry 'Stair Path by Netbuild').

Each run binds to one model (the active one, or the one whose title matches), starts from the Stair Path
settings kept for that model, applies the overrides given, and keeps the result for the next run.
"""

import csv
import datetime
import os
import threading

from . import revit, rules
from .rules import Check


class StepResult(object):
    def __init__(self, name, log_path=None):
        self.name, self.log_path = name, log_path
        self.checks, self.lines = [], []
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
    """One POST to Revit on a background thread, so Ctrl+C stays responsive."""

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


def pick_model(docs, match):
    """The model a run binds to: the active one, or the only project whose title contains one of ``match``
    -- the same rule the code inside Revit applies (revit.DRIVER)."""
    want = [m.lower() for m in match if m]
    projects = [d for d in docs if not d.get("linked") and not d.get("family")]
    if not want:
        active = [d for d in docs if d.get("active")]
        if not active:
            raise Aborted("no active model in Revit")
        return active[0]
    hits = [d for d in projects if [w for w in want if w in (d.get("title") or "").lower()]]
    if len(hits) != 1:
        raise Aborted("%d open model(s) match %s -- open models: %s" % (
            len(hits), list(match), [d.get("title") for d in projects]))
    return hits[0]


def describe(values):
    """One line of the settings a run uses."""
    views = "open plan views" if values["views"] == "open" else "plan views named '*%s*'" % values["name_filter"]
    return ("%s; clear in the %s; directional %s (X %g, Y %g mm); standard 1:200 X %g / Y %g, 1:100 X %g / Y %g mm"
            "; sweep %s; room tags %s; create types %s" % (
                views, "target views" if values["clear"] == "views" else "whole model",
                "on" if values["directional"] else "off", values["dir_x_mm"], values["dir_y_mm"],
                values["std_x_200"], values["std_y_200"], values["std_x_100"], values["std_y_100"],
                "on" if values["sweep"] else "off", "on" if values["room_tags"] else "off",
                "on" if values["create_types"] else "off"))


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
        reply = self._call(revit.list_docs_code(nonce), float(self.s["probe_timeout_seconds"]), "SP: list models")
        self._need(reply, nonce, "List open models", "DOCS")
        return reply.marker("DOCS", nonce) or []

    # ---- plan / trial / apply
    def run(self, action, overrides=None, reset=False):
        """action: plan | trial | apply; ``overrides``: Stair Path settings for this run (kept for the model)."""
        res = self._begin(action)
        try:
            model = pick_model(self.list_docs(), self.s.match())
            title = model["title"]
            values = self.s.model_values(title, reset)
            values = rules.settings(dict(values, **(overrides or {})))
            res.info["settings"] = values
            res.checks.extend(rules.check_settings(values))
            if not res.ok:
                raise Aborted("fix the FAIL lines above first")
            self.s.keep_model_values(title, values)
            self.s.save()
            self.say("[stair path] %s on %s" % (action, title))
            self.say("  settings: " + describe(values))
            nonce = revit.new_nonce()
            code = revit.action_code(nonce, action, self.s.match(), values, self.s["max_rows"])
            timeout = float(self.s["apply_timeout_seconds"] if action != "plan" else self.s["probe_timeout_seconds"])
            reply = self._need(self._call(code, timeout, "SP: %s" % action), nonce, action.capitalize())
            doc = reply.marker("DOC", nonce)
            if doc is None:
                raise Aborted("model binding failed: %s" % (reply.error.splitlines()[0] if reply.error else
                                                             "no answer"))
            res.info["doc"] = doc
            res.add("Model", True, doc["title"] + ("" if doc.get("active") else "  (not the active window)"))
            result = reply.marker("RESULT", nonce)
            if result is None:
                raise Aborted("%s did not finish -- %s" % (action, reply.error or "no result"))
            res.info["result"] = result
            res.checks.extend(Check(label, ok, detail) for ok, label, detail in result["checks"])
            for line in result["lines"]:
                self.say(line)
            res.info["rows_csv"] = self._write_rows(action, result.get("rows") or [])
            if result.get("rows_total", 0) > len(result.get("rows") or []):
                res.add("Annotation list", None, "%d of %d rows (max_rows)" % (len(result["rows"]),
                                                                             result["rows_total"]))
        except Aborted as e:
            res.add("Stopped", False, str(e))
            res.aborted = True
        return self._end(res)

    def _write_rows(self, action, rows):
        if not rows:
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.s.logs_dir(), "%s_%s_stair_paths.csv" % (stamp, action))
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(rules.CSV_FIELDS)
            for row in rows:
                w.writerow([row.get(k, "") for k in rules.CSV_FIELDS])
        return path

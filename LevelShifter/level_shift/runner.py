"""Level Shift, independent of the GUI/CLI.

Steps:  levels (read)  ->  plan (who is driven by the moved levels; nothing changed)
        ->  trial (the whole move, measured, then rolled back)  ->  apply (the same, kept).

Revit's answer is trusted only through what it measured: every model element's bounding box
before and after.  An element that still moved is reported by Id, never hidden.
"""

import csv
import datetime
import os
import subprocess
import sys
import threading

from . import revit
from .settings import MAX_LEVELS
from .units import FEET, fmt, fmt_ft, from_ft, parse_length, to_ft


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


class Aborted(Exception):
    pass


class MoveSpec(object):
    """One row: a level (name or id) and either a new elevation ('to') or a move ('by'), in ``units``."""

    def __init__(self, level, mode, value):
        if mode not in ("to", "by"):
            raise ValueError("mode must be 'to' or 'by'")
        self.level, self.mode, self.value = level, mode, float(value)

    @classmethod
    def parse(cls, text, mode, units):
        """'Level 01=3800' (mode to) / 'Level 01=+300' (mode by); the value may carry mm / m."""
        name, sep, val = (text or "").rpartition("=")
        if not sep or not name.strip():
            raise ValueError("expected LEVEL=VALUE, got %r" % text)
        return cls(name.strip(), mode, parse_length(val, units))

    def as_dict(self):
        return {"level": self.level, "mode": self.mode, "value": self.value}


def find_level(levels, ref):
    ref = ("%s" % ref).strip()
    for lv in levels:
        if str(lv["id"]) == ref:
            return lv
    hits = [lv for lv in levels if lv["name"].strip().lower() == ref.lower()]
    return hits[0] if len(hits) == 1 else None


def resolve(levels, specs, units, tol_mm=1.0):
    """[MoveSpec] -> (moves, checks). A move: the level row + 'new' and 'delta' in feet."""
    checks, moves, seen = [], [], set()
    tol = to_ft(tol_mm, "mm")
    if len(specs) > MAX_LEVELS:
        checks.append(Check("Levels", False, "%d given -- at most %d per run" % (len(specs), MAX_LEVELS)))
    for sp in specs:
        lv = find_level(levels, sp.level)
        if lv is None:
            checks.append(Check("Level %r" % sp.level, False, "not found in the model (names: %s)"
                                % ", ".join(l["name"] for l in levels)))
            continue
        if lv["id"] in seen:
            checks.append(Check(lv["name"], False, "selected twice"))
            continue
        seen.add(lv["id"])
        v = to_ft(sp.value, units)
        new, delta = (v, v - lv["elev"]) if sp.mode == "to" else (lv["elev"] + v, v)
        if abs(delta) < tol:
            checks.append(Check(lv["name"], None, "no change (%s) -- skipped" % fmt_ft(lv["elev"], units)))
            continue
        moves.append(dict(lv, new=new, delta=delta))
    final = dict((lv["id"], lv["elev"]) for lv in levels)
    for m in moves:
        final[m["id"]] = m["new"]
    names = dict((lv["id"], lv["name"]) for lv in levels)
    for m in moves:
        checks.append(Check("%s" % m["name"], True, "%s -> %s  (move %s)" % (
            fmt_ft(m["elev"], units), fmt_ft(m["new"], units), fmt_ft(m["delta"], units, signed=True))))
        same = [names[i] for i, e in final.items() if i != m["id"] and abs(e - m["new"]) < tol]
        if same:
            checks.append(Check("%s elevation" % m["name"], None, "same elevation as %s" % ", ".join(same)))
        if m.get("pinned"):
            checks.append(Check("%s pinned" % m["name"], None, "the level is pinned -- Revit may refuse to move it"))
        if m.get("monitored"):
            checks.append(Check("%s monitored" % m["name"], None,
                                "Copy/Monitor level -- a Coordination Review will flag it in the other model"))
    old = dict((lv["id"], lv["elev"]) for lv in levels)
    crossed = set()
    for m in moves:
        for i in final:
            if i != m["id"] and (old[i] < m["elev"]) != (final[i] < m["new"]):
                crossed.add(" / ".join(sorted((m["name"], names[i]))))
    if crossed:
        checks.append(Check("Level order", None, "the stacking order changes: %s" % ", ".join(sorted(crossed))))
    if not moves and not [c for c in checks if c.ok is False]:
        checks.append(Check("Levels", False, "nothing to move"))
    return moves, checks


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


ROW_FIELDS = ["id", "category", "name", "level", "rule", "params", "method", "drift", "status"]


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
        code = revit.action_code(
            nonce, action, self.s.match(),
            [{"id": m["id"], "name": m["name"], "delta": m["delta"]} for m in moves],
            tol_ft=to_ft(float(self.s["tolerance_mm"]), "mm"), rounds=int(self.s["correction_rounds"]),
            move_fallback=bool(self.s["move_fallback"]), rollback_on_drift=bool(self.s["rollback_on_drift"]),
            max_rows=int(self.s["max_rows"]))
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
        names = dict((m["id"], m["name"]) for m in moves)
        res.add("Elements driven by the moved levels", True, "%d to compensate (of %d model elements)"
                % (plan["compensate"], plan["elements"]))
        by_level = {}
        for lid, cat, n in plan["counts"]:
            by_level.setdefault(lid, []).append((cat, n))
        for lid in names:
            cats = sorted(by_level.get(lid, []), key=lambda kv: -kv[1])
            self.say("  %s: %s" % (names[lid], ", ".join("%s x%d" % kv for kv in cats) or "no hosted elements"))
        if plan["no_offset"]:
            res.add("No offset parameter", None, "%d element(s) -- measured after the move and moved back if they "
                    "drift: %s" % (len(plan["no_offset"]), ", ".join("%s %s" % (r["category"], r["id"])
                                                                       for r in plan["no_offset"][:10])))
        if plan["group_members"]:
            res.add("Model groups", None, "%d member(s) in %d group(s) reference a moved level -- the group "
                    "origin is compensated; members are measured" % (plan["group_members"], plan["groups"]))
        for b in plan["blockers"]:
            res.add("Blocked: %s %s" % (b["category"], b["id"]), False, "%s -- %s" % (b["name"], b["why"]))

    def _report_result(self, action, r, res):
        rows = r.get("rows") or []
        res.info["result"] = r
        u = self.units
        if r.get("stopped"):
            res.add("Not applied", False, r["stopped"])
            return
        res.add("Elements measured", True, "%d (bounding box min/max Z, before and after)" % r.get("measured", 0))
        by_method = {}
        for row in rows:
            by_method[row["method"] or "-"] = by_method.get(row["method"] or "-", 0) + 1
        res.add("Compensated", True, ", ".join("%s x%d" % kv for kv in sorted(by_method.items())) or "nothing needed")
        drift = r.get("drift") or []
        if drift:
            res.add("Still moved", False, "%d element(s): %s" % (len(drift), "; ".join(
                "%s %s %s (%s)" % (d["category"], d["id"], fmt(from_ft(d["drift"], u), u, True), d["status"])
                for d in drift[:15])) + (" ..." if len(drift) > 15 else ""))
        else:
            res.add("Every element kept its X, Y, Z", True, "within %s mm" % self.s["tolerance_mm"])
        for e in r.get("errors") or []:
            res.add("Revit error", False, e)
        warns = r.get("warnings") or []
        if warns:
            uniq = sorted(set(warns))
            res.add("Revit warnings (dismissed)", None, "%d: %s" % (len(warns), " | ".join(uniq[:5])))
        for lv in r.get("levels_after") or []:
            self.say("  %s now %s" % (lv["name"], fmt_ft(lv["elev"], u)))
        if action == "trial":
            res.add("Trial", True if not drift and not r.get("errors") else None,
                    "rolled back -- the model is unchanged")
        elif r.get("committed"):
            res.add("Applied", True, "one Undo entry in Revit: 'Netbuild Level Shift'. Save / Synchronize when happy")
        else:
            res.add("Applied", False, "rolled back -- the model is unchanged (%s)" % (
                "an element still moved; untick 'Undo all if anything moves' on Setup to keep it anyway"
                if drift else "Revit error"))
        res.info["rows_csv"] = self._write_rows(action, rows)

    def _say_failures(self, res):
        for c in res.checks:
            if c.ok is not True:
                self.say("  %s" % c)

    def _write_rows(self, action, rows):
        if not rows:
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.s.logs_dir(), "%s_%s_elements.csv" % (stamp, action))
        u = self.units
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(ROW_FIELDS[:-2] + ["drift (%s)" % u, "status"])
            for r in rows:
                ps = "; ".join("%s %s -> %s" % (n, fmt(from_ft(a, u), u), fmt(from_ft(b, u), u))
                               for n, a, b in r.get("params") or [])
                w.writerow([r["id"], r["category"], r["name"], r["level"], r["rule"], ps, r["method"],
                            round(from_ft(r["drift"], u), 3), r["status"]])
        return path


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)  # noqa: pylint: disable=no-member
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

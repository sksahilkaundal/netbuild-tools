"""What the window, the command line and the pyRevit buttons share.

Runs on CPython 3 (the exe) and on IronPython 2.7 (pyRevit, inside Revit): no f-strings, no
keyword-only arguments, no print(..., end=), no super() without arguments.  The pyRevit
extension carries a copy of this file (see sync_pyrevit_lib.py; a test keeps them identical).
"""

import io

from .units import fmt, fmt_ft, from_ft, parse_length, to_ft

MAX_LEVELS = 10

# what the engine (payload.py) needs; settings.json / the pyRevit config may override them
ENGINE_DEFAULTS = {
    "tolerance_mm": 1.0,            # min Z and max Z must each move less than this
    "correction_rounds": 4,         # measure -> correct rounds after the level move
    "move_fallback": True,          # an element with no offset parameter is moved back by (0, 0, -dz)
    "rollback_on_drift": True,      # Apply: if any element still moved, undo everything
    "max_rows": 20000,              # element rows returned / written to the CSV
    "fix_groups": True,             # group members that cannot be kept in place: ungroup, fix, regroup
}


class Check(object):
    def __init__(self, label, ok, detail=""):
        self.label, self.ok, self.detail = label, ok, detail

    @property
    def mark(self):
        return "OK  " if self.ok is True else ("WARN" if self.ok is None else "FAIL")

    def __str__(self):
        return "[%s] %s%s" % (self.mark, self.label, (" -- " + self.detail) if self.detail else "")


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
    ref = (u"%s" % ref).strip()
    for lv in levels:
        if str(lv["id"]) == ref:
            return lv
    hits = [lv for lv in levels if lv["name"].strip().lower() == ref.lower()]
    return hits[0] if len(hits) == 1 else None


def counterpart(cur, mode, text, units):
    """One row's other field: a new elevation typed -> the move; a move typed -> the new elevation.

    ``cur`` is the current elevation in ``units`` (None if no level is picked). Returns '' for a
    blank entry and for an unknown current elevation; raises ValueError for a bad number.
    """
    if not (text or "").strip():
        return ""
    v = parse_length(text, units)
    if cur is None:
        return ""
    n = 1 if units == "mm" else 4
    return ("%+." + str(n) + "f") % (v - cur) if mode == "to" else ("%." + str(n) + "f") % (cur + v)


def define_value(how, abs_text, amount_text, up, units):
    """The "Define new level" dialog: ('to', new elevation) or ('by', +/- move), in ``units``."""
    if how == "to":
        return "to", parse_length(abs_text, units)
    v = abs(parse_length(amount_text, units))
    return "by", v if up else -v


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
        m = dict(lv)
        m.update({"new": new, "delta": delta})
        moves.append(m)
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


# ------------------------------------------------------------ the engine

def config(nonce, action, match=(), moves=(), s=None):
    """The ``_LS`` dict the payload reads. ``moves``: [{"id", "name", "delta" (feet)}]."""
    o = dict(ENGINE_DEFAULTS)
    o.update(s or {})
    return {"nonce": nonce, "action": action, "match": list(match or []),
            "moves": [{"id": int(m["id"]), "name": m["name"], "delta": float(m["delta"])} for m in moves],
            "tol": to_ft(float(o["tolerance_mm"]), "mm"), "rounds": int(o["correction_rounds"]),
            "move_fallback": bool(o["move_fallback"]), "rollback_on_drift": bool(o["rollback_on_drift"]),
            "max_rows": int(o["max_rows"]), "fix_groups": bool(o["fix_groups"])}


def run_local(doc, action, moves=(), s=None, match=()):
    """Run the engine in this process (inside Revit, from a pyRevit button) on ``doc``.

    Returns {tag: data} -- the same DOC / LEVELS / PLAN / RESULT the listener route prints.
    Revit API errors propagate as exceptions.
    """
    from .payload import CODE
    out = {}
    ns = {"__name__": "__level_shift__", "doc": doc, "_LS": config("local", action, match, moves, s),
          "_LS_SINK": out.__setitem__}
    exec(compile(CODE, "<level shift>", "exec"), ns)
    return out


# ------------------------------------------------------------ reading the engine's answers

def plan_checks(plan, moves):
    """(checks, lines) for the engine's PLAN."""
    checks, lines = [], []
    names = dict((m["id"], m["name"]) for m in moves)
    checks.append(Check("Elements driven by the moved levels", True, "%d to compensate (of %d model elements)"
                        % (plan["compensate"], plan["elements"])))
    by_level = {}
    for lid, cat, n in plan["counts"]:
        by_level.setdefault(lid, []).append((cat, n))
    for lid in names:
        cats = sorted(by_level.get(lid, []), key=lambda kv: -kv[1])
        lines.append("  %s: %s" % (names[lid], ", ".join("%s x%d" % kv for kv in cats) or "no hosted elements"))
    if plan["no_offset"]:
        checks.append(Check("No offset parameter", None, "%d element(s) -- measured after the move and moved back "
                            "if they drift: %s" % (len(plan["no_offset"]), ", ".join(
                                "%s %s" % (r["category"], r["id"]) for r in plan["no_offset"][:10]))))
    if plan["group_members"]:
        checks.append(Check("Model groups", None, "%d member(s) in %d group(s) reference a moved level -- compensated "
                            "in place; %s" % (plan["group_members"], plan["groups"], (
                                "a group whose members still move is ungrouped, fixed and regrouped"
                                if plan.get("fix_groups", True) else "groups are never ungrouped (option off)"))))
    for b in plan["blockers"]:
        checks.append(Check("Blocked: %s %s" % (b["category"], b["id"]), False, "%s -- %s" % (b["name"], b["why"])))
    return checks, lines


def result_checks(action, r, units, tol_mm):
    """(checks, lines) for the engine's RESULT of a trial / apply."""
    checks, lines = [], []
    if r.get("stopped"):
        return [Check("Not applied", False, r["stopped"])], lines
    rows = r.get("rows") or []
    checks.append(Check("Elements measured", True, "%d (bounding box min/max Z, before and after)"
                        % r.get("measured", 0)))
    by_method = {}
    for row in rows:
        key = row["method"] or "-"
        by_method[key] = by_method.get(key, 0) + 1
    checks.append(Check("Compensated", True, ", ".join("%s x%d" % kv for kv in sorted(by_method.items()))
                        or "nothing needed"))
    drift = r.get("drift") or []
    if drift:
        checks.append(Check("Still moved", False, "%d element(s): %s" % (len(drift), "; ".join(
            "%s %s %s (%s)" % (d["category"], d["id"], fmt(from_ft(d["drift"], units), units, True), d["status"])
            for d in drift[:15])) + (" ..." if len(drift) > 15 else "")))
    else:
        checks.append(Check("Every element kept its X, Y, Z", True, "within %s mm" % tol_mm))
    for e in r.get("errors") or []:
        checks.append(Check("Revit error", False, e))
    for n in r.get("notes") or []:
        checks.append(Check("Groups", None, n))
    groups = r.get("groups") or []
    if groups:
        renamed = sorted(set("'%s' -> '%s'" % (g["type"], g["new_type"]) for g in groups))
        checks.append(Check("Groups regrouped", None, "%d instance(s): %s" % (len(groups), "; ".join(renamed[:8]))
                            + ("" if not [g for g in groups if g["detail"]] else
                               "; their attached detail groups need re-attaching")))
    plane = r.get("on_plane") or {}
    if plane:
        checks.append(Check("Lines on the level's plane", None, "%d follow their level by design (sketch / "
                            "separation lines; the elements they shape kept their position): %s" % (
                                sum(plane.values()), ", ".join("%s x%d" % kv for kv in sorted(plane.items())))))
    warns = r.get("warnings") or []
    if warns:
        checks.append(Check("Revit warnings (dismissed)", None, "%d: %s" % (len(warns), " | ".join(sorted(set(warns))[:5]))))
    for lv in r.get("levels_after") or []:
        lines.append("  %s now %s" % (lv["name"], fmt_ft(lv["elev"], units)))
    if action == "trial":
        checks.append(Check("Trial", True if not drift and not r.get("errors") else None,
                            "rolled back -- the model is unchanged"))
    elif r.get("committed"):
        checks.append(Check("Applied", True, "one Undo entry in Revit: 'Level Shift by Netbuild'. "
                                             "Save / Synchronize when happy"))
    else:
        checks.append(Check("Applied", False, "rolled back -- the model is unchanged (%s)" % (
            "an element still moved; untick 'Undo all if anything moves' to keep it anyway" if drift
            else "Revit error")))
    return checks, lines


def _csv_cell(v):
    t = u"%s" % v
    if any(ch in t for ch in u'",\n\r'):
        t = u'"%s"' % t.replace(u'"', u'""')
    return t


def write_rows_csv(path, rows, units):
    """One row per element the move touched (Excel-friendly UTF-8)."""
    head = ["id", "category", "name", "level", "rule", "params", "method", "drift (%s)" % units, "status"]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(u",".join(_csv_cell(h) for h in head) + u"\r\n")
        for r in rows:
            ps = u"; ".join(u"%s %s -> %s" % (n, fmt(from_ft(a, units), units), fmt(from_ft(b, units), units))
                            for n, a, b in r.get("params") or [])
            cells = [r["id"], r["category"], r["name"], r["level"], r["rule"], ps, r["method"],
                     round(from_ft(r["drift"], units), 3), r["status"]]
            f.write(u",".join(_csv_cell(c) for c in cells) + u"\r\n")
    return path

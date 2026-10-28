"""What the command line and the pyRevit button share.

Runs on CPython 3 (the exe) and on IronPython 2.7 (pyRevit, inside Revit): no f-strings, no
keyword-only arguments, no print(..., end=), no super() without arguments.  The pyRevit
extension carries a copy of this file (see sync_pyrevit_lib.py; a test keeps them identical).
"""

import io

# what the engine (payload.py) needs; settings.json / the pyRevit config may override them
ENGINE_DEFAULTS = {
    "skip_pinned": True,            # pinned targets are listed, not removed
    "fix_groups": True,             # targets inside model groups: ungroup, remove, regroup
    "merge_groups": True,           # regrouped instances that are identical share one group type again
    "model_only": True,             # annotation / view-specific elements are never removed
    "max_rows": 20000,              # element rows returned / written to the CSV
}


class Check(object):
    def __init__(self, label, ok, detail=""):
        self.label, self.ok, self.detail = label, ok, detail

    @property
    def mark(self):
        return "OK  " if self.ok is True else ("WARN" if self.ok is None else "FAIL")

    def __str__(self):
        return "[%s] %s%s" % (self.mark, self.label, (" -- " + self.detail) if self.detail else "")


def split_names(text):
    """'Walls, Doors' -> ['Walls', 'Doors'] (also ';' or new lines)."""
    out = []
    for part in (text or "").replace(";", ",").replace("\n", ",").split(","):
        if part.strip() and part.strip() not in out:
            out.append(part.strip())
    return out


class Targets(object):
    """What to remove: elements on ``worksets`` and / or passing ``filters`` (view filter or saved
    selection names), only of ``categories`` (blank = every category).  ``combine``: "any" = on a
    workset OR passing a filter; "all" = on a workset AND passing a filter."""

    def __init__(self, worksets=(), filters=(), categories=(), combine="any"):
        if combine not in ("any", "all"):
            raise ValueError("combine must be 'any' or 'all'")
        self.worksets, self.filters = list(worksets or []), list(filters or [])
        self.categories, self.combine = list(categories or []), combine

    def checks(self):
        if not self.worksets and not self.filters:
            return [Check("Targets", False, "pick at least one workset or filter")]
        out = []
        if self.combine == "all" and not (self.worksets and self.filters):
            out.append(Check("Combine", None, "'both' needs a workset and a filter -- using the one given"))
        return out

    def describe(self):
        parts = []
        if self.worksets:
            parts.append("worksets: " + ", ".join(self.worksets))
        if self.filters:
            parts.append("filters: " + ", ".join(self.filters))
        how = " AND " if self.combine == "all" else " OR "
        text = how.join(parts) if parts else "nothing"
        return text + ("  (categories: %s)" % ", ".join(self.categories) if self.categories else "  (every category)")

    def as_dict(self):
        return {"worksets": self.worksets, "filters": self.filters, "categories": self.categories,
                "combine": self.combine}


# ------------------------------------------------------------ the engine

def config(nonce, action, match=(), targets=None, s=None):
    """The ``_ER`` dict the payload reads."""
    o = dict(ENGINE_DEFAULTS)
    o.update(s or {})
    t = targets or Targets()
    return {"nonce": nonce, "action": action, "match": list(match or []), "worksets": list(t.worksets),
            "filters": list(t.filters), "categories": list(t.categories), "combine": t.combine,
            "skip_pinned": bool(o["skip_pinned"]), "fix_groups": bool(o["fix_groups"]),
            "merge_groups": bool(o["merge_groups"]),
            "model_only": bool(o["model_only"]), "max_rows": int(o["max_rows"])}


def run_local(doc, action, targets=None, s=None, match=()):
    """Run the engine in this process (inside Revit, from a pyRevit button) on ``doc``.

    Returns {tag: data} -- the same DOC / SOURCES / PLAN / RESULT the listener route prints.
    Revit API errors propagate as exceptions.
    """
    from .payload import CODE
    out = {}
    ns = {"__name__": "__element_remover__", "doc": doc, "_ER": config("local", action, match, targets, s),
          "_ER_SINK": out.__setitem__}
    exec(compile(CODE, "<element remover>", "exec"), ns)
    return out


# ------------------------------------------------------------ reading the engine's answers

def sources_lines(src):
    """Text lines for the engine's SOURCES (the command line's `sources`)."""
    lines = ["Worksets%s:" % ("" if src["workshared"] else " -- the model is not workshared")]
    for w in src["worksets"]:
        lines.append("  %-40s %6d element(s)%s" % (w["name"], w["elements"], "" if w["open"] else "   [closed]"))
    lines.append("Filters:")
    for f in src["filters"]:
        what = ("saved selection, %d element(s)" % f["elements"]) if f["kind"] == "selection" else \
            ("rules on " + (", ".join(f["categories"]) or "no categories"))
        lines.append("  %-40s %s" % (f["name"], what))
    lines.append("Categories in use: " + ", ".join(src["categories"]))
    return lines


def _pairs(pairs, limit=12):
    text = ", ".join("%s x%d" % (k or "(no category)", v) for k, v in pairs[:limit])
    return text + (" ..." if len(pairs) > limit else "")


def plan_checks(plan):
    """(checks, lines) for the engine's PLAN."""
    checks, lines = [], []
    for m in plan.get("missing") or []:
        checks.append(Check("Not found", False, m))
    for name in plan.get("closed") or []:
        checks.append(Check("Workset closed", False, "'%s' is closed -- open it (Manage Worksets) so its elements "
                                                     "can be found and removed" % name))
    n = plan["targets"]
    checks.append(Check("Elements to remove", True if n else None, "%d: %d standalone, %d inside model groups%s" % (
        n, plan["standalone"], plan["in_groups"],
        (", %d model group instance(s) as a whole" % plan["whole_groups"]) if plan["whole_groups"] else "")
        if n else "none match"))
    if plan["by_category"]:
        lines.append("  by category: " + _pairs(plan["by_category"], 30))
    for label, count in plan.get("by_source") or []:
        lines.append("  %s: %d" % (label, count))
    if plan.get("with_group"):
        checks.append(Check("Inside a removed group", True, "%d more go with the group instance that holds them"
                            % plan["with_group"]))
    if plan["in_groups"]:
        checks.append(Check("Model groups", None, "%d group instance(s) (%s) will be ungrouped, the targets removed, "
                            "and regrouped without them%s" % (plan["groups"], ", ".join(plan["group_types"][:8]), (
                                "; identical regrouped instances share one group type again (their members get new "
                                "Element Ids, so tags on them go)") if plan.get("merge_groups", True) else "")))
    if plan["skipped"]:
        checks.append(Check("Skipped", None, "%d: %s" % (plan["skipped"], _pairs(plan["skipped_why"]))))
    for b in plan["blockers"]:
        checks.append(Check("Blocked: %s %s" % (b["category"], b["id"]), False, "%s -- %s" % (b["name"], b["why"])))
    if not plan.get("modifiable", True):
        checks.append(Check("Model is read-only", False, "open it editable (detach / local copy) to remove elements"))
    return checks, lines


def result_checks(action, r):
    """(checks, lines) for the engine's RESULT of a trial / apply."""
    checks, lines = [], []
    if r.get("stopped"):
        return [Check("Not removed", False, r["stopped"])], lines
    checks.append(Check("Removed", True if not r.get("left") else False, "%d of %d target(s)%s" % (
        r["deleted"], r["requested"], (" + %d inside removed groups" % r["with_group"]) if r.get("with_group") else "")))
    deps = r.get("dependents") or []
    if deps:
        checks.append(Check("Deleted with them by Revit", None, "%d: %s (hosted / dependent elements)" % (
            sum(v for k, v in deps), _pairs(deps))))
    left = r.get("left") or []
    if left:
        checks.append(Check("Still in the model", False, "%d: %s" % (len(left), "; ".join(
            "%s %s" % (x["category"], x["id"]) for x in left[:15]))))
    for e in r.get("errors") or []:
        checks.append(Check("Revit error", False, e))
    groups = r.get("groups") or []
    if groups:
        renamed = sorted(set("'%s' -> '%s'" % (g["type"], g["new_type"]) for g in groups if g["new_id"] > 0))
        gone = len([g for g in groups if g["new_id"] <= 0])
        merged = [g for g in groups if g.get("merged")]
        if merged:
            checks.append(Check("Group types merged", None, "%d regrouped instance(s) now share the type of an identical "
                                "one (checked member by member); their members have new Element Ids -- re-tag them "
                                "if they were tagged" % len(merged)))
        kept = [g for g in groups if g.get("merge", "").startswith("kept")]
        if kept:
            checks.append(Check("Group types not merged", None, "%d instance(s) keep their own type: %s" % (
                len(kept), "; ".join("%s (id %d)" % (g["merge"], g["new_id"]) for g in kept[:5]))))
        checks.append(Check("Groups regrouped", None, "%d instance(s): %s%s%s" % (
            len(groups), "; ".join(renamed[:8]), ("; %d emptied and gone" % gone) if gone else "",
            "" if not [g for g in groups if g["detail"]] else "; their attached detail groups need re-attaching")))
    for n in r.get("notes") or []:
        lines.append("  " + n)
    warns = r.get("warnings") or []
    if warns:
        checks.append(Check("Revit warnings (dismissed)", None, "%d: %s" % (len(warns), " | ".join(sorted(set(warns))[:5]))))
    lines.append("  Revit deleted %d element(s) in total" % r.get("total", 0))
    if action == "trial":
        checks.append(Check("Trial", True if not left and not r.get("errors") else None,
                            "rolled back -- the model is unchanged"))
    elif r.get("committed"):
        checks.append(Check("Applied", True, "one Undo entry in Revit: 'Element Remover by Netbuild'. "
                                             "Save / Synchronize when happy"))
    else:
        checks.append(Check("Applied", False, "rolled back -- the model is unchanged (%s)" % (
            "a target is still in the model" if left else "Revit error")))
    return checks, lines


def _csv_cell(v):
    t = u"%s" % v
    if any(ch in t for ch in u'",\n\r'):
        t = u'"%s"' % t.replace(u'"', u'""')
    return t


def write_rows_csv(path, rows):
    """One row per element matched, skipped or deleted (Excel-friendly UTF-8)."""
    head = ["id", "category", "name", "workset", "group", "matched", "status"]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(u",".join(_csv_cell(h) for h in head) + u"\r\n")
        for r in rows:
            f.write(u",".join(_csv_cell(r.get(h, "")) for h in head) + u"\r\n")
    return path

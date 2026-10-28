"""Clear Warnings by Netbuild -- the engine. Runs inside Revit (IronPython 2.7); CPython 3 in the tests.

The six steps of scripts/clear_model_warnings.py (developed on ProjectC-Studio-BIM-B001-ZZZ-BM-950001: 2,120
warnings -> 0), each optional, in this order:

  1. area_plans  Delete Area Plan views + schedules of Areas (view templates and the active view are kept).
  2. areas       Delete all Areas.
  3. area_lines  Delete all Area Separation Lines.
  4. matchlines  Delete orphaned Matchlines (OwnerViewId invalid). Revit refuses to edit a Matchline sketch
                 from the API, so a live Matchline still in a warning is listed for manual review instead.
  5. room_tags   Delete Room Tags flagged "outside of its Room" whose room reference is dangling (Room is None
                 and TaggedLocalRoomId raises). A tag with a valid room is only out of place: manual review.
  6. type_marks  Unique Type Marks for each duplicate group: keyword prefix, thickness suffix (Walls /
                 Floors), then a letter suffix that always succeeds.

Every function takes the Revit API namespace as ``DB`` (``from pyrevit import DB`` in a button), so the
tests can hand in a stand-in. Run applies every step in one TransactionGroup -- one Undo entry.
"""

import re

from . import about

STEPS = [
    ("area_plans", "1. Delete Area Plan views + Area schedules"),
    ("areas", "2. Delete all Areas"),
    ("area_lines", "3. Delete all Area Separation Lines"),
    ("matchlines", "4. Delete orphaned Matchlines (no owner view)"),
    ("room_tags", "5. Delete orphaned Room Tags (dangling room reference)"),
    ("type_marks", "6. Fix duplicate Type Marks"),
]
STEP_KEYS = [k for k, _ in STEPS]
LABELS = dict(STEPS)
UNDO_NAME = about.PRODUCT                              # the Revit Undo entry

DEFAULT_RULES = "ritz=RITZ-; dormakaba=DK-"            # Type Mark keyword -> prefix (step 6), per project
THICKNESS_SUFFIX_CATEGORIES = ("Walls", "Floors")
PROFILE_SHARE = 0.5                                    # B001 profile: at least half the warnings on Areas
ROOM_TAG_OUTSIDE = "room tag is outside"
TOP = 25                                               # warning groups shown in a summary

COLOURS = {"ok": "#1B7F2A", "warn": "#B26A00", "fail": "#C62828", "head": "#000000", "": "#333333"}


# ------------------------------------------------------------ small helpers

def int_id(eid):
    """An ElementId as int: .Value (Revit 2024+) or .IntegerValue (older)."""
    v = getattr(eid, "Value", None)
    return int(v if v is not None else eid.IntegerValue)


def _bic(DB, name):
    return int(getattr(DB.BuiltInCategory, name))


def _cat_id(el):
    cat = getattr(el, "Category", None)
    return int_id(cat.Id) if cat is not None else None


def _cat_name(el):
    cat = getattr(el, "Category", None)
    return cat.Name if cat is not None else "N/A"


def _of_category(doc, DB, name):
    return list(DB.FilteredElementCollector(doc).OfCategory(getattr(DB.BuiltInCategory, name))
                .WhereElementIsNotElementType().ToElements())


def _name(el):
    try:
        return el.Name
    except Exception:
        return "?"


def _view_name(doc, view_id):
    if view_id is None or int_id(view_id) < 0:
        return "no view"
    v = doc.GetElement(view_id)
    return _name(v) if v is not None else "missing view"


def _id_list(DB, ids):
    try:
        from System.Collections.Generic import List
        return List[DB.ElementId](ids)
    except ImportError:                                # CPython (tests)
        return list(ids)


def parse_rules(text):
    """'ritz=RITZ-; dormakaba=DK-' -> [('ritz', 'RITZ-'), ('dormakaba', 'DK-')]. ValueError when malformed."""
    rules = []
    for part in re.split(r"[;\n]", text or ""):
        part = part.strip()
        if not part:
            continue
        if part.count("=") != 1:
            raise ValueError("Type Mark rule '%s' -- write keyword=PREFIX, separated by ;" % part)
        kw, prefix = [s.strip() for s in part.split("=")]
        if not kw or not prefix:
            raise ValueError("Type Mark rule '%s' -- keyword and prefix both needed" % part)
        rules.append((kw.lower(), prefix))
    return rules


# ------------------------------------------------------------ warnings summary

def summary(doc, DB):
    """{'total', 'groups': [(description, count)] most first, 'area': warnings on Areas / Area lines}."""
    area_cats = set([_bic(DB, "OST_Areas"), _bic(DB, "OST_AreaSchemeLines")])
    counts, area = {}, 0
    for w in doc.GetWarnings():
        text = w.GetDescriptionText()
        counts[text] = counts.get(text, 0) + 1
        hit = "area" in text.lower()
        if not hit:
            for eid in w.GetFailingElements():
                el = doc.GetElement(eid)
                if el is not None and _cat_id(el) in area_cats:
                    hit = True
                    break
        if hit:
            area += 1
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"total": sum(counts.values()), "groups": groups, "area": area}


def profile(s):
    """(matches, text): does the model match the B001 profile -- mostly Area / Area Separation Line warnings?"""
    if not s["total"]:
        return False, "No warnings in this model."
    share = float(s["area"]) / s["total"]
    text = "%d of %d warnings (%d%%) are on Areas / Area Separation Lines" % (s["area"], s["total"],
                                                                              int(round(share * 100)))
    if share >= PROFILE_SHARE:
        return True, text + " -- matches the B001 profile: steps 1 - 3 clear most of them."
    return False, text + (" -- does NOT match the B001 profile: steps 1 - 3 will clear only those; "
                          "look at the groups before deleting Areas.")


def summary_lines(s, title="Warnings", top=TOP):
    """[(colour key, text)] for a summary: the total, the profile line and the largest groups."""
    out = [("head", "%s: %d" % (title, s["total"]))]
    ok, text = profile(s)
    out.append(("ok" if ok else "warn", "  " + text))
    for desc, n in s["groups"][:top]:
        out.append(("", "  %6d  %s" % (n, desc)))
    if len(s["groups"]) > top:
        rest = sum(n for _, n in s["groups"][top:])
        out.append(("", "  %6d  ... %d more group(s)" % (rest, len(s["groups"]) - top)))
    return out


# ------------------------------------------------------------ the steps: what each one targets

def _warned_ids(doc, contains=None):
    ids = set()
    for w in doc.GetWarnings():
        if contains and contains not in w.GetDescriptionText().lower():
            continue
        for eid in w.GetFailingElements():
            ids.add(int_id(eid))
    return ids


def plan_area_plans(doc, DB, rules=None):
    active = getattr(doc, "ActiveView", None)
    active = int_id(active.Id) if active is not None else None
    areas = _bic(DB, "OST_Areas")
    ids, lines, review = [], [], []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan).ToElements():
        if v.ViewType != DB.ViewType.AreaPlan or v.IsTemplate:
            continue
        if int_id(v.Id) == active:
            review.append("Area Plan '%s' [%d] is the active view -- open another view and run step 1 again"
                          % (_name(v), int_id(v.Id)))
            continue
        ids.append(v.Id)
        lines.append("Area Plan: %s" % _name(v))
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule).ToElements():
        try:
            if s.IsTemplate or int_id(s.Definition.CategoryId) != areas:
                continue
        except Exception:                              # revision / panel schedules have no Definition
            continue
        ids.append(s.Id)
        lines.append("Area schedule: %s" % _name(s))
    return {"ids": ids, "lines": lines, "review": review}


def plan_areas(doc, DB, rules=None):
    return {"ids": [a.Id for a in _of_category(doc, DB, "OST_Areas")], "lines": [], "review": []}


def plan_area_lines(doc, DB, rules=None):
    return {"ids": [l.Id for l in _of_category(doc, DB, "OST_AreaSchemeLines")], "lines": [], "review": []}


def plan_matchlines(doc, DB, rules=None):
    warned = _warned_ids(doc)
    ids, review, live = [], [], 0
    for m in _of_category(doc, DB, "OST_Matchline"):
        if int_id(m.OwnerViewId) < 0:
            ids.append(m.Id)
            continue
        live += 1
        if int_id(m.Id) in warned:
            review.append("Matchline [%d] in view '%s' is live and still in a warning -- fix it by hand "
                          "(select it, Edit Sketch)" % (int_id(m.Id), _view_name(doc, m.OwnerViewId)))
    lines = ["%d live Matchline(s) left untouched" % live] if live else []
    return {"ids": ids, "lines": lines, "review": review}


def plan_room_tags(doc, DB, rules=None):
    ids, review, flagged = [], [], 0
    seen = set()
    for w in doc.GetWarnings():
        if ROOM_TAG_OUTSIDE not in w.GetDescriptionText().lower():
            continue
        for eid in w.GetFailingElements():
            if int_id(eid) in seen:
                continue
            seen.add(int_id(eid))
            tag = doc.GetElement(eid)
            if tag is None:
                continue
            flagged += 1
            room = getattr(tag, "Room", None)
            dangling = False
            if room is None:
                try:
                    tag.TaggedLocalRoomId                # raises when the room reference is dangling
                except Exception:
                    dangling = True
            if dangling:
                ids.append(eid)
                continue
            where = ("room %s [%d]" % (getattr(room, "Number", "") or "?", int_id(room.Id))) if room is not None \
                else "room not in this model (linked)"
            review.append("Room Tag [%d] in view '%s' (%s) has a valid room and is only out of place -- "
                          "move it into its room by hand" % (int_id(eid), _view_name(doc, tag.OwnerViewId), where))
    lines = ["%d Room Tag(s) flagged 'outside of its Room'" % flagged] if flagged else []
    return {"ids": ids, "lines": lines, "review": review}


# ------------------------------------------------------------ step 6: duplicate Type Marks

def _type_name(DB, et):
    p = et.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
    name = p.AsString() if p is not None else None
    return name or _name(et) or ""


def _type_mark(DB, et):
    p = et.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_MARK)
    return p.AsString() if p is not None else None


def numeric_token(name):
    """'Wall 200mm Red' -> '200R': the thickness in a type name, R for 'red'."""
    m = re.search(r"(\d+)\s*mm", name, re.IGNORECASE) or re.search(r"(\d+)", name)
    if not m:
        return None
    token = m.group(1)
    if re.search(r"\bred\b", name, re.IGNORECASE):
        token += "R"
    return token


def _letters():
    i = 0
    while True:
        n, s = i, ""
        while True:
            s = chr(ord("a") + n % 26) + s
            n = n // 26 - 1
            if n < 0:
                break
        yield s
        i += 1


def plan_group(types_info, rules, used=None):
    """{id: new mark} for one duplicate group of (id, category, type name, mark) -- the three passes."""
    plan = {}
    used = set(used or ()) | set(t[3] for t in types_info)
    remaining = []
    for tid, cat, tname, mark in types_info:
        handled = False
        for kw, prefix in rules:
            if kw not in tname.lower():
                continue
            base = prefix + (mark or "").replace(" ", "")
            new = base
            if new in used:
                token = numeric_token(tname)
                candidate = base + "-" + token if token else None
                if candidate and candidate not in used:
                    new = candidate
                else:
                    break
            plan[tid] = new
            used.add(new)
            handled = True
            break
        if not handled:
            remaining.append((tid, cat, tname, mark))
    still = []
    for tid, cat, tname, mark in remaining:
        if cat in THICKNESS_SUFFIX_CATEGORIES:
            token = numeric_token(tname)
            if token:
                new = "%s-%s" % (mark, token)
                if new not in used:
                    plan[tid] = new
                    used.add(new)
                    continue
        still.append((tid, cat, tname, mark))
    still.sort(key=lambda t: t[2])
    letters = _letters()
    for tid, cat, tname, mark in still:
        for suffix in letters:
            new = "%s%s" % (mark, suffix)
            if new not in used:
                plan[tid] = new
                used.add(new)
                break
    return plan


def plan_type_marks(doc, DB, rules=None):
    rules = parse_rules(DEFAULT_RULES) if rules is None else rules
    plan, ids, lines, seen = {}, [], [], set()
    used = set()
    for t in DB.FilteredElementCollector(doc).WhereElementIsElementType().ToElements():
        mark = _type_mark(DB, t)
        if mark:
            used.add(mark)
    for w in doc.GetWarnings():
        text = w.GetDescriptionText().lower()
        if "duplicate" not in text or "type mark" not in text:
            continue
        info = []
        for eid in w.GetFailingElements():
            et = doc.GetElement(eid)
            if et is None or int_id(eid) in seen:
                continue
            seen.add(int_id(eid))
            info.append((int_id(eid), _cat_name(et), _type_name(DB, et), _type_mark(DB, et)))
            ids.append(eid)
        if len(info) < 2:
            continue
        group = plan_group(info, rules, used)
        used.update(group.values())
        for tid, cat, tname, mark in info:
            if tid in group:
                plan[tid] = group[tid]
                lines.append("[%s] %s | '%s' -> '%s'  [%d]" % (cat, tname, mark, group[tid], tid))
    by_int = dict((int_id(i), i) for i in ids)
    return {"ids": [by_int[t] for t in sorted(plan)], "marks": plan, "lines": lines, "review": []}


PLANS = {"area_plans": plan_area_plans, "areas": plan_areas, "area_lines": plan_area_lines,
         "matchlines": plan_matchlines, "room_tags": plan_room_tags, "type_marks": plan_type_marks}


# ------------------------------------------------------------ run

def _delete(doc, DB, ids):
    ids = [i for i in ids if doc.GetElement(i) is not None]     # an earlier step may have taken them
    if not ids:
        return 0
    return len(list(doc.Delete(_id_list(DB, ids))))


def _set_marks(doc, DB, plan, review):
    done = 0
    for eid in plan["ids"]:
        et = doc.GetElement(eid)
        p = et.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_MARK) if et is not None else None
        if p is None or p.IsReadOnly:
            review.append("Type [%d] -- Type Mark could not be set; give it a unique mark by hand" % int_id(eid))
            continue
        p.Set(plan["marks"][int_id(eid)])
        done += 1
    return done


def run(doc, DB, steps=None, apply=False, rules=None):
    """Run the chosen steps (all by default). apply=False is the dry run: counts only, nothing changes.

    Returns {'doc', 'apply', 'before', 'after', 'steps': [{'key', 'label', 'targeted', 'done', 'lines',
    'review'}], 'committed'}. A Revit error rolls back every step and propagates.
    """
    steps = [k for k in STEP_KEYS if steps is None or k in steps]
    rules = parse_rules(DEFAULT_RULES) if rules is None else rules
    out = {"doc": doc.Title, "apply": apply, "before": summary(doc, DB), "steps": [], "committed": False}
    group = DB.TransactionGroup(doc, UNDO_NAME) if apply else None
    if group is not None:
        group.Start()
    try:
        for key in steps:
            plan = PLANS[key](doc, DB, rules)
            review = list(plan["review"])
            done = 0
            if apply and plan["ids"]:
                t = DB.Transaction(doc, LABELS[key].split(". ", 1)[1])
                t.Start()
                try:
                    done = _set_marks(doc, DB, plan, review) if key == "type_marks" else _delete(doc, DB, plan["ids"])
                    t.Commit()
                except Exception:
                    t.RollBack()
                    raise
            out["steps"].append({"key": key, "label": LABELS[key], "targeted": len(plan["ids"]), "done": done,
                                 "lines": plan["lines"], "review": review})
        if group is not None:
            group.Assimilate()
            out["committed"] = True
    except Exception:
        if group is not None:
            group.RollBack()
        raise
    out["after"] = summary(doc, DB) if apply else out["before"]
    return out


def review_items(result):
    return [r for s in result["steps"] for r in s["review"]]


def report_lines(result, top=TOP):
    """[(colour key, text)] for the window and the log: before, each step, after, manual review."""
    apply = result["apply"]
    out = [("head", "%s -- %s" % ("Run" if apply else "Dry run (nothing changed)", result["doc"]))]
    out += summary_lines(result["before"], "Warnings before", top)
    out.append(("head", "Steps"))
    for s in result["steps"]:
        what = "Type Marks" if s["key"] == "type_marks" else "elements"
        if apply:
            verb = "updated" if s["key"] == "type_marks" else "deleted (incl. dependents)"
            out.append(("ok", "  %s: %d targeted, %d %s %s" % (s["label"], s["targeted"], s["done"], what, verb)))
        else:
            out.append(("", "  %s: %d would be %s" % (s["label"], s["targeted"],
                                                       "changed" if s["key"] == "type_marks" else "deleted")))
        for line in s["lines"]:
            out.append(("", "      " + line))
    if apply:
        b, a = result["before"], result["after"]
        out += summary_lines(a, "Warnings after", top)
        before = dict(b["groups"])
        after = dict(a["groups"])
        out.append(("head", "Change by description"))
        for desc in sorted(set(before) | set(after), key=lambda d: (-before.get(d, 0), d)):
            n0, n1 = before.get(desc, 0), after.get(desc, 0)
            if n0 != n1:
                out.append(("ok" if n1 < n0 else "warn", "  %6d -> %-6d %s" % (n0, n1, desc)))
        out.append(("ok" if a["total"] < b["total"] or not b["total"] else "warn",
                    "Warnings: %d before -> %d after (%+d)" % (b["total"], a["total"], a["total"] - b["total"])))
    review = review_items(result)
    out.append(("warn" if review else "ok", "Manual review: %d item(s)%s" % (
        len(review), " -- left alone on purpose" if review else "")))
    for r in review:
        out.append(("warn", "  " + r))
    return out

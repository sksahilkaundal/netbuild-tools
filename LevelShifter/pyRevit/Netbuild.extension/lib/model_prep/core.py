"""Model Prep engine: the three steps worked out on a snapshot of the model -- no Revit calls here, so every rule can
be tested outside Revit (revit.py takes the snapshot and applies the plan).  IronPython 2.7 + CPython 3.

    snapshot = {"title": str,
                "worksets": [{"id": int, "name": str}],                    # user worksets
                "links": [{"id": int, "name": "ProjectC-...rvt", "ws": int, "owner": str,
                           "instances": [{"id": int, "ws": int, "owner": str}]}]}

Step 01  discipline links, building-specific only: OK / WRONG SCOPE (a Tower / Site-Wide / Podium / Basement file
         instead of the building's own) / OTHER BUILDING / MISSING (+ the ACC Consumed folder to link it from).
Step 02  worksets against the register: MATCHED / MISSING (created) / EXTRA (never deleted); near-duplicate
         spellings suggested, renamed to the register's name only for the pairs the user ticks.
Step 03  every link type + every instance onto its Link-* workset; no confident rule -> asked, never guessed.
"""

import re
from difflib import SequenceMatcher

STEPS = (1, 2, 3)
OK, WARN, FAIL, INFO, HEAD = "OK  ", "WARN", "FAIL", "", "HEAD"


# ------------------------------------------------------------------ names
def parse(name, rules):
    """(building, discipline) from a link file name / model title, upper case; (None, None) if it doesn't match."""
    m = re.match(rules["name_pattern"], name or "", re.IGNORECASE)
    if not m:
        return None, None
    return m.group(1).upper(), m.group(2).upper()


def host(title, rules):
    """The open model's building and discipline from its title (a local copy's _user suffix is fine)."""
    building, disc = parse(title, rules)
    return {"building": building, "disc": disc}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def similarity(a, b):
    """How much two workset names look like one name spelled two ways (0..1).

    Compared without case, spaces and punctuation, after their common start: 'Link-EL' / 'Link-ELE',
    'Wall Fixtures' / 'Walls Fixtures', 'Link-Studio-AR-Facade' / 'Link-Facade', 'Ceiling' / 'Ceiling '.
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    p = 0
    while p < min(len(na), len(nb)) and na[p] == nb[p]:
        p += 1
    short, long_ = sorted((na[p:], nb[p:]), key=len)
    if not short:
        return 0.95 if len(long_) <= 3 else 0.0        # EL -> ELE, PL -> PLB
    if len(short) >= 2 and (long_.startswith(short) or long_.endswith(short)):
        return 0.9                                      # Wall -> Walls Fixtures, Studio-AR-Facade -> Facade
    return SequenceMatcher(None, short, long_).ratio()


def suggest_pairs(live, register, threshold=0.85):
    """Model worksets that are not in the register but look like a register name: [{"old", "new", "score", "both"}],
    best first; each name used once. "both" = the register's spelling is in the model too."""
    live_set, reg_set = set(live), set(register)
    extra = [n for n in live if n not in reg_set]
    scored = []
    for old in extra:
        for new in register:
            s = similarity(old, new)
            if s >= threshold:                                  # ties: the closer whole name, then a missing one
                whole = SequenceMatcher(None, _norm(old), _norm(new)).ratio()
                scored.append((-s, -whole, new in live_set, old, new))
    scored.sort()
    used, out = set(), []
    for neg, _, both, old, new in scored:
        if old in used or new in used:
            continue
        used.update([old, new])
        out.append({"old": old, "new": new, "score": -neg, "both": both})
    return out


def check_register(names, live):
    """How well a register tab fits the model: (names, already in the model, share)."""
    names, live = list(names), set(live)
    hit = len([n for n in names if n in live])
    return len(names), hit, (float(hit) / len(names) if names else 0.0)


def best_tab(tabs, live, wanted=None):
    """The tab to use: the wanted one when it has names, else the one sharing most names with the model."""
    with_names = [(t, n) for t, n in tabs if n]
    for t, n in with_names:
        if t == wanted:
            return t
    if not with_names:
        return None
    return sorted(with_names, key=lambda tn: -check_register(tn[1], live)[1])[0][0]


# ------------------------------------------------------------------ step 01
def step01(links, rules, building):
    required = [(d.upper(), f) for d, f in rules["required_disciplines"]]
    broad = set(c.upper() for c in rules["broad_scope_codes"])
    expected = dict((k.upper(), v) for k, v in (rules.get("expected_missing") or {}).items())
    disc_set = set(d for d, _ in required)
    ok, wrong, missing, others = [], [], [], 0
    for disc, folder in required:
        own = [l for l in links if parse(l["name"], rules) == (building, disc)]
        if own:
            ok.extend((disc, l) for l in own)
        else:
            missing.append({"disc": disc, "folder": folder, "expected": expected.get(disc)})
    for l in links:
        b, d = parse(l["name"], rules)
        if d not in disc_set:
            others += 1
        elif b != building:
            wrong.append({"link": l, "disc": d, "code": b,
                          "kind": "WRONG SCOPE" if b in broad else "OTHER BUILDING"})
    return {"ok": ok, "wrong": wrong, "missing": missing, "others": others}


def link_instructions(missing, rules, building):
    """How to link each MISSING discipline by hand (the Revit API cannot browse ACC)."""
    lines = []
    for m in missing:
        lines.append(u"[%s] Insert > Link Revit > Autodesk Docs > <project> > %s > %s -- pick the %s file only "
                     u"(ProjectC-*-BIM-%s-ZZZ-%s-*.rvt), Positioning: Auto - By Shared Coordinates%s" % (
                         m["disc"], rules["consumed_folder"], m["folder"], building, building, m["disc"],
                         (u"  (expected: %s)" % m["expected"]) if m["expected"] else u""))
    if lines:
        lines.append(u"Then Netbuild > Place Links (or Model Prep > Check) to put each new link on its workset.")
    return lines


# ------------------------------------------------------------------ step 02
def step02(live, register, pairs, counts=None):
    """Worksets to create and to rename. pairs = the ticked (old model name, register name) pairs; counts =
    {register name: elements on it} for a register name that is in the model already (merging into it needs it
    empty)."""
    counts = counts or {}
    seen, reg, dupes = set(), [], []
    for n in register:
        if n in seen:
            dupes.append(n)
        else:
            seen.add(n)
            reg.append(n)
    live_set = set(live)
    matched = [n for n in reg if n in live_set]
    missing = [n for n in reg if n not in live_set]
    extra = [n for n in sorted(live_set) if n not in seen]
    renames, problems, used = [], [], set()
    for old, new in pairs:
        if old not in live_set or old in seen:
            problems.append(u"'%s' is not an extra model workset -- pair skipped" % old)
        elif new not in seen:
            problems.append(u"'%s' is not in the register -- pair skipped" % new)
        elif old in used or new in used:
            problems.append(u"'%s' -> '%s': a name is in two pairs -- pair skipped" % (old, new))
        elif new in live_set and counts.get(new, 1) != 0:
            problems.append(u"'%s' and '%s' both hold elements -- merge them by hand (pair skipped)" % (old, new))
        else:
            used.update([old, new])
            renames.append({"old": old, "new": new, "delete_new": new in live_set})
    targets = set(r["new"] for r in renames)
    create = [n for n in missing if n not in targets]
    final = (live_set - set(r["old"] for r in renames)) | targets | set(create)
    return {"matched": matched, "missing": missing, "extra": extra, "create": create, "renames": renames,
            "problems": problems, "dupes": dupes, "final": final}


# ------------------------------------------------------------------ step 03
def target_for(name, rules, host_info, final):
    """(target workset, rule, question) for one link: target None + a question when there is no confident rule."""
    building, disc = parse(name, rules)
    overrides = rules.get("manual_overrides") or {}
    target = rule = None
    tier = re.match(rules.get("tower_tier_pattern") or "$^", name or "", re.IGNORECASE)
    if name in overrides:
        target, rule = overrides[name], "exact file name rule"
    elif building is None:
        return None, None, {"why": "file name does not follow the naming rule", "suggest": None}
    elif (disc == "AR" and building == host_info["building"] and host_info.get("disc") != "AR"
          and rules.get("own_ar_in_non_ar_host")):
        target, rule = rules["own_ar_in_non_ar_host"], "the building's own AR model in a %s host" % (
            host_info.get("disc") or "non-AR")
    elif tier:
        target, rule = rules["tower_tier_workset"].format(tier=tier.group(1)), "Tower Tier T%s model" % tier.group(1)
    elif disc in (rules.get("discipline_worksets") or {}):
        target, rule = rules["discipline_worksets"][disc], "discipline %s" % disc
    elif building in (rules.get("building_worksets") or {}):
        target, rule = rules["building_worksets"][building], "building code %s" % building
    elif disc == "AR" and building != host_info["building"]:
        return None, None, {"why": "cross-building AR link: %s's model inside %s -- confirm the workset" % (
            building, host_info["building"] or "this model"), "suggest": rules.get("cross_building_ar_suggestion")}
    else:
        return None, None, {"why": "no rule for building %s / discipline %s" % (building, disc), "suggest": None}
    if target not in final:
        return None, None, {"why": "rule '%s' gives '%s', which is not in the model and not created by Step 02" % (
            rule, target), "suggest": None}
    return target, rule, None


def step03(links, rules, host_info, ws_names, final, answers=None, skip_ids=()):
    """One row per link. ws_names = {workset id: name after Step 02}; answers = {link name: workset or ""}."""
    answers = answers or {}
    rows = []
    for l in links:
        if l["id"] in skip_ids:
            continue
        name = l["name"]
        cur = ws_names.get(l["ws"], "?")
        inst = [ws_names.get(i["ws"], "?") for i in l["instances"]]
        row = {"link": l, "name": name, "type_ws": cur, "inst_ws": inst, "target": None, "rule": None,
               "question": None, "moves": 0, "borrowed": []}
        if name in answers:
            if answers[name]:
                row["target"], row["rule"] = answers[name], "your answer"
            else:
                row["status"] = "LEAVE"
                rows.append(row)
                continue
        else:
            row["target"], row["rule"], row["question"] = target_for(name, rules, host_info, final)
        if row["target"] is None:
            row["status"] = "ASK"
            rows.append(row)
            continue
        t = row["target"]
        movers = ([l] if cur != t else []) + [i for i, n in zip(l["instances"], inst) if n != t]
        row["moves"] = len(movers)
        row["borrowed"] = sorted(set(m["owner"] for m in movers if m.get("owner")))
        row["status"] = "OK" if not movers else ("BORROWED" if row["borrowed"] else "MOVE")
        rows.append(row)
    return rows


# ------------------------------------------------------------------ the plan
def default_decisions():
    return {"steps": set(STEPS), "remove_ids": None, "pairs": [], "answers": {}}


def make_plan(snap, rules, building, register, decisions=None, counts=None, host_disc=None):
    """Everything the three steps would do, as data. decisions: steps (set of 1..3), remove_ids (None = every
    WRONG SCOPE link), pairs [(old, new)], answers {link name: workset or ""}."""
    d = default_decisions()
    d.update(decisions or {})
    steps = set(d["steps"])
    detected = host(snap["title"], rules)
    hinfo = {"building": building, "disc": host_disc if host_disc is not None else detected["disc"]}
    live = [w["name"] for w in snap["worksets"]]

    s1 = step01(snap["links"], rules, building) if 1 in steps else None
    remove = []
    if s1:
        ids = d["remove_ids"]
        remove = [w for w in s1["wrong"] if (w["kind"] == "WRONG SCOPE" if ids is None else w["link"]["id"] in ids)]
    s2 = step02(live, register, d["pairs"] if 2 in steps else [], counts) if register is not None else None
    if 2 in steps and s2:
        final = s2["final"]
        renamed = dict((r["old"], r["new"]) for r in s2["renames"])
    else:
        final, renamed = set(live), {}
    ws_names = dict((w["id"], renamed.get(w["name"], w["name"])) for w in snap["worksets"])
    skip = set(w["link"]["id"] for w in remove)
    s3 = step03(snap["links"], rules, hinfo, ws_names, final, d["answers"], skip) if 3 in steps else None
    suggest = suggest_pairs(live, register) if (2 in steps and register) else []
    return {"title": snap["title"], "building": building, "host": hinfo, "detected": detected, "steps": steps,
            "step01": s1, "remove": remove, "step02": s2 if 2 in steps else None, "register": s2,
            "step03": s3, "suggest": suggest, "final": sorted(final), "decisions": d}


def actions(plan):
    """What Apply would change: links removed, worksets created / renamed, link placements set."""
    s2, s3 = plan["step02"], plan["step03"] or []
    return {"remove": len(plan["remove"]),
            "create": len(s2["create"]) if s2 else 0,
            "rename": len(s2["renames"]) if s2 else 0,
            "move": sum(r["moves"] for r in s3 if r["status"] == "MOVE")}


def questions(plan):
    """Things only the user can decide: near-duplicate pairs (unticked), links without a rule."""
    s3 = plan["step03"] or []
    return [r for r in s3 if r["status"] == "ASK"]


def preflight(plan, rules):
    """Checks that must pass before Apply: [(level, text)]."""
    out = []
    b, det = plan["building"], plan["detected"]
    if not b or not re.match(r"^[A-Z0-9]+$", b):
        out.append((FAIL, u"Host building code is empty or not a code (e.g. B001)"))
    elif det["building"] and det["building"] != b:
        out.append((WARN, u"The open model looks like %s (%s) -- you set the host building to %s" % (
            det["building"], plan["title"], b)))
    elif not det["building"]:
        out.append((WARN, u"Could not read a building code from the model name -- host building %s as typed" % b))
    else:
        out.append((OK, u"Open model is %s -- %s host (%s)" % (b, det["disc"] or "?", plan["title"])))
    s2 = plan["register"]
    if 2 in plan["steps"] and s2 is None:
        out.append((FAIL, u"No workset register list -- pick the register file and tab"))
    for e in rules.get("_errors") or []:
        out.append((WARN, u"Rules: %s" % e))
    return out


def report(plan, rules, register_info=None):
    """The full dry-run report as [(level, text)]; register_info = (source text, level)."""
    out = [(HEAD, u"Model Prep -- %s -- host building %s" % (plan["title"], plan["building"] or "?"))]
    out += preflight(plan, rules)
    b = plan["building"]

    s1 = plan["step01"]
    if s1 is not None:
        out.append((HEAD, u"STEP 01 -- discipline links (%s-specific only; never adds a link)" % b))
        out.append((INFO, u"OK %d  |  WRONG SCOPE %d  |  OTHER BUILDING %d  |  MISSING %d  |  other links left "
                          u"alone %d" % (len(s1["ok"]), len([w for w in s1["wrong"] if w["kind"] == "WRONG SCOPE"]),
                                         len([w for w in s1["wrong"] if w["kind"] == "OTHER BUILDING"]),
                                         len(s1["missing"]), s1["others"])))
        for disc, l in s1["ok"]:
            out.append((OK, u"[%s] %s" % (disc, l["name"])))
        removing = set(w["link"]["id"] for w in plan["remove"])
        for w in s1["wrong"]:
            act = u"-> REMOVE on Apply" if w["link"]["id"] in removing else u"-> kept (not ticked)"
            out.append((FAIL if w["kind"] == "WRONG SCOPE" else WARN, u"%s [%s] %s -- a %s file, not %s's own  %s" % (
                w["kind"], w["disc"], w["link"]["name"], w["code"], b, act)))
        for m in s1["missing"]:
            out.append((INFO if m["expected"] else WARN, u"MISSING [%s] link by hand from Consumed > %s%s" % (
                m["disc"], m["folder"], (u"  (expected: %s)" % m["expected"]) if m["expected"] else u"")))

    s2 = plan["step02"]
    if 2 in plan["steps"]:
        out.append((HEAD, u"STEP 02 -- worksets vs the register (none deleted)"))
        if register_info:
            out.append((register_info[1], register_info[0]))
        if s2 is not None:
            out.append((INFO, u"Register %d  |  matched %d  |  missing %d (will create %d)  |  extra %d" % (
                len(s2["matched"]) + len(s2["missing"]), len(s2["matched"]), len(s2["missing"]),
                len(s2["create"]), len(s2["extra"]))))
            for n in s2["create"]:
                out.append((INFO, u"CREATE '%s'" % n))
            for r in s2["renames"]:
                out.append((INFO, u"RENAME '%s' -> '%s' (register name wins; elements stay on it)%s" % (
                    r["old"], r["new"], u" -- the empty register workset is merged in" if r["delete_new"] else u"")))
            renamed = set(r["old"] for r in s2["renames"])
            alike = dict((p["old"], p) for p in plan["suggest"])
            for n in s2["extra"]:
                if n in renamed:
                    continue
                if n in alike:
                    out.append((WARN, u"LOOKS ALIKE '%s' ~ register '%s'%s -- same workset? Tick the pair in "
                                      u"Decisions... to rename it (register name wins); left alone until then" % (
                                          n, alike[n]["new"], u" (both in the model)" if alike[n]["both"] else u"")))
                else:
                    out.append((INFO, u"EXTRA '%s' -- in the model, not in the register: left alone" % n))
            for p in s2["problems"]:
                out.append((WARN, p))
            for n in s2["dupes"]:
                out.append((WARN, u"'%s' is in the register twice" % n))

    s3 = plan["step03"]
    if s3 is not None:
        out.append((HEAD, u"STEP 03 -- link type + instance worksets"))
        n_ok = len([r for r in s3 if r["status"] == "OK"])
        out.append((INFO, u"%d links: %d already placed, %d to move, %d to decide" % (
            len(s3), n_ok, len([r for r in s3 if r["status"] in ("MOVE", "BORROWED")]),
            len([r for r in s3 if r["status"] == "ASK"]))))
        for r in s3:
            on = where(r)
            if r["status"] == "OK":
                out.append((OK, u"%s on '%s' (%s)" % (r["name"], r["target"], r["rule"])))
            elif r["status"] == "MOVE":
                out.append((INFO, u"MOVE %s: %s -> '%s' (%s)" % (r["name"], on, r["target"], r["rule"])))
            elif r["status"] == "BORROWED":
                out.append((FAIL, u"BORROWED %s: %s -> '%s' -- owned by %s; ask them to synchronize" % (
                    r["name"], on, r["target"], ", ".join(r["borrowed"]))))
            elif r["status"] == "LEAVE":
                out.append((INFO, u"LEFT AS IS %s on %s (your answer)" % (r["name"], on)))
            else:
                out.append((WARN, u"ASK %s on %s -- %s%s" % (r["name"], on, r["question"]["why"], (
                    u"; suggested '%s'" % r["question"]["suggest"]) if r["question"]["suggest"] else u"")))
    a = actions(plan)
    out.append((HEAD, u"Apply would: remove %d link(s), create %d workset(s), rename %d, set %d link placement(s)" % (
        a["remove"], a["create"], a["rename"], a["move"])))
    return out


def q(name):
    """A workset name in quotes, so a trailing space shows."""
    return u"'%s'" % name


def where(row):
    inst = sorted(set(row["inst_ws"]))
    if not inst:
        return u"type '%s' (no instance)" % row["type_ws"]
    if inst == [row["type_ws"]]:
        return u"'%s'" % row["type_ws"]
    return u"type '%s' / instances %s" % (row["type_ws"], ", ".join(q(i) for i in inst))


# ------------------------------------------------------------------ after Apply
def verify(plan, snap):
    """Read the model back after Apply: [(level, text)] -- links removed, worksets there, type == instance ==
    target for every link that was moved."""
    out = []
    ids = set(l["id"] for l in snap["links"])
    names = set(w["name"] for w in snap["worksets"])
    by_id = dict((w["id"], w["name"]) for w in snap["worksets"])
    left = [w["link"]["name"] for w in plan["remove"] if w["link"]["id"] in ids]
    if plan["remove"]:
        out.append((FAIL, u"Still linked: " + ", ".join(left)) if left else
                   (OK, u"Removed %d wrong-scope link(s)" % len(plan["remove"])))
    s2 = plan["step02"]
    if s2:
        want = list(s2["create"]) + [r["new"] for r in s2["renames"]]
        gone = [n for n in want if n not in names]
        if want:
            out.append((FAIL, u"Worksets not there: " + ", ".join(q(n) for n in gone)) if gone else
                       (OK, u"Worksets created %d, renamed %d -- every register workset is in the model" % (
                           len(s2["create"]), len(s2["renames"]))))
        still = [r["old"] for r in s2["renames"] if r["old"] in names]
        if still:
            out.append((FAIL, u"Old spellings still there: " + ", ".join(q(n) for n in still)))
    moved = [r for r in (plan["step03"] or []) if r["status"] == "MOVE"]
    bad = []
    links = dict((l["id"], l) for l in snap["links"])
    for r in moved:
        l = links.get(r["link"]["id"])
        if l is None:
            bad.append(u"%s (not found)" % r["name"])
            continue
        placed = [by_id.get(l["ws"])] + [by_id.get(i["ws"]) for i in l["instances"]]
        if [p for p in placed if p != r["target"]]:
            bad.append(u"%s (%s)" % (r["name"], ", ".join(q(p) for p in placed)))
    if moved:
        out.append((FAIL, u"Not on their workset: " + "; ".join(bad)) if bad else
                   (OK, u"%d link(s): type and every instance on the target workset" % len(moved)))
    if not out:
        out.append((OK, u"Nothing needed changing"))
    return out

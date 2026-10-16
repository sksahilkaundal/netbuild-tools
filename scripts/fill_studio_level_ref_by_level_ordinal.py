# -*- coding: UTF-8 -*-
"""
fill_studio_level_ref_by_level_ordinal.py

For the Revit MCP `execute_revit_code` tool (uses the pre-supplied `doc`;
no extra imports needed beyond Autodesk.Revit.DB and `re`).

Fills blank "Studio-Level Ref." on placed Area elements, deriving the value
from the area's own Constraints > Level ordinal number - NOT by copying
whatever value happens to be most common on that Level (that was tried
first and rejected: many Levels carry noisy/inconsistent legacy tags,
e.g. "51st Floor" areas mostly tagged '53', "76th Floor" mostly '75' -
majority-vote would have propagated that drift).

Rule (edit SPECIAL_CASE_OVERRIDES / ORDINAL / BASEMENT logic below for a
different building's level-naming convention):
  - "<N><st|nd|rd|th> Floor"  -> zero-padded 2-digit code, e.g.
    "21st Floor" -> "21", "02nd Floor" -> "02".
  - "Basement 0N"             -> "Basement N" (matches this model's
    existing "Basement 1" style tag, confirmed live - basements do NOT
    use the bare numeric-code convention the floor levels use).
  - Range-named levels (e.g. "27th to 36th Floor", one Level element
    covering multiple physical floors) have no single ordinal to parse -
    add an explicit entry to SPECIAL_CASE_OVERRIDES per user confirmation
    (here: "27th to 36th Floor" -> "27", the level's starting floor,
    confirmed by user 2026-09-11).
  - Any Level name matching none of the above is left untouched and
    reported as unresolved - never guessed.

Only areas with a currently BLANK "Studio-Level Ref." are touched; areas
that already carry any value (including a "wrong"-looking legacy one)
are left completely alone.

Verified live 2026-09-11 against ProjectC-Studio-BIM-SW00-ZZZ-AR-970002:
309 blank areas across 28 Levels, all resolved (0 unresolved), applied
and post-commit verified (0 still blank).

Gotcha: always check the actual t.Commit() return value string and
re-verify post-commit by re-querying the model - a transaction can
silently RollBack if a tool call is interrupted mid-run.
"""

import re

PARAM = "Studio-Level Ref."
ORDINAL = re.compile(r"^(\d+)(st|nd|rd|th)\s+Floor$")

# Level names that don't fit the ordinal/basement rules - fill in per
# building/model after reviewing dry_run()'s "unresolved" list.
SPECIAL_CASE_OVERRIDES = {
    "27th to 36th Floor": "27",
}


def target_code(level_name):
    if level_name in SPECIAL_CASE_OVERRIDES:
        return SPECIAL_CASE_OVERRIDES[level_name]
    m = ORDINAL.match(level_name)
    if m:
        return "%02d" % int(m.group(1))
    if level_name.startswith("Basement"):
        num = re.search(r"\d+", level_name)
        return "Basement %d" % int(num.group()) if num else None
    return None


def _blank_targets():
    """Returns (targets, unresolved) where targets is a list of
    (area, level_name, code) and unresolved is a list of
    (area_id, level_name) for blanks whose Level name matched no rule."""
    areas = DB.FilteredElementCollector(doc).OfCategory(
        DB.BuiltInCategory.OST_Areas
    ).WhereElementIsNotElementType().ToElements()
    areas = [a for a in areas if a.Area > 0]

    targets, unresolved = [], []
    for a in areas:
        lp = a.LookupParameter("Level")
        lvl = lp.AsValueString() if lp else "N/A"
        rp = a.LookupParameter(PARAM)
        rv = rp.AsString() if rp else None
        if rv and rv.strip():
            continue
        code = target_code(lvl)
        if code is None:
            unresolved.append((a.Id, lvl))
        else:
            targets.append((a, lvl, code))
    return targets, unresolved


def dry_run():
    targets, unresolved = _blank_targets()

    by_level_count = {}
    for _, lvl, code in targets:
        key = (lvl, code)
        by_level_count[key] = by_level_count.get(key, 0) + 1

    print("=== DRY RUN: fill blank %r by Level ordinal (no changes made) ===" % PARAM)
    for (lvl, code), cnt in sorted(by_level_count.items()):
        print("  %s -> %r : %d area(s)" % (lvl, code, cnt))
    print()
    print("Total areas to be updated:", len(targets))
    print("Unresolved (no rule matched, would be skipped):", unresolved)
    return targets, unresolved


def apply():
    targets, unresolved = _blank_targets()
    print("Applying to %d areas (unresolved/skipped: %d)" % (len(targets), len(unresolved)))

    t = DB.Transaction(doc, "Fill blank %s by Level ordinal" % PARAM)
    t.Start()
    for a, lvl, code in targets:
        rp = a.LookupParameter(PARAM)
        rp.Set(code)
    status = t.Commit()
    print("Transaction status:", str(status))

    # post-commit re-verify - don't trust the print above alone
    still_blank = []
    for a, lvl, code in targets:
        rp = a.LookupParameter(PARAM)
        rv = rp.AsString() if rp else None
        if not rv or not rv.strip():
            still_blank.append(a.Id)
    print("Post-commit: still blank (should be 0):", len(still_blank))


# Example usage per MCP execute_revit_code invocation:
# dry_run()
# apply()

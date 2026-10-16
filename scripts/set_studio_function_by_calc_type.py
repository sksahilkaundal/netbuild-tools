# -*- coding: UTF-8 -*-
"""
set_studio_function_by_calc_type.py

For the Revit MCP `execute_revit_code` tool (uses the pre-supplied `doc`;
no extra imports needed beyond Autodesk.Revit.DB).

**SUPERSEDES** the original 4-step hand-written RULES draft (Voids/
Structure/MEP Rooms/Stairs-Lift Lobby) with a single master-key-driven
pass. The old draft was never applied (per the standing dry-run-only
rule) and is fortunate not to have been: its Step 1 set Voids ->
Function="MEP", but the authoritative master key
(`C:\\Users\\user\\Downloads\\Area Test\\+KEY-Area Typology.xlsx`,
71-row "+KEY-Area Typology" sheet) says Voids -> Function="Shared".
Structure/MEP Rooms/Stairs(Non-GFA)/Lift Lobby(Non-GFA)/Service Lift
Lobby(Non-GFA) happened to match the key exactly, but the key is now
the single source of truth for ALL Area Calc. Types, not just those 4.

KEY below is a direct transcription of that Excel's data rows (Area
Calc. Type -> Studio_Function Code, Studio_Sub-Function Code), captured
2026-09-11. Re-open the Excel and re-transcribe if it's revised.

Rule (same "never clobber existing work" principle as the old script,
but Function and Sub-Function are gated INDEPENDENTLY, no exceptions
this time - even Unaccessible/Voids, whose key Sub-Function is None,
simply have nothing to backfill there):
  - For each placed Area (Area > 0): look up its "Area Calc. Type".
  - If that calc type has a KEY entry with a Function value, AND the
    area's Studio_Function Code is currently BLANK -> set it to the key's
    Function value. Areas with an existing Function value (anything,
    even one that looks "wrong" vs. the key) are left completely alone.
  - Independently: if the calc type's key Sub-Function is not None AND
    the area's Studio_Sub-Function Code is currently BLANK -> set it to
    the key's Sub-Function value. Same never-touch-existing rule.
  - Calc types with NO key entry at all (e.g. "(none)" - blank Area
    Calc. Type; "Pool(Internal)" - not in the key) are left unresolved
    and reported, never guessed.

Live dry-run 2026-09-11 against ProjectC-Studio-BIM-SW00-ZZZ-AR-970002:
801 Function blanks / 231 Sub-Function blanks resolvable across 28
calc types (Voids 526 Function being the largest single group).
"(none)" (2367 areas, blank Area Calc. Type) and "Pool(Internal)"
(1 area) have no key entry and are left unresolved. NOT YET APPLIED -
awaiting explicit per-run authorization (see [[dry-run-only-standing-rule]]).

Gotcha: always check the actual t.Commit() return value string and
re-verify post-commit by re-querying the model - a transaction can
silently RollBack if a tool call is interrupted mid-run.
"""

FUNCTION_PARAM = "Studio_Function Code"
SUBFUNCTION_PARAM = "Studio_Sub-Function Code"

# Transcribed from +KEY-Area Typology.xlsx, "+KEY-Area Typology" sheet,
# columns Area Calc. Type | Studio_Function Code | Studio_Sub-Function Code.
KEY = {
    "All Day Dining": {"func": "Retail", "sub": "F&B"},
    "Balcony": {"func": "Shared", "sub": "Terrace/Balconies"},
    "Ballroom": {"func": "Hotel", "sub": "Ballroom"},
    "Ballroom Prefunction": {"func": "Hotel", "sub": "Ballroom"},
    "BOH": {"func": "Shared", "sub": "Storage"},
    "Changing rooms": {"func": "Shared", "sub": "Services"},
    "Circulation": {"func": "Circulation", "sub": "Circulation"},
    "Circulation (MEP/Service/Parking)": {"func": "Circulation", "sub": "Circulation"},
    "Covered Area (Non Seating)": {"func": "Shared", "sub": "Terrace/Balconies"},
    "Covered Area (Seating)": {"func": "Shared", "sub": "Terrace/Balconies"},
    "Engineering": {"func": "Shared", "sub": "Services"},
    "F&B units": {"func": "Retail", "sub": "F&B"},
    "Fire Command Center": {"func": "MEP", "sub": "MEP Rooms"},
    "Fire Horse Cabinet": {"func": "MEP", "sub": "MEP Rooms"},
    "Function Rooms": {"func": "Shared", "sub": "Meeting Room"},
    "Garbage Room": {"func": "Shared", "sub": "Services"},
    "GYM (support Areas)": {"func": "Shared", "sub": "Gym/Fitness"},
    "GYM Facilities": {"func": "Shared", "sub": "Gym/Fitness"},
    "Hotel - ADA Room": {"func": "Hotel", "sub": "Hotel Guest Rooms"},
    "Hotel - Standard Room": {"func": "Hotel", "sub": "Hotel Guest Rooms"},
    "Hotel - Suites with Pantry": {"func": "Hotel", "sub": "Hotel Guest Rooms"},
    "Hotel - Suites without Pantry": {"func": "Hotel", "sub": "Hotel Guest Rooms"},
    "Housekeeping": {"func": "Shared", "sub": "Storage"},
    "Janitor": {"func": "Shared", "sub": "Services"},
    "Kitchen": {"func": "Retail", "sub": "F&B Kitchen"},
    "Kitchen (Support Areas)": {"func": "Retail", "sub": "Services"},
    "Lift (Considered once)": {"func": "Circulation", "sub": "Circulation"},
    "Lift Lobby": {"func": "Circulation", "sub": "Circulation"},
    "Lift Lobby (Non-GFA)": {"func": "Circulation", "sub": "Circulation"},
    "Lobby": {"func": "Circulation", "sub": "Circulation"},
    "Lounge": {"func": "Hotel", "sub": "Gym/Fitness"},
    "Meeting Room": {"func": "Hotel", "sub": "Meeting Room"},
    "MEP Rooms": {"func": "MEP", "sub": "MEP Rooms"},
    "MEP Tanks": {"func": "MEP", "sub": "MEP Rooms"},
    "Offices (BOH)": {"func": "Office", "sub": "Offices"},
    "Offices (FOH)": {"func": "Office", "sub": "Offices"},
    "Outside Terrace (Non Seating Area)": {"func": "MEP", "sub": "Terrace/Balconies"},
    "Outside Terrace (Seating Area)": {"func": "Shared", "sub": "Terrace/Balconies"},
    "Pantry": {"func": "Shared", "sub": "Services"},
    "Parking": {"func": "Parking", "sub": "Parking"},
    "Pool": {"func": "Pool", "sub": "Pool"},
    "Prayer room": {"func": "Shared", "sub": "Services"},
    "Residential (1 Bed)": {"func": "Residential", "sub": "Residential Units"},
    "Residential (2 Bed)": {"func": "Residential", "sub": "Residential Units"},
    "Residential (3 Bedrooms)": {"func": "Residential", "sub": "Residential Units"},
    "Residential (4+ Bedrooms)": {"func": "Residential", "sub": "Residential Units"},
    "Residential (Penthouse)": {"func": "Residential", "sub": "Residential Units"},
    "Residential (Studio)": {"func": "Residential", "sub": "Residential Units"},
    "Retail Units": {"func": "Retail", "sub": "Retail"},
    "Roof (Seating Area)": {"func": "Shared", "sub": "Terrace/Balconies"},
    "Roof Terrace (Non Siting Area)": {"func": "Shared", "sub": "Terrace/Balconies"},
    "Server Room": {"func": "MEP", "sub": "MEP Rooms"},
    "Service Ap (1 Bedrooms)": {"func": "Hotel", "sub": "Hotel Apartments"},
    "Service Ap.(2 Bedrooms)": {"func": "Hotel", "sub": "Hotel Apartments"},
    "Service Ap.(3 Bedrooms)": {"func": "Hotel", "sub": "Hotel Apartments"},
    "Service Ap.(4+Bedrooms)": {"func": "Hotel", "sub": "Hotel Apartments"},
    "Service Ap.(Penthouse)": {"func": "Hotel", "sub": "Hotel Apartments"},
    "Service Ap.(Studio)": {"func": "Hotel", "sub": "Hotel Apartments"},
    "Service Lift Lobby (Non-GFA)": {"func": "Circulation", "sub": "Circulation"},
    "SPA (Support areas)": {"func": "Hotel", "sub": "SPA"},
    "SPA Facilities": {"func": "Hotel", "sub": "SPA"},
    "Staff Canteen": {"func": "Shared", "sub": "Services"},
    "Stairs (Non-GFA)": {"func": "Circulation", "sub": "Circulation"},
    "Store (Below Ground AC)": {"func": "Shared", "sub": "Storage"},
    "Store (Below Ground Non AC)": {"func": "Shared", "sub": "Storage"},
    "Store (Over Ground)": {"func": "Shared", "sub": "Storage"},
    "Structure": {"func": "Facade Structure", "sub": "Facade Structure"},
    "Toilets": {"func": "Shared", "sub": "Services"},
    "Unaccessible": {"func": "Shared", "sub": None},
    "Voids": {"func": "Shared", "sub": None},
    "Voids (Considered once)": {"func": "Shared", "sub": None},
}


def _placed_areas():
    areas = DB.FilteredElementCollector(doc).OfCategory(
        DB.BuiltInCategory.OST_Areas
    ).WhereElementIsNotElementType().ToElements()
    return [a for a in areas if a.Area > 0]


def _collect_targets():
    """Returns (func_targets, sub_targets, unresolved) where:
    func_targets / sub_targets: list of (area, new_value) - independent,
      an area can appear in one, both, or neither.
    unresolved: dict of calc_type -> count, for calc types with no KEY
      entry at all (including blank "Area Calc. Type" -> "(none)")."""
    func_targets, sub_targets = [], []
    unresolved = {}

    for a in _placed_areas():
        ctp = a.LookupParameter("Area Calc. Type")
        ct = ctp.AsValueString() if ctp else None
        if not ct:
            ct = "(none)"

        entry = KEY.get(ct)
        if entry is None:
            unresolved[ct] = unresolved.get(ct, 0) + 1
            continue

        if entry["func"]:
            fp = a.LookupParameter(FUNCTION_PARAM)
            fv = fp.AsString() if fp else None
            if not fv or not fv.strip():
                func_targets.append((a, entry["func"]))

        if entry["sub"]:
            sp = a.LookupParameter(SUBFUNCTION_PARAM)
            sv = sp.AsString() if sp else None
            if not sv or not sv.strip():
                sub_targets.append((a, entry["sub"]))

    return func_targets, sub_targets, unresolved


def dry_run():
    func_targets, sub_targets, unresolved = _collect_targets()

    by_func = {}
    for a, v in func_targets:
        by_func[v] = by_func.get(v, 0) + 1
    by_sub = {}
    for a, v in sub_targets:
        by_sub[v] = by_sub.get(v, 0) + 1

    print("=== DRY RUN: fill blank Function/Sub-Function from master key (no changes made) ===")
    print("Function blanks fillable:", len(func_targets))
    for k, v in sorted(by_func.items(), key=lambda kv: -kv[1]):
        print("  ", k, ":", v)
    print()
    print("Sub-Function blanks fillable:", len(sub_targets))
    for k, v in sorted(by_sub.items(), key=lambda kv: -kv[1]):
        print("  ", k, ":", v)
    print()
    print("Unresolved (no key entry, left untouched):", sum(unresolved.values()))
    for k, v in sorted(unresolved.items(), key=lambda kv: -kv[1]):
        print("  ", k, ":", v)
    return func_targets, sub_targets, unresolved


def apply():
    func_targets, sub_targets, unresolved = _collect_targets()
    print("Applying: %d Function blanks, %d Sub-Function blanks" % (len(func_targets), len(sub_targets)))

    t = DB.Transaction(doc, "Fill blank Studio_Function/Sub-Function Code from master key")
    t.Start()
    for a, v in func_targets:
        fp = a.LookupParameter(FUNCTION_PARAM)
        fp.Set(v)
    for a, v in sub_targets:
        sp = a.LookupParameter(SUBFUNCTION_PARAM)
        sp.Set(v)
    status = t.Commit()
    print("Transaction status:", str(status))

    # post-commit re-verify - don't trust the print above alone
    verify_func, verify_sub, _ = _collect_targets()
    print("Post-commit: Function blanks STILL fillable (should be 0):", len(verify_func))
    print("Post-commit: Sub-Function blanks STILL fillable (should be 0):", len(verify_sub))


# Example usage per MCP execute_revit_code invocation:
# dry_run()
# apply()

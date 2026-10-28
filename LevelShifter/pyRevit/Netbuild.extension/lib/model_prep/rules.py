"""The project rules Model Prep works by: link naming, required disciplines, the workset register and the link ->
workset map.  IronPython 2.7 + CPython 3.

DEFAULT_RULES are the ProjectA Wadi High Rise rules, settled on the B001-B005 rollout (AR and BM hosts, 2026-09-08).
Each user can keep their own copy in %APPDATA%\\Netbuild\\ModelPrep\\rules.json (Model Prep > Rules...): every key
there replaces the default one, so a new project only changes what differs. Answers given in the window with
"Remember" ticked are added to that file's "manual_overrides".
"""

import io
import json
import os

RULES_NAME = "rules.json"

DEFAULT_RULES = {
    "project": "ProjectA Wadi High Rise",
    # ProjectC-<ORG>-BIM-<BUILDING>-ZZZ-<DISC>-<SEQNO>.rvt -> group 1 = building, group 2 = discipline
    "name_pattern": r"^ProjectC-[A-Z]+-BIM-([A-Z0-9]+)-ZZZ-([A-Z]+)-\d+",

    # ---- Step 01: discipline links, building-specific only
    "required_disciplines": [
        ["ST", "04_ST_STRUCTURE"], ["HV", "05_ME_MECHANICAL-HVAC"], ["PL", "06_PL_PLUMBING"],
        ["FF", "07_FF_FIRE FIGHTING"], ["EL", "09_EL_ELECTRICAL"], ["ID", "02_ID_INTERIORS"],
        ["LA", "03_LA_LANDSCAPE"], ["WS", "08_WS_WAYFINDING & SIGNAGE"], ["TC", "10_TC_TELECOMMUNICATION"],
        ["AV", "19_AV_Audio Visual"],
    ],
    "consumed_folder": "A.WIP > 01.Architecture > Consumed",
    # Tower-wide / site-wide / podium / basement files: never a substitute for the building's own model
    "broad_scope_codes": ["T00O", "SW00", "PO00", "BA00"],
    # disciplines with no building-specific model upstream yet (B001-B005): MISSING is expected
    "expected_missing": {"ID": "no building-specific Interiors model exists yet",
                         "TC": "no building-specific Telecommunication model exists yet"},

    # ---- Step 02: the workset register
    "register_path": r"C:\SK\Projects\ProjectA\Excel\3470 ProjectA Wadi High Rise - Worksets.xlsx",
    "register_sheet": "Sheet Model ",              # trailing space is part of the tab name
    "register_column": "A",
    "register_skip_rows": 0,                       # no header
    # used when the register cannot be read (the 'Sheet Model ' list as of 2026-10-02, exact spelling)
    "worksets": [
        "Studio_AR-00 Link-AV", "Studio_AR-00 Link-Basement", "Studio_AR-00 Link-CAD Host model",
        "Studio_AR-00 Link-Core", "Studio_AR-00 Link-ELE", "Studio_AR-00 Link-Facade",
        "Studio_AR-00 Link-INT", "Studio_AR-00 Link-FF", "Studio_AR-00 Link-LAN",
        "Studio_AR-00 Link-Levels ", "Studio_AR-00 Link-LGT", "Studio_AR-00 Link-MEC",
        "Studio_AR-00 Link-PLB", "Studio_AR-00 Link-Podium Buildings", "Studio_AR-00 Link-STR",
        "Studio_AR-00 Link-TC", "Studio_AR-00 Link-WS", "Studio_AR-00 Link-Tower (PO)",
        "Studio_AR-00 Link-Tower (T1)", "Studio_AR-00 Link-Tower (T2)", "Studio_AR-00 Link-Tower (T3)",
        "Studio_AR-00 Link-Tower (T4)", "Studio_AR-00 Link-Tower (T5)", "Studio_AR-01 Datum Grids (BA)",
        "Studio_AR-01 Datum Grids (PO)", "Studio_AR-01 Datum Grids (TO)",
        "Studio_AR-01 Datum Part Plan Scope Box", "Studio_AR-01 Datum Levels",
        "Studio_AR-01 Datum Ref. Planes", "Studio_AR-Ceiling ", "Studio_AR-Ceiling Fixtures",
        "Studio_AR-Doors (BOH)", "Studio_AR-Doors (FOH)", "Studio_AR-Entourage", "Studio_AR-Facade ",
        "Studio_AR-Facade Cladding", "Studio_AR-Facade Fins", "Studio_AR-Facade Glazing",
        "Studio_AR-Facade Screens", "Studio_AR-Fixtures", "Studio_AR-Floors (BOH)",
        "Studio_AR-Floors (FOH)", "Studio_AR-Furniture ", "Studio_AR-Lifts", "Studio_AR-Parking",
        "Studio_AR-Plot Boundary", "Studio_AR-Railings", "Studio_AR-Ramps",
        "Studio_AR-Room Separation Lines", "Studio_AR-Rooms ", "Studio_AR-Shafts", "Studio_AR-Stairs",
        "Studio_AR-STR Placeholder", "Studio_AR-Walls ", "Studio_AR-Windows", "Studio_AR-Walls Fixtures",
    ],
    # below this share of register names already in the model, the tab is flagged as possibly the wrong one
    "register_min_match": 0.5,

    # ---- Step 03: link -> workset (checked in this order)
    # 1. exact file names
    "manual_overrides": {
        "ProjectC-Studio-BIM-SW00-ZZZ-BM-925001.rvt": "Studio_AR-00 Link-Levels ",
    },
    # 2. a non-AR host (e.g. the BM model) linking its own building's AR model
    "own_ar_in_non_ar_host": "Studio_AR-00 Link-Podium Buildings",
    # 3. Tower Tier models: ...-TO-ZZZ-AR-90000X.rvt (code literally TO) -> Link-Tower (TX)
    "tower_tier_pattern": r"^ProjectC-[A-Z]+-BIM-TO-ZZZ-AR-\d{5}(\d)",
    "tower_tier_workset": "Studio_AR-00 Link-Tower (T{tier})",
    # 4. discipline code
    "discipline_worksets": {
        "ST": "Studio_AR-00 Link-STR", "EL": "Studio_AR-00 Link-ELE", "FF": "Studio_AR-00 Link-FF",
        "PL": "Studio_AR-00 Link-PLB", "HV": "Studio_AR-00 Link-MEC", "WS": "Studio_AR-00 Link-WS",
        "AV": "Studio_AR-00 Link-AV", "ID": "Studio_AR-00 Link-INT", "LA": "Studio_AR-00 Link-LAN",
        "TC": "Studio_AR-00 Link-TC", "LGT": "Studio_AR-00 Link-LGT",
    },
    # 5. building code (context links)
    "building_worksets": {
        "BA00": "Studio_AR-00 Link-Basement",
        "T00O": "Studio_AR-00 Link-Core",
        "PO00": "Studio_AR-00 Link-Tower (PO)",
    },
    # never applied on its own: offered first when one building's AR model is linked into another building
    "cross_building_ar_suggestion": "Studio_AR-00 Link-Podium Buildings",
}


def user_dir(env=None):
    env = os.environ if env is None else env
    return os.path.join(env.get("APPDATA") or os.path.expanduser("~"), "Netbuild", "ModelPrep")


def user_path(env=None):
    return os.path.join(user_dir(env), RULES_NAME)


def _read(path):
    try:
        with io.open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def load(env=None):
    """The default rules with the user's rules file laid over them, plus "_errors" (unreadable / unknown keys)."""
    rules = json.loads(json.dumps(DEFAULT_RULES))          # deep copy
    path = user_path(env)
    errors = []
    if os.path.isfile(path):
        mine = _read(path)
        if not mine:
            errors.append("%s could not be read (not a JSON object) -- the default rules are used" % path)
        for key, value in mine.items():
            if key.startswith("_"):
                continue
            if key not in DEFAULT_RULES:
                errors.append("unknown key in %s: %s" % (RULES_NAME, key))
                continue
            rules[key] = value
    rules["_errors"] = errors
    rules["_path"] = path
    return rules


def save(rules, env=None):
    """Write the rules (without the "_" keys) to the user's rules file. Returns its path."""
    path = user_path(env)
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    data = dict((k, v) for k, v in rules.items() if not k.startswith("_"))
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(u"%s\n" % text)
    return path


def ensure_user_file(env=None):
    """The user's rules file, written from the current rules when there is none yet (for Rules... to open)."""
    path = user_path(env)
    if not os.path.isfile(path):
        save(load(env), env)
    return path


def remember(answers, env=None):
    """Add {link file name: workset} answers to the user's manual_overrides. Returns the rules file path."""
    mine = _read(user_path(env))                           # only the user's own keys, plus the overrides
    overrides = dict(load(env).get("manual_overrides") or {})
    overrides.update(answers)
    mine["manual_overrides"] = overrides
    return save(mine, env)

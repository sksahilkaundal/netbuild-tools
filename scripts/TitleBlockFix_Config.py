# -*- coding: utf-8 -*-
"""
Project profiles for Title Block Fix.

Everything project-specific lives in a JSON profile so the tool works on
any project without editing code or rebuilding the .exe. Profiles sit in a
"profiles" folder next to the launcher (or next to the .exe when frozen);
the bundled ProjectA profile is written there on first run as a worked example.

Profile shape:

{
  "name": "ProjectA",
  "folders":  {"pdf": "2_PDF", "dwg": "1_DWG", "output": "Updated"},
  "filename": {"separator": "-", "zone_index": 3, "level_index": 4, "dwgno_index": 6},
  "skip_zones": ["B001", "B002"],
  "revision_descriptions": {"50% schematic design": "50% SCHEMATIC DESIGN SUBMISSION"},
  "model_ref": {
      "label": "Model Ref Number",
      "rules": [ {"zone": [...], "level": "ZZZ"|"LEVEL", "dwgno_prefix": "7500",
                  "value": "..."} ]
  }
}

model_ref.rules are tried IN ORDER and the first match wins, so put the
most specific first. A key that is absent is not tested:
  zone          - list of zone tokens this rule applies to
  level         - "ZZZ" (the level token is literally ZZZ, i.e. no level)
                  or "LEVEL" (any real level token)
  dwgno_prefix  - drawing number starts with this

Filename parsing assumes <A>-<B>-<C>-<ZONE>-<LEVEL>-<D>-<DWGNO>_<REV>.ext
by default; point the *_index values at whichever positions your project
uses, counting from 0 after splitting on `separator`.
"""
import json
import os

DEFAULT_PROFILE = {
    "name": "ProjectA",
    "folders": {"pdf": "2_PDF", "dwg": "1_DWG", "output": "Updated",
                "plot": "PDF_from_CAD"},
    "filename": {"separator": "-", "zone_index": 3, "level_index": 4, "dwgno_index": 6},
    "skip_zones": ["B001", "B002", "B003", "B004", "B005"],
    "revision_descriptions": {
        "50% schematic design": "50% SCHEMATIC DESIGN SUBMISSION",
        "100% schematic design": "100% SCHEMATIC DESIGN SUBMISSION",
    },
    "model_ref": {
        "label": "Model Ref Number",
        "rules": [
            {"zone": ["SW00"], "level": "ZZZ", "dwgno_prefix": "7500",
             "value": "ProjectC-Studio-BIM-SW00-ZZZ-AR-970002"},
            {"zone": ["SW00", "B2B5"],
             "value": "ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001"},
            {"zone": ["T00O", "TO00"], "level": "ZZZ",
             "value": "ProjectC-Studio-BIM-T00O-ZZZ-BM-950002"},
            {"zone": ["T00O", "TO00"], "level": "LEVEL",
             "value": "ProjectC-Studio-BIM-T00O-ZZZ-BM-950001"},
        ],
    },
}

_active = dict(DEFAULT_PROFILE)


def profiles_dir(base):
    return os.path.join(base, "profiles")


def ensure_profiles(base):
    """Create the profiles folder and drop the example profile in it."""
    d = profiles_dir(base)
    os.makedirs(d, exist_ok=True)
    example = os.path.join(d, "ProjectA.json")
    if not os.path.exists(example):
        with open(example, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PROFILE, f, indent=2)
    return d


def list_profiles(base):
    d = profiles_dir(base)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d)
                  if f.lower().endswith(".json"))


def load(base, name):
    with open(os.path.join(profiles_dir(base), name + ".json"), encoding="utf-8") as f:
        prof = json.load(f)
    missing = [k for k in ("folders", "filename", "model_ref") if k not in prof]
    if missing:
        raise ValueError("profile %r is missing: %s" % (name, ", ".join(missing)))
    return prof


def set_active(profile):
    global _active
    _active = profile


def active():
    return _active


# ------------------------------------------------------------------ lookups
def parse_name(filename):
    """-> (zone, level, dwgno) using the active profile's convention."""
    f = _active["filename"]
    parts = os.path.splitext(os.path.basename(filename))[0].split(f["separator"])
    need = max(f["zone_index"], f["level_index"], f["dwgno_index"])
    if len(parts) <= need:
        return None, None, None
    return (parts[f["zone_index"]],
            parts[f["level_index"]],
            parts[f["dwgno_index"]].split("_")[0])


def model_ref_for_filename(filename):
    """-> (value, skip_reason). value is None when nothing should be written."""
    zone, level, dwgno = parse_name(filename)
    if zone is None:
        return None, "unparseable filename"
    if zone in _active.get("skip_zones", []):
        return None, "skip (already corrected)"
    for rule in _active["model_ref"]["rules"]:
        if "zone" in rule and zone not in rule["zone"]:
            continue
        if rule.get("level") == "ZZZ" and level != "ZZZ":
            continue
        if rule.get("level") == "LEVEL" and level == "ZZZ":
            continue
        if "dwgno_prefix" in rule and not (dwgno or "").startswith(rule["dwgno_prefix"]):
            continue
        return rule["value"], None
    return None, "no model-ref rule matches zone %r" % zone


def revision_descriptions():
    return _active.get("revision_descriptions", {})


def model_ref_label():
    return _active["model_ref"].get("label", "Model Ref Number")


# Folders a profile may omit. Older profiles predate "plot", and a profile
# written by hand need not spell out the obvious ones -- fall back rather
# than making an existing profile invalid.
_FOLDER_DEFAULTS = {"output": "Updated", "plot": "PDF_from_CAD"}


def folder(kind):
    f = _active["folders"]
    if kind in f:
        return f[kind]
    if kind in _FOLDER_DEFAULTS:
        return _FOLDER_DEFAULTS[kind]
    raise KeyError("profile has no %r folder" % kind)

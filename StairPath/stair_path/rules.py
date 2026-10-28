"""The office standard for Stair Path annotations, as plain data -> plain data (no Revit API).

engine.py reads the model into the shapes below, asks these functions what to place, and places it.
IronPython 2.7 + CPython 3.

Shapes (lengths in feet, like the Revit API):
  level  {"id", "name", "elev"}
  stair  {"id", "base", "top"            -- level names from the Base / Top Level parameters (or None)
          "base_elev", "top_elev"        -- level elevation + base / top offset (None when unknown)
          "box": (minx, miny, maxx, maxy), "run": (dx, dy) of the first flight (BaseElevation 0)}
  view   {"id", "name", "scale", "level", "crop": (minx, miny, maxx, maxy) or None, "visible": [stair ids]}
  type   {"id", "family", "name"}
"""

import re

MM_PER_FT = 304.8
FIXED = "Fixed Up Direction"
AUTO = "Automatic Up/Down Direction"
SCALES = (500, 200, 100)
TEXT_SCALES = (200, 100)            # 1:500 shows arrows only

# Every setting of a run; the button keeps one set per model (distances are tuned per building).
DEFAULTS = {
    "views": "open",                # open | name -- the open plan views, or every plan view whose name contains:
    "name_filter": "GA Plan",
    "clear": "views",               # views | model -- existing stair paths cleared in the target views / whole model
    "directional": True,            # text placed away from the way each stair's first flight runs
    "dir_x_mm": 300.0,              # length > width, run toward +X: text this far on the -X side
    "dir_y_mm": 300.0,              # width > length: text this far against the run (-Y for a +Y run, +Y for -Y)
    "std_x_200": 600.0,             # standard offsets (the -X run of an X stair, and no-direction cases)
    "std_y_200": 200.0,
    "std_x_100": 400.0,
    "std_y_100": 200.0,
    "sweep": True,                  # tag every other visible stair: Automatic Up/Down, both texts
    "room_tags": True,              # nudge room tags off the stair paths; Staircase tags back inside their room
    "tag_nudge_mm": 300.0,
    "tag_pad_mm": 400.0,
    "staircase_keyword": "stair",
    "check_dimensions": True,       # report stair paths that overlap a dimension string (nothing is moved)
    "create_types": False,          # duplicate each family's "Standard" type into a missing "Standard 1-xxx"
    "core_tol_mm": 1500.0,          # flights whose plan centres are this close (or plans overlap) share a core
    "level_tol_mm": 300.0,          # a flight's base / top snaps to the level within this distance
}

# columns of the annotation list (CSV) the button and the command line write
CSV_FIELDS = ["view", "scale", "level", "core", "kind", "stair", "result", "path", "offset_mm", "why"]

NUMBERS = ("dir_x_mm", "dir_y_mm", "std_x_200", "std_y_200", "std_x_100", "std_y_100", "tag_nudge_mm",
           "tag_pad_mm", "core_tol_mm", "level_tol_mm")


class Check(object):
    def __init__(self, label, ok, detail=""):
        self.label, self.ok, self.detail = label, ok, detail

    @property
    def mark(self):
        return "OK  " if self.ok is True else ("WARN" if self.ok is None else "FAIL")

    def __str__(self):
        return "[%s] %s%s" % (self.mark, self.label, (" -- " + self.detail) if self.detail else "")


def settings(values=None):
    """DEFAULTS updated with ``values`` (strings from the window or the config are converted; bad ones dropped)."""
    s = dict(DEFAULTS)
    for key, v in (values or {}).items():
        if key not in DEFAULTS or v is None:
            continue
        default = DEFAULTS[key]
        try:
            if isinstance(default, bool):
                s[key] = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(default, float):
                s[key] = float(v)
            else:
                s[key] = u"%s" % v
        except (TypeError, ValueError):
            pass
    if s["views"] not in ("open", "name"):
        s["views"] = "open"
    if s["clear"] not in ("views", "model"):
        s["clear"] = "views"
    return s


def check_settings(s):
    """FAIL checks for distances that make no sense (negative, or tolerances of zero)."""
    out = []
    for key in NUMBERS:
        if s[key] < 0:
            out.append(Check("Setting %s" % key, False, "must not be negative (%s)" % s[key]))
    for key in ("core_tol_mm", "level_tol_mm"):
        if s[key] <= 0:
            out.append(Check("Setting %s" % key, False, "must be more than 0"))
    if s["views"] == "name" and not s["name_filter"].strip():
        out.append(Check("Views", False, "type the text the plan view names contain"))
    return out


# ------------------------------------------------------------ family types (fuzzy names)

def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or u"").lower()).strip()


def family_kind(family):
    """FIXED / AUTO for a Stair Path family name, loosely ("Fixed Up Direction", "automatic up-down", ...)."""
    n = _norm(family)
    if "fixed" in n:
        return FIXED
    if "auto" in n:
        return AUTO
    return None


def type_scale(name):
    """The scale a type name is meant for: 'Standard 1-500' / '1:200' / '1/100' / 'Standard 100' -> 500 / 200 / 100."""
    m = re.search(r"1\s*[-:/_ ]\s*(\d{2,4})(?!\d)", name or u"")
    if not m:
        m = re.search(r"(?<!\d)(\d{3})\s*$", (name or u"").strip())
    return int(m.group(1)) if m else None


def pick_type(types, kind, scale):
    """The type of family ``kind`` for ``scale``: a 'Standard' name first, then the shortest name. None if none."""
    hits = [t for t in types if family_kind(t["family"]) == kind and type_scale(t["name"]) == scale]
    if not hits:
        return None
    hits.sort(key=lambda t: ("standard" not in _norm(t["name"]), len(t["name"]), t["name"]))
    return hits[0]


def missing_types(types, scales):
    """[(kind, scale)] needed for these view scales but not in the model."""
    need = []
    for sc in sorted(set(scales), reverse=True):
        kinds = (AUTO,) if sc == 500 else (FIXED, AUTO)
        for kind in kinds:
            if pick_type(types, kind, sc) is None:
                need.append((kind, sc))
    return need


def type_to_create(types, kind, scale):
    """(source type, new name) to duplicate for a missing type: the family's plain 'Standard' type (or any)."""
    fam = [t for t in types if family_kind(t["family"]) == kind]
    if not fam:
        return None, None
    fam.sort(key=lambda t: (_norm(t["name"]) != "standard", type_scale(t["name"]) is not None, t["name"]))
    return fam[0], u"Standard 1-%d" % scale


# ------------------------------------------------------------ levels and cores

def snap_level(levels, elev, tol):
    """Name of the level nearest ``elev`` (feet) within ``tol``, else None."""
    if elev is None:
        return None
    best = None
    for lv in levels:
        d = abs(lv["elev"] - elev)
        if d <= tol and (best is None or d < best[0]):
            best = (d, lv["name"])
    return best[1] if best else None


def flight_levels(stair, levels, tol):
    """(base, top, note) -- each end snapped to a level from its real elevation (level + offset), falling back
    to the parameter's level. note says when the parameter names a different level than the elevation."""
    base = snap_level(levels, stair.get("base_elev"), tol) or stair.get("base")
    top = snap_level(levels, stair.get("top_elev"), tol) or stair.get("top")
    notes = []
    if stair.get("base") and base != stair.get("base"):
        notes.append("base %s (parameter: %s)" % (base, stair.get("base")))
    if stair.get("top") and top != stair.get("top"):
        notes.append("top %s (parameter: %s)" % (top, stair.get("top")))
    return base, top, "; ".join(notes)


def _centre(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _overlap_ratio(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return (w * h) / small if small > 0 else 0.0


def same_core(a, b, tol):
    ca, cb = _centre(a["box"]), _centre(b["box"])
    near = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5 <= tol
    return near or _overlap_ratio(a["box"], b["box"]) >= 0.5


def build_cores(stairs, levels, s):
    """Group the flights into stair cores (stacked in plan) with their resolved base / top levels.

    Returns (cores, skipped, notes): cores = [{"name", "flights": [{"id", "base", "top"}]}] ordered by plan
    position; skipped = [(id, why)] for flights without two different levels; notes = [(id, text)].
    """
    tol_lv = s["level_tol_mm"] / MM_PER_FT
    order = dict((lv["name"], i) for i, lv in enumerate(levels))
    flights, skipped, notes = [], [], []
    for st in stairs:
        base, top, note = flight_levels(st, levels, tol_lv)
        if note:
            notes.append((st["id"], note))
        if base not in order or top not in order:
            skipped.append((st["id"], "no base or top level"))
        elif order[base] >= order[top]:
            skipped.append((st["id"], "does not climb from one level to a higher one (%s -> %s)" % (base, top)))
        else:
            flights.append(dict(st, base=base, top=top))
    tol = s["core_tol_mm"] / MM_PER_FT
    parent = list(range(len(flights)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(flights)):
        for j in range(i + 1, len(flights)):
            if same_core(flights[i], flights[j], tol):
                parent[root(j)] = root(i)
    groups = {}
    for i, f in enumerate(flights):
        groups.setdefault(root(i), []).append(f)
    ordered = sorted(groups.values(), key=lambda fs: (round(min(_centre(f["box"])[0] for f in fs), 3),
                                                       round(min(_centre(f["box"])[1] for f in fs), 3)))
    cores = []
    for n, fs in enumerate(ordered):
        fs.sort(key=lambda f: (order[f["base"]], f["id"]))
        cores.append({"name": "Core %s" % _letters(n), "flights": [{"id": f["id"], "base": f["base"],
                                                                     "top": f["top"]} for f in fs]})
    return cores, skipped, notes


def _letters(n):
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def up_down(cores):
    """({level: [(core, stair id)]} going up, {level: [(core, stair id)]} arriving from below).

    Duplicate flights of one core at the same base (or top) level: the newest element (highest id) wins."""
    ups, downs = {}, {}
    for core in cores:
        by_base, by_top = {}, {}
        for f in core["flights"]:
            by_base.setdefault(f["base"], []).append(f["id"])
            by_top.setdefault(f["top"], []).append(f["id"])
        for lvl, ids in by_base.items():
            ups.setdefault(lvl, []).append((core["name"], max(ids)))
        for lvl, ids in by_top.items():
            downs.setdefault(lvl, []).append((core["name"], max(ids)))
    return ups, downs


def pass_through(cores, levels, level):
    """{core: stair id} of a flight that runs through ``level`` (base below it, top above it)."""
    order = dict((lv["name"], i) for i, lv in enumerate(levels))
    li = order.get(level)
    out = {}
    if li is None:
        return out
    for core in cores:
        ids = [f["id"] for f in core["flights"] if order[f["base"]] < li < order[f["top"]]]
        if ids:
            out[core["name"]] = max(ids)
    return out


# ------------------------------------------------------------ what to place in each view

def boxes_overlap(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def style(scale, kind):
    """(family kind, show up text, show down text, offsets set) for an annotation of ``kind`` at ``scale``.

    kind: up | down | through (a flight passing the level, in place of a hidden arriving one) | sweep.
    show_down None = leave it alone (Fixed Up Direction has no Show Down Text)."""
    if scale == 500:
        return AUTO, False, False, ()
    if kind == "up":
        return FIXED, True, None, ("up",)
    if kind == "down":
        return AUTO, False, True, ("down",)
    return AUTO, True, True, ("up", "down")


def text_offset(stair, scale, s):
    """(x, y) offset of the Up / Down text in mm, from the stair's own plan proportions and run direction.

    Length >= width (travel along X): a run toward +X puts the text dir_x_mm on the -X side; a run toward -X
    (or unknown) keeps the standard distance on the +X side. Width > length (travel along Y): the text goes
    dir_y_mm against the run (-Y for a +Y run, +Y for a -Y run); unknown -> the standard distance on +Y."""
    if scale not in TEXT_SCALES:
        return (0.0, 0.0)
    box = stair["box"]
    dx, dy = stair.get("run") or (0.0, 0.0)
    std_x, std_y = s["std_x_%d" % scale], s["std_y_%d" % scale]
    if box[2] - box[0] >= box[3] - box[1]:
        if s["directional"] and dx > 1e-9:
            return (-s["dir_x_mm"], 0.0)
        return (std_x, 0.0)
    if s["directional"] and abs(dy) > 1e-9:
        return (0.0, -s["dir_y_mm"] if dy > 0 else s["dir_y_mm"])
    return (0.0, std_y)


def plan_view(view, cores, levels, ups, downs, stairs_by_id):
    """The annotations one view should get: [{"kind", "core", "stair", "fallback"}] plus notes for flights
    outside the view's crop. A Down whose flight Revit will not show here falls back to ``fallback`` (a flight
    of the same core passing through the level), placed as 'through'."""
    level = view["level"]
    jobs, notes = [], []
    through = pass_through(cores, levels, level)

    def in_crop(sid):
        st = stairs_by_id.get(sid)
        return view.get("crop") is None or st is None or boxes_overlap(st["box"], view["crop"])

    for core, sid in sorted(ups.get(level, [])):
        if in_crop(sid):
            jobs.append({"kind": "up", "core": core, "stair": sid, "fallback": None})
        else:
            notes.append("%s: %s Up (stair %d) is outside the crop region -- skipped" % (view["name"], core, sid))
    for core, sid in sorted(downs.get(level, [])):
        fb = through.get(core)
        if in_crop(sid) or (fb is not None and in_crop(fb)):
            jobs.append({"kind": "down", "core": core, "stair": sid, "fallback": fb})
        else:
            notes.append("%s: %s Down (stair %d) is outside the crop region -- skipped" % (view["name"], core, sid))
    return jobs, notes


def sweep_jobs(view, tagged):
    """Visible stairs in the view that still have no stair path: Automatic Up/Down with both texts."""
    return [{"kind": "sweep", "core": None, "stair": sid, "fallback": None}
            for sid in sorted(set(view.get("visible") or [])) if sid not in tagged]


def scale_problems(views):
    """Views at a scale the standard does not cover (only 1:500, 1:200 and 1:100 are)."""
    return [v for v in views if v["scale"] not in SCALES]

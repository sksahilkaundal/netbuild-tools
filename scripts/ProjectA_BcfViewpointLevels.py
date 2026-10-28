# -*- coding: utf-8 -*-
r"""
ProjectA BCF viewpoint levels -- which level / tier is a 3D-pinned ACC issue on?

The walkthrough (ProjectA_IssueWalkthrough.py) and the report builder take an
issue's level from its placement SHEET name (-L26-, -GFL-, -B01-). Issues
pinned in a 3D model instead (placement = "...-SW00-ZZZ-BM-922001.nwd",
"...-T00O-ZZZ-AR-980001.rvt") have no sheet level, so `pending --lo/--hi`
silently skips them (20261009 export: 25 of 245). Their BCF viewpoint still
says how high the view is:

  * horizontal section plane (Direction 0,0,+1) = the top cut of the section
    box -> the floor being viewed is the highest level AT OR BELOW the cut.
    Reliable.
  * otherwise the perspective camera Z only -> rough (a camera looking down
    from above reads a few floors too high). Labelled "camera (rough)".
  * sheet pins carry NO viewpoint at all (checked 2026-10-08, 220 of 220).

BCF heights are SHARED (survey) metres. Map them to levels with a levels table
dumped from Revit in the same system:
    python ProjectA_BcfViewpointLevels.py dump-levels    (Revit open with any ProjectA
                                                     tier model; read-only)
which posts scripts\revit_dump_levels_survey.py over the pyRevit listener and
writes LEVELS_CSV. Without that file the heights are printed unmapped.

Usage:
    python ProjectA_BcfViewpointLevels.py                  3D-pinned issues: heights (+ level/tier once mapped)
    python ProjectA_BcfViewpointLevels.py --all            every issue in the export
    python ProjectA_BcfViewpointLevels.py --lo 24 --hi 40  only those estimated in a level range
    python ProjectA_BcfViewpointLevels.py dump-levels      refresh LEVELS_CSV from the open Revit model
Writes <BASE>\<EXPORT_SUBDIR>\ProjectA_bcf_viewpoint_levels.csv. Read-only otherwise.
"""
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ProjectA_IssueWalkthrough as w      # export CSV reader, sheet level parser, Revit listener call

# ----------------------------- CONFIG ---------------------------------
BASE = r"C:\SK\Projects\ProjectA\Issues\260914"
EXPORT_SUBDIR = "20261009"                                   # folder holding the export CSV + BCF(s)
BCF_FILE = "2026-10-08 16_06 245 Issues-260916 to 261008.bcf"  # one name, a list, or None = every *.bcf
LEVELS_CSV = os.path.join(BASE, "projecta_levels_survey.csv")      # from `dump-levels`
REVIT_URL = "http://127.0.0.1:48884/revit_mcp/execute_code/"
# ------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
REVIT_SNIPPET = os.path.join(HERE, "revit_dump_levels_survey.py")
TOL_M = 0.05                       # a cut exactly at a level counts as that level
TIERS = [("Basement", -99, -1), ("Podium", 0, 6), ("Tier 01", 7, 23), ("Tier 02", 24, 40),
         ("Tier 03", 41, 58), ("Tier 04", 59, 75), ("Tier 05", 76, 999)]
NUM = re.compile(r"<([XYZ])>\s*([-0-9.eE+]+)\s*</[XYZ]>")
NO_VIEWPOINT = {"kind": "none", "cam_z": None, "dir_z": None, "cuts": []}
OUT_COLS = ["issue_id", "title", "placement", "camera", "camera_z_m", "view_dir_z",
            "section_cut_z_m", "basis", "est_level", "tier"]


def bcf_paths():
    d = os.path.join(BASE, EXPORT_SUBDIR)
    if not BCF_FILE:
        names = sorted(n for n in os.listdir(d) if n.lower().endswith(".bcf"))
    else:
        names = [BCF_FILE] if isinstance(BCF_FILE, str) else list(BCF_FILE)
    return [os.path.join(d, n) for n in names]


def xyz(block):
    v = dict((k, float(n)) for k, n in NUM.findall(block or ""))
    return v.get("X", 0.0), v.get("Y", 0.0), v.get("Z", 0.0)


def viewpoints():
    """{issue id: dict(kind, cam_z, dir_z, cuts=[top-cut Z, ...])} over all BCFs."""
    out = {}
    for path in bcf_paths():
        z = zipfile.ZipFile(path)
        names = set(z.namelist())
        for m in [n for n in names if n.endswith("markup.bcf")]:
            x = z.read(m).decode("utf-8", "replace")
            idx = re.search(r"<Index>(\d+)</Index>", x)
            if not idx:
                continue
            folder = m.rsplit("/", 1)[0]
            ref = re.search(r"<Viewpoint>([^<]+\.bcfv)</Viewpoint>", x)
            cand = [folder + "/" + ref.group(1)] if ref else []
            cand += sorted(n for n in names if n.startswith(folder + "/") and n.endswith(".bcfv"))
            vp = next((c for c in cand if c in names), None)
            if vp is None:
                out[idx.group(1)] = dict(NO_VIEWPOINT)
                continue
            v = z.read(vp).decode("utf-8", "replace")
            kind = "perspective" if "<PerspectiveCamera>" in v else ("orthogonal" if "<OrthogonalCamera>" in v else "none")
            cam = re.search(r"<CameraViewPoint>(.*?)</CameraViewPoint>", v, re.S)
            dr = re.search(r"<CameraDirection>(.*?)</CameraDirection>", v, re.S)
            cuts = []
            for loc, d in re.findall(r"<ClippingPlane>\s*<Location>(.*?)</Location>\s*<Direction>(.*?)</Direction>", v, re.S):
                if xyz(d)[2] > 0.9:                 # horizontal plane, normal up = top of the section box
                    cuts.append(xyz(loc)[2])
            out[idx.group(1)] = {"kind": kind, "cam_z": xyz(cam.group(1))[2] if cam else None,
                                 "dir_z": xyz(dr.group(1))[2] if dr else None, "cuts": cuts}
    return out


def load_levels():
    """[(survey_z, name, number)] sorted by height, or [] if LEVELS_CSV is missing."""
    if not os.path.exists(LEVELS_CSV):
        return []
    return sorted((float(r["elevation_survey_m"]), r["level"], level_number(r["level"]))
                  for r in w.read_csv(LEVELS_CSV)[1])


def level_number(name):
    """'24th Floor' 24, 'Ground Floor' 0, 'Basement 02' -2, else None (roof, top of building...)."""
    n = (name or "").strip()
    m = re.match(r"^0*(\d+)(st|nd|rd|th)\b", n, re.I)
    if m: return int(m.group(1))
    m = re.match(r"^(?:basement|b)\s*0*(\d+)\b", n, re.I)
    if m: return -int(m.group(1))
    return 0 if re.match(r"^ground", n, re.I) else None


def level_at(z, levels):
    """Highest level at or below z (shared metres)."""
    below = [lv for lv in levels if lv[0] <= z + TOL_M]
    return below[-1] if below else None


def tier_of(num):
    return "" if num is None else next((t for t, lo, hi in TIERS if lo <= num <= hi), "")


def dump_levels():
    """Post revit_dump_levels_survey.py to the open Revit (read-only) -> LEVELS_CSV."""
    w.REVIT_URL = REVIT_URL
    with open(REVIT_SNIPPET, encoding="utf-8") as f:
        code = "OUT_CSV_OVERRIDE = r'%s'\n" % LEVELS_CSV + f.read()
    print(w.revit(code, description="ProjectA_BcfViewpointLevels dump-levels"))


def main(argv):
    if argv and argv[0] == "dump-levels":
        return dump_levels()
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__); return
    lo = hi = None
    if "--lo" in argv:
        lo = int(argv[argv.index("--lo") + 1]); hi = int(argv[argv.index("--hi") + 1])
    w.BASE, w.EXPORT_SUBDIR = BASE, EXPORT_SUBDIR
    rows = w.export_rows()
    if "--all" not in argv:
        rows = [r for r in rows if w.level_of(r["placement_sheet"]) is None]
    vps, levels = viewpoints(), load_levels()
    if lo is not None and not levels:
        raise SystemExit("--lo/--hi needs the levels table (%s) -- run dump-levels first" % LEVELS_CSV)
    print("Export %s: %d issue(s) | levels table: %s" % (
        EXPORT_SUBDIR, len(rows), "%d levels" % len(levels) if levels else "MISSING -- run dump-levels to map heights"))
    out = []
    for r in rows:
        vp = vps.get(r["issue_id"], NO_VIEWPOINT)
        if vp["cuts"]:
            z, basis = max(vp["cuts"]), "section cut"
        elif vp["cam_z"] is not None:
            z, basis = vp["cam_z"], "camera (rough)"
        else:
            z, basis = None, "no viewpoint"
        lv = level_at(z, levels) if (z is not None and levels) else None
        num = lv[2] if lv else w.level_of(r["placement_sheet"])
        if lo is not None and (num is None or not lo <= num <= hi):
            continue
        model = os.path.basename(r["placement_sheet"] or "")
        rec = {"issue_id": r["issue_id"], "title": r["title"], "placement": model,
               "camera": vp["kind"], "camera_z_m": "%.1f" % vp["cam_z"] if vp["cam_z"] is not None else "",
               "view_dir_z": "%.2f" % vp["dir_z"] if vp["dir_z"] is not None else "",
               "section_cut_z_m": ";".join("%.1f" % c for c in vp["cuts"]),
               "basis": basis, "est_level": lv[1] if lv else "", "tier": tier_of(num)}
        out.append(rec)
        print("  #%s %-34s %-26s %-15s z=%-6s %-18s %s" % (
            rec["issue_id"], rec["title"][:34], model[:26], basis, "%.1f" % z if z is not None else "-",
            rec["est_level"][:18], rec["tier"]))
    path = os.path.join(BASE, EXPORT_SUBDIR, "ProjectA_bcf_viewpoint_levels.csv")
    w.write_csv(path, OUT_COLS, out)
    print("CSV: %s (%d rows)" % (path, len(out)))


if __name__ == "__main__":
    main(sys.argv[1:])

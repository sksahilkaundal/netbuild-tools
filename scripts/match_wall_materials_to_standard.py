# -*- coding: utf-8 -*-
r"""
Fuzzy-match the materials on a target model's USED wall types to the standard model's
materials, and report what would change (material assignment + material graphics/hatch).

    python scripts\match_wall_materials_to_standard.py <src_materials.json> <tgt_walls.json> [--csv out.csv]

  src_materials.json : every material in the standard model, with graphics  (_src_podium_materials.json)
  tgt_walls.json     : target used wall types + layer materials + graphics  (_tgt_*_walls.json)

Matching is material-name driven, because that is what carries the hatch:
  1. exact name                                   -> "exact"
  2. same material family + best name similarity  -> "strong" (>=0.78) / "weak" (>=0.55)
  3. otherwise                                    -> "none" (listed for a human decision)
Material family comes from the material name AND the wall types that use it, never from
Type Mark - the marks are unreliable in both models (e.g. a WBT type marked "WBS 200").

DRY RUN ONLY - this script never writes to Revit. It prints and optionally writes a CSV.
"""
import csv
import difflib
import json
import re
import sys

FAMILY_PATTERNS = [
    ("solid_block",   r"solid\s*block|\bwbs\b"),
    ("thermal_block", r"thermal\s*block|\bwbt\b"),
    ("hollow_block",  r"hollow\s*block|\bwbh\b"),
    ("aac_block",     r"autoclaved|aerated|\bwba\b"),
    ("light_block",   r"lighweight|lightweight\s*block|\bwbl\b"),
    ("gypsum_board",  r"gypsum\s*(wall\s*)?board|plaster\s*board"),
    ("drywall",       r"dry\s*wall|drywall|\bwdl?\b|partition"),
    ("concrete",      r"concrete|in-?situ|\bconc\b"),
    ("glass",         r"glass|glazed|vision|glazing"),
    ("stone",         r"stone|marble|granite"),
    ("metal",         r"metal|aluminium|aluminum|steel|louver"),
    ("generic_fill",  r"generic|indicative|by specialist|by others"),
]


def family_of(*texts):
    blob = " ".join(t or "" for t in texts).lower()
    for fam, pat in FAMILY_PATTERNS:
        if re.search(pat, blob):
            return fam
    return "other"


def norm(name):
    s = (name or "").lower()
    s = re.sub(r"\[studio\]|\bstudio[_ -]*", " ", s)
    s = re.sub(r"\b\d+(\.\d+)?\s*mm\b", " ", s)      # thickness in a material name is noise
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def graphics_diff(cur, std):
    out = []
    for label, k in (("cut fg pattern", "cut_fg"), ("cut bg pattern", "cut_bg"),
                     ("surface fg pattern", "surface_fg"), ("surface bg pattern", "surface_bg")):
        if (cur.get(k) or None) != (std.get(k) or None):
            out.append("%s: %s -> %s" % (label, cur.get(k) or "-", std.get(k) or "-"))
    for label, k in (("cut fg colour", "cut_fg_color"), ("shading colour", "color")):
        if cur.get(k) != std.get(k):
            out.append("%s: %s -> %s" % (label, cur.get(k), std.get(k)))
    if cur.get("transparency") != std.get("transparency"):
        out.append("transparency: %s -> %s" % (cur.get("transparency"), std.get("transparency")))
    if cur.get("material_class") != std.get("material_class"):
        out.append("class: %s -> %s" % (cur.get("material_class") or "-", std.get("material_class") or "-"))
    return out


def main():
    src_path, tgt_path = sys.argv[1], sys.argv[2]
    csv_out = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    S = json.load(open(src_path, encoding="utf-8"))
    T = json.load(open(tgt_path, encoding="utf-8"))
    std = {int(k): v for k, v in S["materials"].items()}
    std_by_name = {v["name"]: v for v in std.values()}
    tgt_mats = {int(k): v for k, v in T["materials"].items()}
    tgt_pats = T["patterns"]

    # which wall types use each target material, and how many walls that is
    users = {}
    for t in T["types"]:
        for L in t["layers"]:
            if L["material_id"]:
                u = users.setdefault(L["material_id"], {"walls": 0, "types": []})
                u["walls"] += t["count"]
                u["types"].append("%s (L%d)" % (t["type"], L["layer"]))

    # candidate standards: only materials the standard model actually uses on walls,
    # plus any standard material whose name matches a target material's family
    rows = []
    for mid, m in sorted(tgt_mats.items(), key=lambda kv: -users.get(kv[0], {"walls": 0})["walls"]):
        use = users.get(mid, {"walls": 0, "types": []})
        fam = family_of(m["name"], *use["types"])
        best, best_sc = None, 0.0
        if m["name"] in std_by_name:
            best, best_sc = std_by_name[m["name"]], 1.0
        else:
            for s in std.values():
                if family_of(s["name"]) != fam:
                    continue
                sc = difflib.SequenceMatcher(None, norm(s["name"]), norm(m["name"])).ratio()
                # prefer a standard material that the standard model actually uses on walls
                if s["name"] in S.get("wall_materials", []):
                    sc += 0.05
                if sc > best_sc:
                    best, best_sc = s, sc
        gradeval = "exact" if best_sc >= 0.999 else "strong" if best_sc >= 0.78 else "weak" if best_sc >= 0.55 else "none"
        diffs = graphics_diff(m, best) if best is not None and gradeval != "none" else []
        missing = []
        if best is not None and gradeval != "none":
            missing = [p for p in (best.get("cut_fg"), best.get("cut_bg"), best.get("surface_fg"), best.get("surface_bg"))
                       if p and p not in tgt_pats]
        rows.append(dict(mat=m, use=use, fam=fam, std=best, sc=best_sc, grade=gradeval, diffs=diffs, missing=missing))

    print("STANDARD : %s  (%d materials)" % (S["doc"], len(std)))
    print("TARGET   : %s  (%d walls, %d used wall types, %d layer materials)\n" % (
        T["doc"], T["placed"], len(T["types"]), len(tgt_mats)))
    for r in rows:
        m, s = r["mat"], r["std"]
        print("%-34s  walls %-6d family %-13s ->  %-34s [%s]" % (
            m["name"], r["use"]["walls"], r["fam"], s["name"] if s else "(no standard found)", r["grade"]))
        print("      used by: %s" % ", ".join(r["use"]["types"][:6]) + (" ..." if len(r["use"]["types"]) > 6 else ""))
        if r["grade"] == "none":
            print("      -> no match in the standard model; needs a decision")
        elif not r["diffs"]:
            print("      -> already matches the standard (no graphics change)")
        else:
            if s and m["name"] != s["name"]:
                print("      -> RENAME/REASSIGN to '%s'  (material-level decision)" % s["name"])
            for d in r["diffs"]:
                print("      -> %s" % d)
        for p in r["missing"]:
            print("      !! fill pattern '%s' does not exist in the target - would have to be created" % p)
        print()

    n = {}
    for r in rows:
        n[r["grade"]] = n.get(r["grade"], 0) + 1
    print("DRY RUN - nothing written. %d materials: %s. %d with graphics changes, %d needing a decision." % (
        len(rows), ", ".join("%s %d" % (k, v) for k, v in sorted(n.items())),
        sum(1 for r in rows if r["diffs"]), sum(1 for r in rows if r["grade"] == "none")))

    if csv_out:
        with open(csv_out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Target material", "Walls", "Family", "Used by wall types", "Standard material",
                        "Match", "Score", "Proposed change", "Missing pattern in target"])
            for r in rows:
                w.writerow([r["mat"]["name"], r["use"]["walls"], r["fam"], "; ".join(r["use"]["types"]),
                            r["std"]["name"] if r["std"] else "", r["grade"], "%.2f" % r["sc"],
                            " | ".join(r["diffs"]) if r["diffs"] else ("needs decision" if r["grade"] == "none" else "none"),
                            "; ".join(r["missing"])])
        print("CSV: %s" % csv_out)


if __name__ == "__main__":
    main()

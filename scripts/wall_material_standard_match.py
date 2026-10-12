# -*- coding: utf-8 -*-
r"""
Fuzzy-match a target model's USED wall types to a source (standard) model's wall types,
and propose: (a) the layer material each target layer should carry, and (b) the material
graphics (cut/surface hatch patterns + colours) to copy from the source material.

    python scripts\wall_material_standard_match.py <source.json> <target.json> [--csv out.csv]

Both JSONs come from execute_revit_code dumps (see the session that created them):
  source: {doc, types:[{type, type_mark, total_mm, layers:[{width_mm, material, ...}]}], materials:{id: {...graphics}}}
  target: same + all_materials (names) + patterns (name -> drafting|model)

Matching is deliberately conservative and explainable - four signals, in order:
  1. token family     WBS / WBT / WBH / WBA / WBL / WD / WG / concrete / glass / drywall / generic ...
  2. nominal thickness (from the type name where present, else the compound-structure width)
  3. name similarity  (difflib ratio on normalised names)
  4. material family  of the existing target material, as a tie-break / sanity check
A match is reported as exact / strong / weak / none; nothing below "strong" is proposed
for automatic application - weak and none are listed for a human decision.
"""
import csv
import difflib
import json
import re
import sys

# --------------------------------------------------------------- normalising ---
FAMILY_PATTERNS = [
    ("solid_block",   r"\bwbs\b|solid\s*block"),
    ("thermal_block", r"\bwbt\b|thermal\s*block"),
    ("hollow_block",  r"\bwbh\b|hollow\s*block"),
    ("aac_block",     r"\bwba\b|autoclaved|aerated"),
    ("light_block",   r"\bwbl\b|lighweight|lightweight"),
    ("drywall",       r"\bwdl?\b|dry\s*wall|drywall|gypsum|gyp\b|tile/gyp"),
    ("concrete",      r"concrete|\bconc\b"),
    ("glass",         r"\bwg\b|glass|glazed|vision"),
    ("stone",         r"stone"),
    ("finish",        r"finish|ledge|legde"),
    ("generic",       r"generic"),
    ("curtain",       r"curtain|screen|mullion|louver"),
]


def family_of(*texts):
    blob = " ".join(t or "" for t in texts).lower()
    for fam, pat in FAMILY_PATTERNS:
        if re.search(pat, blob):
            return fam
    return "other"


def thickness_from_name(name):
    """Nominal mm in a type name: WBS.150, 'concrete 300mm', 'Drywall 125mm', 'WG-35'."""
    m = re.findall(r"(?<![\d.])(\d{2,4})(?:\s*mm)?(?![\d.])", name or "")
    vals = [int(v) for v in m if 20 <= int(v) <= 1000]
    return vals[0] if vals else None


def norm(name):
    s = (name or "").lower()
    s = re.sub(r"^studio[-_ ]*(arc|wal|str)?[-_ ]*", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def score(src, tgt):
    """0..1 similarity of two type records, plus the reasons."""
    s_fam = family_of(src["type"], src.get("type_mark"), *[l["material"] for l in src["layers"]])
    t_fam = family_of(tgt["type"], tgt.get("type_mark"), *[l["material"] for l in tgt["layers"]])
    s_th = thickness_from_name(src["type"]) or src.get("total_mm")
    t_th = thickness_from_name(tgt["type"]) or tgt.get("total_mm")
    reasons = []
    if s_fam != t_fam:
        return 0.0, ["family %s != %s" % (t_fam, s_fam)]
    sc = 0.55
    reasons.append("family %s" % s_fam)
    if s_th and t_th:
        d = abs(float(s_th) - float(t_th))
        if d < 0.6:
            sc += 0.30; reasons.append("thickness %gmm" % s_th)
        elif d <= 12.5:
            sc += 0.18; reasons.append("thickness %gmm~%gmm" % (t_th, s_th))
        else:
            sc -= 0.25; reasons.append("thickness %gmm vs %gmm" % (t_th, s_th))
    ratio = difflib.SequenceMatcher(None, norm(src["type"]), norm(tgt["type"])).ratio()
    sc += 0.15 * ratio
    reasons.append("name %.0f%%" % (ratio * 100))
    if (src.get("type_mark") or "") and src.get("type_mark") == tgt.get("type_mark"):
        sc += 0.05; reasons.append("same Type Mark")
    return max(0.0, min(1.0, sc)), reasons


def grade(sc):
    if sc >= 0.93:
        return "exact"
    if sc >= 0.78:
        return "strong"
    if sc >= 0.60:
        return "weak"
    return "none"


def main():
    src_path, tgt_path = sys.argv[1], sys.argv[2]
    csv_out = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    S = json.load(open(src_path, encoding="utf-8"))
    T = json.load(open(tgt_path, encoding="utf-8"))
    src_types = [t for t in S["types"] if t["layers"]]          # curtain walls have no layers
    src_mats = {int(k): v for k, v in S["materials"].items()}
    tgt_mats = {int(k): v for k, v in T["materials"].items()}
    tgt_mat_names = set(T["all_materials"])
    patterns = T["patterns"]

    rows = []
    for t in sorted(T["types"], key=lambda x: -x["count"]):
        if not t["layers"]:
            rows.append((t, None, 0.0, ["curtain/stacked wall - no layers, skipped"], []))
            continue
        best, best_sc, best_why = None, 0.0, []
        for s in src_types:
            sc, why = score(s, t)
            if sc > best_sc:
                best, best_sc, best_why = s, sc, why
        actions = []
        if best is not None and grade(best_sc) in ("exact", "strong"):
            # pair layers by order; propose the source material for each
            for i, tl in enumerate(t["layers"]):
                sl = best["layers"][i] if i < len(best["layers"]) else best["layers"][-1]
                src_mat = src_mats.get(sl["material_id"]) if sl["material_id"] else None
                if src_mat is None:
                    continue
                cur = tgt_mats.get(tl["material_id"]) if tl["material_id"] else None
                cur_name = tl["material"]
                if cur_name != src_mat["name"]:
                    exists = src_mat["name"] in tgt_mat_names
                    actions.append(dict(kind="assign_material", layer=tl["layer"], width=tl["width_mm"],
                                        frm=cur_name, to=src_mat["name"],
                                        note="material exists in target" if exists else "MATERIAL MISSING - would be created"))
                    cur = None if not exists else cur
                # hatch comparison against whatever material will end up on the layer
                ref = cur if cur is not None else None
                if ref is not None:
                    diffs = []
                    if (ref.get("cut_fg") or None) != (src_mat.get("cut_fg") or None):
                        diffs.append("cut fg %s -> %s" % (ref.get("cut_fg") or "-", src_mat.get("cut_fg") or "-"))
                    if (ref.get("surface_fg") or None) != (src_mat.get("surface_fg") or None):
                        diffs.append("surface fg %s -> %s" % (ref.get("surface_fg") or "-", src_mat.get("surface_fg") or "-"))
                    if ref.get("color") != src_mat.get("color"):
                        diffs.append("colour %s -> %s" % (ref.get("color"), src_mat.get("color")))
                    if ref.get("transparency") != src_mat.get("transparency"):
                        diffs.append("transparency %s -> %s" % (ref.get("transparency"), src_mat.get("transparency")))
                    if diffs:
                        actions.append(dict(kind="set_graphics", layer=tl["layer"], material=ref["name"],
                                            to=src_mat["name"], detail="; ".join(diffs)))
                for p in (src_mat.get("cut_fg"), src_mat.get("surface_fg"), src_mat.get("cut_bg"), src_mat.get("surface_bg")):
                    if p and p not in patterns:
                        actions.append(dict(kind="missing_pattern", layer=tl["layer"], detail="fill pattern '%s' not in target" % p))
        rows.append((t, best, best_sc, best_why, actions))

    print("SOURCE (standard): %s" % S["doc"])
    print("TARGET           : %s   (%d walls, %d used types)\n" % (T["doc"], T["placed"], len(T["types"])))
    hdr = "%-42s %6s %8s  %-38s %-7s %s"
    print(hdr % ("Target wall type", "Count", "Total", "Matched source type", "Match", "Why"))
    print("-" * 150)
    for t, best, sc, why, actions in rows:
        print(hdr % (t["type"][:42], t["count"], ("%gmm" % t["total_mm"]) if t["total_mm"] else "-",
                     (best["type"][:38] if best else "-"), grade(sc), ", ".join(why)))
        for a in actions:
            if a["kind"] == "assign_material":
                print("      L%d %gmm  material: %s  ->  %s   (%s)" % (a["layer"], a["width"], a["frm"], a["to"], a["note"]))
            elif a["kind"] == "set_graphics":
                print("      L%d graphics on '%s' (to match '%s'): %s" % (a["layer"], a["material"], a["to"], a["detail"]))
            else:
                print("      L%d %s" % (a["layer"], a["detail"]))
    n_act = sum(len(a) for *_x, a in rows)
    by_grade = {}
    for t, best, sc, why, actions in rows:
        by_grade[grade(sc)] = by_grade.get(grade(sc), 0) + 1
    print("\nDRY RUN - nothing written. %d target types: %s. %d proposed actions." % (
        len(rows), ", ".join("%s %d" % (k, v) for k, v in sorted(by_grade.items())), n_act))

    if csv_out:
        with open(csv_out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Target type", "Count", "Total mm", "Layer", "Layer mm", "Current material",
                        "Matched source type", "Match", "Why", "Action", "Proposed material", "Detail"])
            for t, best, sc, why, actions in rows:
                if not actions:
                    w.writerow([t["type"], t["count"], t["total_mm"], "", "", "", best["type"] if best else "",
                                grade(sc), ", ".join(why), "no change", "", ""])
                for a in actions:
                    w.writerow([t["type"], t["count"], t["total_mm"], a.get("layer", ""), a.get("width", ""),
                                a.get("frm", a.get("material", "")), best["type"] if best else "", grade(sc),
                                ", ".join(why), a["kind"], a.get("to", ""), a.get("detail", a.get("note", ""))])
        print("CSV: %s" % csv_out)


if __name__ == "__main__":
    main()

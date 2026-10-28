# -*- coding: utf-8 -*-
r"""
BUA GLA/GSA area audit, step 2 of 2: check the areas the ProjectA Calculations sheet counts as
"Common GLA/GSA to Tenants" against their full Revit parameters.

    py -3.14 C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_audit.py "<dump.json>" "<YYMMDD>_..._Option 1.xlsx"
        [--find shared] [--rare 1] [--id 11411422 ...] [--csv out.csv]

<dump.json> comes from step 1, scripts\bua_gla_area_dump.py, run inside Revit (read-only).
The Option 1 workbook is the dated export the ProjectA Calculations workbook was built from.

Uses projecta_calculations_build.py's own rules (load_rows / is_common / in_gla), so "common" here is
exactly what the ProjectA sheet counts: Studio_Area_Department (= the export's "GLA/GSA Component") contains
GLA or GSA, Function-Sub-function is a service-type space (not a unit/amenity GSA line), and Usable
Area (A) > 0 - which the schedule's formula takes from Area Calc. Type. Studio_Is GLA is NOT in the
export and NOT used by the ProjectA sheet; this audit shows where it disagrees.

Each export row is matched to its Revit area by level + building + Function-Sub-function +
department, nearest Usable Area (= area m2 x Studio_Manual no. Of Floors). Reports:
  1. Common GLA/GSA per tenant x Studio_Is GLA (Yes / No / blank), and every area flagged No
  2. any parameter on those areas containing --find (default "shared"), and where --find appears
     in the export's Function / GLA/GSA columns
  3. tagged service-type areas WITHOUT usable area (stay non-lettable), by column B/C/D
  4. rare Sub-Function x Area Calc. Type pairs (<= --rare areas) - e.g. a "Hotel - King Suite"
     Calc. Type on a Storage area (2026-10-01, Tower B 51st, area 2447)
  5. --id: all parameters of the given element ids
Writes a CSV of the common areas (ids, tenant, Calc. Type, Is GLA, name, m2) next to the dump.
Read-only: changes nothing in Revit or the workbooks.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import projecta_calculations_build as f  # noqa: E402

FLOORS = "Studio_Manual no. Of  Floors"     # (two spaces, as named in the model)
SERVICE_SUBS = {"Services", "Storage", "Kitchen", "Pool", "Circulation", "F&B Kitchen"}


def fs(c):
    P = c["params"]
    return "%s-%s" % (P.get("Studio_Function Code"), P.get("Studio_Sub-Function Code"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump")
    ap.add_argument("option1")
    ap.add_argument("--find", default="shared", help="text to look for in every parameter (case-insensitive)")
    ap.add_argument("--rare", type=int, default=1, help="flag Sub-Function x Area Calc. Type pairs with <= N areas")
    ap.add_argument("--id", nargs="*", default=[], help="element ids to print in full")
    ap.add_argument("--csv", help="common-areas CSV (default: next to the dump)")
    a = ap.parse_args()

    dump = json.load(open(a.dump, encoding="utf-8"))
    areas = dump["areas"]
    print("dump: %s  (%d GLA/GSA-tagged areas, scheme '%s', host %s, %s)" % (
        a.dump, len(areas), dump.get("area_scheme"), dump.get("host"), dump.get("dumped")))
    wb = openpyxl.load_workbook(a.option1, data_only=True)
    rows = f.load_rows(wb[f.find_data_sheet(wb).title])
    common = [x for x in rows if f.is_common(x)]
    print("export: %s  (%d rows, %d Common GLA/GSA, %s m2)" % (
        a.option1, len(rows), len(common), f"{sum(x['A'] for x in common):,.2f}"))

    pool = defaultdict(list)
    for c in areas:
        P = c["params"]
        try:
            floors = float(P.get(FLOORS) or 1)
        except ValueError:
            floors = 1.0
        pool[(c["level"], P.get("Studio_Building name"), fs(c), P.get("Studio_Area_Department"))].append((c["m2"] * floors, c))
    used, pairs, unmatched = set(), [], []
    for x in common:
        cand = [(abs(v - x["A"]), c) for v, c in pool.get((x["lvl"], x["sec"], x["c"], x["gsa"]), []) if c["id"] not in used]
        if not cand:
            unmatched.append(x)
            continue
        d, c = min(cand, key=lambda t: t[0])
        used.add(c["id"])
        pairs.append((x, c, d))
    loose = [p for p in pairs if p[2] > 0.05 * max(1.0, float(p[1]["params"].get(FLOORS) or 1))]
    print("matched %d of %d to Revit areas%s%s" % (
        len(pairs), len(common), " | %d UNMATCHED" % len(unmatched) if unmatched else "",
        " | %d matched loosely (area differs)" % len(loose) if loose else ""))
    for x in unmatched:
        print("  UNMATCHED: %s %s %s %s A=%.2f" % (x["sec"], x["lvl"], x["c"], x["gsa"], x["A"]))

    print("\n1. Common GLA/GSA to Tenants by Studio_Is GLA")
    tab = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    for x, c, _ in pairs:
        t = tab[x["gsa"]][c["params"].get("Studio_Is GLA") or "blank"]
        t[0] += 1
        t[1] += x["A"]
    for tag in sorted(tab):
        print("  %-22s %s" % (tag, " | ".join("%s: %d areas %s m2" % (k, v[0], f"{v[1]:,.2f}")
                                               for k, v in sorted(tab[tag].items()))))
    print("  Area Type: %s (all %d tagged areas in the dump: %s)" % (
        dict(Counter(c["params"].get("Area Type") for _, c, _ in pairs)), len(areas),
        dict(Counter(c["params"].get("Area Type") for c in areas))))
    no = [(x, c) for x, c, _ in pairs if c["params"].get("Studio_Is GLA") == "No"]
    for x, c in no:
        print("  Is GLA = No: %-11s %-13s %-16s %-11s %-16s %8.2f  id %s (%s)" % (
            x["sec"], x["lvl"], x["c"], x["gsa"], c["params"].get("Name"), x["A"], c["id"], c["doc"][-6:]))

    needle = a.find.lower()
    print("\n2. '%s' in any parameter of the Common GLA/GSA areas:" % a.find)
    hits = [(c, k, v) for _, c, _ in pairs for k, v in c["params"].items() if needle in str(v).lower()]
    print("  none" if not hits else "")
    for c, k, v in hits:
        print("  id %s %s %s | %s = %s" % (c["id"], c["level"], c["params"].get("Name"), k, v))
    seen = defaultdict(lambda: [0, 0.0, 0.0])
    for x in rows:
        if needle in (x["c"] + " " + str(x["gsa"])).lower():
            s = seen[(x["c"], x["gsa"])]
            s[0] += 1
            s[1] += x["O"]
            s[2] += x["A"]
    print("  in the export's Function / GLA/GSA columns:" + ("" if seen else " none"))
    for (cv, g), (n, o, u) in sorted(seen.items(), key=lambda kv: -kv[1][1]):
        print("    %-28s %-18s %4d areas  BUA %10s  usable %9s" % (cv, g, n, f"{o:,.2f}", f"{u:,.2f}"))

    print("\n3. Tagged GLA/GSA service-type areas WITHOUT usable area (stay non-lettable GFA / BUA):")
    nu = [x for x in rows if f.in_gla(x) and x["cat"] in SERVICE_SUBS and x["A"] <= 0]
    cols = {m: sum(x[m] for x in nu) for m in "BCDEFGH"}
    print("  %d areas, BUA %s m2 - in %s" % (len(nu), f"{sum(x['O'] for x in nu):,.2f}",
                                           ", ".join("%s %s" % (m, f"{v:,.2f}") for m, v in cols.items() if v)))

    print("\n4. Rare Sub-Function x Area Calc. Type pairs among Common GLA/GSA (<= %d areas):" % a.rare)
    combo = Counter((x["c"], c["params"].get("Area Calc. Type")) for x, c, _ in pairs)
    rare = [(k, n) for k, n in combo.items() if n <= a.rare]
    print("  none" if not rare else "")
    for (cv, ct), n in sorted(rare):
        for x, c, _ in pairs:
            if x["c"] == cv and c["params"].get("Area Calc. Type") == ct:
                print("  %-18s Calc. Type %-24s Name %-16s %s %s %.2f m2  id %s (%s)" % (
                    cv, ct, c["params"].get("Name"), x["sec"], x["lvl"], x["A"], c["id"], c["doc"][-6:]))

    if a.id:
        print("\n5. Areas by id:")
        by_id = {c["id"]: c for c in areas}
        for i in a.id:
            c = by_id.get(str(i))
            if not c:
                print("  id %s: not in the dump (not GLA/GSA-tagged, other scheme, or deleted)" % i)
                continue
            print("  id %s  %s  level %s  %.2f m2" % (i, c["doc"], c["level"], c["m2"]))
            for k in sorted(c["params"]):
                print("    %-30s %s" % (k, c["params"][k]))

    out = a.csv or os.path.join(os.path.dirname(os.path.abspath(a.dump)), "_bua_common_gla_areas.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Element ID", "Model", "Building", "Level", "Function-Sub-function", "GLA/GSA (Studio_Area_Department)",
                    "Studio_Is GLA", "Area Calc. Type", "Area Type", "Name", "Number", "Usable Area (A) m2"])
        for x, c, _ in pairs:
            P = c["params"]
            w.writerow([c["id"], c["doc"], x["sec"], x["lvl"], x["c"], x["gsa"], P.get("Studio_Is GLA") or "",
                        P.get("Area Calc. Type") or "", P.get("Area Type") or "", P.get("Name") or "",
                        P.get("Number") or "", round(x["A"], 2)])
    print("\ncommon areas CSV: %s" % out)


if __name__ == "__main__":
    main()

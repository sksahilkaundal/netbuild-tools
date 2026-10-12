# -*- coding: utf-8 -*-
"""
Read-only helpers the launcher runs next to the user's scripts (in the child Python process):
pending notes grouped by tier / model, the previous-export overlap check and the photo spot-check list.
They only read the export CSVs and core_tagging_completed.csv / studio_notes_clean.csv -- nothing is written.
"""
import os
import re
from collections import defaultdict

CSV_RE = re.compile(r"ProjectA_issue_detail_report_\d+_\d+\.csv$")

# fallback buckets, used only when ProjectA_IssueDetailReport_Build.py cannot be imported
# (same labels, order and rules as its BUCKETS / tier_model)
FALLBACK = (["Basement (B01-B04)", "Podium (GF-06)", "Tier 01 (L07-23)", "Tier 02 (L24-40)", "Tier 03 (L41-58)",
             "Tier 04 (L59-75)", "Tier 05 (L76+)"] + ["Building B%d (B%03d)" % (n, n) for n in range(1, 6)] +
            ["Buildings B2-B5 (B2B5 sheet)", "3D (NWD) Overall Model", "3D (RVT) Model", "General (no level)"])


def export_csv(base, subdir):
    d = os.path.join(base, subdir)
    hits = sorted(f for f in os.listdir(d) if CSV_RE.match(f)) if os.path.isdir(d) else []
    return os.path.join(d, hits[0]) if len(hits) == 1 else None


def _fallback_label(r, level_of):
    sheet = r.get("placement_sheet") or ""
    m = re.search(r"-DWG-B00([1-5])-", sheet)
    if m:
        return "Building B%s (B00%s)" % (m.group(1), m.group(1))
    if "-DWG-B2B5-" in sheet:
        return "Buildings B2-B5 (B2B5 sheet)"
    ext = os.path.splitext(sheet)[1].lower()
    if ext == ".nwd":
        return "3D (NWD) Overall Model"
    if ext == ".rvt":
        return "3D (RVT) Model"
    lvl = level_of(sheet)
    if lvl is None:
        return "General (no level)"
    for top, label in zip((-1, 6, 23, 40, 58, 75, 99), FALLBACK[:7]):
        if lvl <= top:
            return label
    return "General (no level)"


def bucketer(base, export, w):
    """(label(row), number(label), source) -- the builder's own tier_model when it imports."""
    try:
        import ProjectA_IssueDetailReport_Build as b
        b.BASE, b.EXPORT_SUBDIR = base, export
        b.OURS_CSV = os.path.join(base, "core_tagging_completed.csv")
        b.Studio_NOTES_CSV = os.path.join(base, "studio_notes_clean.csv")
        b.BEFORE_DIR = os.path.join(base, "snapshots_full")
        b.AFTER_DIR = os.path.join(base, "snapshots_after_photos")
        ours = b.load_ours()
        return (lambda r: b.tier_model(r, ours.get(r["issue_id"])),
                lambda lbl: int(b.BUCKET_NO.get(lbl, 99)), "ProjectA_IssueDetailReport_Build.tier_model")
    except Exception as exc:                       # noqa: BLE001 - fall back, but say so
        return (lambda r: _fallback_label(r, w.level_of),
                lambda lbl: FALLBACK.index(lbl) + 1 if lbl in FALLBACK else 99,
                "launcher fallback rules (builder not importable: %s)" % exc)


def pending_grouped(base, export, prev, w):
    """Every un-noted issue (walkthrough 'pending', no range), grouped by tier / model."""
    todo = w.pending()
    label, number, source = bucketer(base, export, w)
    groups = defaultdict(list)
    for r in todo:
        groups[label(r)].append(r)
    print("Issues with no Studio note: %d   (export %s; grouping: %s)" % (len(todo), export, source))
    for lbl in sorted(groups, key=lambda x: (number(x), x)):
        rows = groups[lbl]
        print("\n  %02d %s - %d issue%s" % (number(lbl), lbl, len(rows), "" if len(rows) == 1 else "s"))
        for r in rows:
            print("     #%s  %-4s %-52s [%s]" % (r["issue_id"], w.level_label(w.level_of(r["placement_sheet"])),
                                                 r["title"][:52], r["status"]))
    if not todo:
        print("  none -- every issue in the export has a Studio note")
    print("\nPENDING_TOTAL=%d" % len(todo))
    shared_with_previous(base, export, prev)


def shared_with_previous(base, export, prev):
    if not prev:
        print("Previous export: none (no 'movement since' table)")
        return
    cur, old = export_csv(base, export), export_csv(base, prev)
    if not old:
        print("!!! Previous export %s: no single ProjectA_issue_detail_report_*.csv in %s" % (prev, os.path.join(base, prev)))
        return
    import csv
    ids = lambda p: {r["issue_id"] for r in csv.DictReader(open(p, encoding="utf-8-sig", newline=""))}
    a, b = ids(cur), ids(old)
    both = a & b
    if not both:
        print("!!! Previous export %s shares NO issues with %s -- the 'movement since' table will be empty" % (prev, export))
    else:
        print("Previous export %s: %d shared issues, %d new, %d no longer in the export" % (
            prev, len(both), len(a - b), len(b - a)))
    print("SHARED_WITH_PREVIOUS=%d" % len(both))


def photo_spot_check(base, export, cap):
    """Issues with 2-3 attachment photos: their After photo must be a real, different photo."""
    import csv
    path = export_csv(base, export)
    if not path:
        print("no export CSV in %s" % os.path.join(base, export))
        return
    after = os.path.join(base, "snapshots_after_photos")
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig", newline=""))
            if str(r.get("photo_count", "")).strip() in ("2", "3") and (not cap or int(r["issue_id"]) <= cap)]
    print("Spot-check the After image on these %d issue(s) with 2-3 attachment photos:" % len(rows))
    for r in sorted(rows, key=lambda r: int(r["issue_id"])):
        files = sorted(f for f in os.listdir(after) if f.startswith(r["issue_id"] + "_photo")) if os.path.isdir(after) else []
        print("  #%s  photos=%s  %s" % (r["issue_id"], r["photo_count"], ", ".join(files) or "(no files in snapshots_after_photos)"))
    print("  photo folder: %s" % after)


# ------------------------------------------------------------------ BUA / ProjectA Calculations
def _projecta_totals(path):
    """{label: column O value} for the Total / Efficiency rows of a workbook's ProjectA Calculations sheet,
    evaluated with projecta_calculations_build's own formula evaluator (openpyxl files carry no cached values)."""
    import openpyxl
    import projecta_calculations_build as f
    ws = openpyxl.load_workbook(path)[f.REF_SHEET]
    ev, out, ctx = f.Evaluator(ws), {}, ""
    for r in range(1, ws.max_row + 1):
        lab = ws["F%d" % r].value
        if isinstance(lab, str) and lab.startswith("="):           # mirror row: the denominator of the ratios below
            ctx = str(ws[lab[1:]].value or "")
            continue
        if not isinstance(lab, str) or not ("Total" in lab or "Efficiency" in lab):
            continue
        key = "%s (/ %s)" % (lab.strip(), ctx) if "Efficiency" in lab else lab.strip()
        try:
            out.setdefault(key, ev.v("O%d" % r))
        except Exception:                                          # noqa: BLE001 - a formula the evaluator can't read
            pass
    return out


def projecta_compare(new, old):
    """Total / Efficiency rows of two ProjectA Calculations workbooks, side by side."""
    a, b = _projecta_totals(old), _projecta_totals(new)
    print("ProjectA Calculations vs previous (column O, all assets)")
    print("  previous: %s\n  new     : %s" % (old, new))
    print("  %-70s %14s %14s %12s" % ("line", "previous", "new", "change"))
    for k in list(b) + [k for k in a if k not in b]:
        pv, nv = a.get(k), b.get(k)
        pct = "Efficiency" in k
        fmt = (lambda v: "-" if v is None else ("%.1f%%" % (100 * v) if pct else "{:,.2f}".format(v)))
        if pv is None or nv is None:
            ch = "new line" if pv is None else "removed"
        else:
            d = nv - pv
            ch = ("%+.1f pt" % (100 * d)) if pct else "{:+,.2f}".format(d)
            if abs(d) < (0.0005 if pct else 0.005):
                ch = "="
        print("  %-70s %14s %14s %12s" % (k[:70], fmt(pv), fmt(nv), ch))


def option1_diff(old, new, limit=60):
    """What changed between two Option 1 workbooks' data sheets, per asset / level / Function-Sub (+ GLA/GSA tag)."""
    import openpyxl
    from collections import defaultdict
    import projecta_calculations_build as f

    def agg(p):
        wb = openpyxl.load_workbook(p, data_only=True)
        d = defaultdict(lambda: [0.0, 0.0])
        for x in f.load_rows(wb[f.find_data_sheet(wb).title]):
            k = (x["sec"], str(x["lvl"]), x["c"], x["gsa"] or "")
            d[k][0] += x["N"]
            d[k][1] += x["O"]
        return d
    a, b = agg(old), agg(new)
    ch = []
    for k in set(a) | set(b):
        dn, do = b[k][0] - a[k][0], b[k][1] - a[k][1]
        if abs(dn) > 0.01 or abs(do) > 0.01:
            ch.append((k, a[k] if k in a else None, b[k] if k in b else None, dn, do))
    print("Option 1 data: what changed in Revit since the replaced export")
    print("  previous: %s\n  new     : %s" % (old, new))
    if not ch:
        print("  no change in GFA / BUA per asset / level / Function-Sub-function / GLA-GSA tag")
        return
    sec = defaultdict(lambda: [0.0, 0.0])
    for (s, _, _, _), _, _, dn, do in ch:
        sec[s][0] += dn
        sec[s][1] += do
    print("  per asset: " + " | ".join("%s GFA %+.2f BUA %+.2f" % (s, round(v[0], 2) + 0.0, round(v[1], 2) + 0.0)
                                for s, v in sorted(sec.items())))
    print("  %-20s %-20s %-30s %-24s %10s %10s" % ("asset", "level", "Function-Sub", "GLA/GSA", "GFA chg", "BUA chg"))
    for (s, lvl, c, g), pv, nv, dn, do in sorted(ch, key=lambda t: -abs(t[4]) - abs(t[3]))[:limit]:
        tag = "" if pv and nv else ("  (new)" if not pv else "  (gone)")
        print("  %-20s %-20s %-30s %-24s %+10.2f %+10.2f%s" % (s, lvl[:20], c[:30], g[:24], dn, do, tag))
    if len(ch) > limit:
        print("  ... %d more rows" % (len(ch) - limit))
    print("  (a matching GFA - / + pair on the same level usually means a retag or an area moved between columns)")

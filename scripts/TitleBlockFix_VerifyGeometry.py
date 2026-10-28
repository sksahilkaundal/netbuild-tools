# -*- coding: utf-8 -*-
"""
Geometry verification for Title Block Fix.

TitleBlockFix_Verify.py checks the VALUES agree between PDF and CAD. This
checks the GEOMETRY of the edited PDF against the untouched original:

  1. NO VECTOR LINE LOST. Every line segment in the original must still be
     in the edited file. The redaction pass is what could eat one -- an
     early version whited out a row border.

  2. NO SHIFT. Each replaced field must keep the edge its column aligns
     on. Dates and the bottom Date field are centred on every sheet; the
     description column is centred on some title block variants and
     LEFT-aligned on others (200001/400002-style), which the ORIGINAL's
     own rows reveal. A centred check on a left-aligned column would pass
     text that had spilled over the divider -- exactly the defect it must
     catch.

  3. NO OVERFLOW / NO WRAP. Each replaced field must stay inside its own
     cell -- between the column dividers that bracket it.

  4. NO COLLISION. A replaced field must not overlap any other text.

  5. PLOTTED-FROM-CAD AGREES. The PDF plotted from the corrected DWG has a
     different origin and a slightly different scale, so a similarity fit
     (scale + offset, per axis) is estimated from the text both sheets
     share unchanged, and each field compared after mapping.

Fields that are byte-identical in the original (sheets already correct at
source) are not "changes" and are not checked.

Set ORIG_DIR / EDIT_DIR / PLOT_DIR and call main().
"""
import os
import re
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import TitleBlockFix_Config as cfg
from TitleBlockFix_PDF import (to_visual, get_spans, infer_desc_alignment,
                               schedule_desc_spans)

ORIG_DIR = ""
EDIT_DIR = ""
PLOT_DIR = ""          # optional; "" skips check 5

TOL_EDGE = 0.75        # pt -- the aligned edge must agree this closely
TOL_BASELINE = 0.40    # pt
CELL_MARGIN = 0.30     # pt clearance required inside the cell
TOL_PLOT = 4.0         # pt (~1.4mm) for the plotted-from-CAD comparison

NEW_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def unconvert(d):
    """'06/09/2026' -> '06-Sep-2026'."""
    dd, mm, yy = d.split("/")
    return "%s-%s-%s" % (dd, MONTHS[int(mm) - 1], yy)


def segments(page):
    """Every straight line segment, visual space, rounded. One scan."""
    out = set()
    for d in page.get_cdrawings():
        for item in d["items"]:
            if item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            a = to_visual(fitz.Rect(p0[0], p0[1], p0[0], p0[1]), page)
            b = to_visual(fitz.Rect(p1[0], p1[1], p1[0], p1[1]), page)
            out.add((round(a.x0, 1), round(a.y0, 1),
                     round(b.x0, 1), round(b.y0, 1)))
    return out


def rules_in(segs, y0, y1):
    """Vertical dividers crossing the band y0..y1, from a segment set."""
    xs = set()
    for x0, ya, x1, yb in segs:
        if abs(x0 - x1) < 0.05 and abs(ya - yb) > 1:
            lo, hi = sorted((ya, yb))
            if hi > y0 and lo < y1:
                xs.add(x0)
    return sorted(xs)


def cell_bounds(segs, span):
    rules = rules_in(segs, span["bbox"].y0, span["bbox"].y1)
    left = max([x for x in rules if x < span["centre_x"]], default=None)
    right = min([x for x in rules if x > span["centre_x"]], default=None)
    return left, right


def same_place(a, b):
    return (a["text"] == b["text"]
            and abs(a["centre_x"] - b["centre_x"]) < 0.5
            and abs(a["baseline"] - b["baseline"]) < 0.5)


def changed_fields(orig_spans, edit_spans):
    """Pair each replaced field with the original text it replaced.

    Matched by CONTENT (the un-converted date / the known before-wording)
    on the same row. Unmatched fields are reported, not skipped.
    """
    after_to_before = {v: k for k, v in cfg.revision_descriptions().items()}
    pairs, unmatched = [], []
    for es in edit_spans:
        if any(same_place(es, o) for o in orig_spans):
            continue                                   # unchanged field
        if NEW_DATE.match(es["text"]):
            kind, needle = "date", unconvert(es["text"])
        elif es["text"] in after_to_before:
            kind, needle = "desc", after_to_before[es["text"]]
        else:
            continue
        best = None
        for o in orig_spans:
            ok = (o["text"] == needle if kind == "date"
                  else o["text"].lower().startswith(needle))
            if not ok or abs(o["baseline"] - es["baseline"]) > 2.0:
                continue
            if best is None or abs(o["centre_x"] - es["centre_x"]) < \
                               abs(best["centre_x"] - es["centre_x"]):
                best = o
        (pairs if best else unmatched).append((kind, best, es) if best else es)
    return pairs, unmatched


def check_sheet(orig_path, edit_path):
    """-> (problems, notes, n_pairs, n_refs)."""
    problems, notes = [], []
    od, ed = fitz.open(orig_path), fitz.open(edit_path)
    try:
        op, ep = od[0], ed[0]
        oseg, eseg = segments(op), segments(ep)

        # 1. no vector line lost
        lost = oseg - eseg
        if lost:
            problems.append("LINE LOST x%d e.g. %s" % (len(lost), sorted(lost)[0]))

        ospans, espans = get_spans(op), get_spans(ep)
        pairs, unmatched = changed_fields(ospans, espans)
        for es in unmatched:
            problems.append("UNMATCHED %r (no original counterpart)" % es["text"][:40])

        # how the ORIGINAL aligns its description column -- same rule as
        # the fixer, so the check cannot drift from the fix
        odesc = schedule_desc_spans(ospans)
        desc_align = infer_desc_alignment(odesc, op) if odesc else "centre"
        if odesc:
            notes.append("descriptions %s-aligned" % desc_align)

        for kind, o, e in pairs:
            edge = "left" if (kind == "desc" and desc_align == "left") else "centre"
            # 2. no shift, on the edge this column aligns on
            if edge == "left":
                d = e["bbox"].x0 - o["bbox"].x0
            else:
                d = e["centre_x"] - o["centre_x"]
            db = e["baseline"] - o["baseline"]
            shrunk = abs(e["size"] - o["size"]) > 0.05
            if abs(d) > TOL_EDGE:
                tag = "SHIFT" if not shrunk else "SHIFT(shrunk)"
                problems.append("%s %s %r %s %+.2fpt" % (tag, kind, e["text"][:28], edge, d))
            if abs(db) > TOL_BASELINE:
                problems.append("SHIFT %s %r baseline %+.2fpt" % (kind, e["text"][:28], db))
            if shrunk:
                notes.append("%r shrunk %.2f->%.2fpt" % (e["text"][:20], o["size"], e["size"]))

            # 3. no overflow past the cell dividers
            left, right = cell_bounds(eseg, e)
            if left is not None and e["bbox"].x0 < left + CELL_MARGIN:
                problems.append("OVERFLOW %s %r past left divider by %.2fpt"
                                % (kind, e["text"][:28], left - e["bbox"].x0))
            if right is not None and e["bbox"].x1 > right - CELL_MARGIN:
                problems.append("OVERFLOW %s %r past right divider by %.2fpt"
                                % (kind, e["text"][:28], e["bbox"].x1 - right))

            # 4. no collision with other text
            for other in espans:
                if other is e:
                    continue
                inter = fitz.Rect(e["bbox"]) & other["bbox"]
                if inter.width > 0.5 and inter.height > 0.5:
                    problems.append("COLLISION %r over %r" % (e["text"][:24], other["text"][:24]))
                    break

        # Model Ref: no original counterpart. Must sit in its own cell,
        # on the page, hitting nothing.
        label = cfg.model_ref_label().lower()
        otexts = {o["text"] for o in ospans}
        refs = [s for s in espans if s["text"].count("-") >= 5 and s["text"] not in otexts]
        for r in refs:
            left, right = cell_bounds(eseg, r)
            if left is not None and r["bbox"].x0 < left + CELL_MARGIN:
                problems.append("OVERFLOW modelref past left divider")
            if right is not None and r["bbox"].x1 > right - CELL_MARGIN:
                problems.append("OVERFLOW modelref past right divider")
            if not ep.rect.contains(r["bbox"]):
                problems.append("OFF PAGE modelref at %s" % r["bbox"])
            for other in espans:
                if other is r or label in other["text"].lower():
                    continue
                inter = fitz.Rect(r["bbox"]) & other["bbox"]
                if inter.width > 0.5 and inter.height > 0.5:
                    problems.append("COLLISION modelref over %r" % other["text"][:24])
                    break
        return problems, notes, len(pairs), len(refs)
    finally:
        od.close()
        ed.close()


# ------------------------------------------------- plotted-from-CAD check
def _fit(p, q):
    """1-D similarity q = s*p + t by least squares."""
    n = len(p)
    mp, mq = sum(p) / n, sum(q) / n
    var = sum((x - mp) ** 2 for x in p)
    if var < 1e-6:
        return 1.0, mq - mp
    s = sum((x - mp) * (y - mq) for x, y in zip(p, q)) / var
    return s, mq - s * mp


def compare_plot(edit_path, plot_path):
    a = fitz.open(edit_path); sa = get_spans(a[0]); a.close()
    b = fitz.open(plot_path); sb = get_spans(b[0]); b.close()
    fields = set(cfg.revision_descriptions().values())

    def is_field(t):
        return bool(NEW_DATE.match(t)) or t.count("-") >= 5 or t in fields

    # anchors: text present exactly once in each, and not something we changed
    ua, ub = {}, {}
    for s in sa:
        if not is_field(s["text"]):
            ua.setdefault(s["text"], []).append(s)
    for s in sb:
        if not is_field(s["text"]):
            ub.setdefault(s["text"], []).append(s)
    common = [t for t, v in ua.items() if len(v) == 1 and len(ub.get(t, [])) == 1]
    if len(common) < 4:
        return ["no fit (%d common anchors)" % len(common)]
    sx, tx = _fit([ua[t][0]["centre_x"] for t in common], [ub[t][0]["centre_x"] for t in common])
    sy, ty = _fit([ua[t][0]["baseline"] for t in common], [ub[t][0]["baseline"] for t in common])

    out = []
    for s in sa:
        if not is_field(s["text"]):
            continue
        cands = [q for q in sb if q["text"] == s["text"]]
        if not cands:
            out.append("MISSING in plot: %r" % s["text"][:30])
            continue
        px, py = sx * s["centre_x"] + tx, sy * s["baseline"] + ty
        d = min(max(abs(q["centre_x"] - px), abs(q["baseline"] - py)) for q in cands)
        if d > TOL_PLOT:
            out.append("PLOT OFFSET %r %.1fpt" % (s["text"][:26], d))
    return out


def main():
    print("Profile : %s" % cfg.active().get("name", "?"))
    print("Original: %s" % ORIG_DIR)
    print("Edited  : %s" % EDIT_DIR)
    print("Plotted : %s" % (PLOT_DIR or "(skipped)"))

    edits = sorted(f for f in os.listdir(EDIT_DIR) if f.lower().endswith(".pdf"))
    print("\nChecking %d edited PDF(s)...\n" % len(edits))

    clean = fields = refs = 0
    bad, plot_bad, align = {}, {}, {}
    for i, f in enumerate(edits, 1):
        orig = os.path.join(ORIG_DIR, f)
        if not os.path.exists(orig):
            bad[f] = ["no original to compare against"]
            continue
        try:
            problems, notes, n_pairs, n_refs = check_sheet(orig, os.path.join(EDIT_DIR, f))
        except Exception as exc:
            bad[f] = ["ERROR %s" % exc]
            continue
        fields += n_pairs
        refs += n_refs
        for n in notes:
            if n.startswith("descriptions "):
                align[n] = align.get(n, 0) + 1
        if PLOT_DIR:
            p = os.path.join(PLOT_DIR, f)
            if os.path.exists(p):
                pp = compare_plot(os.path.join(EDIT_DIR, f), p)
                if pp:
                    plot_bad[f] = pp
        if problems:
            bad[f] = problems
        else:
            clean += 1
        if i % 50 == 0:
            print("  ...%d/%d" % (i, len(edits)), flush=True)

    print("\n--- Geometry vs original ---")
    print("sheets checked : %d" % len(edits))
    print("clean          : %d" % clean)
    print("with problems  : %d" % len(bad))
    print("fields compared: %d replaced + %d model refs" % (fields, refs))
    for k, v in sorted(align.items()):
        print("  %-30s %d sheets" % (k, v))
    for f, ps in sorted(bad.items()):
        print("\n%s" % f)
        for p in ps[:6]:
            print("   %s" % p)
        if len(ps) > 6:
            print("   ... +%d more" % (len(ps) - 6))

    if PLOT_DIR:
        print("\n--- Plotted-from-CAD vs edited PDF ---")
        print("sheets with offsets over %.1fpt: %d" % (TOL_PLOT, len(plot_bad)))
        for f, ps in sorted(plot_bad.items())[:15]:
            print("\n%s" % f)
            for p in ps[:4]:
                print("   %s" % p)


if __name__ == "__main__":
    main()

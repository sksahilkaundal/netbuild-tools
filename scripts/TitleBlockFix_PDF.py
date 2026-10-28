# -*- coding: utf-8 -*-
"""
Fix flattened GA-sheet export PDFs (no AcroForm fields) for three
titleblock defects, via true redaction + re-insertion using PyMuPDF:

1. Revision table rows: "50% Schematic Design [Submission]" / "100%
   Schematic Design Submission" -> SCREAMING CASE description, and the
   DD-Mon-YYYY date -> DD/MM/YYYY (same logic as
   NormalizeRevisionWording_MCP.py for live Revit models).
2. "Model Ref Number:" value (absent on these exports) -> filled by
   matching the sheet's drawing-number zone/level tokens to the federated
   SHEET model that hosts it (routing comes from the active project
   profile). NOT the content-authoring Tier model.
3. The titleblock's bottom "Date:" field (next to Status:/Scale:) ->
   the current/latest revision's date in DD/MM/YYYY.

EXACT-MATCH RULES (measured against the already-correct reference sheet
ProjectC-Studio-DWG-B2B5-GFL-AR-210001_A.pdf, 2026-09-16):

* Dates (schedule rows AND the bottom Date field) are CENTRE-ALIGNED on
  every sheet: across two sheets carrying different strings the bbox
  centres agree to ~0.25pt while the left edges differ by several pt
  (bottom date centre 3086.31 vs 3086.27; rev date 3072.55 vs 3072.48).
  Centre the replacement on the ORIGINAL span's centre.
* The revision DESCRIPTION column is centred on some title block
  variants (750001/300001/B2B5: centres 3192.27 vs 3192.51) and
  LEFT-ALIGNED on others (200001/400002: both rows share x0, 1.4-1.6pt
  inside the divider). The measurement above was taken on a centred
  variant and wrongly generalised: on 110 of 250 sheets the longer
  SCREAMING text then spilled ~10pt over the divider into ISSUED TO.
  infer_desc_alignment() decides per sheet from the original's own rows.
* Place the baseline at the original span's own `origin[1]` from
  get_text("dict"), NOT at a bbox edge. Deriving a baseline from a bbox
  needs the embedded font's metrics and was ~0.8-2.4pt low.
* Use the original span's own `size`, not a hardcoded 8/10.
* Use REAL Arial (C:\\Windows\\Fonts\\arial.ttf), not Helvetica. The two
  are metrically identical (155.144 vs 155.145pt for the 8pt description
  string, so all centring maths is unchanged) but the glyph shapes
  differ, and the surrounding titleblock text is ArialMT.

ROTATION GOTCHA: half of this batch has page.rotation == 90 (portrait
MediaBox + /Rotate 90 to display as landscape A0), half has 0. fitz's
get_text()/insert_text()/draw_rect() all work in the RAW (pre-rotation)
content-stream space, consistently for reading and writing. All geometry
here is computed in VISUAL space and converted to raw only at the final
insert/redact call via page.derotation_matrix. Never hardcode raw
coordinates across a mixed-rotation batch.

Redaction (not a white box) removes the old glyphs from the content
stream; a painted-over box leaves the old text selectable underneath.
All redactions are applied in ONE batch before any insertion, because a
later redaction rect can otherwise wipe out text inserted moments before
for a neighbouring row.

Filename convention comes from the profile (default:
<A>-<B>-<C>-<ZONE>-<LEVEL>-<D>-<DWGNO>_<REV>.pdf).
"""
import fitz
import glob
import os
import re

import TitleBlockFix_Config as cfg

# Set these from the launcher / pipeline. Everything PROJECT-specific
# (zones to skip, model-ref routing, revision wording, filename layout)
# comes from the active profile in TitleBlockFix_Config, so this script is
# generic -- point it at another project by loading another profile.
SRC_FOLDER = ""
# corrected copies go to an "Updated" subfolder next to the source --
# the originals are never touched.
OUT_FOLDER = ""

DRY_RUN = True  # True = report what would change, write nothing

ARIAL_PATH = r"C:\Windows\Fonts\arial.ttf"
FONTNAME = "ARL"  # page-local alias for the embedded Arial

MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}
DATE_RE = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$")

# Model Ref Number has no existing span to copy on a blank sheet, so it is
# anchored off its own "Model Ref Number:" label.
#
# Anchoring off the bottom "Date:" field instead was wrong: 9 sheets in
# this batch (the 410xxx facade sheets and TO00-400002) use a reduced
# titleblock with NO Model Ref Number field at all, and the offset then
# dropped the text into empty space -- 8 of them off the page edge, where
# it was silently clipped. Anchoring to the label means those sheets are
# skipped automatically, because there is nothing to anchor to.
#
# Measured on the reference sheet: label bbox x0=3035.89 baseline=834.890;
# value centre_x=3180.72 baseline=849.899, size 10. These are titleblock
# geometry, not project identity, so they stay here rather than in the
# profile -- override them if a project uses a different titleblock.
MODEL_REF_FROM_LABEL = (144.83, 15.009)  # (centre_x - label_x0, baseline - label_baseline)
MODEL_REF_SIZE = 10.0


def model_ref_for_filename(fname):
    return cfg.model_ref_for_filename(fname)


def convert_date(d):
    parts = d.split("-")
    if len(parts) != 3 or parts[1] not in MONTHS:
        return None
    return "%s/%s/%s" % (parts[0], MONTHS[parts[1]], parts[2])


def to_visual(rect, page):
    return rect * page.rotation_matrix


def to_raw(rect, page):
    return rect * page.derotation_matrix


def to_raw_point(pt, page):
    r = to_raw(fitz.Rect(pt.x, pt.y, pt.x, pt.y), page)
    return fitz.Point(r.x0, r.y0)


# PyMuPDF builds an embedded font's ToUnicode map by reverse-lookup from
# glyph id to codepoint. Arial's cmap points BOTH U+0020/U+00A0 (space,
# no-break space) and U+002D/U+00AD (hyphen, soft hyphen) at the same
# glyph, and the reverse lookup picks the wrong one of each pair. The
# glyphs drawn are correct, but the text becomes un-searchable and
# copy-pastes as "ProjectC\xadStudio\xadBIM..." -- confirmed live, search_for()
# returned 0 hits. Revit's own exported fonts map <0003>-><0020> and
# <0010>-><002D> correctly, so patch ours to match.
_TU_FIXUP = {b"<00a0>": b"<0020>", b"<00ad>": b"<002d>"}
# Match a whole "<src> <dst>" bfchar line, so only the DESTINATION is
# rewritten. A naive replace would also corrupt lines where 00a0/00ad is
# the SOURCE code (e.g. "<00a0> <00e6>").
_TU_LINE = re.compile(rb"^(\s*<[0-9a-fA-F]{4}>\s*)(<[0-9a-fA-F]{4}>)(\s*)$")


def fix_embedded_font_tounicode(doc):
    patched = 0
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Type")[1] != "/Font":
                continue
            base = doc.xref_get_key(xref, "BaseFont")[1]
            tu = doc.xref_get_key(xref, "ToUnicode")
        except Exception:
            continue
        # only our inserted Arial -- never touch Revit's own subsets
        if "Arial Regular" not in base or tu[0] != "xref":
            continue
        tu_xref = int(tu[1].split()[0])
        data = doc.xref_stream(tu_xref)
        lines = []
        for line in data.split(b"\n"):
            m = _TU_LINE.match(line)
            if m and m.group(2).lower() in _TU_FIXUP:
                line = m.group(1) + _TU_FIXUP[m.group(2).lower()] + m.group(3)
                patched += 1
            lines.append(line)
        doc.update_stream(tu_xref, b"\n".join(lines))
    return patched


def vertical_rules(page, y0, y1):
    """X positions (visual space) of column dividers crossing rows y0..y1.

    Clamping a too-wide description against the neighbouring TEXT is not
    enough -- the cell border sits between the two, so text pushed flush
    against the date string still lands on top of the divider (seen live
    on the 200001-series sheets). Clamp to the divider itself.
    """
    xs = set()
    for d in page.get_cdrawings():
        for item in d["items"]:
            if item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            # Transform BEFORE testing the axis: on a rotation==90 page a
            # visually-vertical divider is horizontal in raw space, so
            # testing rawly finds nothing at all.
            a = to_visual(fitz.Rect(p0[0], p0[1], p0[0], p0[1]), page)
            b = to_visual(fitz.Rect(p1[0], p1[1], p1[0], p1[1]), page)
            if abs(a.x0 - b.x0) < 0.01 and abs(a.y0 - b.y0) > 1:
                lo, hi = sorted((a.y0, b.y0))
                # Overlap, not containment: these dividers are drawn as
                # short per-cell segments (one row tall), while the span
                # bbox is the taller font line box, so a containment test
                # matches nothing. Columns line up across rows, so picking
                # up a neighbouring row's segment is harmless -- only the
                # x value is used.
                if hi > y0 and lo < y1:
                    xs.add(round(a.x0, 2))
    return sorted(xs)


def get_spans(page):
    """Every text span with geometry in VISUAL space.

    `origin` is the true baseline point -- the only reliable way to match
    an existing line's vertical position without knowing the embedded
    font's metrics.
    """
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if not text:
                    continue
                bbox_vis = to_visual(fitz.Rect(span["bbox"]), page)
                ox, oy = span["origin"]
                origin_vis = to_visual(fitz.Rect(ox, oy, ox, oy), page)
                out.append({
                    "text": text,
                    "bbox": bbox_vis,
                    "baseline": origin_vis.y0,
                    "centre_x": (bbox_vis.x0 + bbox_vis.x1) / 2.0,
                    "size": span["size"],
                })
    return out


DESC_PAD = 1.5   # pt: a left-aligned schedule cell holds its text this far in


def desc_after(span):
    """The replacement wording for a description span, or None."""
    low = span["text"].lower()
    for prefix, after in cfg.revision_descriptions().items():
        if low.startswith(prefix):
            return after
    return None


def schedule_desc_spans(spans):
    """Description spans that sit on a revision ROW -- one that also holds
    a DD-Mon-YYYY date.

    The title block's own status field ("100% SCHEMATIC DESIGN") starts
    with the same words as a description, and it lives in a much wider,
    differently-aligned cell. Letting it in as a "row" flipped the
    alignment inference on two of five sample sheets.
    """
    rows = {}
    for s in spans:
        rows.setdefault(round(s["baseline"], 1), []).append(s)
    out = []
    for items in rows.values():
        if not any(DATE_RE.match(s["text"]) for s in items):
            continue
        d = next((s for s in items if desc_after(s)), None)
        if d is not None:
            out.append(d)
    return out


def infer_desc_alignment(desc_spans, page):
    """'left' or 'centre': how THIS sheet's revision schedule aligns its
    description column.

    It differs between title block variants. The 200001/400002-style
    schedules are left-aligned (both rows share x0, 1.4-1.6pt inside the
    divider); the 750001/300001/B2B5-style ones are centred (both rows
    share a centre to 0.4pt). Centring the SCREAMING replacement on a
    left-aligned sheet spilled 10pt over the divider into the ISSUED TO
    column -- seen on TO00-400002.

    Two rows settle it for free: whichever edge the rows agree on is the
    alignment. A single row falls back to the cell: nearer the cell
    centre, or nearer the left divider plus padding.
    """
    if len(desc_spans) >= 2:
        x0s = [s["bbox"].x0 for s in desc_spans]
        cxs = [s["centre_x"] for s in desc_spans]
        spread_l = max(x0s) - min(x0s)
        spread_c = max(cxs) - min(cxs)
        if abs(spread_l - spread_c) > 1.0:
            return "left" if spread_l < spread_c else "centre"
    s = desc_spans[0]
    rules = vertical_rules(page, s["bbox"].y0, s["bbox"].y1)
    left = max([x for x in rules if x < s["centre_x"]], default=None)
    right = min([x for x in rules if x > s["centre_x"]], default=None)
    if left is None or right is None:
        return "centre"
    dev_c = abs(s["centre_x"] - (left + right) / 2.0)
    dev_l = abs(s["bbox"].x0 - (left + DESC_PAD))
    return "left" if dev_l < dev_c else "centre"


def plan_replacement(span, new_text, arial, size=None, centre_x=None, baseline=None):
    """Centre `new_text` where `span` was, on the same baseline/size."""
    size = size if size is not None else span["size"]
    centre_x = centre_x if centre_x is not None else span["centre_x"]
    baseline = baseline if baseline is not None else span["baseline"]
    width = arial.text_length(new_text, size)
    return {
        "redact": span["bbox"] if span is not None else None,
        "point": fitz.Point(centre_x - width / 2.0, baseline),
        "text": new_text,
        "size": size,
    }


def fix_titleblock(page, model_ref_text, log, arial):
    spans = get_spans(page)

    # ---- revision rows: spans sharing a baseline form one row ----
    rows = {}
    for s in spans:
        rows.setdefault(round(s["baseline"], 1), []).append(s)

    edits = []
    latest_date = None
    cell_rules = [None]  # lazily filled column-divider positions

    desc_all = schedule_desc_spans(spans)
    desc_align = infer_desc_alignment(desc_all, page) if desc_all else "centre"
    if desc_all:
        log.append("  revision descriptions are %s-aligned on this sheet" % desc_align)

    for baseline in sorted(rows.keys()):
        items = rows[baseline]
        desc_span = None
        after_text = None
        for s in items:
            after_text = desc_after(s)
            if after_text:
                desc_span = s
                break
        if not desc_span:
            continue

        date_span = next((s for s in items if DATE_RE.match(s["text"])), None)
        if not date_span:
            continue
        new_date = convert_date(date_span["text"])
        if not new_date:
            continue

        size = desc_span["size"]
        centre_x = desc_span["centre_x"]
        width = arial.text_length(after_text, size)
        box = desc_span["bbox"]
        rights = [s["bbox"].x0 for s in items if s["bbox"].x0 >= box.x1]

        if desc_align == "left":
            # Keep the left edge exactly where it was; the longer text grows
            # to the right. Shrink only if it would cross the right divider.
            if cell_rules[0] is None:
                cell_rules[0] = vertical_rules(page, box.y0, box.y1)
            div_r = [x for x in cell_rules[0] if x >= box.x1]
            hi = div_r[0] if div_r else (min(rights) if rights else None)
            if hi is not None:
                available = (hi - 2.0) - box.x0
                if width > available > 0:
                    size = size * available / width
                    width = arial.text_length(after_text, size)
                    log.append("    (description shrunk to %.2fpt to fit this "
                               "sheet's narrower column)" % size)
            centre_x = box.x0 + width / 2.0
        else:
            # Centred column. The SCREAMING CASE description is wider than
            # the mixed-case original, so a straight centre on the
            # original's centre can spill into the neighbouring cells.
            # Keep the exact centre where it fits, otherwise slide inside
            # the gap, and only shrink if it still will not fit.
            lefts = [s["bbox"].x1 for s in items if s["bbox"].x1 <= box.x0]
            if lefts and rights and width / 2.0 > min(
                    centre_x - max(lefts), min(rights) - centre_x):
                # Only pay for the line-art scan when the text actually
                # needs constraining -- get_cdrawings() costs ~2s.
                if cell_rules[0] is None:
                    cell_rules[0] = vertical_rules(page, box.y0, box.y1)
                div_l = [x for x in cell_rules[0] if x <= box.x0]
                div_r = [x for x in cell_rules[0] if x >= box.x1]
                lo = (div_l[-1] if div_l else max(lefts)) + 2.0
                hi = (div_r[0] if div_r else min(rights)) - 2.0
                available = hi - lo
                if width > available > 0:
                    size = size * available / width
                    width = arial.text_length(after_text, size)
                    log.append("    (description shrunk to %.2fpt to fit this "
                               "sheet's narrower column)" % size)
                x0 = centre_x - width / 2.0
                if x0 < lo:
                    centre_x = lo + width / 2.0
                elif x0 + width > hi:
                    centre_x = hi - width / 2.0

        log.append("  revision row: '%s' -> %s | '%s' -> '%s'" % (
            date_span["text"], new_date, desc_span["text"], after_text))

        edits.append(plan_replacement(date_span, new_date, arial))
        edits.append(plan_replacement(desc_span, after_text, arial,
                                      size=size, centre_x=centre_x))
        latest_date = new_date  # rows ascend top-to-bottom = A, B, C...

    # ---- bottom "Date:" field ----
    # Locate it by its own "Date:" label (with colon -- the schedule's
    # column header is "Date" without one), then take the nearest date
    # span. Picking "the first date span outside the schedule rows"
    # instead is unsafe on sheets where no schedule row matched.
    schedule_baselines = {round(e["point"].y, 1) for e in edits}
    date_spans = [s for s in spans if DATE_RE.match(s["text"])]
    label = next((s for s in spans if s["text"] == "Date:"), None)
    if label is not None and date_spans:
        bottom_date_span = min(
            date_spans,
            key=lambda s: abs(s["baseline"] - label["baseline"]) + abs(s["centre_x"] - label["centre_x"]),
        )
    else:
        bottom_date_span = next(
            (s for s in date_spans if round(s["baseline"], 1) not in schedule_baselines),
            None,
        )

    if bottom_date_span is not None:
        # Reformat this field's OWN value. It already holds the sheet's
        # current revision date, so deriving it from the schedule is both
        # unnecessary and wrong: on the 410xxx facade sheets the schedule
        # rows run newest-first, so "last row processed" picked the older
        # June date and silently changed 06-Sep-2026 into 16/06/2026.
        new_bottom = convert_date(bottom_date_span["text"]) or latest_date
        if new_bottom:
            log.append("  Bottom Date field: '%s' -> '%s'"
                       % (bottom_date_span["text"], new_bottom))
            edits.append(plan_replacement(bottom_date_span, new_bottom, arial))
        else:
            log.append("  Bottom Date field -- unparseable date, SKIPPED")
    else:
        log.append("  Bottom Date field not found -- SKIPPED")

    # ---- Model Ref Number (no existing span; create one) ----
    label = next((s for s in spans if s["text"].startswith(cfg.model_ref_label())), None)
    if any(s["text"].startswith("ProjectC-Studio-BIM") for s in spans):
        log.append("  Model Ref Number already present -- left untouched")
    elif label is None:
        log.append("  Model Ref Number -- this titleblock has no such field, SKIPPED")
    else:
        centre_x = label["bbox"].x0 + MODEL_REF_FROM_LABEL[0]
        baseline = label["baseline"] + MODEL_REF_FROM_LABEL[1]
        log.append("  Model Ref Number -> '%s'" % model_ref_text)
        edits.append(plan_replacement(
            None, model_ref_text, arial,
            size=MODEL_REF_SIZE, centre_x=centre_x, baseline=baseline))

    if DRY_RUN or not edits:
        return latest_date

    # pass 1: strip every old span in one batch, so no later redaction can
    # erase text inserted for an earlier edit.
    #
    # fill=None paints no white box, and LINE_ART_NONE leaves vector
    # graphics alone. Both matter: a span's bbox is the font LINE box,
    # taller than the glyph ink, so it overlaps the table rules above and
    # below. With the default settings the white fill thinned those rules
    # and the line-art removal clipped them -- visible at high zoom as
    # faded/broken cell borders. Removing only the text leaves the grid
    # untouched and needs no bbox clamping.
    for e in edits:
        if e["redact"] is not None:
            page.add_redact_annot(to_raw(e["redact"], page), fill=None)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE)

    # pass 2: insert the replacements
    page.insert_font(fontname=FONTNAME, fontfile=ARIAL_PATH)
    for e in edits:
        page.insert_text(to_raw_point(e["point"], page), e["text"],
                         fontname=FONTNAME, fontsize=e["size"],
                         rotate=page.rotation)

    fix_embedded_font_tounicode(page.parent)

    return latest_date


def main():
    files = sorted(glob.glob(os.path.join(SRC_FOLDER, "*.pdf")))
    print("Found %d PDF(s) in source folder" % len(files))

    if not DRY_RUN and not os.path.isdir(OUT_FOLDER):
        os.makedirs(OUT_FOLDER)
        print("Created output folder:", OUT_FOLDER)

    arial = fitz.Font(fontfile=ARIAL_PATH)

    n_skip = n_process = n_error = 0

    for fpath in files:
        fname = os.path.basename(fpath)
        model_ref, skip_reason = model_ref_for_filename(fname)
        if model_ref is None:
            n_skip += 1
            continue

        n_process += 1
        log = ["%s  (Model Ref target: %s)" % (fname, model_ref)]
        try:
            doc = fitz.open(fpath)
            fix_titleblock(doc[0], model_ref, log, arial)
            if not DRY_RUN:
                # insert_font() embeds the FULL Arial (~1.2MB per sheet).
                # Subsetting cuts a test sheet from 1.55MB back to 0.36MB
                # (source 0.33MB), leaves the render pixel-identical, keeps
                # the text searchable, and preserves the ToUnicode patch --
                # all verified live. It also matches how Revit embeds its
                # own text (OXQRRV+ArialMT etc. are subsets).
                doc.subset_fonts(verbose=False)
                doc.save(os.path.join(OUT_FOLDER, fname), garbage=4, deflate=True)
            doc.close()
        except Exception as e:
            n_error += 1
            log.append("  ERROR: %s" % e)

        for line in log:
            print(line)

    print("\n--- Summary ---")
    print("Processed: %d, Skipped (per profile / unparseable): %d, Errors: %d"
          % (n_process, n_skip, n_error))
    if DRY_RUN:
        print("DRY_RUN is True -- no files written. Set DRY_RUN = False to apply.")


if __name__ == "__main__":
    main()

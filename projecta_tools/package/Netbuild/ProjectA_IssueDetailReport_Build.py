# -*- coding: utf-8 -*-
"""
ProjectA_IssueDetailReport_Build.py -- build the client-ready ProjectA issue report PDF.

Inputs (BASE): <EXPORT_SUBDIR>/ProjectA_issue_detail_report_<a>_<b>.csv from
ProjectA_IssueExport_Extract.py, core_tagging_completed.csv (ACC id -> index,
level), studio_notes_clean.csv (index -> Studio note, filled by the walkthrough),
snapshots_full/<id>.png and snapshots_after_photos/<id>_photoN.jpeg.

Output: the SUMMARY first (resolved/pending, by ACC status, by tier / model,
movement since PREVIOUS_EXPORT_SUBDIR), then the issue table -- both start with
the report's two title lines (report_heading()) -- then one page per issue
(status badge, fields, description, comments, Studio note, Before/After images),
issues in ACC id order -> OUT_PATH. (Before 2026-10-09 the table came first.) With BY_MODEL_PATH set, a second PDF holds
the same issues grouped by tier / model (BUCKETS order, ACC id order inside a
group): a linked group row per group in the issue table, a band above each
group's first issue page, and PDF bookmarks per group and per issue.
Tier / model numbering is the same everywhere (BUCKET_NO: 01 Basement ... 16
General): the summary's "By tier / model" rows read "NN label" and, when the
row has issues, are a highlighted link -- to the group band in the by
Tier-Model report, to that tier / model's lowest-id issue page in the complete
report; the issue table's Tier / Model column reads "NN short label".

Links: the issue table's ACC ID jumps to that issue's page inside the PDF
(named destination issue_<id>, like ACC's own Contents page); the #ID in each
issue heading opens the issue in ACC (CSV column acc_url, from the extractor;
older CSVs without it simply get no ACC link).

Tier / model (tier_model(), the summary grid and the issue table's Tier / Model
column): a podium-building sheet -DWG-B001..B005- counts under its building and
the combined -DWG-B2B5- sheet under "Buildings B2-B5", whatever the level; a
3D pin counts as "3D (NWD) Overall Model" (.nwd) or "3D (RVT) Model" (.rvt);
only tower / site-wide sheets (T00O, SW00) go by level to Basement, Podium
GF-06 or Tier 01-05.

Normally run through scripts\\ProjectA_IssueReport_Pipeline.py, which sets the
CONFIG globals, NEW_REPORT_CSV and OUT_PATH.
"""
import csv
import functools
import os
import re
from xml.sax.saxutils import escape as xml_escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Flowable, HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

# ----------------------------- CONFIG ---------------------------------
BASE = r"C:\SK\Projects\ProjectA\Issues\260914"
EXPORT_SUBDIR = "20261009"     # the ACC export folder ProjectA_IssueExport_Extract.py wrote into
MAX_ISSUE_ID = None            # e.g. 1164 -> ignore anything newer in the export; None = all
PREVIOUS_EXPORT_SUBDIR = "20261008"   # for the summary page's "movement since" table; "" to skip
# ------------------------------------------------------------------------
OURS_CSV = os.path.join(BASE, "core_tagging_completed.csv")
Studio_NOTES_CSV = os.path.join(BASE, "studio_notes_clean.csv")
BEFORE_DIR = os.path.join(BASE, "snapshots_full")
AFTER_DIR = os.path.join(BASE, "snapshots_after_photos")
NEW_REPORT_CSV = None          # None = the one export CSV in EXPORT_SUBDIR
OUT_PATH = None                # None = BASE\Issue detail-<EXPORT_SUBDIR> (Updated with Current Status).pdf
BY_MODEL_PATH = None           # set -> also a second PDF grouped by tier / model (ID order inside each group)

REPORT_CSV_RE = re.compile(r"ProjectA_issue_detail_report_\d+_\d+\.csv$")
LEVEL_RE = re.compile(r"-(L\d{1,2}|GFL|B\d{2})-")
AUTHOR_DATE_RE = re.compile(r"^(.*?)\s*\(([^)]+)\):\s*(.*)$", re.DOTALL)
RESOLVED_STATUSES = {"completed", "resolved", "closed"}
NO_LEVEL = "General (no level)"
TIERS = [  # (label, first level, last level) -- see the projecta-model-reference-by-tier memory
    ("Basement (B01-B04)", -4, -1),  # basement levels are negative: B02 -> -2 (BA00 model)
    ("Podium (GF-06)", 0, 6), ("Tier 01 (L07-23)", 7, 23), ("Tier 02 (L24-40)", 24, 40),
    ("Tier 03 (L41-58)", 41, 58), ("Tier 04 (L59-75)", 59, 75), ("Tier 05 (L76+)", 76, 99),
]
# podium buildings have their own models: a pin on a B00x sheet never counts in a tower tier
ZONE_RE = re.compile(r"-DWG-([A-Z0-9]{4})-")      # same rule as ProjectA_IssueWalkthrough.bldg_of
BUILDINGS = {"B%03d" % n: "Building B%d (B%03d)" % (n, n) for n in range(1, 6)}
B2B5 = "Buildings B2-B5 (B2B5 sheet)"             # one combined sheet, cannot say which building
NWD = "3D (NWD) Overall Model"                    # pinned in the federated Navisworks model
RVT = "3D (RVT) Model"                            # pinned in a Revit model, not on a sheet
SHOW_IF_USED = {B2B5, NWD, RVT, NO_LEVEL}         # summary rows hidden when they have no issues
SHORT = dict([(t[0], t[0].split(" (")[0]) for t in TIERS] + [("Podium (GF-06)", "Podium GF-06")]
             + [(v, "Bldg B%d" % n) for n, v in enumerate(BUILDINGS.values(), 1)]
             + [(B2B5, "Bldg B2-B5"), (NWD, "3D NWD Overall"), (RVT, "3D RVT model"), (NO_LEVEL, "General")])
BUCKETS = [t[0] for t in TIERS] + list(BUILDINGS.values()) + [B2B5, NWD, RVT, NO_LEVEL]   # summary row order
BUCKET_NO = {label: n for n, label in enumerate(BUCKETS, 1)}   # 01 Basement ... 16 General, in every report
LINK_COLOR = "#5f60ff"         # design\tokens.json "accent" (Autodesk indigo)
STATUS_COLORS = {
    "open": "#d9534f", "in review": "#f0ad4e", "in progress": "#f0ad4e", "pending": "#f0ad4e",
    "completed": "#5cb85c", "resolved": "#5cb85c", "closed": "#5cb85c", "draft": "#999999",
}


def esc(s):
    return xml_escape(s or "")


def status_of(row):
    return (row.get("status") or "").strip()


def acc_link(markup, url):
    """Paragraph markup made a clickable link to the issue in ACC (unchanged when the
    export CSV has no acc_url -- exports extracted before 2026-10-08)."""
    return '<a href="%s" color="%s"><u>%s</u></a>' % (esc(url), LINK_COLOR, markup) if url else markup


def page_anchor(issue_id):
    """Named destination on the issue's page heading; the issue table links to it."""
    return "issue_%s" % issue_id


def page_link(markup, issue_id):
    """Paragraph markup made an in-PDF jump to the issue's page (like ACC's own Contents)."""
    return '<a href="#%s" color="%s"><u>%s</u></a>' % (page_anchor(issue_id), LINK_COLOR, markup)


def _report_csvs(subdir):
    """Sorted ProjectA_issue_detail_report_<a>_<b>.csv names in BASE\\subdir ([] if no folder)."""
    d = os.path.join(BASE, subdir)
    return sorted(f for f in os.listdir(d) if REPORT_CSV_RE.match(f)) if os.path.isdir(d) else []


def _export_csv():
    """The ProjectA_issue_detail_report_<a>_<b>.csv inside EXPORT_SUBDIR (exactly one expected)."""
    d = os.path.join(BASE, EXPORT_SUBDIR)
    hits = _report_csvs(EXPORT_SUBDIR)
    if len(hits) != 1:
        raise SystemExit("expected one ProjectA_issue_detail_report_*.csv in %s, found %s" % (d, hits))
    return os.path.join(d, hits[0])


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_ours():
    """{ACC id: core_tagging row}."""
    return {r["acc_issue_id"].strip(): r for r in read_csv(OURS_CSV) if (r.get("acc_issue_id") or "").strip()}


def load_studio_notes():
    return {r["index"].strip(): r["studio_note"] for r in read_csv(Studio_NOTES_CSV) if r.get("index")}


def load_previous_statuses():
    """{issue_id: status} from PREVIOUS_EXPORT_SUBDIR, or {} if not configured."""
    hits = _report_csvs(PREVIOUS_EXPORT_SUBDIR) if PREVIOUS_EXPORT_SUBDIR else []
    if not hits:
        return {}
    return {r["issue_id"]: r["status"] for r in read_csv(os.path.join(BASE, PREVIOUS_EXPORT_SUBDIR, hits[0]))}


def extract_level(row, our_row):
    lvl = (our_row or {}).get("level", "").strip()
    if lvl:
        return lvl
    m = LEVEL_RE.search(row.get("placement_sheet", "") or "")
    return m.group(1) if m else ""


def tier_of(level):
    """'L47' / 'GFL' / 'L07-L23' -> tier label (first level number decides)."""
    lv = (level or "").upper()
    mb = re.match(r"B(\d{1,2})", lv)
    if lv.startswith("GF"):
        n = 0
    elif mb:
        n = -int(mb.group(1))
    else:
        m = re.search(r"L?(\d{1,2})", lv)
        if not m:
            return NO_LEVEL
        n = int(m.group(1))
    return next((label for label, lo, hi in TIERS if lo <= n <= hi), NO_LEVEL)


def tier_model(row, our_row):
    """Summary bucket of an issue: a podium building sheet (B001-B005, B2B5), a 3D model
    pin (NWD / RVT), else the tower tier of its level (T00O / SW00 sheets)."""
    sheet = row.get("placement_sheet") or ""
    m = ZONE_RE.search(sheet)
    zone = m.group(1) if m else ""
    if zone in BUILDINGS:
        return BUILDINGS[zone]
    if zone == "B2B5":
        return B2B5
    ext = os.path.splitext(sheet)[1].lower()
    if ext == ".nwd":
        return NWD
    if ext == ".rvt":
        return RVT
    return tier_of(extract_level(row, our_row))


# ---------------------------------------------------------------- images
def find_before_image(issue_id):
    p = os.path.join(BEFORE_DIR, "%s.png" % issue_id)
    return p if os.path.exists(p) else None


@functools.lru_cache(maxsize=None)
def _small_gray_signature(path):
    try:
        return tuple(PILImage.open(path).convert("L").resize((32, 32)).getdata())
    except Exception:
        return None


def _images_are_duplicate(path_a, path_b, threshold=8.0):
    sig_a, sig_b = _small_gray_signature(path_a), _small_gray_signature(path_b)
    if sig_a is None or sig_b is None or len(sig_a) != len(sig_b):
        return False
    return sum(abs(a - b) for a, b in zip(sig_a, sig_b)) / float(len(sig_a)) < threshold


def _image_is_blank(path, min_range=8):
    """ACC's PDF export sometimes emits an all-white 800x800 'photo' (7.8 KB)
    ahead of the real attachment -- seen on 14 of 205 issues in the 18 Sep
    export. It is not a duplicate of the pin snapshot, so the duplicate test
    let it through and #1201's real after-photo (photo3) was never shown."""
    try:
        lo, hi = PILImage.open(path).convert("L").getextrema()
        return hi - lo < min_range
    except Exception:
        return False


def find_after_image(issue_id, before_path):
    """First attachment photo that is neither the re-embedded pin snapshot
    (ACC re-embeds it for issues with no real photo) nor a blank page."""
    if not os.path.isdir(AFTER_DIR):
        return None
    prefix = "%s_photo" % issue_id
    for c in sorted(os.path.join(AFTER_DIR, fn) for fn in os.listdir(AFTER_DIR) if fn.startswith(prefix)):
        if before_path and _images_are_duplicate(before_path, c):
            continue
        if not _image_is_blank(c):
            return c
    return None


def img_flowable(path, max_w_mm, max_h_mm):
    try:
        iw, ih = ImageReader(path).getSize()
    except Exception:
        return None
    scale = min(max_w_mm * mm / float(iw), max_h_mm * mm / float(ih))
    return Image(path, width=iw * scale, height=ih * scale)


# ---------------------------------------------------------------- layout
def build_styles():
    styles = getSampleStyleSheet()
    dark, grey = colors.HexColor("#1a1a1a"), colors.HexColor("#555555")
    for name, kw in [
        ("IssueTitle", dict(fontSize=14, leading=17, fontName="Helvetica-Bold", textColor=dark)),
        ("StatusBadge", dict(fontSize=10, leading=12, fontName="Helvetica-Bold", textColor=colors.white, alignment=1)),
        ("FieldLabel", dict(fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=grey)),
        ("FieldValue", dict(fontSize=9, leading=12, fontName="Helvetica", textColor=dark)),
        ("SectionHeader", dict(fontSize=11, leading=14, fontName="Helvetica-Bold", textColor=dark,
                               spaceBefore=8, spaceAfter=4)),
        ("CommentAuthor", dict(fontSize=9, leading=12, fontName="Helvetica-Bold")),
        ("CommentDate", dict(fontSize=7.5, leading=10, fontName="Helvetica-Oblique",
                             textColor=colors.HexColor("#777777"))),
        ("CommentText", dict(fontSize=9, leading=12, fontName="Helvetica", leftIndent=8, spaceAfter=6)),
        ("StudioNote", dict(fontSize=10, leading=15, fontName="Helvetica", textColor=dark,
                         backColor=colors.HexColor("#fff8e1"), borderPadding=12,
                         borderColor=colors.HexColor("#f0c419"), borderWidth=0.75, spaceBefore=4, spaceAfter=4)),
        ("TOCCell", dict(fontSize=7.5, leading=9.5, fontName="Helvetica")),
        ("TOCHeader", dict(fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=colors.white)),
        ("ReportTitle", dict(fontSize=18, leading=22, fontName="Helvetica-Bold", alignment=1)),
        ("ReportSubtitle", dict(fontSize=11, leading=14, fontName="Helvetica", alignment=1, textColor=grey)),
        # by Tier-Model report only: group row in the issue table, group band above a group's first issue
        ("TOCGroup", dict(fontSize=8.5, leading=11, fontName="Helvetica-Bold", textColor=dark)),
        ("GroupBand", dict(fontSize=12, leading=15, fontName="Helvetica-Bold", textColor=dark,
                           backColor=colors.HexColor("#eef0ff"), borderPadding=7,
                           borderColor=colors.HexColor(LINK_COLOR), borderWidth=0.75, spaceAfter=10)),
    ]:
        styles.add(ParagraphStyle(name=name, **kw))
    return styles


def status_color(status):
    return colors.HexColor(STATUS_COLORS.get((status or "").strip().lower(), "#777777"))


def parse_comments(raw):
    """CSV comments column -> [(author, date, text)]."""
    out = []
    for line in (raw or "").split("\n"):
        line = line.strip()
        if line:
            m = AUTHOR_DATE_RE.match(line)
            out.append(tuple(g.strip() for g in m.groups()) if m else ("", "", line))
    return out


def build_issue_page(row, our_row, studio_note, styles):
    issue_id = row["issue_id"]
    status = row.get("status", "") or ""
    header_tbl = Table(
        [[Paragraph('<a name="%s"/>%s: %s' % (page_anchor(issue_id), acc_link("#" + esc(issue_id), row.get("acc_url")),
                                                esc(row.get("title", "") or "")),
                    styles["IssueTitle"]),
          Paragraph(esc(status.upper() or "N/A"), styles["StatusBadge"])]],
        colWidths=[140 * mm, 35 * mm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (1, 0), (1, 0), status_color(status)),
        ("BOX", (1, 0), (1, 0), 0, colors.white),
        ("TOPPADDING", (1, 0), (1, 0), 5),
        ("BOTTOMPADDING", (1, 0), (1, 0), 5),
        ("LEFTPADDING", (1, 0), (1, 0), 4),
        ("RIGHTPADDING", (1, 0), (1, 0), 4),
    ]))
    story = [header_tbl,
             HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc"), spaceBefore=4, spaceAfter=8)]

    field_rows = [("Assigned to", row.get("assigned_to", "")), ("Created by", row.get("created_by", "")),
                  ("Created on", row.get("created_on", "")), ("Due date", row.get("due_date", "")),
                  ("Level", extract_level(row, our_row)), ("Placement sheet", row.get("placement_sheet", "")),
                  ("Description", row.get("description", ""))]
    field_data = [[Paragraph(esc(label), styles["FieldLabel"]), Paragraph(esc(val), styles["FieldValue"])]
                  for label, val in field_rows if val]
    if field_data:
        ftbl = Table(field_data, colWidths=[32 * mm, 143 * mm])
        ftbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ]))
        story += [ftbl, Spacer(1, 6)]

    comments = parse_comments(row.get("comments", ""))
    if comments:
        story.append(Paragraph("Comments", styles["SectionHeader"]))
        for author, date, text in comments:
            if author:
                story.append(Paragraph(esc(author), styles["CommentAuthor"]))
            if date:
                story.append(Paragraph(esc(date), styles["CommentDate"]))
            story.append(Paragraph(esc(text), styles["CommentText"]))

    if studio_note:
        story += [Paragraph("Studio Note", styles["SectionHeader"]), Spacer(1, 4),
                  Paragraph(esc(studio_note), styles["StudioNote"]), Spacer(1, 14)]

    # Before = pin snapshot, After = first real attachment photo; one image -> full width, none -> nothing
    before_path = find_before_image(issue_id)
    images = [p for p in (before_path, find_after_image(issue_id, before_path)) if p]
    if images:
        story.append(Paragraph("Before / After", styles["SectionHeader"]))
        cells = [img_flowable(p, 82, 60) or Paragraph("(image unavailable)", styles["FieldValue"]) for p in images]
        if len(cells) == 2:
            img_tbl = Table([cells], colWidths=[85 * mm, 85 * mm])
            img_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(img_tbl)
        else:
            story.append(cells[0])

    story.append(PageBreak())
    return story


def _grid(data, col_widths, header_bg="#2f4f6f", bold_last=False):
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    st = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
    ]
    if bold_last:
        st += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8edf2")),
               ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
    tbl.setStyle(TableStyle(st))
    return tbl


def build_summary(rows, ours_by_id, styles, targets=None):
    """The summary (the report's first page): totals by ACC status, resolved/pending roll-up, per-tier split,
    and movement since the previous export (when configured). Tier / model rows
    are numbered NN like the by Tier-Model groups; targets = {label: anchor}
    makes a row with issues a highlighted in-PDF link to that anchor."""
    body = lambda s: Paragraph(esc(str(s)), styles["FieldValue"])
    hdr = lambda s: Paragraph(esc(s), styles["TOCHeader"])

    statuses = sorted({status_of(r) for r in rows}, key=lambda s: (s.lower() not in RESOLVED_STATUSES, s))
    total = len(rows)
    resolved = sum(1 for r in rows if status_of(r).lower() in RESOLVED_STATUSES)
    pending = total - resolved
    pct = lambda n: 100.0 * n / total if total else 0

    story = [Paragraph("Summary", styles["ReportTitle"]), Spacer(1, 4),
             Paragraph("ACC status as exported on %s; %d issues (#%s - #%s)" % (
                 EXPORT_SUBDIR, total, rows[0]["issue_id"], rows[-1]["issue_id"]), styles["ReportSubtitle"]),
             Spacer(1, 14)]

    # --- headline roll-up
    data = [[hdr("Total issues"), hdr("Resolved (Completed)"), hdr("Pending (Open + In Review)")],
            [body(total), body("%d  (%.0f%%)" % (resolved, pct(resolved))), body("%d  (%.0f%%)" % (pending, pct(pending)))]]
    story += [_grid(data, [50 * mm, 60 * mm, 65 * mm]), Spacer(1, 14)]

    # --- by ACC status
    story.append(Paragraph("By ACC status", styles["SectionHeader"]))
    data = [[hdr("ACC status"), hdr("Issues"), hdr("Share")]]
    for st in statuses:
        n = sum(1 for r in rows if status_of(r) == st)
        data.append([body(st or "(blank)"), body(n), body("%.0f%%" % (100.0 * n / total))])
    data.append([body("Total"), body(total), body("100%")])
    story += [_grid(data, [70 * mm, 30 * mm, 30 * mm], bold_last=True), Spacer(1, 14)]

    # --- by tier / model x status: tower tiers, podium buildings, 3D model pins
    story.append(Paragraph("By tier / model", styles["SectionHeader"]))
    tier_labels = BUCKETS
    counts = {t: dict.fromkeys(statuses, 0) for t in tier_labels}
    for r in rows:
        counts[tier_model(r, ours_by_id.get(r["issue_id"]))][status_of(r)] += 1
    data = [[hdr("Tier / model")] + [hdr(st or "(blank)") for st in statuses] + [hdr("Pending"), hdr("Total")]]
    for t in tier_labels:
        row_total = sum(counts[t].values())
        if row_total == 0 and t in SHOW_IF_USED:
            continue
        pend = sum(n for st, n in counts[t].items() if st.lower() not in RESOLVED_STATUSES)
        label = "%02d  %s" % (BUCKET_NO[t], esc(t))
        if row_total and (targets or {}).get(t):
            label = '<a href="#%s" color="%s"><u>%s</u></a>' % (targets[t], LINK_COLOR, label)
        data.append([Paragraph(label, styles["FieldValue"])] + [body(counts[t][st]) for st in statuses]
                    + [body(pend), body(row_total)])
    data.append([body("Total")] + [body(sum(counts[t][st] for t in tier_labels)) for st in statuses]
                + [body(pending), body(total)])
    story.append(_grid(data, [50 * mm] + [24 * mm] * (len(statuses) + 2), bold_last=True))

    # --- movement since the previous export
    prev = load_previous_statuses()
    if prev:
        story += [Spacer(1, 14), Paragraph("Movement since the %s export" % PREVIOUS_EXPORT_SUBDIR, styles["SectionHeader"])]
        moves = {}
        for r in rows:
            a, b = prev.get(r["issue_id"]), status_of(r)
            if a is not None and a != b:
                moves[(a, b)] = moves.get((a, b), 0) + 1
        new_ids = [r["issue_id"] for r in rows if r["issue_id"] not in prev]
        data = [[hdr("Change"), hdr("Issues")]]
        data += [[body("%s  ->  %s" % ab), body(n)] for ab, n in sorted(moves.items(), key=lambda kv: -kv[1])]
        data.append([body("Newly in range"), body(len(new_ids))])
        data.append([body("Unchanged"), body(sum(1 for r in rows if prev.get(r["issue_id"]) == status_of(r)))])
        story.append(_grid(data, [80 * mm, 30 * mm]))
        if new_ids:
            story += [Spacer(1, 4), Paragraph("New: " + ", ".join("#" + i for i in new_ids), styles["FieldValue"])]
    return story


def build_toc(rows, ours_by_id, styles, groups=None):
    """Issue table. groups = [(nn, label, rows)] -> a linked group row above each group's issues."""
    cell = lambda s, style="TOCCell": Paragraph(esc(s), styles[style])
    data = [[cell(h, "TOCHeader") for h in
             ("ACC ID", "Title", "Level", "Tier / Model", "Assigned To", "Created By", "Status")]]
    group_rows = []
    for nn, label, members in (groups or [(None, None, rows)]):
        if label:
            group_rows.append(len(data))
            data.append([Paragraph('<a href="#%s" color="%s"><u>%02d  %s</u></a>  -  %d issue%s' % (
                group_anchor(nn), LINK_COLOR, nn, esc(label), len(members), "" if len(members) == 1 else "s"),
                styles["TOCGroup"])] + [""] * 6)
        for row in members:
            our_row = ours_by_id.get(row["issue_id"])
            data.append([Paragraph(page_link(esc(row["issue_id"]), row["issue_id"]), styles["TOCCell"]),
                         cell(row.get("title", "")), cell(extract_level(row, our_row)),
                         cell("%02d %s" % (BUCKET_NO[tier_model(row, our_row)], SHORT[tier_model(row, our_row)])),
                         cell(row.get("assigned_to", "")), cell(row.get("created_by", "")), cell(row.get("status", ""))])
    tbl = Table(data, colWidths=[14 * mm, 37 * mm, 12 * mm, 23 * mm, 30 * mm, 36 * mm, 20 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ] + [c for r in group_rows for c in (("SPAN", (0, r), (-1, r)),
                                         ("BACKGROUND", (0, r), (-1, r), colors.HexColor("#e8ebff")))]))
    return tbl


class Bookmark(Flowable):
    """Zero-size flowable: a PDF outline (bookmark) entry pointing at this spot."""

    def __init__(self, key, title, level=0, show=False):
        Flowable.__init__(self)
        self.key, self.title, self.level, self.show = key, title, level, show

    def wrap(self, avail_w, avail_h):
        return 0, 0

    def draw(self):
        self.canv.bookmarkHorizontal(self.key, 0, 0)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=self.level == 0)
        if self.show:
            self.canv.showOutline()


def group_anchor(nn):
    return "group_%02d" % nn


def model_groups(rows, ours_by_id):
    """[(nn, label, rows sorted by ACC id)] for every tier / model bucket with issues, in summary-row order."""
    by = {}
    for r in rows:
        by.setdefault(tier_model(r, ours_by_id.get(r["issue_id"])), []).append(r)
    return [(nn, label, sorted(by[label], key=lambda r: int(r["issue_id"])))
            for nn, label in enumerate(BUCKETS, 1) if by.get(label)]


def report_heading(rows, styles, by_model=False):
    """The report's first two lines (title + subtitle), on top of the summary and again on top of the issue table."""
    return [Paragraph("ProjectF - Sports Boulevard ProjectA TOWER", styles["ReportTitle"]),
            Paragraph("Issue Detail Report%s - Updated with Current Status (%d Issues)" % (
                " by Tier / Model" if by_model else "", len(rows)), styles["ReportSubtitle"]),
            Spacer(1, 10)]


def write_report(rows, out_path, ours_by_id, note_for, styles, by_model=False):
    """One report PDF: summary (first page), issue table, one page per issue (ACC id order);
    the summary and the table both start with the report's title + subtitle.
    by_model: the same issues grouped by tier / model (summary-row order, ACC id order
    inside a group), with group rows in the table, a band above each group's first
    issue, and PDF bookmarks per group and per issue."""
    if not by_model:
        first = {}
        for r in rows:   # rows are in id order: the first one seen per bucket is its lowest id
            first.setdefault(tier_model(r, ours_by_id.get(r["issue_id"])), page_anchor(r["issue_id"]))
        story = report_heading(rows, styles) + build_summary(rows, ours_by_id, styles, first) + [PageBreak()]
        story += report_heading(rows, styles) + [build_toc(rows, ours_by_id, styles), PageBreak()]
        for row in rows:
            story += build_issue_page(row, ours_by_id.get(row["issue_id"]), note_for(row), styles)
    else:
        groups = model_groups(rows, ours_by_id)
        story = [Bookmark("bm_summary", "Summary", 0, show=True)] + report_heading(rows, styles, by_model=True)
        story += build_summary(rows, ours_by_id, styles, {label: group_anchor(nn) for nn, label, _ in groups})
        story += [PageBreak(), Bookmark("bm_table", "Issue table", 0)] + report_heading(rows, styles, by_model=True)
        story += [build_toc(rows, ours_by_id, styles, groups), PageBreak()]
        for nn, label, members in groups:
            story += [Bookmark("bm_" + group_anchor(nn), "%02d  %s  (%d)" % (nn, label, len(members)), 0),
                      Paragraph('<a name="%s"/>%02d  %s  -  %d issue%s' % (
                          group_anchor(nn), nn, esc(label), len(members), "" if len(members) == 1 else "s"),
                          styles["GroupBand"])]
            for row in members:
                story.append(Bookmark("bm_issue_%s" % row["issue_id"],
                                      "#%s  %s" % (row["issue_id"], (row.get("title") or "")[:70]), 1))
                story += build_issue_page(row, ours_by_id.get(row["issue_id"]), note_for(row), styles)
    SimpleDocTemplate(out_path, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
                      leftMargin=15 * mm, rightMargin=15 * mm).build(story)


def main():
    ours_by_id = load_ours()
    notes_by_index = load_studio_notes()
    note_for = lambda r: notes_by_index.get(((ours_by_id.get(r["issue_id"]) or {}).get("index") or "").strip())
    out_path = OUT_PATH or os.path.join(BASE, "Issue detail-%s (Updated with Current Status).pdf" % EXPORT_SUBDIR)

    all_issues = read_csv(NEW_REPORT_CSV or _export_csv())
    if MAX_ISSUE_ID:
        all_issues = [r for r in all_issues if int(r["issue_id"]) <= MAX_ISSUE_ID]
    all_issues.sort(key=lambda r: int(r["issue_id"]))
    missing_notes = [r["issue_id"] for r in all_issues if not note_for(r)]
    print("issues in export: %d | without a Studio note: %s" % (len(all_issues), missing_notes or "none"))

    styles = build_styles()
    write_report(all_issues, out_path, ours_by_id, note_for, styles)
    print("Wrote:", out_path)
    print("Total issues:", len(all_issues))

    if BY_MODEL_PATH:   # the second report: grouped by tier / model, ACC id order inside each group
        write_report(all_issues, BY_MODEL_PATH, ours_by_id, note_for, styles, by_model=True)
        print("Wrote:", BY_MODEL_PATH)
        for nn, label, members in model_groups(all_issues, ours_by_id):
            print("   %02d  %-30s %4d issues" % (nn, label, len(members)))


if __name__ == "__main__":
    main()

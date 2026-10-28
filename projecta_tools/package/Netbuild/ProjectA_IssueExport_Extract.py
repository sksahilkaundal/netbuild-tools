# -*- coding: utf-8 -*-
"""
ProjectA_IssueExport_Extract.py -- turn an ACC "Issue detail" PDF export (+ its BCF)
into the inputs ProjectA_IssueDetailReport_Build.py needs.

Reads
  ACC_PDF   the ACC Build "Issue detail ... .pdf" export
  BCF_PATH  the matching BCF export(s) -- source of the pin snapshots (its
            snapshot.png is ~70 KB; the same view re-encoded from the PDF is
            1-2 MB and made the report 6x larger). ACC caps a BCF export at
            250 issues, so this may be a list of BCFs (or one string with the
            paths separated by ";"); their snapshots are merged by issue id.

Writes, under BASE (the issue-date folder the report builder reads):
  <EXPORT_SUBDIR>/ProjectA_issue_detail_report_<first>_<last>.csv
      issue_id, title, status, assigned_to, created_by, created_on,
      due_date, placement_sheet, description, comments, photo_count, acc_url
      comments = "Author (Mon D, YYYY, H:MM AM UTC+03:00): text" per line
      acc_url  = the issue's ACC web link (from the PDF heading's link)
  snapshots_full/<id>.png            the pin snapshot (BCF first, PDF fallback)
  snapshots_after_photos/<id>_photoN.jpeg
      photo1 = the pin snapshot again (ACC re-embeds it as an attachment;
      the report builder's duplicate filter drops it), photo2.. = the real
      attachment photos from the "References and Attachments" pages.

PDF layout (ACC Build, Sept 2026): one "Issue detail" page per issue with
label/value pairs, followed by zero or more "References and Attachments"
pages holding the photos and the Comments thread. A page belongs to the
most recent "Issue detail" page before it.

Normally run through scripts\\ProjectA_IssueReport_Pipeline.py, which sets the
ProjectA_* environment variables below. Rebuilt 2026-09-17 after the original
extractor was lost with a cleared scratchpad.
"""
import csv
import os
import re
import zipfile

import pymupdf

# ----------------------------- CONFIG ---------------------------------
BASE = r"C:\SK\Projects\ProjectA\Issues\260914"
EXPORT_SUBDIR = "20261009"
ACC_PDF = os.path.join(BASE, EXPORT_SUBDIR, "Issue detail-260916 to 261008-202610081210.pdf")
BCF_PATH = os.path.join(BASE, EXPORT_SUBDIR, "2026-10-08 16_06 245 Issues-260916 to 261008.bcf")
MAX_ISSUE_ID = None          # e.g. 1164 to ignore anything newer; None = all
# environment overrides, set by ProjectA_IssueReport_Pipeline.py
BASE = os.environ.get("ProjectA_BASE", BASE)
EXPORT_SUBDIR = os.environ.get("ProjectA_EXPORT_SUBDIR", EXPORT_SUBDIR)
ACC_PDF = os.environ.get("ProjectA_ACC_PDF", ACC_PDF)
BCF_PATH = os.environ.get("ProjectA_BCF", BCF_PATH)      # several BCFs: separate with ";"
MAX_ISSUE_ID = int(os.environ["ProjectA_MAX_ISSUE_ID"]) if os.environ.get("ProjectA_MAX_ISSUE_ID") else MAX_ISSUE_ID
# ------------------------------------------------------------------------

FIELDS = ["issue_id", "title", "status", "assigned_to", "created_by", "created_on",
          "due_date", "placement_sheet", "description", "comments", "photo_count", "acc_url"]
LOGO = (178, 63)
PLACEHOLDER = "\ufffd"       # ACC prints an em-dash the PDF font lacks
FOOTER = re.compile(r"^Created by .* with Autodesk.* on .*$")
NOISE = re.compile(r"^(ProjectF - .*|Issue detail - Issue .*|Page \d+ of \d+|References and Attachments|"
                   r"Photos \(\d+\)|image\.png|.*\.(jpe?g|png)|Added as Attachment|Added on .*|Added by .*)$")
DATE_FULL = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M$")
DATE_HEAD = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4},$")
TIME_LINE = re.compile(r"^\d{1,2}:\d{2} [AP]M$")


def clean(s):
    s = (s or "").strip()
    return "" if s == PLACEHOLDER else s


def field(lines, label):
    """Value on the line after `label` (issue page label/value layout)."""
    for i, ln in enumerate(lines[:-1]):
        if ln.strip() == label:
            return clean(lines[i + 1])
    return ""


def parse_issue_page(text):
    lines = text.split("\n")
    m = re.search(r"^#(\d+): (.+)$", text, re.M)
    if not m:
        return None
    row = dict.fromkeys(FIELDS, "")
    title = [m.group(2).strip()]
    for ln in lines[lines.index(m.group(0)) + 1:]:      # long titles wrap
        if ln.strip() in ("Status", "Standard fields", "Type"):   # label order varies
            break
        title.append(ln.strip())
    row["issue_id"], row["title"] = m.group(1), " ".join(t for t in title if t).rstrip(".").strip()
    for key, label in (("status", "Status"), ("assigned_to", "Assigned to"), ("created_by", "Created by"),
                       ("created_on", "Created on"), ("due_date", "Due date"),   # keeps "(N days late)"
                       ("placement_sheet", "Placement")):
        row[key] = field(lines, label)
    # the description can wrap onto several lines, up to the next label
    desc = []
    if "Description" in (ln.strip() for ln in lines):
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "Description")
        for nxt in lines[start + 1:]:
            if nxt.strip() == "Assigned to":
                break
            desc.append(nxt.strip())
    row["description"] = clean(" ".join(d for d in desc if d))
    return row


def issue_stream(pages):
    """All text lines of an issue's pages as one list, page furniture removed."""
    return [ln for text in pages for ln in (s.strip() for s in text.splitlines())
            if ln and not FOOTER.match(ln) and not NOISE.match(ln)]


def parse_comments(lines, authors):
    """-> ["Author (Mon D, YYYY, H:MM AM UTC+03:00): text", ...]

    A comment block is: author line, timestamp, text -- but the timestamp
    may be split over two lines and, at a page break, may come AFTER the
    text. So blocks are delimited by author lines, and the timestamp is
    located anywhere inside the block.
    """
    if "Comments" not in lines:
        return []
    blocks = []
    for ln in lines[lines.index("Comments") + 1:]:
        if ln in authors:
            blocks.append([ln])
        elif blocks:
            blocks[-1].append(ln)
    out = []
    for b in blocks:
        body, date, i = [], "", 1
        while i < len(b):
            if DATE_FULL.match(b[i]) and i + 1 < len(b) and b[i + 1].startswith("UTC"):
                date = "%s %s" % (b[i], b[i + 1]); i += 2; continue
            if DATE_HEAD.match(b[i]) and i + 2 < len(b) and TIME_LINE.match(b[i + 1]) and b[i + 2].startswith("UTC"):
                date = "%s %s %s" % (b[i], b[i + 1], b[i + 2]); i += 3; continue
            body.append(b[i]); i += 1
        out.append("%s (%s): %s" % (b[0], date, clean(" ".join(body))))
    return out


def issue_url(page, issue_id):
    """ACC web link ACC puts on the issue page's "#NNNN: title" heading ('' if none).
    The BCF topic Guid is NOT the ACC issueId, so the PDF is the only source."""
    links = [l for l in page.get_links() if "/issues?issueId=" in (l.get("uri") or "")]
    for l in links:
        if page.get_textbox(l["from"]).strip().startswith("#%s:" % issue_id):
            return l["uri"]
    return links[0]["uri"] if links else ""


def page_images(page):
    """[(xref, w, h)] of real images on the page, in page order, logos dropped."""
    return [(info[0], info[2], info[3]) for info in page.get_images(full=True)
            if (info[2], info[3]) != LOGO and info[2] >= 60 and info[3] >= 60]


def save_image(doc, xref, path):
    pix = pymupdf.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:                      # CMYK -> RGB
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if path.lower().endswith(".png") or not hasattr(pix, "pil_save"):
        pix.save(path)
    else:
        pix.pil_save(path, format="JPEG", quality=90)


def bcf_paths(bcf_path):
    """BCF_PATH as a list: accepts one path, a list, or "a.bcf;b.bcf"."""
    if not bcf_path:
        return []
    if isinstance(bcf_path, str):
        bcf_path = bcf_path.split(";")
    return [p.strip() for p in bcf_path if p and p.strip()]


def bcf_snapshots(bcf_path):
    """{issue index: png bytes} of each topic's snapshot.png, merged over all
    the BCFs (ACC caps one BCF export at 250 issues, so a big export comes in
    several files)."""
    out = {}
    for path in bcf_paths(bcf_path):
        if not os.path.exists(path):
            raise SystemExit("missing BCF: %s" % path)
        z = zipfile.ZipFile(path)
        names = set(z.namelist())
        found = 0
        for markup in [n for n in names if n.endswith("markup.bcf")]:
            idx = re.search(r"<Index>(\d+)</Index>", z.read(markup).decode("utf-8", "replace"))
            snap = markup.rsplit("/", 1)[0] + "/snapshot.png"
            if idx and snap in names:
                if idx.group(1) in out:
                    print("  BCF %s: #%s also in an earlier BCF -- keeping the later one"
                          % (os.path.basename(path), idx.group(1)))
                out[idx.group(1)] = z.read(snap)
                found += 1
        print("BCF %s: %d snapshots" % (os.path.basename(path), found))
    return out


def read_issues(doc):
    """[{row, pin, photos, pages}] in PDF order, each issue with its follow-on pages."""
    issues, current = [], None
    for page in doc:
        text = page.get_text("text")
        if "\nIssue detail\n#" in text or text.startswith("Issue detail\n#"):
            row = parse_issue_page(text)
            # Contents pages also read "Issue detail / #NNNN: title" when the
            # export's running header is plain "Issue detail"; only a real
            # issue page carries a Status value.
            if row is None or not row["status"]:
                continue
            if MAX_ISSUE_ID and int(row["issue_id"]) > MAX_ISSUE_ID:
                current = None
                continue
            row["acc_url"] = issue_url(page, row["issue_id"])
            big = [xref for xref, w, h in page_images(page) if w >= 400]
            current = {"row": row, "pin": big[0] if big else None,
                       "photos": big, "pages": [text]}           # photo1 = pin copy
            issues.append(current)
        elif current is not None:
            current["pages"].append(text)
            for xref, w, h in page_images(page):
                if xref not in current["photos"]:
                    current["photos"].append(xref)
    return issues


def comment_authors(doc, issues):
    """Everyone who created or is assigned an issue in this export, plus the exporter."""
    strip_org = lambda s: re.sub(r"\s*\(.*\)\s*$", "", s).strip()
    authors = {strip_org(it["row"][k]) for it in issues for k in ("created_by", "assigned_to")}
    m = re.search(r"Created by (.+?) with Autodesk", doc[0].get_text("text"))
    if m:
        authors.add(m.group(1).strip())
    authors.discard("")
    return authors


def main():
    before_dir = os.path.join(BASE, "snapshots_full")
    after_dir = os.path.join(BASE, "snapshots_after_photos")
    os.makedirs(before_dir, exist_ok=True)
    os.makedirs(after_dir, exist_ok=True)

    doc = pymupdf.open(ACC_PDF)
    print("PDF: %s (%d pages)" % (os.path.basename(ACC_PDF), len(doc)))
    issues = read_issues(doc)
    authors = comment_authors(doc, issues)
    snaps = bcf_snapshots(BCF_PATH)

    rows, n_pin, n_bcf, n_photos = [], 0, 0, 0
    for it in issues:
        row, iid = it["row"], it["row"]["issue_id"]
        # before: pin snapshot. Prefer the BCF's own snapshot.png (~70 KB) over
        # the same view re-encoded from the PDF (1-2 MB PNG each): with 164
        # issues that difference is a 240 MB report versus ~40 MB.
        before = os.path.join(before_dir, "%s.png" % iid)
        if iid in snaps:
            with open(before, "wb") as f:
                f.write(snaps[iid])
            n_bcf += 1
        elif it["pin"] is not None:
            save_image(doc, it["pin"], before)
            n_pin += 1
        # after: photos, incl. the pin copy as photo1 -- clear this issue's
        # photos from any earlier export first, or a now-removed attachment
        # would linger and be picked up by the report builder
        for stale in os.listdir(after_dir):
            if re.match(r"%s_photo\d+\." % re.escape(iid), stale):
                os.remove(os.path.join(after_dir, stale))
        for k, xref in enumerate(it["photos"], 1):
            save_image(doc, xref, os.path.join(after_dir, "%s_photo%d.jpeg" % (iid, k)))
        n_photos += len(it["photos"])
        row["photo_count"] = str(len(it["photos"]))
        row["comments"] = "\n".join(parse_comments(issue_stream(it["pages"]), authors))
        rows.append(row)

    ids = [int(r["issue_id"]) for r in rows]
    out_csv = os.path.join(BASE, EXPORT_SUBDIR, "ProjectA_issue_detail_report_%d_%d.csv" % (min(ids), max(ids)))
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("issues: %d (#%d..#%d)" % (len(rows), min(ids), max(ids)))
    print("pin snapshots: %d from BCF, %d from PDF (fallback), %d missing" % (n_bcf, n_pin, len(rows) - n_pin - n_bcf))
    print("after photos written: %d" % n_photos)
    print("comments parsed: %d issues with comments" % sum(1 for r in rows if r["comments"]))
    print("ACC links: %d of %d issues" % (sum(1 for r in rows if r["acc_url"]), len(rows)))
    print("CSV: %s" % out_csv)
    return out_csv


if __name__ == "__main__":
    main()

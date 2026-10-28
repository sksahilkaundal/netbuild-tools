# -*- coding: utf-8 -*-
"""
Cross-check the corrected DWGs against the corrected PDFs.

Both pipelines fix the same three titleblock fields but by completely
different means -- the PDF one redacts and re-inserts text at measured
coordinates, the CAD one edits AcDbMText objects in place -- so agreeing
on every field is strong evidence both are right. A disagreement points
at whichever side handled that sheet differently.

Compares, per sheet:
  * every revision row's date + description
  * the bottom "Date:" field
  * the Model Ref Number

The DWG side is read from the batch log (which records exactly what was
written) rather than by reopening 250 drawings in AutoCAD, which would
cost another full pass. Use --spotcheck N to additionally reopen N of the
saved DWGs and confirm the log matches what is actually on disk.
"""
import argparse
import glob
import os
import re
import sys

import fitz

# Set these from the launcher / pipeline.
PDF_DIR = ""
DWG_DIR = ""
CAD_LOG = ""

RE_ROW = re.compile(r"revision row y=[-\d.]+: '([^']+)' -> (\S+) \| '([^']+)' -> '([^']+)'")
RE_BOTTOM = re.compile(r"Bottom Date field: '([^']+)' -> '([^']+)'")
RE_MODELREF = re.compile(r"Model Ref Number -> '([^']+)'")
RE_MODELREF_PRESENT = re.compile(r"Model Ref Number already present")
DATE_NEW = re.compile(r"^\d{2}/\d{2}/\d{4}$")
DESC_NEW = re.compile(r"^\d+% SCHEMATIC DESIGN SUBMISSION$")


def parse_cad_log(path):
    """{stem: {'rows': {date: desc}, 'bottom': str, 'modelref': str}}"""
    out = {}
    cur = None
    for line in open(path, encoding="utf-8", errors="replace"):
        s = line.rstrip()
        if s and not s.startswith(" ") and s.lower().endswith(".dwg") is False and ".dwg" in s.lower():
            cur = os.path.splitext(s.split()[0])[0]
            out[cur] = {"rows": {}, "bottom": None, "modelref": None}
            continue
        if cur is None:
            continue
        m = RE_ROW.search(s)
        if m:
            out[cur]["rows"][m.group(2)] = m.group(4)
            continue
        m = RE_BOTTOM.search(s)
        if m:
            out[cur]["bottom"] = m.group(2)
            continue
        m = RE_MODELREF.search(s)
        if m:
            out[cur]["modelref"] = m.group(1)
    return out


def read_pdf(path):
    doc = fitz.open(path)
    page = doc[0]
    rows, dates, modelref = {}, [], None
    spans = []
    # Half these sheets have page.rotation == 90, where the raw origin[1]
    # runs ALONG the text line rather than across lines -- grouping rows
    # by it finds nothing. Transform to visual space first.
    rot = page.rotation_matrix
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for sp in line.get("spans", []):
                t = sp["text"].strip()
                if not t:
                    continue
                ox, oy = sp["origin"]
                v = fitz.Rect(ox, oy, ox, oy) * rot
                bb = fitz.Rect(sp["bbox"]) * rot
                spans.append((round(v.y0, 1), bb.x0, t))
    doc.close()

    bybase = {}
    for base, x, t in spans:
        bybase.setdefault(base, []).append((x, t))
        if t.startswith("ProjectC-Studio-BIM"):
            modelref = t
        if DATE_NEW.match(t):
            dates.append((base, t))

    for base, items in bybase.items():
        items.sort()
        date = next((t for _, t in items if DATE_NEW.match(t)), None)
        desc = next((t for _, t in items if DESC_NEW.match(t)), None)
        if date and desc:
            rows[date] = desc

    # the bottom Date: field is the date span that is not part of a row
    bottom = None
    row_bases = {b for b, items in bybase.items()
                 if any(DESC_NEW.match(t) for _, t in items)}
    for base, t in dates:
        if base not in row_bases:
            bottom = t
    return {"rows": rows, "bottom": bottom, "modelref": modelref}


_ACAD = []


def read_dwg_rows(path):
    """Revision rows as they actually sit in a saved DWG."""
    if not os.path.exists(path):
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import TitleBlockFix_DWG as m
        import win32com.client
        if not _ACAD:
            _ACAD.append(win32com.client.GetActiveObject("AutoCAD.Application"))
        acad = _ACAD[0]
        for _ in range(8):
            if m.com_retry(lambda: acad.Documents.Count) == 0:
                break
            d = m.com_retry(lambda: acad.Documents.Item(0))
            m.com_retry(lambda: d.Close(False))
        doc = m.com_retry(lambda: acad.Documents.Open(path))
        m.wait_quiescent(acad)
        ps = m.com_retry(lambda: doc.PaperSpace)
        byy = {}
        for i in range(m.com_retry(lambda: ps.Count)):
            e = m.com_retry(lambda: ps.Item(i))
            if m.com_retry(lambda: e.ObjectName) == "AcDbMText":
                byy.setdefault(round(e.InsertionPoint[1], 1), []).append(e.TextString.strip())
        m.com_retry(lambda: doc.Close(False))
        rows = {}
        for _, items in byy.items():
            d = next((t for t in items if DATE_NEW.match(t)), None)
            s = next((t for t in items if DESC_NEW.match(t)), None)
            if d and s:
                rows[d] = s
        return rows
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spotcheck", type=int, default=0,
                    help="reopen N saved DWGs in AutoCAD to confirm the log matches disk")
    args = ap.parse_args()

    cad = parse_cad_log(CAD_LOG)
    print("CAD log entries: %d" % len(cad))

    checked = matched = 0
    problems = []
    for dwg in sorted(glob.glob(os.path.join(DWG_DIR, "*.dwg"))):
        stem = os.path.splitext(os.path.basename(dwg))[0]
        pdf = os.path.join(PDF_DIR, stem + ".pdf")
        if not os.path.exists(pdf):
            problems.append((stem, "no matching PDF in 2_PDF\\Updated"))
            continue
        if stem not in cad:
            problems.append((stem, "no CAD log entry"))
            continue
        checked += 1
        c, p = cad[stem], read_pdf(pdf)

        # A sheet the CAD batch did not need to touch has no rows in the
        # log, while the PDF reader reports what the FILE contains. That
        # asymmetry is not a mismatch -- it means the sheet was already
        # correct (the B2B5 sheets were, in both formats). Read those few
        # DWGs directly instead of flagging them.
        if not c["rows"] and p["rows"]:
            disk = read_dwg_rows(os.path.join(DWG_DIR, stem + ".dwg"))
            if disk is None:
                problems.append((stem, "no CAD edits logged; could not read DWG to confirm"))
                continue
            c = dict(c, rows=disk)

        issues = []
        if c["rows"] != p["rows"]:
            only_cad = {k: v for k, v in c["rows"].items() if p["rows"].get(k) != v}
            only_pdf = {k: v for k, v in p["rows"].items() if c["rows"].get(k) != v}
            issues.append("rows differ: CAD=%s PDF=%s" % (only_cad, only_pdf))
        if c["bottom"] and p["bottom"] and c["bottom"] != p["bottom"]:
            issues.append("bottom date CAD=%s PDF=%s" % (c["bottom"], p["bottom"]))
        if c["modelref"] and p["modelref"] and c["modelref"] != p["modelref"]:
            issues.append("model ref CAD=%s PDF=%s" % (c["modelref"], p["modelref"]))

        if issues:
            problems.append((stem, "; ".join(issues)))
        else:
            matched += 1

    print("\n--- DWG vs PDF ---")
    print("compared : %d" % checked)
    print("identical: %d" % matched)
    print("mismatch : %d" % len(problems))
    for stem, msg in problems[:40]:
        print("   %-44s %s" % (stem, msg))
    if len(problems) > 40:
        print("   ... and %d more" % (len(problems) - 40))

    if args.spotcheck:
        spotcheck(sorted(cad)[:: max(1, len(cad) // args.spotcheck)][:args.spotcheck])


def positional_check(stem, dwg_points, pdf_path):
    """Confirm the Model Ref sits in the same place in both formats.

    The DWG paperspace origin and the PDF page origin do not coincide --
    the Revit-exported PDF carries a plot offset of roughly 22mm in x --
    so the two coordinate sets cannot be compared directly. Instead derive
    that per-sheet offset from a landmark present in BOTH (the bottom
    Date: field), then predict where the Model Ref should land in the PDF
    and compare against where it actually is.
    """
    MM = 72.0 / 25.4
    if not (dwg_points.get("bottom") and dwg_points.get("modelref")):
        return None
    doc = fitz.open(pdf_path)
    page = doc[0]
    h = page.rect.height
    pdf_bottom = pdf_ref = None
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for sp in line.get("spans", []):
                t = sp["text"].strip()
                if t.startswith("ProjectC-Studio-BIM"):
                    pdf_ref = (sp["bbox"][0], sp["bbox"][1])
                elif DATE_NEW.match(t) and sp["size"] > 9:
                    pdf_bottom = (sp["bbox"][0], sp["bbox"][1])
    doc.close()
    if not (pdf_bottom and pdf_ref):
        return None

    dx_dwg = (dwg_points["modelref"][0] - dwg_points["bottom"][0]) * MM
    dy_dwg = -(dwg_points["modelref"][1] - dwg_points["bottom"][1]) * MM  # PDF y grows downward
    dx_pdf = pdf_ref[0] - pdf_bottom[0]
    dy_pdf = pdf_ref[1] - pdf_bottom[1]
    return (dx_pdf - dx_dwg, dy_pdf - dy_dwg)


def spotcheck(stems):
    """Reopen saved DWGs and confirm the log matches what is on disk."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import TitleBlockFix_DWG as m
    import win32com.client
    acad = win32com.client.GetActiveObject("AutoCAD.Application")
    cad = parse_cad_log(CAD_LOG)
    print("\n--- spot-check (reading %d saved DWGs) ---" % len(stems))
    for stem in stems:
        path = os.path.join(DWG_DIR, stem + ".dwg")
        if not os.path.exists(path):
            print("   %-44s MISSING" % stem)
            continue
        doc = m.com_retry(lambda: acad.Documents.Open(path))
        m.wait_quiescent(acad)
        ps = m.com_retry(lambda: doc.PaperSpace)
        n = m.com_retry(lambda: ps.Count)
        found_rows, found_ref = {}, None
        texts, points = [], {}
        for i in range(n):
            e = m.com_retry(lambda: ps.Item(i))
            if m.com_retry(lambda: e.ObjectName) == "AcDbMText":
                t = e.TextString.strip()
                ip = e.InsertionPoint
                texts.append((round(ip[1], 1), t))
                if t.startswith("ProjectC-Studio-BIM"):
                    points["modelref"] = (ip[0], ip[1])
                elif DATE_NEW.match(t) and e.Height > 2.0:
                    points["bottom"] = (ip[0], ip[1])
        m.com_retry(lambda: doc.Close(False))
        byy = {}
        for y, t in texts:
            byy.setdefault(y, []).append(t)
            if t.startswith("ProjectC-Studio-BIM"):
                found_ref = t
        for y, items in byy.items():
            d = next((t for t in items if DATE_NEW.match(t)), None)
            s = next((t for t in items if DESC_NEW.match(t)), None)
            if d and s:
                found_rows[d] = s
        exp = cad.get(stem, {})
        ok = (found_rows == exp.get("rows")) and (found_ref == exp.get("modelref"))
        pos = positional_check(stem, points, os.path.join(PDF_DIR, stem + ".pdf"))
        pos_txt = ""
        if pos:
            pos_txt = "  | Model Ref offset vs PDF: dx=%+.2fpt dy=%+.2fpt" % pos
        print("   %-44s %s%s" % (stem, "OK" if ok else
                                 "DIFFERS disk_rows=%s disk_ref=%s" % (found_rows, found_ref),
                                 pos_txt))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Export a building's Podium GA sheets (Part Plans / Elevations / Sections)
to PDF (and optionally CAD/DWG), filtered to only sheets whose "Current
Revision Date" matches the requested issue date — skipping any stale or
superseded sheets that don't carry that revision.

REUSABLE TEMPLATE — edit only the CONFIG block below for a new run.
See [[podium-sheet-export-by-revision-prompt-template]] for the matching
fill-in-the-blanks chat prompt, and [[revit-duplicate-sheets-revision-gotcha]]
for why the revision-date filter matters in these ProjectA models (some
buildings carry a superseded duplicate sheet — same Sheet Name, SheetNumber
suffixed "(1)", 1:200 scale referencing a "_Linked View" — alongside the
real current 1:100 sheet; only the one with the matching Current Revision
Date is correct).

Output layout (created if missing), under BASE_OUTPUT_FOLDER:
    PDF\03_Podium Building Part Plans (1-100)\<filename>.pdf
    PDF\04_Podium Building Elevations (1-100)\<filename>.pdf
    PDF\05_Podium Building Sections (1-100)\<filename>.pdf
    CAD\03_Podium Building Part Plans (1-100)\<filename>.dwg   (if EXPORT_CAD)
    CAD\04_Podium Building Elevations (1-100)\<filename>.dwg
    CAD\05_Podium Building Sections (1-100)\<filename>.dwg

A sheet is routed to Part Plans / Elevations / Sections by the ViewType
of its first placed view (FloorPlan -> Part Plans, Elevation -> Elevations,
Section -> Sections). Sheets with none of those view types are skipped.

Filename = the 7 SBFX_SHEET_01..07 parameters joined with "-", e.g.
    ProjectC-Studio-DWG-B001-GFL-AR-210001
This must match the Drawing Number shown on the titleblock (see the
project's "Change Parameter Values" / titleblock parameter mapping) —
same string for PDF and DWG, differing only by extension.

Filename suffix = "_" + the sheet's own "Current Revision" parameter
(the letter being issued, e.g. A/B/C/D/E/F) — read PER SHEET, never a
fixed string like "_Current Revision". Two sheets matching the same
REVISION_DATE_FILTER can still carry different revision letters.

Run this via the Revit MCP execute_revit_code tool ONE SHEET AT A TIME —
see [[revit-pdf-cad-export-mcp-technique]] for why (multi-sheet loops in a
single call reliably time out the MCP round trip past ~60s, and the MCP
channel can return a STALE result from a previous call instead of hanging;
always verify the output file landed on disk rather than trusting the
printed return value). Run as a single pyRevit button/script it is fine
to loop over every match in one execution.

CAD (DWG) export dumps hatch-pattern (FP_*.pat), plot-config (.pcp) and
embedded titleblock logo (.jpg/.png) files into the destination folder as
byproducts — this script does NOT clean those up automatically since it
runs one export per invocation; sweep them with e.g.
    rm -f "<folder>"/FP_*.pat "<folder>"/*.pcp "<folder>"/*.jpg "<folder>"/*.png
after a batch of DWG exports.
"""
from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewSheet, ElementId,
    PDFExportOptions, ExportPaperFormat, PaperPlacementType, ZoomType,
    DWGExportOptions, ACADVersion,
)
from System.Collections.Generic import List
import os

doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
BASE_OUTPUT_FOLDER = r"C:\SK\Projects\ProjectA\Plot\20260903"
REVISION_DATE_FILTER = "06-Sep-2026"   # must appear in "Current Revision Date"; None = no filter

EXPORT_PDF = True
EXPORT_CAD = False   # DWG export; leave off unless explicitly requested

SBFX_PARAM_NAMES = [
    "SBFX_SHEET_01_Project ID/WorkPackage Code",
    "SBFX_SHEET_02_Originating Org Code",
    "SBFX_SHEET_03_Drawing Type",
    "SBFX_SHEET_04_Location/Zone",
    "SBFX_SHEET_05_Level Code",
    "SBFX_SHEET_06_Discipline Code",
    "SBFX_SHEET_07_Number",
]

SUBFOLDER_BY_VIEWTYPE = {
    "FloorPlan": "03_Podium Building Part Plans (1-100)",
    "Elevation": "04_Podium Building Elevations (1-100)",
    "Section": "05_Podium Building Sections (1-100)",
}

DRY_RUN = True   # True = list what would be exported, no files written
# ------------------------------------------------------------------------


def sheet_filename(sheet):
    vals = []
    for n in SBFX_PARAM_NAMES:
        p = sheet.LookupParameter(n)
        vals.append(p.AsString() if p else "")
    base = "-".join(vals)
    rev = sheet.LookupParameter("Current Revision")
    rev_letter = rev.AsString() if rev else ""
    return base + ("_" + rev_letter if rev_letter else "")


def sheet_primary_viewtype(sheet):
    # Skip Legend/Schedule views (notes/legends often placed alongside the
    # real content view, e.g. "Studio_Elevation Legend" on every Elevation/
    # Section sheet) -- return the first placed view whose ViewType is one
    # we actually route (FloorPlan/Elevation/Section). GetAllPlacedViews()
    # order is not guaranteed to put the "real" view first -- confirmed live
    # 2026-09-16 on ProjectC-Studio-BIM-B001-ZZZ-BM-950001, where taking the raw
    # first view silently dropped every Elevation/Section sheet (matched
    # Legend instead, which isn't in SUBFOLDER_BY_VIEWTYPE, so they were
    # skipped with no error).
    for vid in sheet.GetAllPlacedViews():
        v = doc.GetElement(vid)
        if v is None:
            continue
        vt = str(v.ViewType)
        if vt in SUBFOLDER_BY_VIEWTYPE:
            return vt
    return None


def export_pdf(sheet, folder, fname):
    if not os.path.isdir(folder):
        os.makedirs(folder)
    ids = List[ElementId]([sheet.Id])
    opts = PDFExportOptions()
    opts.FileName = fname
    opts.PaperFormat = ExportPaperFormat.ISO_A0
    opts.PaperPlacement = PaperPlacementType.Center
    opts.ZoomType = ZoomType.Zoom
    opts.ZoomPercentage = 100
    opts.HideCropBoundaries = True
    opts.HideScopeBoxes = True
    opts.HideUnreferencedViewTags = True
    opts.HideReferencePlane = True
    doc.Export(folder, ids, opts)


def export_dwg(sheet, folder, fname):
    if not os.path.isdir(folder):
        os.makedirs(folder)
    ids = List[ElementId]([sheet.Id])
    opts = DWGExportOptions()
    opts.MergedViews = True   # flattens linked-model geometry, no external references
    opts.FileVersion = ACADVersion.Default
    doc.Export(folder, fname, ids, opts)


all_sheets = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()

candidates = []
for s in all_sheets:
    if s.IsPlaceholder:
        continue
    rp = s.LookupParameter("Current Revision Date")
    rdate = rp.AsString() if rp else None
    if REVISION_DATE_FILTER and (not rdate or REVISION_DATE_FILTER not in rdate):
        continue
    vt = sheet_primary_viewtype(s)
    subfolder = SUBFOLDER_BY_VIEWTYPE.get(vt)
    if subfolder is None:
        continue
    candidates.append((s, subfolder, sheet_filename(s)))

print("Matched %d sheet(s) with revision date %r:" % (len(candidates), REVISION_DATE_FILTER))
for s, subfolder, fname in candidates:
    print("  %-20s -> %-45s %s" % (s.SheetNumber, subfolder, fname))

if DRY_RUN:
    print("DRY_RUN is True — no files exported. Set DRY_RUN = False to run for real.")
else:
    # Export ALL PDFs first, then ALL DWGs -- not interleaved per-sheet.
    # Standing order confirmed by user 2026-09-16: PDF pass completes fully
    # before the CAD pass starts, for every model in a run.
    if EXPORT_PDF:
        for s, subfolder, fname in candidates:
            export_pdf(s, os.path.join(BASE_OUTPUT_FOLDER, "PDF", subfolder), fname)
            print("PDF done:", fname)
    if EXPORT_CAD:
        for s, subfolder, fname in candidates:
            export_dwg(s, os.path.join(BASE_OUTPUT_FOLDER, "CAD", subfolder), fname)
            print("DWG done:", fname)

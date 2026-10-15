# -*- coding: utf-8 -*-
"""
Export the ProjectA Master/Site-Wide model's ("SW00", document
ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001) GA sheets to PDF (and optionally CAD/DWG),
filtered to only sheets whose "Current Revision Date" matches the requested
issue date -- same revision-date-filter idea as
export_podium_sheets_by_revision.py, but routing is by the sheet's
"Studio_03 - Browser Filter" parameter value (NOT by placed ViewType, since
this model groups sheets across different drawing types under a shared
project-wide GA-plan filter, not per-building).

IMPORTANT gotcha (confirmed live 2026-09-16): the parameter is named
"Studio_03 - Browser Filter" on sheets -- the plain name "Browser Filter" does
NOT exist as a parameter and returns nothing from LookupParameter. Always
verify the real parameter name on one sheet's Parameters collection before
assuming a name from a verbal instruction.

IMPORTANT gotcha #2: "Current Revision Date" format is NOT consistent across
models. On this SW00/BM-discipline model it reads DD/MM/YYYY (e.g.
"06/09/2026"), not DD-Mon-YYYY (e.g. "06-Sep-2026") like some other models.
Always print a few real values live before hardcoding REVISION_DATE_FILTER.

REUSABLE TEMPLATE -- edit only the CONFIG block below for a new run.
See [[export-master-ga-sheets-by-browser-filter-script]] memory.

Output layout (created if missing), under BASE_OUTPUT_FOLDER:
    PDF\01_GA Plans (1-500) - Site\<filename>.pdf
    PDF\02_GA Plans B2 B5 (1-200)\<filename>.pdf
    CAD\01_GA Plans (1-500) - Site\<filename>.dwg   (if EXPORT_CAD)
    CAD\02_GA Plans B2 B5 (1-200)\<filename>.dwg

Filename = the 7 SBFX_SHEET_01..07 parameters joined with "-", suffixed with
"_" + that sheet's own "Current Revision" letter, same convention as the
Podium script -- read PER SHEET, never hardcoded.

Export order: ALL PDFs first, then ALL DWGs (standing rule, not interleaved
per-sheet) -- confirmed by user 2026-09-16.

Run via Revit MCP execute_revit_code. Batching multiple sheets in one call
is fine and often completes despite the tool reporting a 60s timeout -- the
export keeps running in Revit after the MCP round trip times out. ALWAYS
verify results by listing the actual output folder on disk (excluding
FP_*.pat/*.pcp/*.jpg/*.png byproducts), never trust the printed return
value, which can also be STALE (echoing a previous call's output) -- see
[[revit-pdf-cad-export-mcp-technique]]. If a batch call genuinely stalls
(nothing new appears on disk after ~20-30s of polling), fall back to
submitting the remaining sheets one at a time.

CAD (DWG) export dumps hatch-pattern (FP_*.pat), plot-config (.pcp) and
embedded titleblock logo (.jpg/.png) files into the destination folder as
byproducts -- sweep them after a batch of DWG exports:
    rm -f "<folder>"/FP_*.pat "<folder>"/*.pcp "<folder>"/*.jpg "<folder>"/*.png
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
BASE_OUTPUT_FOLDER = r"C:\SK\Projects\ProjectA\Plot\20260916"
REVISION_DATE_FILTER = "06/09/2026"   # DD/MM/YYYY on this model -- verify live per model!

EXPORT_PDF = True
EXPORT_CAD = True

SBFX_PARAM_NAMES = [
    "SBFX_SHEET_01_Project ID/WorkPackage Code",
    "SBFX_SHEET_02_Originating Org Code",
    "SBFX_SHEET_03_Drawing Type",
    "SBFX_SHEET_04_Location/Zone",
    "SBFX_SHEET_05_Level Code",
    "SBFX_SHEET_06_Discipline Code",
    "SBFX_SHEET_07_Number",
]

BROWSER_FILTER_PARAM = "Studio_03 - Browser Filter"

# Browser Filter value -> output subfolder. Add more mappings here if the
# master model has other GA-plan filter groups to export later (this run
# only covers the two the user asked for).
SUBFOLDER_BY_BROWSER_FILTER = {
    "Site": "01_GA Plans (1-500) - Site",
    "B2 B5_1-200": "02_GA Plans B2 B5 (1-200)",
}

# Sheet Names to always exclude from the "Site" filter group, regardless of
# revision date (Solar Shading sheets and the overview "Site Plan" sheet
# are not part of this GA-plan export set).
EXCLUDE_SHEET_NAMES = {"Solar Shading 01", "Solar Shading 02", "Site Plan"}

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
    opts.MergedViews = True
    opts.FileVersion = ACADVersion.Default
    doc.Export(folder, fname, ids, opts)


all_sheets = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()

candidates = []
for s in all_sheets:
    if s.IsPlaceholder:
        continue
    if s.Name in EXCLUDE_SHEET_NAMES:
        continue
    bf = s.LookupParameter(BROWSER_FILTER_PARAM)
    bfv = bf.AsString() if bf else None
    subfolder = SUBFOLDER_BY_BROWSER_FILTER.get(bfv)
    if subfolder is None:
        continue
    rp = s.LookupParameter("Current Revision Date")
    rdate = rp.AsString() if rp else None
    if REVISION_DATE_FILTER and (not rdate or REVISION_DATE_FILTER not in rdate):
        continue
    candidates.append((s, subfolder, sheet_filename(s)))

print("Matched %d sheet(s) with revision date %r:" % (len(candidates), REVISION_DATE_FILTER))
for s, subfolder, fname in candidates:
    print("  %-20s -> %-45s %s" % (s.SheetNumber, subfolder, fname))

if DRY_RUN:
    print("DRY_RUN is True — no files exported. Set DRY_RUN = False to run for real.")
else:
    # Export ALL PDFs first, then ALL DWGs (standing order, not interleaved).
    if EXPORT_PDF:
        for s, subfolder, fname in candidates:
            export_pdf(s, os.path.join(BASE_OUTPUT_FOLDER, "PDF", subfolder), fname)
            print("PDF done:", fname)
    if EXPORT_CAD:
        for s, subfolder, fname in candidates:
            export_dwg(s, os.path.join(BASE_OUTPUT_FOLDER, "CAD", subfolder), fname)
            print("DWG done:", fname)

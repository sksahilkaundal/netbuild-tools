# -*- coding: utf-8 -*-
"""
Title Block Fix pipeline for an already-exported issue set.

Fixes three title block fields on exported PDF and DWG sheets, then
cross-verifies the two against each other:

  Step 1  PDF  -> <pdf folder>\\Updated   (TitleBlockFix_PDF.py)
  Step 2  CAD  -> <dwg folder>\\Updated   (TitleBlockFix_DWG.py, AutoCAD open)
  Step 3  verify PDF vs DWG               (TitleBlockFix_Verify.py)

The three fields, on every sheet that has them:
  * revision rows: description -> SCREAMING CASE, DD-Mon-YYYY -> DD/MM/YYYY
  * the title block's bottom "Date:" field -> DD/MM/YYYY
  * "Model Ref Number" -> the model that hosts the sheet

PROJECT-AGNOSTIC. Everything project-specific -- folder names, filename
layout, zones to skip, revision wording, model-ref routing -- lives in a
JSON profile under profiles\\, so another project needs a new profile, not
a code change. See TitleBlockFix_Config.py.

Steps are independent: run any one alone. Step 3 needs Steps 1 and 2 to
have run for real (it reads the CAD log Step 2 writes).

WHY BOTH FORMATS AND A CROSS-CHECK: the two fixers share no code. The PDF
one redacts text and re-inserts it at measured coordinates; the CAD one
edits AcDbMText objects in place. Agreement between them is real evidence.
On the first full run it caught three defects invisible in the output
itself -- see below.

------------------------------------------------------------------
HARD-WON, DO NOT REGRESS (each of these shipped a wrong file once)
------------------------------------------------------------------
1. ANCHOR ON THE FIELD'S OWN LABEL, NOT A CONVENIENT NEIGHBOUR.
   Model Ref Number was first anchored off the bottom "Date:" field.
   9 sheets used a reduced title block with no Model Ref field at all, so
   the value was written into empty space -- 8 of them off the page edge,
   silently clipped. Anchoring to the "Model Ref Number" label makes those
   sheets skip themselves. In DWG the label lives inside the title block
   BLOCK DEFINITION, not PaperSpace, so it must be looked for there.

2. NEVER DERIVE A FIELD'S VALUE FROM ROW ORDER.
   The bottom Date: field was first set from "the last revision row
   processed". Some sheets list revisions newest-first, so that wrote the
   June date onto a sheet whose current revision was September. The field
   already holds the right date -- only reformat it.

3. MTEXT KEEPS ITS OLD WRAP WIDTH (CAD).
   A short original ("50% Schematic Design", Width=31.05) wraps the longer
   SCREAMING replacement onto a second line, colliding with the row below.
   Set Width = 0 (no wrap) after changing the text.

4. TRANSFORM BEFORE TESTING AN AXIS (PDF).
   Half a batch can have page.rotation == 90. fitz works in RAW
   pre-rotation space, where a visually-vertical line is horizontal and a
   text baseline runs along the wrong axis. Detecting column dividers,
   grouping rows and placing text all broke differently until each one
   transformed to visual space FIRST.

5. ALIGNMENT IS PER FIELD AND PER TITLE BLOCK VARIANT -- MEASURE IT.
   Dates are centred everywhere; the revision DESCRIPTION column is
   centred on some variants and LEFT-aligned on others (200001/400002).
   Generalising "centre" from one sheet spilled the longer SCREAMING
   text ~10pt over the divider on 110 of 250 sheets -- and the PDF-vs-CAD
   VALUE check passed that batch. infer_desc_alignment() reads the
   original's own rows; TitleBlockFix_VerifyGeometry.py checks the edge
   the column actually aligns on. Run it after every PDF batch.

6. USE THE SPAN'S OWN `origin` FOR THE BASELINE, AND ITS OWN `size`.
   A bbox-derived baseline needs the embedded font's metrics and landed
   0.8-2.4pt low.

7. EMBED REAL ARIAL, THEN PATCH ITS ToUnicode.
   Arial maps space/no-break-space and hyphen/soft-hyphen to the same
   glyph; PyMuPDF's reverse lookup picks the wrong one, so the text
   renders correctly but is un-searchable. Subset the font afterwards: a
   full embed adds ~1.2MB per sheet.

8. THE SCHEDULE DRIFTS, THE TITLE BLOCK DOES NOT.
   Title block fields sit at byte-identical PaperSpace coordinates across
   sheets; the revision schedule moves ~0.7mm and changes layer name.
   Anchor to the title block.
"""
import os
import sys

# ----------------------------- CONFIG ---------------------------------
ISSUE_FOLDER = r"C:\Users\user\Downloads\New folder (4)"
PROFILE = "ProjectA"        # profiles\<name>.json -- everything project-specific

RUN_PDF = True
RUN_CAD = True         # requires AutoCAD running with no open drawings
RUN_PLOT = False       # optional: plot PDFs back out of the corrected DWGs,
                       # for visual checking only. Slow. Not the deliverable.
RUN_VERIFY = True

DRY_RUN = True         # True = report only, write nothing
# ------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import TitleBlockFix_Config as cfg


def main():
    cfg.ensure_profiles(HERE)
    cfg.set_active(cfg.load(HERE, PROFILE))

    pdf_dir = os.path.join(ISSUE_FOLDER, cfg.folder("pdf"))
    dwg_dir = os.path.join(ISSUE_FOLDER, cfg.folder("dwg"))
    out_sub = cfg.folder("output")
    cad_log = os.path.join(ISSUE_FOLDER, "_titleblockfix_cad.log")

    print("Issue folder :", ISSUE_FOLDER)
    print("Profile      :", cfg.active().get("name", PROFILE))
    print("DRY_RUN      :", DRY_RUN)

    if RUN_PDF:
        print("\n" + "=" * 70)
        print("Step 1  PDF title block fix")
        print("=" * 70)
        import TitleBlockFix_PDF as pdffix
        pdffix.SRC_FOLDER = pdf_dir
        pdffix.OUT_FOLDER = os.path.join(pdf_dir, out_sub)
        pdffix.DRY_RUN = DRY_RUN
        pdffix.main()

    if RUN_CAD:
        print("\n" + "=" * 70)
        print("Step 2  CAD title block fix  (AutoCAD open, no drawings)")
        print("=" * 70)
        import io
        from contextlib import redirect_stdout
        import TitleBlockFix_DWG as dwgfix
        dwgfix.SRC_FOLDER = dwg_dir
        dwgfix.OUT_FOLDER = os.path.join(dwg_dir, out_sub)
        dwgfix.DRY_RUN = DRY_RUN
        buf = io.StringIO()
        with redirect_stdout(buf):
            dwgfix.main()
        print(buf.getvalue())
        if not DRY_RUN:
            with open(cad_log, "w", encoding="utf-8") as f:
                f.write(buf.getvalue())      # Step 3 reads this

    if RUN_PLOT:
        print("\n" + "=" * 70)
        print("Step 2b  plot PDFs from the corrected CAD  (visual check only)")
        print("=" * 70)
        import TitleBlockFix_Plot as plot
        plot.SRC_FOLDER = os.path.join(dwg_dir, out_sub)
        plot.OUT_FOLDER = os.path.join(ISSUE_FOLDER, cfg.folder("plot"))
        plot.DRY_RUN = DRY_RUN
        plot.main()

    if RUN_VERIFY:
        print("\n" + "=" * 70)
        print("Step 3  verify PDF vs CAD")
        print("=" * 70)
        if not os.path.exists(cad_log):
            print("No CAD log yet -- run Step 2 for real first.")
        else:
            import TitleBlockFix_Verify as ver
            ver.PDF_DIR = os.path.join(pdf_dir, out_sub)
            ver.DWG_DIR = os.path.join(dwg_dir, out_sub)
            ver.CAD_LOG = cad_log
            ver.main()

    print("\nPipeline finished.")


if __name__ == "__main__":
    main()

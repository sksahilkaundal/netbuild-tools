# -*- coding: utf-8 -*-
"""
CAD counterpart to TitleBlockFix_PDF.py -- fixes the same two/three
titleblock defects, but directly in the DWG via AutoCAD COM automation
(win32com), since DWG stores real editable text entities (no redaction/
masking needed at all here -- this is the "no text masking" PDF concern
made moot: we just change AcDbMText.TextString in place).

Confirmed live 2026-09-16 against ProjectC-Studio-DWG-B001-GFL-AR-210001_A.dwg
(an already-corrected reference, same as the PDF batch) and the blank
target ProjectC-Studio-DWG-SW00-GFL-AR-200001_B.dwg:

- Revision table (Rev./Date/Description/Auth./Chk.) and the titleblock's
  own "Rev."/"Date" header live in PaperSpace as individual AcDbMText
  entities on layer A-SYMB-MISC (or G-ANNO-SCHD in older exports) --
  NOT block attributes. Each row's Date/Description are separate MText
  objects at the SAME y per row. Editing .TextString in place is safe:
  position/style/layer are already correct, only the string is wrong.
- "Model Ref Number" is DIFFERENT: when blank, Revit's DWG exporter
  writes NO entity at all (neither the "Model Ref Number:" caption nor
  a value) -- confirmed by its total absence in the target file's
  PaperSpace dump. There is nothing to edit; a new AcDbMText must be
  CREATED. Position is derived from the SAME file's own "Rev." header
  position plus a fixed offset measured from the B001 reference (where
  "Rev." and the Model Ref value both exist): offset = (+21.55, -69.69)
  in PaperSpace units. Confirmed the "Rev." header sits at virtually the
  same absolute PaperSpace position across a 210001-series (B001) and a
  200001-series (SW00) sheet (1045.47,608.36) vs (1044.74,608.45) --
  the titleblock block is placed identically regardless of drawing-
  number series, so this offset is expected to generalize.
- The bottom "Date:" field (Status:/Scale: row) DOES already exist as
  an MText even when in the wrong DD-Mon-YYYY format (unlike Model Ref)
  -- edit in place like the revision rows, no creation needed.
  KNOWN RESIDUAL (accepted for the 2026-09-16 batch): this MText is
  TopLeft-anchored, so the narrower DD/MM/YYYY keeps its LEFT edge while
  Revit and the PDF step keep the CENTRE -- the CAD field lands ~3.8pt
  (1.35mm) left of the PDF's, on every sheet that has it. Invisible to
  the value cross-check; measured by fitting the CAD plot to the edited
  PDF. If it is ever to be fixed: GetBoundingBox() before and after the
  TextString change, then shift InsertionPoint.x by (w_before-w_after)/2.
  Revision dates are TopCenter and need nothing.
- Style/layer names are NOT consistent across files (e.g. "Arial_11" /
  "G-ANNO-TTLB" in B001 vs "Arial_9" / "A-TITL-TXT" in SW00) -- never
  hardcode a style/layer name from one file and reuse it in another.
  For the new Model Ref entity, clone Height/StyleName/Layer from that
  SAME file's own comparable small titleblock-value text (its "ProjectC"
  drawing-number-prefix entity), not from a different file.

Filename convention: ProjectC-Studio-DWG-<ZONE>-<LEVEL>-AR-<DWGNO>_<REV>.dwg
(from the active profile -- identical routing to the PDF batch).
"""
import win32com.client
import pythoncom
import glob
import os
import re
import time

import TitleBlockFix_Config as cfg

# Set these from the launcher / pipeline. Everything PROJECT-specific
# (zones to skip, model-ref routing, revision wording, filename layout)
# comes from the active profile in TitleBlockFix_Config, so this script is
# generic -- point it at another project by loading another profile.
SRC_FOLDER = ""
OUT_FOLDER = ""

DRY_RUN = True  # True = report what would change, write nothing

MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}
DATE_RE = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$")

# Anchor for placing a NEW "Model Ref Number" value.
#
# DO NOT anchor this off the revision schedule. Confirmed live 2026-09-16:
# the revision schedule is a Revit schedule placed on the sheet and its
# position drifts slightly per sheet (B001 "Rev." at x=1045.469 on layer
# G-ANNO-SCHD vs SW00 at x=1044.742 on layer A-SYMB-MISC). The TITLEBLOCK
# fields, by contrast, are pinned to byte-identical PaperSpace coordinates
# across every sheet in the batch (e.g. "URBAN WADI HIGH RISE TOWERS" is at
# (1059.44941045182, 119.415042574065) in both files, to 12 decimals).
# Model Ref Number belongs to the titleblock, so anchor it there.
#
# ANCHOR_TEXT is a titleblock string that is constant project-wide (the
# project name) -- more stable than the status field, which can change
# per issue ("FOR APPROVAL" / "FOR CONSTRUCTION" / ...).
ANCHOR_TEXT = "URBAN WADI HIGH RISE TOWERS"
# offset = B001's ModelRef insertion point - B001's anchor insertion point
# B001 ModelRef: (1067.0243185153515, 538.6730668218463)
# B001 anchor:   (1059.44941045182,   119.415042574065)
MODEL_REF_OFFSET_FROM_ANCHOR = (7.5749080635315, 419.2580242477813)
# AcAttachmentPoint of the reference file's Model Ref entity -- measured
# from B001 (= 1, acAttachmentPointTopLeft), not guessed, because a
# mismatch would shift the text by its own width/height. It happens to
# match AddMText's default, but set it explicitly so a future change to
# that default cannot silently move the text.
MODEL_REF_ATTACHMENT = 1


def com_retry(fn, tries=30, delay=1.0):
    """AutoCAD rejects COM calls while it is busy ("Call was rejected by
    callee") -- routinely right after Open/Close, while the drawing is
    still regenerating. A fixed sleep is unreliable on heavy sheets, so
    retry until it answers.

    AttributeError is caught as well as com_error: pywin32's late-bound
    dispatch reports a busy-rejected property read as
    "AttributeError: Item.ObjectName" rather than a com_error, so
    catching only com_error misses the common case.
    """
    last = None
    for _ in range(tries):
        try:
            return fn()
        except (pythoncom.com_error, AttributeError) as exc:
            last = exc
            time.sleep(delay)
    raise last


def wait_quiescent(acad, timeout=60.0):
    """Block until AutoCAD reports it is idle."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if acad.GetAcadState().IsQuiescent:
                return True
        except (pythoncom.com_error, AttributeError):
            pass
        time.sleep(0.5)
    return False


def model_ref_for_filename(fname):
    return cfg.model_ref_for_filename(fname)


def convert_date(d):
    parts = d.split("-")
    if len(parts) != 3 or parts[1] not in MONTHS:
        return None
    return "%s/%s/%s" % (parts[0], MONTHS[parts[1]], parts[2])


def has_model_ref_field(doc, ps, count):
    """Does this sheet's titleblock actually carry a Model Ref Number field?

    9 sheets in this batch (the 410xxx facade sheets and TO00-400002) use a
    reduced titleblock with no such field. Without this check the value gets
    created in empty space -- in the PDF batch the equivalent mistake put it
    off the page edge, where it was silently clipped.

    The label lives inside the titleblock BLOCK DEFINITION, not in
    PaperSpace, so it cannot be found by scanning PaperSpace text.
    """
    for i in range(count):
        e = com_retry(lambda: ps.Item(i))
        if com_retry(lambda: e.ObjectName) != "AcDbBlockReference":
            continue
        name = com_retry(lambda: e.Name)
        if "Title Block" not in name:
            continue
        blk = com_retry(lambda: doc.Blocks.Item(name))
        for j in range(com_retry(lambda: blk.Count)):
            be = com_retry(lambda: blk.Item(j))
            if com_retry(lambda: be.ObjectName) in ("AcDbText", "AcDbMText"):
                if cfg.model_ref_label() in com_retry(lambda: be.TextString):
                    return True
    return False


def fix_dwg(doc, model_ref_text, log):
    ps = com_retry(lambda: doc.PaperSpace)
    count = com_retry(lambda: ps.Count)
    mtexts = []
    for i in range(count):
        e = com_retry(lambda: ps.Item(i))
        if com_retry(lambda: e.ObjectName) == "AcDbMText":
            mtexts.append(e)

    # --- revision table rows: group by y (rounded), same pattern as PDF ---
    rows = {}
    for e in mtexts:
        y = round(e.InsertionPoint[1], 1)
        rows.setdefault(y, []).append(e)

    latest_date = None

    # The revision schedule and the titleblock live on DIFFERENT layers,
    # and the layer NAMES differ per file (A-SYMB-MISC vs G-ANNO-SCHD,
    # A-TITL-TXT vs G-ANNO-TTLB). Derive the schedule layer from this
    # file's own "Rev." header rather than hardcoding any name.
    rev_header = next((e for e in mtexts if e.TextString == "Rev."), None)
    schedule_layer = rev_header.Layer if rev_header is not None else None

    anchor = next((e for e in mtexts if e.TextString == ANCHOR_TEXT), None)
    anchor_pt = tuple(anchor.InsertionPoint) if anchor is not None else None

    # (Height, StyleName, Layer) cloned from this file's own small
    # titleblock-value text, so the new entity inherits this file's text
    # style and titleblock layer rather than another file's names.
    reference_style = None
    style_source = next(
        (e for e in mtexts
         if e.TextString == "ProjectC" and e.Layer != schedule_layer),
        None,
    )
    if style_source is None:
        style_source = next(
            (e for e in mtexts
             if DATE_RE.match(e.TextString) and e.Layer != schedule_layer),
            None,
        )
    if style_source is not None:
        reference_style = (style_source.Height, style_source.StyleName, style_source.Layer)

    for y, items in sorted(rows.items(), reverse=True):
        texts = {e.TextString: e for e in items}
        matched_after = None
        desc_entity = None
        for prefix, after in cfg.revision_descriptions().items():
            for s, e in texts.items():
                if s.lower().startswith(prefix):
                    matched_after = after
                    desc_entity = e
                    break
            if matched_after:
                break
        if not matched_after:
            continue

        date_entity = next((e for s, e in texts.items() if DATE_RE.match(s)), None)
        if not date_entity:
            continue
        new_date = convert_date(date_entity.TextString)

        log.append("  revision row y=%.1f: '%s' -> %s | '%s' -> '%s'" % (
            y, date_entity.TextString, new_date, desc_entity.TextString, matched_after))

        if new_date:
            latest_date = new_date

        if DRY_RUN:
            continue

        date_entity.TextString = new_date
        desc_entity.TextString = matched_after
        # Each MText keeps the wrap width it was created with, sized for
        # the OLD text. "50% Schematic Design" had Width=31.05, and the
        # longer "50% SCHEMATIC DESIGN SUBMISSION" then wrapped onto a
        # second line and collided with the row below (caught in the
        # plotted output). Width 0 means "no wrap" in AutoCAD.
        desc_entity.Width = 0

    # --- bottom "Date:" field: already exists, edit in place ---
    # By this point the schedule's own dates have already been rewritten to
    # DD/MM/YYYY, so any remaining DD-Mon-YYYY match off the schedule layer
    # is the titleblock's bottom Date field.
    bottom_date_entity = next(
        (e for e in mtexts
         if DATE_RE.match(e.TextString) and e.Layer != schedule_layer),
        None,
    )
    if bottom_date_entity:
        # Reformat this field's OWN value rather than reusing the last
        # schedule row's date. The schedule is not always ordered oldest
        # first -- on the 410xxx facade sheets it runs newest-first, and
        # taking "the last row processed" turned 06-Sep-2026 into
        # 16/06/2026 (caught in the PDF batch, same defect would apply
        # here).
        new_bottom = convert_date(bottom_date_entity.TextString) or latest_date
        if new_bottom:
            log.append("  Bottom Date field: '%s' -> '%s'"
                       % (bottom_date_entity.TextString, new_bottom))
            if not DRY_RUN:
                bottom_date_entity.TextString = new_bottom
        else:
            log.append("  Bottom Date field -- unparseable date, SKIPPED")
    else:
        log.append("  Bottom Date field not found -- SKIPPED")

    # --- Model Ref Number: create if absent ---
    has_model_ref = any("ProjectC-Studio-BIM" in e.TextString for e in mtexts)
    if has_model_ref:
        log.append("  Model Ref Number already present -- left untouched")
    elif not has_model_ref_field(doc, ps, count):
        log.append("  Model Ref Number -- this titleblock has no such field, SKIPPED")
    elif anchor_pt is None:
        log.append("  Model Ref Number -- titleblock anchor %r not found, SKIPPED" % ANCHOR_TEXT)
    elif reference_style is None:
        log.append("  Model Ref Number -- no reference style found in this file, SKIPPED")
    else:
        new_x = anchor_pt[0] + MODEL_REF_OFFSET_FROM_ANCHOR[0]
        new_y = anchor_pt[1] + MODEL_REF_OFFSET_FROM_ANCHOR[1]
        height, style_name, layer = reference_style
        log.append("  Model Ref Number -> '%s' at (%.4f, %.4f)" % (model_ref_text, new_x, new_y))
        if not DRY_RUN:
            pt = win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_R8, [new_x, new_y, 0.0])
            new_e = ps.AddMText(pt, 200.0, model_ref_text)
            new_e.Height = height
            new_e.Layer = layer
            try:
                new_e.StyleName = style_name
            except Exception:
                pass
            # AddMText defaults to top-left attachment; match the reference
            # file's Model Ref entity so the insertion point means the same
            # thing here as it does there.
            try:
                new_e.AttachmentPoint = MODEL_REF_ATTACHMENT
            except Exception:
                pass

    return latest_date


def main():
    files = sorted(glob.glob(os.path.join(SRC_FOLDER, "*.dwg")))
    print("Found %d DWG(s) in source folder" % len(files))

    if not DRY_RUN and not os.path.isdir(OUT_FOLDER):
        os.makedirs(OUT_FOLDER)

    acad = win32com.client.GetActiveObject("AutoCAD.Application")

    n_skip = 0
    n_process = 0
    n_error = 0

    for fpath in files:
        fname = os.path.basename(fpath)
        model_ref, skip_reason = model_ref_for_filename(fname)
        if model_ref is None:
            n_skip += 1
            continue

        n_process += 1
        log = ["%s  (Model Ref target: %s)" % (fname, model_ref)]
        try:
            doc = com_retry(lambda: acad.Documents.Open(fpath))
            wait_quiescent(acad)
            com_retry(lambda: doc.PaperSpace.Count)  # wait out the regen
            fix_dwg(doc, model_ref, log)
            if not DRY_RUN:
                out_path = os.path.join(OUT_FOLDER, fname)
                com_retry(lambda: doc.SaveAs(out_path))
            com_retry(lambda: doc.Close(False))
        except Exception as e:
            n_error += 1
            log.append("  ERROR: %s" % e)
            try:
                com_retry(lambda: doc.Close(False), tries=5)
            except Exception:
                pass  # leave it open rather than stall the whole batch

        for line in log:
            print(line)

    print("\n--- Summary ---")
    print("Processed: %d, Skipped (per profile / unparseable): %d, Errors: %d" % (n_process, n_skip, n_error))
    if DRY_RUN:
        print("DRY_RUN is True -- no files written. Set DRY_RUN = False to apply.")


if __name__ == "__main__":
    main()

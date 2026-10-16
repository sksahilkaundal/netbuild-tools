# -*- coding: utf-8 -*-
"""
Align floor-plan viewports AND their view titles on many sheets to match a
reference sheet (same plan position on the sheet, same title position/length).

REUSABLE TEMPLATE -- edit only the CONFIG block. Run through the Revit MCP
`execute_revit_code` tool (or a pyRevit button); `doc` must be the host model.

How it aligns (verified live 2026-09-23, 3505-ProjectG-Studio-ARC-RVT-00010):
- Plans: by the viewport's projection ORIGIN on the sheet
  (Viewport.GetProjectionToSheetTransform().Origin), not by box centre. Box
  centres differ between sheets because crop/annotation-crop extents differ, so
  centre-matching would leave the plans (and grids) misaligned.
- Pairing: plan viewports are paired by SLOT (sorted top -> bottom by box
  centre Y), never by detail number -- detail numbers are not consistent
  (e.g. sheet 10025 had detail 1 at the bottom).
- Titles: Viewport.LabelOffset is measured from the viewport BOX corner
  (label min = box min + offset + a constant from the title family). Box sizes
  differ per sheet, so the reference offset must be corrected:
      new_offset = ref_offset + (ref_box_min - target_box_min_after_move)
  Copying the reference offset verbatim misplaces titles.
- Gotcha (VERIFY BY RENDER, NOT BY READ-BACK): GetLabelOutline() and even
  GetBoxOutline()+LabelOffset return stale/junk values for sheets that are not
  open on screen -- metres of "error" on an 841 mm sheet, growing sheet by
  sheet -- both inside the edit transaction AND in a later separate call, even
  though the sheets are correct. Only the projection origin reads back reliably.
  Verify titles by exporting a few sheets with ImageExportOptions and comparing
  pixel positions against the reference sheet.
- Gotcha: doc.Regenerate() across ~20 sheets with linked views can outlast the
  MCP timeout -- this script does not call it; verify afterwards.

DRY_RUN = True  -> prints the plan, applies inside a TransactionGroup and rolls back.
DRY_RUN = False -> commits.
"""
from Autodesk.Revit.DB import (FilteredElementCollector, ViewSheet, ViewType,
                               Transaction, TransactionGroup)

try:
    doc  # injected by MCP execute_revit_code / a pyRevit wrapper
except NameError:
    doc = __revit__.ActiveUIDocument.Document

# ----------------------------- CONFIG ---------------------------------
DRY_RUN = True
EXPECTED_DOC_TITLE = "3505-ProjectG-Studio-ARC-RVT-00010"   # refuse to run on any other model
REFERENCE_SHEET = "10023"
# Target sheets: numeric sheet numbers in this inclusive range (reference excluded).
TARGET_RANGE = (10001, 10039)
TARGET_EXTRA = []            # additional sheet numbers, e.g. ["10B01"]
VIEW_TYPES = (ViewType.FloorPlan,)   # which viewports are aligned; legends etc. left alone
ALIGN_TITLES = True
# ----------------------------------------------------------------------

MM = 304.8
assert doc.Title == EXPECTED_DOC_TITLE, "Wrong active document: %s" % doc.Title

sheets = dict((s.SheetNumber, s) for s in FilteredElementCollector(doc).OfClass(ViewSheet))
targets = sorted(n for n in sheets
                 if n != REFERENCE_SHEET and ((n.isdigit() and TARGET_RANGE[0] <= int(n) <= TARGET_RANGE[1]) or n in TARGET_EXTRA))


def plan_vps(sheet):
    vps = [doc.GetElement(i) for i in sheet.GetAllViewports()]
    vps = [vp for vp in vps if doc.GetElement(vp.ViewId).ViewType in VIEW_TYPES]
    return sorted(vps, key=lambda vp: -vp.GetBoxCenter().Y)   # slot 0 = top


ref = plan_vps(sheets[REFERENCE_SHEET])
R = [dict(origin=vp.GetProjectionToSheetTransform().Origin,
          box_min=vp.GetBoxOutline().MinimumPoint,
          offset=vp.LabelOffset, length=vp.LabelLineLength) for vp in ref]

plan, skipped = [], []
for n in targets:
    vps = plan_vps(sheets[n])
    if len(vps) > len(R):
        skipped.append((n, "%d viewports, reference has %d" % (len(vps), len(R))))
        continue
    for slot, vp in enumerate(vps):
        d = R[slot]["origin"] - vp.GetProjectionToSheetTransform().Origin
        new_box_min = vp.GetBoxOutline().MinimumPoint + d
        new_off = R[slot]["offset"] + (R[slot]["box_min"] - new_box_min)
        plan.append((n, slot, vp, d, new_off))

print("=" * 70)
print("DOC %s | reference %s (%d slots) | targets %d | viewports %d | DRY_RUN %s"
      % (doc.Title, REFERENCE_SHEET, len(R), len(targets), len(plan), DRY_RUN))
for n, slot, vp, d, no in plan:
    print("  %s slot%d %-30s move (%+.1f, %+.1f) mm | title offset (%.1f, %.1f) -> (%.1f, %.1f)"
          % (n, slot, doc.GetElement(vp.ViewId).Name[:30], d.X * MM, d.Y * MM,
             vp.LabelOffset.X * MM, vp.LabelOffset.Y * MM, no.X * MM, no.Y * MM))
for s in skipped:
    print("  SKIP", s)

tg = TransactionGroup(doc, "Align viewports to sheet %s" % REFERENCE_SHEET)
tg.Start()
t = Transaction(doc, "Align viewports to sheet %s" % REFERENCE_SHEET)
t.Start()
fails = []
for n, slot, vp, d, no in plan:
    try:
        vp.SetBoxCenter(vp.GetBoxCenter() + d)
        if ALIGN_TITLES:
            vp.LabelLineLength = R[slot]["length"]
            vp.LabelOffset = no
    except Exception as ex:
        fails.append((n, slot, str(ex)[:100]))
status = t.Commit()
if DRY_RUN:
    tg.RollBack()
    print("DRY RUN: %d viewport(s) computed, rolled back. Failures: %s" % (len(plan) - len(fails), fails))
else:
    tg.Assimilate()
    print("APPLIED (%s): %d viewport(s). Failures: %s" % (status, len(plan) - len(fails), fails))

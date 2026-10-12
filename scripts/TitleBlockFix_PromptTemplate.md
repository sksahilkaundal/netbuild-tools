# Title Block Fix — Reusable Prompt

Corrects revision wording/date format, the bottom `Date:` field, and
`Model Ref Number` on an **already-exported** issue set (PDF + DWG), then
cross-verifies the two formats against each other.

Project-agnostic: everything project-specific lives in a JSON profile under
`scripts\profiles\`, so a new project needs a new profile, not a code change.

Fill in the blanks and paste as-is.

```
Run the Title Block Fix pipeline on <ISSUE FOLDER>, using profile <PROFILE NAME>:
- scripts\TitleBlockFix_Pipeline.py (C:\SK\OneDrive\Netbuild\scripts\TitleBlockFix_Pipeline.py) as the orchestrator
- scripts\TitleBlockFix_PDF.py (C:\SK\OneDrive\Netbuild\scripts\TitleBlockFix_PDF.py) for the PDFs
- scripts\TitleBlockFix_DWG.py (C:\SK\OneDrive\Netbuild\scripts\TitleBlockFix_DWG.py) for the DWGs
- scripts\TitleBlockFix_Verify.py (C:\SK\OneDrive\Netbuild\scripts\TitleBlockFix_Verify.py) to cross-check them
- scripts\TitleBlockFix_Plot.py (C:\SK\OneDrive\Netbuild\scripts\TitleBlockFix_Plot.py) ONLY if I ask for plotted PDFs from the CAD
- scripts\TitleBlockFix_Config.py (C:\SK\OneDrive\Netbuild\scripts\TitleBlockFix_Config.py) holds the profiles

If profile <PROFILE NAME> does not exist yet, create it from the ProjectA example and set:
  folders    : PDF folder, DWG folder, output subfolder name
  filename   : separator and the 0-based positions of ZONE, LEVEL and DRAWING NO.
  skip_zones : zones already correct at source
  revision_descriptions : lowercase "before" prefix -> exact "after" text
  model_ref  : the label text, and rules mapping zone/level/drawing-no to the hosting model
Ask me for any of these you cannot infer from the files — do not guess the model-ref routing.

Write corrected copies to the profile's output subfolder inside each source folder. Never modify the originals.

Fix on every sheet that HAS the field:
1. Revision rows -> SCREAMING CASE description, and DD-Mon-YYYY -> DD/MM/YYYY.
2. The bottom "Date:" field -> DD/MM/YYYY, reformatting its OWN value (never copy a revision row's date).
3. "Model Ref Number" -> per the profile's rules. Skip sheets whose title block has no such field.

Match this reference sheet exactly: <PATH TO AN ALREADY-CORRECT SAMPLE SHEET>.
Dry-run first. Do one sample sheet, show me before/after, and wait for my go-ahead before the full batch.
For CAD, close all drawings in AutoCAD first, and do not plot unless I ask —
plotted PDFs are a visual check, never the deliverable.
Afterwards run BOTH verifications: TitleBlockFix_Verify.py (values agree PDF vs CAD) and
TitleBlockFix_VerifyGeometry.py (C:\SK\OneDrive\Netbuild\scripts\TitleBlockFix_VerifyGeometry.py)
(no line lost, no shift, no overflow, no collision vs the original). Report any sheet flagged by either.
```

## Blanks to fill

- **Issue folder** — the one *containing* the PDF and DWG folders.
- **Profile name** — an existing profile, or a new one to create.
- **Reference sheet** — an already-correct sheet to match geometry against.

## Gotchas baked into the scripts (don't relearn these)

Each of these produced a wrong file once before being fixed.

- **Anchor on the field's own label.** `Model Ref Number` was first anchored
  off the bottom `Date:` field. 9 sheets used a reduced title block with no
  Model Ref field, so the value landed in empty space — 8 of them **off the
  page edge**, silently clipped. In DWG the label is inside the title block
  **block definition**, not PaperSpace.
- **Never derive a value from row order.** Some sheets list revisions
  **newest-first**; taking "the last row processed" wrote the June date onto
  September sheets. Reformat the field's own value instead.
- **MText keeps its old wrap width (CAD).** The longer SCREAMING text wrapped
  to a second line and collided with the row below. Set `Width = 0`.
- **Transform before testing an axis (PDF).** Half a batch can be
  `page.rotation == 90`; fitz works in raw pre-rotation space. Row grouping,
  divider detection and text placement each broke separately until they
  transformed first.
- **Alignment is per field and per title-block variant.** Dates are
  centred; the description column is centred on some variants and
  left-aligned on others. The fixer infers it from the original's own rows.
  Always run `TitleBlockFix_VerifyGeometry.py` after the PDF step — the
  value check passed a batch where 110 sheets had text over a divider.
- **Use the span's own `origin` for the baseline and its own `size`** — a
  bbox-derived baseline sits 0.8–2.4pt low.
- **Embed real Arial, then patch its ToUnicode**, or the text renders fine but
  is un-searchable. Subset afterwards — a full embed adds ~1.2 MB per sheet.
- **The schedule drifts, the title block doesn't.** Anchor to the title block.
- **Known, accepted CAD residual:** the bottom `Date:` MText is
  left-anchored, so its centre lands ~1.35mm left of the PDF's after the
  string shortens. Expect the plot check to flag a few sheets at 4.0–4.5pt
  on that one field. Fix recipe is in `TitleBlockFix_DWG.py`'s notes.
- **AutoCAD COM:** close all drawings first (`SaveAs` fails if the target name
  is open); busy-rejections surface as `AttributeError`, not just `com_error`.

## Portable tool

Non-technical users can run the same pipeline from
`C:\SK\OneDrive\Netbuild\Portable\Title Block Fix.exe` — no Python, no install,
no admin. Profiles live in `Portable\profiles\`, editable from the UI.

## Plotting a sample from CAD (optional, for visual sign-off)

AutoCAD's plotter search path on this machine points **only** at Bluebeam's
folder, so the built-in PDF plotters are invisible to automation. Temporarily
append `%APPDATA%\Autodesk\AutoCAD 2025\R25.0\enu\Plotters`, call
`Layout.RefreshPlotDeviceInfo()` (without this the device list does not
refresh), plot, then **restore the original `PrinterConfigPath`**. Use
`ISO_full_bleed_A0` with centred extents at 1:1 — plain `ISO_A0` with
`PlotType = acLayout` clips the right-hand column off the sheet.

# Align Viewports by Netbuild

© 2026 Netbuild. All rights reserved. · Proprietary software owned by Netbuild · [skaec.com](https://skaec.com) · see **Licence** below

Line up the viewports **and their view titles** on many sheets with a reference sheet. Each plan lands
at the same place on the sheet, so its grids line up from sheet to sheet. Each view title lands in the
same position with the same line length.

It is the ribbon-button version of the `scripts/align_viewports_from_reference_sheet.py` workflow
(see `scripts/align_viewports_from_reference_sheet_PromptTemplate.md`). It needs no Claude session,
no MCP listener and no editing of a CONFIG block.

## Where it is

**Netbuild** tab → **Sheets** panel → **Align Viewports**. It runs directly inside Revit, in pyRevit's
IronPython engine. The code lives in the shared `Netbuild.extension`
(`LevelShifter/pyRevit/Netbuild.extension`):

| File | What |
|---|---|
| `Netbuild.tab/Sheets.panel/Align Viewports.pushbutton/script.py` | The button and its window |
| `lib/align_viewports/core.py` | The engine: pick sheets, plan, apply, verify, export check images, logs |
| `lib/align_viewports/about.py` | Product, version, requirements, licence (About / Licence screens) |
| `lib/alignviewports_ui.py` | The window layout (XAML) |

Install the extension the same way as for Level Shift (see [`LevelShifter/README.md`](../LevelShifter/README.md#install-the-ribbon-buttons-pyrevit)).
**Script Folder** / **Update Scripts** reach this button too.

## The window

| Step | What you do |
|---|---|
| 1. **Reference sheet** | Pick the sheet whose viewports are already where you want them. The window lists its viewport slots, top to bottom |
| 2. **Viewports to align** | Floor plans by default. Ceiling, area and structural plans, sections, elevations, detail, drafting and 3D views can be ticked too. Legends, schedules and unticked kinds stay where they are. **Align the view titles too** is on by default |
| 3. **Target sheets** | Type a number range (e.g. `10001` to `10039`) and any other sheet numbers (e.g. `10B01`), then click **Select these**. You can also pick sheets by hand with Ctrl / Shift + Click. The reference is never a target |

Then:

| Button | What happens in Revit |
|---|---|
| **Check (plan only)** | Lists every target viewport: its move in mm, and its title offset and line length before and after. It also lists the sheets that are skipped, have fewer viewports, or have nothing to align. Nothing is changed |
| **Trial run (rolls back)** | Does the whole move inside a TransactionGroup and re-reads every projection origin, then **rolls back**. The model is untouched |
| **Apply** | Asks first, then does the same move and keeps it as **one Undo entry** (*Align Viewports by Netbuild*). If any viewport can't be changed (for example, borrowed by another user), nothing is changed |
| **Export check images** | Exports the reference and up to 3 aligned sheets (first, middle, last) to PNG, then opens the folder so you can compare the titles |

The window remembers the reference, the range, the ticked kinds and the options for next time.

### Logs

Every run writes these files to `%APPDATA%\Netbuild\AlignViewports\logs`:
- `<time>_<step>.log`;
- `<time>_<step>_viewports.csv`, one row per viewport: the move, the title offset and line length
  before and after, and the re-read origin error.

After **Apply**, one row is added to the **time-saved log (CSV)** when one is set. It uses the same
columns as the Plot Runner's log: date, task, project, export, issues, manual / actual minutes and
minutes saved. If the file already has a header, the row follows its columns. *Manual minutes per
viewport* (default 2) sets the hand-work estimate. The default log is
`%USERPROFILE%\OneDrive - Studio\Documents\Claude\time_saved_log.csv`, used when that folder exists.

## How it aligns

- **Plans by projection origin, not box centre.** Box centres differ between sheets because the crop
  and annotation-crop extents differ, so matching centres would leave the plans and grids misaligned.
  The engine moves each viewport by the difference between `GetProjectionToSheetTransform().Origin`
  and the origin of the reference viewport in the same slot.
- **Pairing by slot, not detail number.** Viewports are sorted top to bottom by box-centre Y, then
  left to right. Detail numbers are not consistent between sheets.
  - A sheet with **more** viewports than the reference is skipped and listed.
  - A sheet with **fewer** is aligned to the reference's top slots.
- **Titles.** `LabelOffset` is measured from the viewport's box corner, and box sizes differ, so the
  reference offset is corrected for each target:
  `new_offset = ref_offset + (ref_box_min - target_box_min_after_move)`. The line length is copied
  from the reference.
- **Verify by render, not by read-back.** For sheets that are not open on screen, Revit returns stale
  values from `GetLabelOutline()` and from `GetBoxOutline()` + `LabelOffset`. The plans are verified by
  re-reading their projection origins, which read back reliably and must be 0.0 mm off. The titles are
  verified with **Export check images**.
- `doc.Regenerate()` is never called. Across many sheets with linked views it is slow; Commit
  regenerates.

## Requirements

- Windows 10 / 11, 64-bit.
- Autodesk Revit **2022 – 2026**. The viewport title and projection API (`LabelOffset`,
  `LabelLineLength`, `GetProjectionToSheetTransform`) arrived in Revit 2022; on older versions the
  window stops with a message.
- pyRevit 4.8 or later, IronPython engine (pyRevit's default).
- A project model opened editable (not read-only), with a reference sheet that is already right.
  In a workshared model, the target viewports must not be borrowed by other users.
- Save / Synchronize after Apply. Ctrl+Z in Revit undoes the whole alignment.

## About and Licence

- The window has **About** and **Licence** buttons.
- So does the ribbon: **Netbuild → About** and **Netbuild → Licence**, where you pick
  *Align Viewports by Netbuild* from the list.
- No licence key is needed for this product.

## Tests

```
python -m unittest discover -s LevelShifter/tests -v
```

`test_align_viewports.py` runs the engine and the button end to end, against a stand-in sheet set with
different crops, slot orders, title offsets and line lengths:
- plans and titles land exactly on the reference;
- legends and skipped sheets are untouched;
- a trial or a failure changes nothing;
- the logs, the time-saved row and the check images are written.

## Licence

**Netbuild Software Licence Agreement (proprietary)** -- see [`LICENSE`](../LICENSE). Proprietary software
owned by Netbuild, https://skaec.com.

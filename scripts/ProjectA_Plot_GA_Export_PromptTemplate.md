# ProjectA Plot GA Export Pass — Reusable Prompt

Fill in the blanks and paste as-is.

```
Connect to Revit MCP and confirm status.

Run the full ProjectA Plot GA export pass, model by model, using:
- scripts\export_master_ga_sheets_by_browser_filter.py (C:\SK\OneDrive\Netbuild\scripts\export_master_ga_sheets_by_browser_filter.py) for the SW00 master model
- scripts\export_podium_sheets_by_revision.py (C:\SK\OneDrive\Netbuild\scripts\export_podium_sheets_by_revision.py) for each Podium building model
(BASE_OUTPUT_FOLDER = C:\SK\Projects\ProjectA\Plot\<YYYYMMDD>)

Revision-date filter: <DD-Mon-YYYY or DD/MM/YYYY, verify the real format live per model> — export only sheets whose "Current Revision Date" includes this exact date.

Export <PDF only / PDF and CAD/DWG>. A0 size, Center placement, 100% scale.
Export ALL PDFs first, then ALL DWGs (never interleaved per-sheet).
Batch export by category, verify every file on disk afterward (ignore misleading timeout messages and stale printed output — trust the filesystem), fall back to one-sheet-per-call if a batch genuinely stalls.

1) Master model "SW00" (ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001) — route by "Studio_03 - Browser Filter" (not "Browser Filter"):
   - "B2 B5_1-200" -> "02_GA Plans B2 B5 (1-200)"
   - "Site" (excluding Solar Shading sheets and "Site Plan") -> "01_GA Plans (1-500) - Site"

2) Each Podium building model B001-B005 in turn — route by placed view type:
   FloorPlan -> "03_Podium Building Part Plans (1-100)", Elevation -> "04_Podium Building Elevations (1-100)", Section -> "05_Podium Building Sections (1-100)"

Filename = the 7 SBFX_SHEET_01..07 parameters joined with "-", plus "_<letter>" from that sheet's own "Current Revision" parameter, looked up per sheet.

I'll open each model and tell you when it's ready — wait for me to say "<model> is open" before switching context to it.
```

## Key gotchas baked into the scripts (don't relearn these)

- **Parameter name**: `"Studio_03 - Browser Filter"`, not `"Browser Filter"` — verify any such name live on one sheet before trusting a verbal spec.
- **Date format varies per model**: some models use `DD-Mon-YYYY` (e.g. "06-Sep-2026"), others `DD/MM/YYYY` (e.g. "06/09/2026") for "Current Revision Date". Always print real values first.
- **MCP timeouts are misleading**: a 60s timeout message does NOT mean the export failed — Revit keeps running it. Never trust the printed return value (it can also be a *stale* echo of a previous call). Only trust what's actually on disk.
- **Export order**: all PDFs for a batch first, then all DWGs — not interleaved per sheet.
- **DWG byproducts**: sweep `FP_*.pat`, `*.pcp`, `*.jpg`, `*.png` from the CAD output folder after each batch.
- **Duplicate/superseded sheets**: see [[revit-duplicate-sheets-revision-gotcha]] — the revision-date filter is what protects against exporting a stale duplicate.

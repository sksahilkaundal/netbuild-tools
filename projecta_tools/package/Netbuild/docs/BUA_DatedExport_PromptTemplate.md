# BUA dated export (raw Revit Area export -> dated Option 1 / Option 2 workbooks -> ProjectA Calculations): prompt template

Scripts:
- Step 1 runner: `C:\SK\OneDrive\Netbuild\scripts\bua_dated_export.py` (`py -3.14`, needs openpyxl). Takes the raw, writes the two dated workbooks next to it, prints the checks, and lists the exact raw rows behind a "!!!" banner.
- Step 1 logic: `C:\SK\Projects\ProjectA\Excel\BUA - Overall With Assets For MEP Team\update_bua_workbooks.py`. The runner executes it unchanged except for its three path lines. Its tracked `260702_...` workbooks are copied as templates and never written, so the BUA git repo is not touched.
- Step 2: `C:\SK\OneDrive\Netbuild\scripts\projecta_calculations_build.py` (`py -3.14`). Takes step 1's dated Option 1 workbook and writes `<YYMMDD>_ProjectB_Overall BUA_ProjectA Calculations.xlsx` next to it: the workbook plus "Detail Split" and an "ProjectA Calculations" GSA / GFA / BUA summary sheet. That sheet copies the layout and styles of the style template `C:\SK\Projects\ProjectA\Excel\Templates\ProjectA Calculations template - ProjectC-Studio-SCH-AR-000001_00.xlsx` (sheet "ProjectA Calculations"; copied 2026-10-01 from the reference schedule the user supplied). Only its formatting is used, never its numbers. Pass `--reference` to use another template.
- Step 3 (optional, needs Revit open with the schedule's host model): `C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_dump.py` (inside Revit, read-only) + `C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_audit.py` (`py -3.14`). Checks the Common GLA/GSA areas against their full Revit parameters. Its own short prompt: `BUA_GLA_Audit_PromptTemplate.md` (same folder).
- Repo copy: `C:\SK\Projects\ProjectA\Excel\BUA - Overall With Assets For MEP Team\tools\` (branch `bua`, remote = private GitHub `sksahilkaundal/netbuild`). Commit / push ONLY when asked.

## Prompt (fill in the raw path)

```
Using bua_dated_export.py (C:\SK\OneDrive\Netbuild\scripts\bua_dated_export.py), which runs
update_bua_workbooks.py (C:\SK\Projects\ProjectA\Excel\BUA - Overall With Assets For MEP Team\update_bua_workbooks.py),
then projecta_calculations_build.py (C:\SK\OneDrive\Netbuild\scripts\projecta_calculations_build.py):

Raw data: "<RAW PATH, e.g. C:\SK\Projects\ProjectA\Excel\<YYMMDD>\Excel - Area - Overall With Assets For MEP Team.xlsx>"
(the itemized export of the Revit schedule "Excel - Area - Overall With Assets For MEP Team", host model
ProjectC-Studio-BIM-SW00-ZZZ-AR-970002 with 970001 linked; its "GLA/GSA Component" column = Studio_Area_Department)
Back up that day's existing outputs to the scratchpad before overwriting them.

STEP 1 - Re-export the Excel output at the same path as the raw, with today's date:
    py -3.14 C:\SK\OneDrive\Netbuild\scripts\bua_dated_export.py "<RAW PATH>"
(add --overwrite to replace that day's earlier outputs; --date YYMMDD for another date)

Outputs (same folder as the raw):
  - <YYMMDD>_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx - single "Overall BUA" sheet,
    all 10 assets stacked like the raw layout (each block shows ONLY that asset's own levels; towers include
    the typical cross-reference rows 07-20 / 21-22 / 27-36 / 66-71), a "<Asset> Total" subtotal row and a
    blank separator after each block, Grand Total row at the end.
  - <YYMMDD>_ProjectB_Overall BUA_Space_Room Split_Raw Levels Only_Option 2.xlsx - one sheet per asset, own levels
    (towers incl. typical cross-refs).
The column format is FROZEN (10 GFA Components x 24 Space/Room Categories = 274 columns); it never changes
between reloads - other disciplines use it as a base. The templates' stale "Roof Areas" sheet is dropped,
and the first (data) sheet is renamed to the date by the kind of raw: itemized (one row per Area) ->
"<YYMMDD>_BUA Space Split-Itemized", grouped (Itemize every instance off) -> "<YYMMDD>_BUA Space Room Split".
The script sums itemized rows per level. A grouped raw shows "<varies>" in GLA/GSA Component, so it is fine
for Option 1/2 but NOT for the ProjectA step (STEP 2) - tell me if the raw is grouped.

Report the result:
- "ALL TOTALS TIE OUT - DONE" -> confirm success with the overall BUA/GFA totals and attach both files.
- A "!!!" banner about NEW components/categories -> show the listed raw rows (row, asset, level, column C,
  BUA, GFA) and the likely Revit cause; ask me before adding anything to the frozen lists.
- "SKIPPED ... close this workbook" / "open in Excel" -> tell me which workbook to close, then rerun.
- Any "*** MISMATCH ***" or error -> show the output and stop; don't modify the workbooks or script without asking.
The raw file may stay open in Excel; the two dated output workbooks must be closed.

STEP 2 - Only if step 1 tied out, build the ProjectA Calculations workbook from step 1's Option 1 file.
Dry run first, then write:
    py -3.14 C:\SK\OneDrive\Netbuild\scripts\projecta_calculations_build.py "<RAW FOLDER>\<YYMMDD>_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx" --out "<RAW FOLDER>\<YYMMDD>_ProjectB_Overall BUA_ProjectA Calculations.xlsx" --dry-run
    (same command without --dry-run; add --overwrite to replace that day's earlier file)

Output (same folder): <YYMMDD>_ProjectB_Overall BUA_ProjectA Calculations.xlsx - sheets <YYMMDD>_BUA Space Split-Itemized,
Detail Split, Overall BUA, ProjectA Calculations (layout and styles of the reference schedule's sheet; values
recalculated from this data; per-asset columns plus Tower A / Tower B / Tower GF to L6 breakdown).
The F&B Terraces / Retail Terraces rows are typed by me; the build carries them over from the workbook it
replaces (or --carry-from "<older ProjectA Calculations.xlsx>" for a new date) - report what it carried.

Report the result:
- "ALL TOTALS TIE OUT - DONE" -> confirm with Total GSA Excl. / Incl. Terraces, Total Combined GFA,
  Total BUA - Including Parking and the GFA efficiencies, compare with the previous ProjectA Calculations,
  and attach the file.
- "not placed exactly once on an ProjectA line - nothing written" -> show the listed rows (a new
  GFA Component-Category); ask me which ProjectA line they belong to (or whether to fix them in Revit)
  before changing the rules.
- Any "*** MISMATCH ***" or error -> show the output and stop; don't modify the workbook or script without asking.
The Option 1 input may stay open in Excel; the ProjectA Calculations output must be closed.
If the raw replaces an earlier one of the same date, diff the two Option 1 data sheets per asset / level /
Function-Sub-function and tell me what changed in Revit (e.g. a retag, an area moved between GFA columns).
Don't commit or push anything unless I ask.
```

## What the checks mean
- **"!!!" banner**: a column C value (`GFA Component-Space/Room Category`) whose component or category isn't in `FROZEN_COMPONENTS` / `FROZEN_CATS`. Its area is left out of the workbooks, so the totals MISMATCH by exactly that amount. It has always been bad data so far, not a real new category (2026-10-01):
  - `MEP Rooms` / `Services` with no hyphen: `Studio_Function Code` is blank, so the combined field loses its "Function-" prefix.
  - `Residential-ser`: a typo'd `Studio_Sub-Function Code`.
  Fix it in Revit, re-export the raw, and rerun with `--overwrite`.
- **MISMATCH without a banner**: a level the script can't place. Check `TYPICAL`, `LEVEL_ALIASES` and the basement prefix list at the top of `update_bua_workbooks.py` against the raw's Level names (2026-09-11: "27th to 36th Floor" needed an alias; "80th Floor" needed the ordinal scan raised to 99).
- **ProjectA step - "not placed exactly once"**: every m² of GFA and BUA must land on exactly one ProjectA line. The rules (`RULES` in `projecta_calculations_build.py`) map each `GFA Component-Category` to a line:
  - GSA lines use Usable Area (A).
  - "(GFA)" lines use GFA (A+B).
  - Non-GFA and facade lines use BUA − GFA.
  - Terraces and parking use BUA.
  - Units follow the GFA Component (Residential-Hotel Apartments → Residential Units).
  - GLA/GSA needs the area's own `GLA/GSA Component` (raw column D) to contain GLA or GSA. Untagged usable area → "Usable Areas Not in GLA/GSA (GFA)"; untagged terraces → BUA-only "Terraces - Not in GLA/GSA - <level>" (one row per level) and "Planters - Not in GLA/GSA". Tagged services/storage/kitchens/pool → "Common GLA/GSA to Tenants - Offices / Hotel Apartments / Hotel / Retail" by tag (in GSA Excl. Terraces; user's decision 2026-10-01 - the reference schedule had them as non-lettable GFA). A common area with any other tag (e.g. GSA Residential) stops the build until a line is agreed. Tagged terraces sort by tag (Residential / Hotel Apartment / Hotel / Office).
  - F&B Terraces / Retail Terraces are manual rows (not GFA/BUA, in GSA Incl. Terraces). An area tagged GLA F&B Terrace / GLA Retail Terrace that carries GFA or BUA stops the build.
  A combination with no rule stops the build, so a new category never disappears silently. Lines added on 2026-10-01 by the user's decision: Office Terrace/Balconies (also in GSA Incl. Terraces), Facade Structure (GFA), Shared Circulation (GFA and non-GFA), Hotel Apartment Terrace/Balconies, Common GLA/GSA to Tenants, the Not-in-GLA/GSA lines, and the two manual terrace rows.
- **ProjectA step - verify**: after saving, it evaluates the written sheet's formulas and checks Total Combined GFA and Total BUA per asset, Tower Total and Grand Total against the data.

## History
- 2026-10-01: raw `C:\SK\Projects\ProjectA\Excel\261001\...`. The first export hit the banner (3 bad rows, 138.53 m²). After the user fixed them and re-exported: ALL TOTALS TIE OUT, BUA 406,808.76 m², GFA 201,273.35 m².
- 2026-10-01: ProjectA Calculations from that data: ALL TOTALS TIE OUT, GSA 151,960.68 / 178,590.10 m² (excl. / incl. terraces), GFA efficiency 75.5% / 88.7%. Previous ProjectA Calculations (reference, 260911 data): GSA 151,639.19 / 172,689.55 m², GFA 201,097.01 m², BUA 405,039.28 m². Its tower columns Q:S were wrong in the reference (a double-counting helper) and are rebuilt correctly.
- 2026-10-01 (later): itemized raw (5,417 Area rows; item-rounded totals BUA 406,807.20 / GFA 200,711.39, ~1.5 m² under Revit's own total row). ProjectA with the GLA/GSA tag rules: GSA 160,227.37 / 180,423.77 m² (incl. Common GLA/GSA to Tenants 9,733.91), GFA efficiency 79.8% / 89.9%.
- 2026-10-01 (final, 18:51 raw): Tower B 07-23 retagged Hotel → Residential and the 47th floor MEP circulation made GFA in Revit (GFA +587.91 → 201,299.30); area 2447 (Tower B 51st) renamed Store / Store (Over Ground). GSA 160,227.37 / 180,423.77, GFA efficiency 79.6% / 89.6%. Committed + pushed as 10c1e20.

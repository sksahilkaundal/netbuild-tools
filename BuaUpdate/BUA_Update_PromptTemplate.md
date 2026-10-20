# BUA Update (raw Revit Area export -> Option 1 / Option 2 BUA workbooks): prompt template

Tool: **BUA Update by Netbuild** (`BuaUpdate.exe`, or `BuaUpdate.bat` from source; the window is
`BUA Update by Netbuild.exe`, also opened by **Netbuild -> Areas -> BUA Update** in Revit).
Rules and engine: `update_bua_workbooks.py` (agreed 2026-07-02), as `BuaUpdate/bua_update/engine.py`.
It writes the same workbooks as the script, cell for cell.
Exit codes: 0 tie out | 1 mismatch | 2 new items | 3 skipped (open in Excel) | 4 error.

## Prompt

```
Update the ProjectA/ProjectB BUA workbooks:

Run: BuaUpdate.exe update --folder "C:\Users\user\OneDrive - Studio\Projects\ProjectA\Excel\BUA - Overall With Assets For MEP Team"
(from source: BuaUpdate.bat update --folder "..."; dry run first if you like: BuaUpdate.exe check --folder "...")

This re-feeds the raw Revit export ("Excel - Raw Area from RVT- Overall With Assets For MEP Team.xlsx", same
folder) into:
  - Option 1 "..._with All Levels_Option 1.xlsx" - single "Overall BUA" sheet, all 10 assets stacked like the
    raw layout (each block shows ONLY that asset's own levels; towers include the typical cross-reference rows),
    with a "<Asset> Total" subtotal row and a blank separator after each block, and a Grand Total row at the end.
  - Option 2 "..._Raw Levels Only_Option 2.xlsx" - one sheet per asset, own levels (towers incl. typical
    cross-refs).
The column format is FROZEN (10 GFA Components x 24 Space/Room Categories = 274 columns); it never changes
between reloads - other disciplines use it as a base.
Typical floors: the tool picks the Level set that fits the raw ("Typical floors:" line) -
2026-07 = 07-20 / 26-36 / 65-72 (July exports, ~222 Option 1 rows, towers 70 rows) or
2026-09 = 07-20 / 21-22 / 27-36 / 66-71 (model since 2026-09). Tell me which one it used.

Report the result:
- "ALL TOTALS TIE OUT - DONE" (exit 0) -> confirm success with the overall BUA/GFA totals (the "Overall BUA = ..."
  line).
- A "!!!" banner about NEW components/categories (exit 2) -> tell me exactly what's new, the raw rows listed
  under it, and how much area is excluded; ask me before adding anything to the frozen lists.
- A "!!!" banner about LEVELS THE TYPICAL-FLOOR SET CANNOT PLACE -> show it; don't rerun with another
  --typical without asking.
- "SKIPPED ... open in Excel" (exit 3) -> tell me which workbook to close, then rerun.
- Any "*** MISMATCH ***" or error (exit 1 / 4) -> show the output and stop; don't modify the workbooks or the
  tool without asking.

The raw file may stay open in Excel; the two Option workbooks must be closed.
Both workbooks are backed up to <folder>\Backup\<yymmdd_hhmmss>\ before they are written - tell me the folder.
```

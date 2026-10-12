# Schedule round-trip (Revit schedule -> Excel -> Revit): prompt template

Scripts (run in this order):
1. `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_dump.py`: IronPython, run inside Revit via `execute_revit_code`. Read-only.
2. Pick one builder (both CPython, `py -3.14` + openpyxl):
   - **Grouped (the user's preferred format, 2026-09-30):** `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_build_grouped_xlsx.py <dump.json> <reference.xlsx> [out.xlsx] --sheet "<yymmdd>_<name>" --id-first --add-after "GFA Component-Space/Room Category=Studio_Function Code,Studio_Sub-Function Code"`. The two flags reproduce the user's requested layout: an Element ID(s) column first (IDs `;`-separated when a row groups several Areas), and Function / Sub-Function columns right after GFA Component. **Latest preference (2026-09-30): add `--itemize --level-order building`.** This gives one row per Area under the grey Building Asset bands. Basement levels run Mezzanine, then 01, 02, 03, 04; the other assets run Ground, 01st, 02nd, 03rd ... and anything else last (Tower levels like "27th to 36th Floor" sort by their first number). The reference workbook is the style template. Since 2026-10-02 use `C:\SK\Projects\ProjectA\Exports\2026-10-02\_reference_template.xlsx`, because the original Downloads reference was deleted. Its Studio_Area_Department heading is renamed to match the schedule, so add `--component "Studio_Area_Department"` and drop `--add-after` (Function / Sub-Function are now reference columns). The original reference was `C:\Users\user\Downloads\GLA_GSA\Area Schedule reference.xlsx`: Aptos Narrow, grey band row per Building Asset, `=SUM` totals row, heading repeated at the bottom). There is one row per unique Level + Building Asset + GFA Component + GLA/GSA Component + Floor Count, so GLA/GSA Component never shows `<varies>`. Rows with an empty GLA/GSA Component are highlighted amber. The Element IDs per row sit in a hidden column after the last one; `_Original` / `_Lists` / `_Meta` are hidden sheets.
   - Itemized (one row per element, all fields + Fields/Key sheets): `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_build_xlsx.py`.
2b. Optional Excel-side logic: `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_copy_logic.py <workbook.xlsx> <dump.json> --source "Building 2" --targets "Building 3,Building 4,Building 5" [--column "GLA/GSA Component"]`. It copies how the source building fills one column onto the target buildings, keyed on Function + Sub-Function + Area Calc. Type. The rule is used as-is if it's the same on every level, otherwise per level. Mixed cases and cases with no precedent are listed, not guessed. It fills blanks only (`--overwrite` to change existing values) and writes to `Updated\` (original untouched). Filled cells are green, and a `<source> Logic` sheet holds the rules, the changes and the rows left for a decision. It needs an itemized workbook.
3. Import back (written 2026-10-02):
   - 3a, CPython (no Revit): `py -3.14 C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_import_diff.py <edited.xlsx> [changes.json] [--params "Studio_Function Code,Studio_Sub-Function Code,Studio_Area_Department"]`. It diffs the data sheet against hidden `_Original`, keyed on the Element ID(s) column, not row order. Edits in other columns are listed and ignored; values that are new to a column are flagged as possible typos.
   - 3b, IronPython via `execute_revit_code`:
     ```python
     CHANGES_JSON = r"C:\SK\Projects\ProjectA\Exports\<date>\_import_changes_<...>.json"
     DRY_RUN = True      # False ONLY when the user says "apply"
     exec(compile(open(r"C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_import.py").read(), "schedule_roundtrip_import.py", "exec"))
     ```
     It refuses to run if the active document isn't the workbook's model. It skips conflicts (value changed in Revit since export), elements owned by others, and elements out of date with central. Apply uses one transaction and re-reads every value in the same call. No save or sync.

## Prompt

Part 1, export (copy, fill in the <...>):

> Connect to Revit PID <PID>. Using the `schedule-roundtrip-excel` skill, export the open schedule "<SCHEDULE NAME>" from <MODEL TITLE> to an editable Excel workbook so I can edit <PARAMETERS, e.g. Studio_Function Code, Studio_Sub-Function Code, Studio_Area_Department>.
> Step 1: `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_dump.py` (execute_revit_code, read-only). Name the dump `_area_schedule_dump_<model title>.json`.
> Step 2: `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_build_grouped_xlsx.py` with `--id-first --itemize --level-order building --component "Studio_Area_Department"` and reference `C:\SK\Projects\ProjectA\Exports\2026-10-02\_reference_template.xlsx`.
> Current (host) model only; exclude linked-model elements. Output to `C:\SK\Projects\ProjectA\Exports\<YYYY-MM-DD>\`. Don't overwrite a workbook I may have edited. Tie the area totals out to the Revit grand total and tell me how many cells are blank.

Part 2, import (after editing and saving the workbook):

> Connect to Revit PID <PID>. Using the `schedule-roundtrip-excel` skill, import the edited workbook `<WORKBOOK PATH>` back into <MODEL TITLE>. Import only <PARAMETERS>.
> Step 3a: `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_import_diff.py`. Step 3b: `C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_import.py` with DRY_RUN = True.
> Show me the dry run (changes per parameter and value, conflicts, owned or out-of-date elements). Write nothing until I say "apply". Then verify every value from the model in a separate call. Don't save or sync.

## How to run

```python
# 1. execute_revit_code (read-only)
SCHEDULE_NAME = "Excel - Area - Overall With Assets-Cross Check"
OUT_JSON = r"C:\SK\Projects\ProjectA\Exports\<YYYY-MM-DD>\_area_schedule_dump_" + doc.Title + ".json"   # per model: parallel sessions share the folder
exec(compile(open(r"C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_dump.py").read(),
             "schedule_roundtrip_dump.py", "exec"))
```

```bash
# 2. build (always pass an explicit out path)
py -3.14 C:/SK/OneDrive/Netbuild/scripts/schedule_roundtrip_build_grouped_xlsx.py "<dump.json>" "C:/SK/Projects/ProjectA/Exports/2026-10-02/_reference_template.xlsx" "<out.xlsx>" --id-first --itemize --level-order building --component "Studio_Area_Department"
# 3a. diff the edited workbook
py -3.14 C:/SK/OneDrive/Netbuild/scripts/schedule_roundtrip_import_diff.py "<edited.xlsx>" "<changes.json>"
```

Step 3b is the `execute_revit_code` block under step 3 above: `DRY_RUN = True` first, and `False` only on "apply".

## What to check before handing over
- Dump output: `matched to schedule rows` = host element count, `unmatched: 0`. `Excluded` counts rendered rows that aren't host elements: rows from loaded links plus the Building Asset group headers. They are never included in the workbook.
- Totals: recompute every area column in Python (openpyxl doesn't calculate formulas). Host rows must tie to the Revit grand total exactly when links are unloaded. With links loaded, host + link rows must equal it (to within rounding).
- `Owned by others` > 0 means the import will skip those elements unless they are relinquished first.
- Import: the dry run must show `skipped: 0` before you ask to apply. After applying: `COMMIT STATUS: Committed` and `VERIFIED IN MODEL: N of N`, then confirm again in a separate call.

## Workbook layout
- Data sheet: row 3 = Revit parameter name, row 4 = access, row 5 = heading and filter row, data from row 6. Element ID + UniqueId are the keys. Yellow columns are editable, grey are read-only.
- Read-only columns: built-ins (Level, Area); key-schedule-driven values (Name, Studio_DM-Area Class., Studio_Area Code are set by **Area Calc. Type**, key schedule `+KEY-Area Typology`); combined parameters; schedule formulas.
- Key parameters get a dropdown from a `Key - <param>` sheet. Workset gets a dropdown from `Lists`.

## Gotchas
- No Revit API maps a schedule row to an element. The dump matches rows by the visible parameter columns and breaks ties with numeric values (a formula column equal to the element's area). Rows with identical keys and values can swap between elements harmlessly.
- IronPython `json` chokes on non-ASCII from `AsValueString()` (e.g. `m²`). The dump escapes it to `\uXXXX` itself.
- Formula values are rounded in the schedule. The builder writes the unrounded area wherever a formula value equals the area, so totals tie out to the Revit grand total exactly.

# BUA Update by Netbuild

© 2026 Netbuild. All rights reserved. · Proprietary software owned by Netbuild · [skaec.com](https://skaec.com) · see **Licence** below

Updates the ProjectA / ProjectB BUA workbooks from Revit in one click. It re-feeds the raw Revit Area export
(`Excel - Raw Area from RVT- Overall With Assets For MEP Team.xlsx`) into the two formatted BUA workbooks
in the same folder, then checks every BUA / GFA total against the raw:

- **Option 1**, `..._with All Levels_Option 1.xlsx`, has a single **Overall BUA** sheet (222 rows with the July 2026 Level set, 229 with the September one):
  - All 10 assets are stacked like the raw layout.
  - Each block shows **only that asset's own levels**. The towers include the typical cross-reference rows.
  - Each block ends with an **`<Asset> Total`** row and a blank separator.
  - A **Grand Total** row closes the sheet.
- **Option 2**, `..._Raw Levels Only_Option 2.xlsx`, has **one sheet per asset**, each with its own levels.
  Each tower sheet has 70 level rows with the July 2026 Level set (73 with the September one).
- In both, the data sheet (`260622_BUA Space Room Split`) is re-fed from the raw, keeping the template
  formatting. The `Roof Areas` sheet is never touched.

The column format is **frozen**: 10 GFA Components × 24 Space/Room Categories gives 274 columns on
Option 1 and 273 on each Option 2 sheet. It never changes between reloads, because other disciplines use
the workbooks as a base.

The rules are the ones `update_bua_workbooks.py` encodes (agreed 2026-07-02). The engine
(`bua_update/engine.py`) is that script, split into functions. On the July and the October 2026 raw
exports it writes workbooks **identical cell for cell and style for style** to the script's own.

## The result: what to do next

| You see | Exit code | Meaning | Do |
|---|---|---|---|
| **ALL TOTALS TIE OUT - DONE** | 0 | Both workbooks updated; every asset and the overall BUA / GFA tie out to the raw | Nothing. The overall BUA and GFA are printed underneath |
| A **`!!!` banner**: NEW ITEMS ... NOT IN THE FROZEN FORMAT | 2 | Column C (`GFA Component-Space/Room Category`) of some raw rows is not in `FROZEN_COMPONENTS` / `FROZEN_CATS`. Their area is **left out**, so the totals mismatch by exactly that amount. The banner lists those raw rows | Fix them in Revit and re-export. If the item is really new, decide first, then add it to the frozen lists in `bua_update/engine.py` and tell the other disciplines. **Nothing is ever added automatically** |
| **\*\*\* SKIPPED ... file is open in Excel** | 3 | That workbook was open, so it was not written (the other one was) | Close it in Excel, then **Retry** (window) or rerun |
| **\*\*\* MISMATCH \*\*\*** | 1 | A total does not tie out | Stop. Read the checks before you change the workbooks or the rules |
| **ERROR** | 4 | A file is missing, or a workbook is not the expected template | Read the message. **Nothing was written** |

The raw export may stay open in Excel. The two Option workbooks must be closed.

Before writing, both workbooks are copied to `<folder>\Backup\<yymmdd_hhmmss>\`. Turn this off with
`--no-backup` or the check box. **Check** reads the raw and reports the new items and level problems
without writing anything.

### Typical floors: two Level sets

The raw stores a typical floor **once, already × its floor count**. The base floor shows raw ÷ count; the
member floors cross-reference the base. In September 2026 the model's Levels changed, so there are two sets:

| Set | Typical floors | Raw Levels |
|---|---|---|
| `2026-07` | 07th ×14 (07-20), 26th ×11 (26-36), 65th ×8 (65-72) | the July 2026 exports and the `260702` workbooks. *22nd Floor* is its own level |
| `2026-09` | 07th ×14 (07-20), 21st ×2 (21-22), 27th ×10 (27-36), 66th ×6 (66-71) | the model since 2026-09-11. *27th to 36th Floor* is one Level, read as *27th Floor* |

**auto** (the default) picks the set that places every level of the raw. If neither does, it picks the one
with fewest problems.

Using the wrong set loses area. For example, a July raw with the September set treats *22nd Floor* as a copy
of *21st Floor* and drops its own 1,644 m² per tower. When that happens, a second `!!!` banner names each
level the set cannot place, and the totals show a MISMATCH. (`update_bua_workbooks.py` itself only has the
September set, so on a July raw it mismatches without saying why.)

## Run it

| | What | Needs |
|---|---|---|
| `BUA Update by Netbuild.exe` | The window. **Update** tab: folder, files (found automatically), typical floors, backup; **Check**, **Update workbooks**, **Retry**, **Open Option 1 / 2**, a coloured result banner and the full checks. **About** and **Licence** tabs | Windows 10 / 11. No Python |
| `BuaUpdate.exe` | The command line (below) | Windows 10 / 11. No Python |
| **Netbuild → Areas → BUA Update** | Ribbon button that opens the window. Shift+Click picks the exe | pyRevit 4.8+ (no model needed) |
| From source | `BUA Update.bat` (window), `BuaUpdate.bat` (command line) | Python 3.9+ with `openpyxl` (`py -3 -m pip install openpyxl`) |

```
BuaUpdate update                       re-feed both workbooks, then check the totals
BuaUpdate check                        report new items / level problems, write nothing
    --folder "<project folder>"        default: settings, the current folder when it holds the raw,
                                       else C:\Users\user\OneDrive - Studio\Projects\ProjectA\Excel\
                                       BUA - Overall With Assets For MEP Team (then C:\SK\Projects\...)
    --raw / --option1 / --option2      other files than the ones found in the folder
    --typical auto|2026-09|2026-07     typical-floor set (default auto)
    --no-backup                        (update) skip the Backup\<date_time>\ copy
BuaUpdate about | license | licence | --version
```

Files are found like this:
- **Raw:** `Excel - Raw Area from RVT- Overall With Assets For MEP Team.xlsx` in the folder.
- **Option 1 / Option 2:** the script's own `260702_...` names when present. Otherwise the **one** file
  matching `*_with All Levels_Option 1.xlsx` or `*_Raw Levels Only_Option 2.xlsx`, so dated sets work too.
  If several files match, it asks which.
- **Data sheet:** `260622_BUA Space Room Split`, or else the sheet named `*BUA Space*`.

`settings.json` next to the exe remembers the folder, the files, the typical-floor set and the backup choice.

For Claude (or any agent): [`BUA_Update_PromptTemplate.md`](BUA_Update_PromptTemplate.md) is the prompt that runs it
and reports by the table above.

## Build and test

```
python -m unittest discover -s BuaUpdate/tests -v      # engine, command line, window, pyRevit button
python BuaUpdate/sync_pyrevit_lib.py                    # after changing bua_update/__init__.py or about.py
BuaUpdate\build_exe.bat                                 # "BUA Update by Netbuild.exe" + BuaUpdate.exe
```

GitHub Actions (**Build BUA Update by Netbuild (Windows)**) runs the tests on Windows and builds both exes.
It smoke-tests the command-line exe and uploads `BuaUpdate-by-Netbuild-windows`.

## Licence

**BUA Update by Netbuild** is proprietary software owned by **Netbuild** (https://skaec.com). It is covered by
the **Netbuild Software Licence Agreement** in the repository's [`LICENSE`](../LICENSE). No licence key is
required for this product. The window's **Licence** tab, `BuaUpdate licence` and **Netbuild → Licence**
show the full agreement.

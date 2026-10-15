# ProjectA Plot GA Export Runner (portable)

A desktop window and command line for the **ProjectA Plot GA export pass**, model by model, using your
existing export scripts:

| Script | Model | Routing |
|---|---|---|
| `scripts\export_master_ga_sheets_by_browser_filter.py` | SW00 master (`ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001`) | `Studio_03 - Browser Filter`: `B2 B5_1-200` → `02_GA Plans B2 B5 (1-200)`, `Site` → `01_GA Plans (1-500) - Site` (except Solar Shading 01/02 and Site Plan) |
| `scripts\export_podium_sheets_by_revision.py` | Podium B001–B005 | placed view type: FloorPlan → `03_…Part Plans`, Elevation → `04_…Elevations`, Section → `05_…Sections` |
| same Podium script, own folders | TOWER-PLANS (`ProjectC-Studio-BIM-T00O-ZZZ-BM-950001`) | FloorPlan → `06_Tower Plans` |
| same Podium script, own folders | TOWER-ELEV-SEC (`ProjectC-Studio-BIM-T00O-ZZZ-BM-950002`) | Elevation → `07_Tower Elevations`, Section → `08_Tower Sections` |
| same Podium script, own folders | AREAS (`ProjectC-Studio-BIM-SW00-ZZZ-AR-970002`) | AreaPlan / FloorPlan → `09_Area Plans` |

For Tower and Areas, the runner replaces the Podium script's `SUBFOLDER_BY_VIEWTYPE` in memory for that
model only. The script file is not changed. You can edit the folder names on **Setup → Models**
(`view type = folder; …`).

Models are bound by their **full document number**. This matters because the master is
`SW0O-…-BM-950001` and Areas is `SW00-…-AR-970002`, and a short match like `SW00` would hit both.
A `settings.json` saved by an older build has its model list replaced by the new defaults when it is
first opened. Paths and all other settings are kept.

Output: `BASE_OUTPUT_FOLDER = <Plot root>\<YYYYMMDD>\PDF|CAD\<category>\<SBFX 01-07>_<Current Revision>.pdf|.dwg`.
A0, Center placement, 100 % (set in the scripts; Setup checks they still say so).

**Your scripts are never edited.** For each call, the runner reads the script and replaces only the
right-hand side of `BASE_OUTPUT_FOLDER`, `REVISION_DATE_FILTER`, `EXPORT_PDF`, `EXPORT_CAD`,
`DRY_RUN` and `doc`. The rest of the file reaches Revit byte for byte. It also adds a short preamble
and one filter line after the `candidates` loop: they bind the call to the right model by title,
narrow it to one category or to the sheets you listed, and report the exact sheet list.

## How it reaches Revit

It POSTs to the pyRevit MCP listener at `http://127.0.0.1:48884/revit_mcp/execute_code/`. That is the
route the `execute_revit_code` MCP tool uses, and the same one `MultiModelBatch.py` uses. Because the
runner calls it directly with a long timeout:

- the MCP bridge's 60-second cut-off and its misleading "timed out" messages don't apply;
- every reply is tagged with a per-call nonce, so a stale echo of an earlier call is detected and
  ignored;
- it does not matter which Revit window is active. Each call binds to the model whose title contains
  the model's match text (`-SW0O-`, `-B001-`, …).

Revit needs pyRevit plus the MCP extension, the same setup Claude uses. If the **MCP Status** button is
set to *Stop*, the runner says so. No Python is needed for the exe.

## Install (portable, no installer)

1. Download `ProjectA_PlotRunner-windows` from **Actions → Build ProjectA Plot Runner (Windows exe)**. It holds:
   - `ProjectA_PlotRunner.exe`: the window.
   - `ProjectAPlot.exe`: the command line.

   Put them in any folder. `settings.json` and `logs\` are created next to them.
   - Or run from source with `ProjectA_PlotRunner.bat` (Python 3.9+ with tkinter), or build the exes
     yourself with `build_exe.bat`.
2. On the **Setup / Paths** tab, link these:
   - the Netbuild folder (default `C:\Users\user\OneDrive - Studio\Documents\Claude`);
   - both scripts;
   - the Plot root (default `…\Projects\ProjectA\Plot`).

   Click **Check paths + scripts**. It confirms:
   - the CONFIG globals are present;
   - the `candidates` loop is there;
   - A0 / Center / 100 % are set;
   - the routing still matches the prompt above (`Studio_03 - Browser Filter`, the subfolder maps and the
     exclusions).

   Then click **Save**.

## Run tab

| Field | What to enter |
|---|---|
| Output folder | `YYYYMMDD` (defaults to today). The full BASE_OUTPUT_FOLDER is shown next to it |
| Revision date | Any spelling: `06-Sep-2026`, `06/09/2026` or `2026-09-06`. **Each model's real format is read live** before exporting, and the filter uses the spelling that model actually stores (SW00 uses DD/MM/YYYY, the Podium models DD-Mon-YYYY). Only zero-padded forms are used, because `6-Sep-2026` would also match `16-Sep-2026` |
| Export | **PDF only**, **CAD (DWG) only**, or **PDF + CAD (DWG)**. With both, all PDFs go first, then all DWGs, never interleaved per sheet |
| Sheets | **All sheets with that revision date**, or **Only these sheets**. Type them in, use **Load .txt…**, or click **Feed sheets…** |

**Feed sheets…** opens a dialog with three ways in. You can mix them:
- **Single sheet**: `210001`.
- **Series**: from `210001` to `210012`, or `B001-AR-210001` to `B001-AR-210012`. Both ends need the
  same prefix.
- **List**: paste sheets separated by comma, `;`, `|`, tab, space or new line.

A sheet can be named by its Sheet Number, its drawing number (SBFX 01–07, with or without `_<rev>`),
or only the last field (`210001`). The same syntax works in the box and on the command line:
`210001 to 210012`, `210001..210012` or `210001-210012` (digits only).

Leave the date empty to export the listed sheets whatever their revision date. If that would pick up a
superseded duplicate (same drawing number, Sheet Number ending `(1)`), Export reports a FAIL and
nothing is exported.

### Models: you open each one, then tell the runner

| Step | Button | What happens |
|---|---|---|
| 1 | **Model is open – check** | Lists the open models and confirms the selected one is open (warns if it is not the active window; that is fine, calls bind by title). Nothing is switched for you |
| 2 | **Export** | First reads the real "Current Revision Date" values and checks the 7 SBFX parameters, `Current Revision` and (on SW00) `Studio_03 - Browser Filter`. It then lists every sheet → category → filename (read-only, nothing written yet) and stops if any of these turn up: duplicate drawing numbers, listed sheets not found, or 0 sheets (with the reason why). Otherwise it exports by category: a **PDF batch** per category, verified on disk, then a **CAD batch** per category, verified on disk. After each CAD batch, the `FP_*.pat`, `*.pcp`, `*.jpg` and `*.png` files it wrote are swept |
| — | **Next model >** | Moves to the next row. Open that model in Revit, then click **Model is open** |
| — | **Verify output folder** | Checks the whole dated folder: file counts per category, empty or invalid files, leftover byproducts, PDF↔DWG pairs, and that every file exported this session is still there |
| — | **Cancel** | Stops after the current call. Revit may still finish the sheet it is on |

**Trust the filesystem only.** A file counts only when all of these are true:
- it is on disk at the expected path;
- it was written during this pass (a file left from an earlier export is reported as
  `NOT REWRITTEN`);
- it is not empty and has stopped growing;
- it starts with `%PDF` (PDF) or `AC` (DWG).

Whatever Revit prints is logged for the record and nothing more.

**Stalls.** Say a batch has produced no new or growing file for `stall_seconds` (90 by default; you
can change it on Setup). The runner then sends the sheets still missing one per call, re-checking the
disk before each one, since the stalled batch may catch up. The *PDF on disk* line reports how many
needed one-sheet calls.

If you listed sheets that were not found, Export stops before writing anything and asks whether to
export the ones that were found.

Every step is logged to `logs\<timestamp>_<model>_<step>.log`. Each export also writes
`logs\<timestamp>_<model>_files.csv`, with sheet, file, status, batch/single and size. The last inputs
are remembered in `last_run.json`.

## Command line

```bat
ProjectAPlot setup                                      :: paths + script checks
ProjectAPlot models                                     :: models open in Revit (active marked)
ProjectAPlot check B001                                 :: is B001 open?
ProjectAPlot dry SW00 --date 06-Sep-2026
ProjectAPlot export SW00 --date 06-Sep-2026 --mode pdf+cad
ProjectAPlot export B001 --date 06-Sep-2026 --mode pdf --sheets "210001 to 210012, 220003"
ProjectAPlot export B002 --mode cad --sheets-file sheets.txt     :: no date: just these sheets
ProjectAPlot run --date 06-Sep-2026 --mode pdf+cad      :: the full pass: SW00, B001..B005 in turn,
                                                   :: waits for "Enter when <model> is open" (s skip, q quit)
ProjectAPlot verify --mode pdf+cad
ProjectAPlot log-time --actual 35 --sheets 120
```

`--out YYYYMMDD` defaults to today. `--allow-missing` exports the listed sheets that were found even
if some were not.

## What it replaces

This is the reusable prompt (`ProjectA_Plot_GA_Export_PromptTemplate.md`) as a tool. The gotchas in that
prompt are built in:
- the `Studio_03 - Browser Filter` name;
- the date format that varies per model;
- misleading timeouts and stale output;
- PDFs before DWGs;
- the DWG byproduct sweep;
- superseded duplicate sheets.

## Tests

```
python -m unittest discover -s ProjectA_PlotRunner/tests -v
```

The tests run copies of the real export scripts (`tests\fixtures\`) against a stand-in Revit listener
(`tests\fake_revit.py`) with ProjectA-like SW00 and B001 models. They cover:
- routing, exclusions and the per-model date format;
- PDF-before-DWG order and the byproduct sweep;
- sheet lists, series and single sheets;
- stall → one-sheet fallback, and stale replies;
- an old file that was not rewritten;
- paused and unreachable Revit;
- the CLI, and the window.

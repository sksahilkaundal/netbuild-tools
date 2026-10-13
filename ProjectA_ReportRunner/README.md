# ProjectA Issue Report Runner (portable)

A desktop window and command line for regenerating the **ProjectF – Sports Boulevard ProjectA TOWER**
ACC Issue detail report with your existing Netbuild scripts:

| Script | Role |
|---|---|
| `scripts\ProjectA_IssueReport_Pipeline.py` | run by this tool (CONFIG globals set per run) |
| `ProjectA_IssueExport_Extract.py`, `ProjectA_IssueDetailReport_Build.py` | run by the pipeline itself |
| `scripts\ProjectA_IssueWalkthrough.py` | Studio notes: `pending` list and note logging |
| `scripts\ProjectA_IssueReport_Verify.py` | final check, must end `ALL CHECKS PASSED` |

**Your scripts are never edited.** The runner reads the pipeline's source, replaces the
top-level `BASE`, `EXPORT_SUBDIR`, `ACC_PDF`, `BCF_FILE`, `MAX_ISSUE_ID`,
`PREVIOUS_EXPORT_SUBDIR`, `RUN_EXTRACT`, `RUN_BUILD` and `BY_MODEL` assignments in memory, then
runs it as `__main__`. Each value keeps the form of the original assignment: `Path(...)` stays a
Path, and a list stays a list. If several BCFs are selected but `BCF_FILE` holds a single
string, the run stops with an error rather than guessing.

## Install (portable, no installer)

1. Copy the `ProjectA_ReportRunner` folder anywhere, e.g. `C:\SK\OneDrive\Netbuild\ProjectA_ReportRunner`.
2. Double-click **`ProjectA_ReportRunner.bat`**. It needs Python 3.9+ with tkinter, which the
   standard python.org installer includes.
3. On the **Setup / Paths** tab:
   - **Browse...** to link each local path: the Netbuild folder, the five scripts, Python, the
     Issues BASE folder and the time-saved log.
   - Or link the Netbuild folder and click **Auto-find scripts in Netbuild folder**.
   - Each row shows `found` / `NOT FOUND`. Click **Save** to write `settings.json` next to the
     app.
   - **Python**: leave it blank to use the Python that opened the app. Otherwise point it at the
     `python.exe` that has the scripts' packages installed (PyMuPDF etc.).

**Exe version (no Python needed to open it).** Download `ProjectA_ReportRunner-windows` from the
repo's **Actions → Build ProjectA Report Runner (Windows exe)** run. It holds:
- `ProjectA_ReportRunner.exe`: the window.
- `ProjectA.exe`: the command line.

You can also build both locally with `build_exe.bat`. Put the exes in any folder;
`settings.json` and `logs\` are created next to them. Your scripts still run with the Python
linked on the Setup tab.

## Workflow (Run tab)

| Step | Button | What it does / checks |
|---|---|---|
| Inputs | — | BASE; the new dated export folder (newest is pre-selected); the ACC `Issue detail-….pdf`; **every** BCF (all pre-selected, since ACC caps a BCF at 250 issues); Issues = All or "Up to #"; Previous EXPORT folder (pre-set to the newest older dated folder, or `none`) |
| 1 | **1. Extract** | `RUN_BUILD=False`. Checks `pin snapshots: N from BCF, 0 from PDF` and `ACC links: N of N issues`. Compares BCF topic GUIDs against the previous export and warns if they **share no issues** |
| — | **List issues with no Studio note** | `ProjectA_IssueWalkthrough.py pending` (no level range) |
| — | **Run walkthrough** | runs the walkthrough with the arguments you type, e.g. your note command; nothing is invented |
| 2+3 | **2. Build + 3. Verify** | First checks for report PDFs held open in a viewer and asks you to close them; it never closes them itself. Then `RUN_EXTRACT=False`, checks today's `<YYYYMMDD>_ProjectA_ACC Issue detail (Issues a-b)` folder holds both reports, and runs Verify automatically |
| 3 | **Verify only** | `ProjectA_IssueReport_Verify.py <folder>`, must end `ALL CHECKS PASSED`. Lists page count and MB per PDF |
| — | **Open output folder** | opens the folder in Explorer (not the PDFs) for the After-image spot-check |
| — | **Log time saved...** | appends a row to the time-saved CSV. If the file exists, its header is followed |

If the build's move to `_superseded` stops because a PDF is open, the run shows
**"close it, then run Build again"**.

Every run is logged to `logs\<timestamp>_<step>.log` next to the app. The last inputs are
remembered in `last_run.json`.

## Command line

```bat
ProjectA setup                                   :: show path status
ProjectA setup --set netbuild_root=D:\Netbuild   :: link a path
ProjectA extract --export 20261009 --previous 20261001
ProjectA pending
ProjectA walk -- <walkthrough args>
ProjectA build   --export 20261009 --issues all
ProjectA verify                                  :: today's report folder in BASE
ProjectA log-time --export 20261009 --issues 412 --actual 25
```

`--acc-pdf` and `--bcf` (repeat it for each file) default to the files found in the export
folder.

## Assumptions to confirm on first run

- The pipeline assigns each CONFIG name at module top level (`NAME = ...`). Otherwise the
  runner stops and names the missing global.
- `PREVIOUS_EXPORT_SUBDIR = None` means "no movement table", and `MAX_ISSUE_ID = None` means
  all issues.
- One build run with `BY_MODEL=True` writes both reports. You can untick it on Setup.
- `ProjectA_IssueWalkthrough.py pending` needs no further arguments. If it does, edit
  "Walkthrough 'pending' args" on Setup.
- Time-saved log path/format: set it on Setup. The default is
  `C:\SK\OneDrive\Netbuild\time_saved_log.csv`.

## Tests

```
python -m unittest discover -s ProjectA_ReportRunner/tests
```
These run the whole workflow against stand-in scripts (no ACC data needed).

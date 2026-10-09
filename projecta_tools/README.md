# ProjectA Tools — ProjectA ACC Issue Report, portable for Windows (no admin rights)

One zip that runs the ProjectA ACC Issue Report pipeline (prompt **Ver. 05**) on any Windows PC:
no Python install, no admin rights and no internet needed on the PC.

| In the zip | What it is |
|---|---|
| `runtime\` | Official python.org **embeddable Python 3.14** (win_amd64) plus pymupdf, reportlab, Pillow, pywin32, openpyxl and pip. Plain files only: no registry, no installer. |
| `app\projecta_launcher.py` | Menu / command-line front end that runs your scripts unchanged. |
| `Netbuild\` | The ProjectA issue scripts in the same layout as `C:\SK\OneDrive\Netbuild` (`ProjectA_IssueExport_Extract.py`, `ProjectA_IssueDetailReport_Build.py`, `scripts\ProjectA_IssueReport_Pipeline.py`, `scripts\ProjectA_IssueWalkthrough.py`, `scripts\ProjectA_IssueReport_Verify.py`) plus the two prompt templates under `docs\`. |
| `ProjectA Issue Report.bat` | Starts the menu. Also runs portable, straight from the unzipped folder. |
| `Install.bat` / `Uninstall.bat` | Per-user install to `%LOCALAPPDATA%\ProjectA_Tools`, with Start menu and Desktop shortcuts. |

## Install (current user, no admin)

1. Unzip `ProjectA_Tools_<date>.zip` anywhere, e.g. Downloads.
2. Double-click **`Install.bat`**. It:
   - copies the package to `%LOCALAPPDATA%\ProjectA_Tools`;
   - unblocks the downloaded files;
   - adds **ProjectA Issue Report** shortcuts to the Start menu and Desktop;
   - runs the environment check, which should end `READY`.

   Re-running `Install.bat` updates the tool. Your settings and logs are kept, and so are Netbuild scripts you edited after installing (newer files win).
3. **Portable alternative:** skip the install and double-click `ProjectA Issue Report.bat` inside the unzipped folder. A USB stick or a OneDrive folder also works, but OneDrive would sync about 150 MB of runtime files.

**Which scripts it runs.** By default the launcher uses your **live** `C:\SK\OneDrive\Netbuild`, when that folder holds `scripts\ProjectA_IssueReport_Pipeline.py`, so edits you make there take effect straight away. On any other PC it uses the bundled `Netbuild\` copy. To point it elsewhere, use menu **9 Settings**.

## Use — the menu

```
 1  Set up export (folder, ACC PDF, BCFs, issue cap, previous export)
 2  STEP 1  Extract only  + checks + missing notes by tier / model
 3  Missing Studio notes (walkthrough pending) by tier / model
 4  Log Studio notes (walkthrough log)
 5  STEP 2  Build both reports  (+ publish, retry if a PDF is open)
 6  STEP 3  Verify an output folder
 7  RUN ALL: extract -> notes -> build -> verify -> spot-check list
 8  Walkthrough command (next / show / goto / bulk ...)
 9  Settings + environment check
10  After-photo spot-check list (issues with 2-3 photos)
11  Open BASE / logs folder
```

How the prompt's steps map to the menu:

| Prompt (Ver. 05) | Launcher |
|---|---|
| Blanks: BASE, export folder, ACC PDF, BCF(s), Issues (all / up to #NNNN), previous export folder | **1** lists the dated folders, the PDFs and **every** BCF in the export (ACC caps a BCF at 250 issues). For the previous export, it only accepts a folder that holds an extracted `ProjectA_issue_detail_report_*.csv`. |
| 1. Extract only (`RUN_BUILD=False`); confirm `pin snapshots: N from BCF, 0 from PDF` and `ACC links: N of N issues` | **2** checks both lines. It also flags any "missing" snapshots. |
| 1. Issues with no Studio note (`ProjectA_IssueWalkthrough.py pending`, no range), grouped by tier / model; say if the previous export shares no issues | **2 / 3** group the list with your builder's own `tier_model()` and `BUCKET_NO` (01 Basement … 16 General). They also print how many issues the previous export shares, with `!!!` if it is none. |
| Give notes, or "leave blank" | **4** logs **your** notes with the walkthrough's `log`. In **7**, choose `[L]og`, `[B]uild and leave blank` or `[S]top`. The tool never writes a note on its own. |
| 2. Build (`RUN_EXTRACT=False`) → both reports, published to `<BASE>\<YYYYMMDD>_ProjectA_ACC Issue detail (Issues a-b)\`; older builds move to `_superseded` | **5**. If a PDF is open in your viewer, publishing stops and it asks you to **close it yourself**, then retries the same `publish()` (it never closes the viewer). |
| 4. Verify, which must end `ALL CHECKS PASSED`; report page counts, issue counts, sizes; spot-check the After images | **6** runs `ProjectA_IssueReport_Verify.py` and tabulates pages / issues / MB per report. **10** lists the issues with 2–3 photos and their `_photoN` files. |
| Time-saved log | Every run is appended to `%LOCALAPPDATA%\ProjectA_Tools\user\session_log.csv` (when, step, export, minutes, log file). |

Every step runs your scripts **unchanged**, in a fresh Python process, with the CONFIG globals set the way the prompt's "Commands behind the prompt" do. The exact code of each run is saved in `%LOCALAPPDATA%\ProjectA_Tools\user\runs\` and its full output in `...\logs\`.

## Use — command line (scripting, or Claude Code on the PC)

```bat
set ProjectA="%LOCALAPPDATA%\ProjectA_Tools\ProjectA Issue Report.bat"
%ProjectA% check
%ProjectA% extract --base "C:\SK\Projects\ProjectA\Issues\260914" --export 20261009 ^
      --pdf "Issue detail-260916 to 261008-202610081210.pdf" ^
      --bcf "2026-10-08 16_06 245 Issues-260916 to 261008.bcf" --cap all --prev 20261008
%ProjectA% pending
%ProjectA% walk log "1041|L26|<note>"
%ProjectA% walk next --lo 41 --hi 58          &rem any ProjectA_IssueWalkthrough.py argv (Revit open for next/goto)
%ProjectA% build
%ProjectA% verify                              &rem the folder just built (or --folder "<output folder>")
%ProjectA% spotcheck
%ProjectA% all --yes                           &rem extract -> pending -> build -> verify; --yes = leave un-noted blank
```

Options are remembered, so after the first `extract` the other steps need no arguments. Exit code 0 means OK; for `verify` it means `ALL CHECKS PASSED`.

## Notes

- **Python 3.14.7 here vs your `py -3.14`:** same major version. The bundled packages are pinned in `requirements.txt` (pymupdf 1.28.2, reportlab 5.0.1, Pillow 12.3.0). If your PC has older versions and you want byte-identical reports, run `py -3.14 -m pip freeze` on your PC, put those versions in `requirements.txt` and rebuild (below). Then re-run your regression harness (`_backups\2026-10-08_projecta-issue-scripts-pre-cleanup\regress.py` + `compare.py`).
- **Walkthrough `next` / `goto`** reach Revit over the pyRevit MCP listener on `127.0.0.1:48884`, exactly as before. Revit must be open with the listener running.
- **Adding a package later (no admin):** `"%LOCALAPPDATA%\ProjectA_Tools\runtime\python.exe" -m pip install --target "%LOCALAPPDATA%\ProjectA_Tools\runtime\Lib\site-packages" <package>`
- **IT restrictions:** if AppLocker / WDAC blocks `.exe` files under `%LOCALAPPDATA%`, run it portable from a folder that is allowed, or ask IT to allow `runtime\python.exe`, which is the python.org-signed binary. The tool needs no network access at run time.
- **Uninstall:** `Uninstall.bat` in `%LOCALAPPDATA%\ProjectA_Tools`. It never touches BASE, the reports or the notes CSVs.

## Rebuild the zip (after a script or package change)

On any PC or server with Python 3.10+ and internet (it cross-installs the Windows wheels):

```bash
cd projecta_tools
python build_bundle.py               # -> dist/ProjectA_Tools_<YYMMDD>.zip
python build_bundle.py --python 3.14.8
```

Edit the scripts in `package/Netbuild/` (or copy your current ones from `C:\SK\OneDrive\Netbuild`) before rebuilding.

# ProjectA Issue Report — Reusable Prompt

Turns a fresh ACC "Issue detail" export (PDF + BCF) into the client-ready
issue report with Studio notes, a summary page, ACC links and the podium-building
split. Fill in the <blanks> and paste. Skill: `projecta-issue-report`
(`.claude\skills\projecta-issue-report\SKILL.md`), which carries the same prompt —
keep the two in sync. Updated 2026-10-08 (cleanup, ACC links, in-PDF table
links, podium building split) and 2026-10-09 (summary links; summary moved to
page 1 under the report's two title lines, issue table after it).

```
Using scripts\ProjectA_IssueReport_Pipeline.py
(C:\SK\OneDrive\Netbuild\scripts\ProjectA_IssueReport_Pipeline.py),
which runs
  ProjectA_IssueExport_Extract.py (C:\SK\OneDrive\Netbuild\ProjectA_IssueExport_Extract.py) and
  ProjectA_IssueDetailReport_Build.py (C:\SK\OneDrive\Netbuild\ProjectA_IssueDetailReport_Build.py),
regenerate the ProjectA ACC Issue detail report (ProjectF - Sports Boulevard ProjectA TOWER).

Set the pipeline's CONFIG globals from the command line (BASE, EXPORT_SUBDIR,
ACC_PDF, BCF_FILE, MAX_ISSUE_ID, PREVIOUS_EXPORT_SUBDIR); do not edit the file.

BASE = C:\SK\Projects\ProjectA\Issues\260914
New export folder (a NEW dated folder under BASE): <EXPORT SUBDIR, e.g. 20261009>
  ACC PDF : <Issue detail-....pdf>
  BCF(s)  : <.... Issues.bcf>  [list every BCF -- ACC caps a BCF at 250 issues]
Issues  : <all | up to #NNNN>
Previous EXPORT FOLDER for the "movement since" table: <YYYYMMDD | none>
  (the export folder, not the report PDF -- the report's date is the build
   date, e.g. "20261008_ProjectA_ACC Issue detail..." was built from folder 20261009)

1. Run step 1 (extract) only (RUN_BUILD=False). Confirm the log reads
   "pin snapshots: N from BCF, 0 from PDF" and "ACC links: N of N issues".
   Then list the issues with no Studio note using scripts\ProjectA_IssueWalkthrough.py
   pending (no level range; C:\SK\OneDrive\Netbuild\scripts\ProjectA_IssueWalkthrough.py),
   grouped by tier / model (tower tiers, podium buildings B1-B5 / B2-B5 sheet,
   3D NWD / RVT pins). I will either give notes (log them with the same
   walkthrough script) or say "leave blank". Do not invent notes. Also tell me
   if the previous export shares no issues with this one.
2. Then build (RUN_EXTRACT=False). Report layout, the same in both reports:
   - page 1: the SUMMARY, with the report's first two lines copied on top
     of it ("ProjectF - Sports Boulevard ProjectA TOWER" and "Issue Detail Report
     ... - Updated with Current Status (N Issues)"): resolved/pending, by
     ACC status, by tier / model (tower tiers by level; podium-building
     sheets B001-B005 and the combined B2B5 sheet under their buildings
     whatever the level; 3D NWD / RVT pins as their own rows), movement
     since the previous export. The tier / model rows are numbered 01-16
     like the by Tier-Model groups, and every row with issues is a
     highlighted link -- to its group in the by Tier-Model report, to its
     lowest-id issue page in the complete report;
   - then the issue table, under the same two title lines, with a Tier /
     Model column ("NN short label"); each ACC ID jumps to that issue's
     page inside the PDF;
   - one page per issue: status badge, fields, full description, comment
     thread, Studio note box, Before/After images; the #ID in the heading opens
     the issue in ACC.
3. The pipeline writes one folder per export with TWO reports:
   <BASE>\<YYYYMMDD>_ProjectA_ACC Issue detail (Issues <first>-<last>)\
     <YYYYMMDD>_ProjectA_ACC Issue detail (Updated with Current Status).pdf
       -- the complete report, issues in ACC id order (as before)
     <YYYYMMDD>_ProjectA_ACC Issue detail (Updated with Current Status) - by Tier-Model.pdf
       -- the same issues grouped by tower tier / podium building / 3D model,
          ACC id order inside each group, with group rows in the table, a band
          above each group and PDF bookmarks per group and issue (BY_MODEL=True)
   YYYYMMDD = today (the build date). An earlier folder of the same name, and
   any OLDER-dated folder for the same issue range, moves to <BASE>\_superseded\
   by itself, so <BASE> keeps only the latest build of each export. If a PDF
   in one of them is open in my viewer, that move stops -- ask me to close it,
   never close it yourself.
4. Check both reports with scripts\ProjectA_IssueReport_Verify.py
   (C:\SK\OneDrive\Netbuild\scripts\ProjectA_IssueReport_Verify.py) on the output
   folder -- it must end "ALL CHECKS PASSED" (summary first with the title
   lines on top, page count, issue count, size, table jumps, ACC links, by
   Tier-Model grouping / id order / bookmarks).
   Tell me the page counts, issue counts and sizes; spot-check the After
   image on issues with 2-3 attachment photos. The full PDF is 40-100 MB, so
   give me the folder path; do not send the files. Log the session in the
   time-saved log.
```

## Blanks

- **Export subdir / file names** — a NEW dated folder per export (e.g. `20261009`),
  never the previous export's folder: the builder expects exactly one
  `ProjectA_issue_detail_report_*.csv` per folder and the movement table reads the
  previous folder's CSV. Use the `C:\SK\Projects\...` path (junction), not the
  OneDrive path.
- **Issues** — `all` (no cap) or the last id the walkthrough covered. If the BCF
  carries higher ids than the cap, the CSV silently stops at the cap.
- **Previous export folder** — the dated folder of the last export, for the
  movement table; `none` to skip.

## Commands behind the prompt

```powershell
# 1  extract only
py -3.14 -c "import sys; sys.path.insert(0, r'C:\SK\OneDrive\Netbuild\scripts'); import ProjectA_IssueReport_Pipeline as p; p.EXPORT_SUBDIR='<YYYYMMDD>'; p.ACC_PDF='<Issue detail-....pdf>'; p.BCF_FILE=['<.... Issues.bcf>']; p.MAX_ISSUE_ID=None; p.PREVIOUS_EXPORT_SUBDIR='<prev YYYYMMDD>'; p.RUN_BUILD=False; p.main()"
# 1b missing notes (every un-noted issue; 3D pins show level "?")
py -3.14 -c "import sys; sys.path.insert(0, r'C:\SK\OneDrive\Netbuild\scripts'); import ProjectA_IssueWalkthrough as w; w.EXPORT_SUBDIR='<YYYYMMDD>'; w.main(['pending'])"
# 2  build only -- same overrides, p.RUN_EXTRACT=False instead of p.RUN_BUILD=False.
#    It builds into "<folder> (building HHMMSS)" and publishes it as
#    <BASE>\<YYYYMMDD>_ProjectA_ACC Issue detail (Issues <first>-<last>)\ (full + by Tier-Model);
#    p.BY_MODEL=False for the full report only, p.OUT_DATE='YYYYMMDD' to force the date,
#    p.SUPERSEDE_NOTE='<what changed>' for the suffix of a replaced folder in _superseded,
#    p.SUPERSEDE_OLDER=False to keep older-dated folders of the same issue range in BASE.
# 3  verify the published folder (read-only; exit 0 = ALL CHECKS PASSED; finds the export from "(Issues a-b)")
py -3.14 "C:\SK\OneDrive\Netbuild\scripts\ProjectA_IssueReport_Verify.py" "<BASE>\<YYYYMMDD>_ProjectA_ACC Issue detail (Issues <first>-<last>)"
```

## Gotchas baked into the scripts (don't relearn)

- Pin snapshots come from the BCF (~70 KB each); re-encoding the PDF's copy
  made a 240 MB report. ACC caps a BCF export at 250 issues, so a bigger export
  comes as several BCFs (e.g. 230 + 178 on 2026-10-08); BCF_FILE takes them all
  as a list. Check "pin snapshots: N from BCF, 0 from PDF" in the log.
- The ACC link is only in the export PDF (on each issue heading); the BCF
  topic Guid is NOT the ACC issueId. The extractor writes it to the CSV's
  `acc_url` column — an export extracted before 2026-10-08 must be
  re-extracted to get ACC links (the in-PDF table jumps work regardless).
- Only a page with a Status value is an issue page — the Contents pages
  match the `#NNNN:` pattern too.
- DAR's requirement text is often in the comment, not the description; both
  come from the full page stream.
- The extractor does not list missing notes; the walkthrough's `pending` (no
  range) does, and the builder repeats the list as its first log line.
- Tier / model buckets, checked in this order: `-DWG-B001..B005-` sheet ->
  "Building B1..B5"; `-DWG-B2B5-` sheet -> "Buildings B2-B5 (B2B5 sheet)" (one
  combined sheet, building unknown); `.nwd` pin -> "3D (NWD) Overall Model";
  `.rvt` pin -> "3D (RVT) Model"; otherwise (T00O / SW00 sheets) by level ->
  Basement / Podium GF-06 / Tier 01-05. Podium-building sheets share level
  numbers with the tower, so the zone always wins.
- 3D pins have no level, so the walkthrough's level ranges skip them; place
  them by height with `scripts\ProjectA_BcfViewpointLevels.py` (skill
  `projecta-bcf-viewpoint-levels`).
- Output = one folder per export and build date, named with the issue range, so
  two exports built the same day never collide. Inside: the complete report (ACC
  id order) and ONE "by Tier-Model" report -- the user wants these two, not one
  PDF per building. Groups follow the summary-row order (01 Basement, 02 Podium
  GF-06, 03-07 Tier 01-05, 08-12 Building B1-B5, 13 B2-B5 sheet, 14 3D NWD, 15
  3D RVT, 16 General), only groups with issues, ACC id order inside a group.
- PDF-XChange Editor locks an open PDF: the rename fails with "being used by
  another process". Ask the user to close it; never kill the viewer.
- Every script's CONFIG defaults to the latest export (`20261009`, previous
  `20261008`, no cap); still pass the overrides explicitly.
- Check `py -3.14 -c "import reportlab, pymupdf, win32com"` before a run.
- **If any of the scripts is edited**, rerun the regression harness in
  `C:\SK\OneDrive\Netbuild\_backups\2026-10-08_projecta-issue-scripts-pre-cleanup\`
  (`regress.py` old vs new code root, then `compare.py`). "different: 0" = no
  behaviour change; for an intended change read every DIFF. Exact commands:
  the `projecta-issue-report` skill, Check / verify.
- Reference sizes: the by Tier-Model report is the same size as the full one (same pages, plus bookmarks).
  205 issues = 214 pages / 56 MB (09-18); 408 issues = 425
  pages / 95.7 MB (10-08, folder 20261008); 245 issues = 256 pages / 43.1 MB
  (10-08, folder 20261009, with links and the podium split).

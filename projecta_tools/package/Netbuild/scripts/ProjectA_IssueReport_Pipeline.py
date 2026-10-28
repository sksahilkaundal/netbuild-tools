# -*- coding: utf-8 -*-
"""
ProjectA Issue Report pipeline -- ACC export in, client-ready issue report out.

  Step 1  ProjectA_IssueExport_Extract.py     ACC "Issue detail" PDF + BCF
                                          -> <export>/ProjectA_issue_detail_report_<a>_<b>.csv
                                          -> snapshots_full/<id>.png  (BCF pin snapshot)
                                          -> snapshots_after_photos/<id>_photoN.jpeg
                                          (+ acc_url: the issue's ACC link, from the PDF heading)
  Step 2  ProjectA_IssueDetailReport_Build.py  CSV + core_tagging_completed.csv + studio_notes_clean.csv
                                          -> one output folder per export + build date:
     BASE/<YYYYMMDD>_ProjectA_ACC Issue detail (Issues <first>-<last>)/
        <YYYYMMDD>_ProjectA_ACC Issue detail (Updated with Current Status).pdf
            the complete report, issues in ACC id order (unchanged)
        <YYYYMMDD>_ProjectA_ACC Issue detail (Updated with Current Status) - by Tier-Model.pdf
            the same issues grouped by tier / model (summary-row order: Basement,
            Podium GF-06, Tier 01-05, Building B1-B5, B2-B5 sheet, 3D NWD/RVT,
            General), ACC id order inside each group; group rows in the table,
            a band above each group, PDF bookmarks per group and issue (BY_MODEL)
     Both: title, issue table with Tier / Model column, SUMMARY page by tier /
     model, one page per issue; table ID -> issue page, heading #ID -> ACC.
     Built in a staging folder, then published; an existing folder of the same
     name moves to BASE/_superseded/ ("<name> (replaced HHMM)" or SUPERSEDE_NOTE),
     and so do OLDER-dated folders for the same issue range ("<name> (superseded
     by <date>)"; SUPERSEDE_OLDER) -- BASE keeps only the latest build of each
     export. A PDF open in a viewer only blocks the publish: close it and rename
     the staging folder by hand (an older folder that cannot move is reported and
     left in place).

The Studio notes come from studio_notes_clean.csv, which is filled by the
walkthrough (ProjectA_IssueWalkthrough.py) -- this pipeline never invents a note.
List the un-noted issues after extract-only (RUN_BUILD=False) with
ProjectA_IssueWalkthrough.py pending (no range); the builder repeats the list.
Leave them blank deliberately or note them first.

Both step scripts live one folder up (the project root, Netbuild), next to the
report builder's other inputs. Run this file, or run either step on its own.

------------------------------------------------------------------
HARD-WON (each of these cost a wrong report once)
------------------------------------------------------------------
1. TAKE PIN SNAPSHOTS FROM THE BCF, NOT THE PDF. The same 1618x908 view is
   ~70 KB as the BCF's snapshot.png and 1-2 MB re-encoded from the PDF; with
   164 issues that is a 41 MB report versus 240 MB.
2. ONLY A PAGE WITH A STATUS VALUE IS AN ISSUE PAGE. When the export's
   running header is plain "Issue detail", the Contents pages also read
   "Issue detail / #NNNN: title" and were parsed as issues (3 duplicates).
3. DAR's REQUIREMENT TEXT IS OFTEN IN THE COMMENT, NOT THE DESCRIPTION, and
   the description wraps -- read the whole issue (all its pages) as one
   stream. Timestamps split over lines and across page breaks.
4. PURGE AN ISSUE'S OLD _photoN FILES BEFORE WRITING NEW ONES, or an
   attachment removed in ACC lingers into the next report.
5. CAP WITH MAX_ISSUE_ID. An export filtered differently (e.g. not just
   "assigned to Studio") pulls in issues that were never walked.
6. THE ACC LINK IS ONLY IN THE PDF. The BCF topic Guid is not the ACC
   issueId; the extractor reads the link on each issue heading ("ACC links:
   N of N issues" in the log). Re-extract an old export to get its links.
7. PODIUM-BUILDING SHEETS ARE NOT TOWER TIERS. B001..B005 / B2B5 sheets share
   level numbers with the tower (L01-L06), so the builder buckets by sheet
   zone first, level second.
"""
import os
import re
import sys
import time

# ----------------------------- CONFIG ---------------------------------
BASE = r"C:\SK\Projects\ProjectA\Issues\260914"
EXPORT_SUBDIR = "20261009"                       # folder under BASE holding the ACC PDF + BCF(s)
ACC_PDF = "Issue detail-260916 to 261008-202610081210.pdf"   # file names inside EXPORT_SUBDIR
BCF_FILE = ["2026-10-08 16_06 245 Issues-260916 to 261008.bcf"]   # one name or a list -- ACC caps a BCF
                                                 # export at 250 issues; None = every *.bcf in EXPORT_SUBDIR
MAX_ISSUE_ID = None                              # ignore anything newer; None = all
PREVIOUS_EXPORT_SUBDIR = "20261008"              # summary page's "movement since"; "" to skip
BY_MODEL = True              # also the 'by Tier-Model' PDF (grouped by tier / model, id order inside)
OUT_DATE = None              # date in the output names; None = today (the build date)
SUPERSEDE_NOTE = ""          # suffix for a replaced output folder in _superseded; "" = "replaced HHMM"
SUPERSEDE_OLDER = True       # also move OLDER-dated output folders for the same issue range to _superseded

RUN_EXTRACT = True
RUN_BUILD = True
# ------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)          # …\Netbuild -- where the two step scripts live
sys.path.insert(0, TOOLS)


def main():
    export_dir = os.path.join(BASE, EXPORT_SUBDIR)
    pdf = os.path.join(export_dir, ACC_PDF)
    if not BCF_FILE:
        names = sorted(n for n in os.listdir(export_dir) if n.lower().endswith(".bcf"))
    else:
        names = [BCF_FILE] if isinstance(BCF_FILE, str) else list(BCF_FILE)
    bcfs = [os.path.join(export_dir, n) for n in names]
    print("Export  :", export_dir)
    print("BCF     : %s" % (", ".join(names) or "none"))
    print("Cap     : #%s" % (MAX_ISSUE_ID or "none"))

    if RUN_EXTRACT:
        print("\n" + "=" * 70 + "\nStep 1  extract ACC export\n" + "=" * 70)
        if not bcfs:
            raise SystemExit("no .bcf in %s" % export_dir)
        for p in [pdf] + bcfs:
            if not os.path.exists(p):
                raise SystemExit("missing: %s" % p)
        # the extractor reads its config from the environment when set
        # (several BCFs travel as one ";"-separated value)
        os.environ.update({"ProjectA_BASE": BASE, "ProjectA_EXPORT_SUBDIR": EXPORT_SUBDIR,
                           "ProjectA_ACC_PDF": pdf, "ProjectA_BCF": ";".join(bcfs),
                           "ProjectA_MAX_ISSUE_ID": str(MAX_ISSUE_ID or "")})
        import ProjectA_IssueExport_Extract as ext
        ext.BCF_PATH = bcfs          # env is only read on first import
        ext.main()

    if RUN_BUILD:
        print("\n" + "=" * 70 + "\nStep 2  build report\n" + "=" * 70)
        import ProjectA_IssueDetailReport_Build as build
        build.BASE = BASE
        build.EXPORT_SUBDIR = EXPORT_SUBDIR
        build.MAX_ISSUE_ID = MAX_ISSUE_ID
        build.PREVIOUS_EXPORT_SUBDIR = PREVIOUS_EXPORT_SUBDIR
        build.OURS_CSV = os.path.join(BASE, "core_tagging_completed.csv")
        build.Studio_NOTES_CSV = os.path.join(BASE, "studio_notes_clean.csv")
        build.BEFORE_DIR = os.path.join(BASE, "snapshots_full")
        build.AFTER_DIR = os.path.join(BASE, "snapshots_after_photos")
        build.NEW_REPORT_CSV = build._export_csv()          # fails early if the folder has 0 or 2+ export CSVs

        # one output folder per export + build date: the full report and the by Tier-Model report.
        # Build into a staging folder, then publish it (an older folder of the same name moves to
        # _superseded) -- a PDF left open in a viewer only blocks the publish step, never the build.
        date = OUT_DATE or time.strftime("%Y%m%d")
        ids = sorted(int(r["issue_id"]) for r in build.read_csv(build.NEW_REPORT_CSV)
                     if not MAX_ISSUE_ID or int(r["issue_id"]) <= MAX_ISSUE_ID)
        folder = os.path.join(BASE, "%s_ProjectA_ACC Issue detail (Issues %d-%d)" % (date, ids[0], ids[-1]))
        staging = "%s (building %s)" % (folder, time.strftime("%H%M%S"))
        name = "%s_ProjectA_ACC Issue detail (Updated with Current Status)" % date
        build.OUT_PATH = os.path.join(staging, name + ".pdf")
        build.BY_MODEL_PATH = os.path.join(staging, name + " - by Tier-Model.pdf") if BY_MODEL else None
        os.makedirs(staging)
        build.main()
        publish(staging, folder)

    print("\nPipeline finished.")


def publish(staging, folder):
    """Rename the staging folder to the final output folder, moving an existing one to _superseded."""
    try:
        if os.path.exists(folder):
            note = SUPERSEDE_NOTE or "replaced %s" % time.strftime("%H%M")
            old = os.path.join(BASE, "_superseded", "%s (%s)" % (os.path.basename(folder), note))
            os.makedirs(os.path.dirname(old), exist_ok=True)
            os.rename(folder, old)
            print("\nSuperseded: %s" % old)
        os.rename(staging, folder)
        print("\nOutput  : %s" % folder)
        for name in sorted(os.listdir(folder)):
            print("   %s" % name)
    except OSError as exc:
        print("\nNOT PUBLISHED (%s). A PDF in the old folder is probably open in a viewer:"
              " close it, then rename\n   %s\nto\n   %s" % (exc, staging, folder))
        return
    if SUPERSEDE_OLDER:
        retire_older(folder)


def retire_older(folder):
    """Move OLDER-dated output folders for the same issue range to _superseded: a newer
    build of the same issues replaces them (the user's rule, 2026-10-09)."""
    m = re.match(r"(\d{8})(_ProjectA_ACC Issue detail \(Issues \d+-\d+\))$", os.path.basename(folder))
    if not m:
        return
    date, rest = m.groups()
    for other in sorted(os.listdir(BASE)):
        mo = re.match(r"(\d{8})%s$" % re.escape(rest), other)
        if not mo or mo.group(1) >= date or not os.path.isdir(os.path.join(BASE, other)):
            continue
        old = os.path.join(BASE, "_superseded", "%s (%s)" % (other, SUPERSEDE_NOTE or "superseded by %s" % date))
        if os.path.exists(old):
            old = "%s %s" % (old, time.strftime("%H%M%S"))
        try:
            os.makedirs(os.path.dirname(old), exist_ok=True)
            os.rename(os.path.join(BASE, other), old)
            print("Superseded: %s" % old)
        except OSError as exc:
            print("NOT MOVED (%s): %s -- a PDF in it is probably open; close it and move the folder to"
                  " _superseded by hand" % (exc, other))


if __name__ == "__main__":
    main()

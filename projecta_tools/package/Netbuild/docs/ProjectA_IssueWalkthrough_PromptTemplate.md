# ProjectA ACC Issue Walkthrough — Reusable Prompt

Scroll through un-noted ACC issues one at a time, see each in Revit, give the
note, move on. Fill in the <blanks> and paste. Skill: `projecta-issue-walkthrough`.
Updated 2026-10-09 (B1–B5 podium buildings: `--bldg` filter, `B1-05th Floor`
level names; Revit opens `<level>_Part Plan_Linked View` in the B1–B5 models,
`<level> GA Plan_Linked View` elsewhere — CONFIG `VIEW_ORDER`).

```
Using scripts\ProjectA_IssueWalkthrough.py
(C:\SK\OneDrive\Netbuild\scripts\ProjectA_IssueWalkthrough.py),
walk the ACC issues for <TIER / BUILDING> (levels <LO>–<HI>, sheet code
<--bldg CODE | none>) in ACC-ID order, starting from #<FIRST ISSUE | the first
pending one>. The <MODEL FILE NAME> model is open in Revit.
Export: folder <YYYYMMDD> under C:\SK\Projects\ProjectA\Issues\260914, BCF <.... Issues.bcf>
(the BCF that holds these issues -- the walkthrough reads one BCF).

First confirm which model is open in Revit, then show me how many issues are
pending for that range / building, and how many un-noted issues are pinned
in a 3D model (no sheet level) and so outside every range.

For each issue: show me the title, level, status, the FULL description and
comment thread from the BCF, and the snapshot; put Revit on that level's
view -- "<level>_Part Plan_Linked View" in the B1-B5 models (e.g. "Ground
Floor_Part Plan_Linked View"), "<level> GA Plan_Linked View" elsewhere --
with the pinned rooms selected; offer any note already logged for the same
title on another level; then wait for my note and log it. If the issue's
building model is not the one open, tell me which model to open.

Do not measure or analyse anything unless I say "select", "measure",
"analyse" or "check". When I say "same as #NNNN" use that note verbatim
(never copy another level's measured numbers into a new note). When I give
one note for a whole title or level range, apply it in one pass with the
bulk command and only stop on the exceptions.
```

## Blanks

- **Tier / building + model** — every model contains every level, so the range (and for podium buildings the sheet code) decides the model, not the level list:
  - Tower tiers: Podium GF–06 `PO00-…-900001`, Tier 01 L07–23 `T00O-…-900001`, Tier 02 L24–40 `…-900002`, Tier 03 L41–58 `…-900003`, Tier 04 L59–75 `…-900004`, Tier 05 L76+ `…-900005`. No `--bldg` needed.
  - **Basements** B01–B04 `BA00-…-900001`: `--lo -4 --hi -1` (basement levels are negative numbers, B02 = -2).
  - **Podium buildings** B001–B005 (`ProjectC-Studio-BIM-B00x-ZZZ-AR-900001`): add `--bldg B001` (etc.). One export mixes B001, B003, B004, B2B5, T00O and SW00 sheets on the same level numbers; `--bldg` keeps only issues whose placement sheet is `ProjectC-Studio-DWG-<code>-L##-…`. Example: B001 = `--bldg B001`, levels GF–L06 (`--lo 0 --hi 6` or no range). `--bldg B2B5` = the combined B2–B5 sheet: the snapshot shows which building, so open that model. `goto` only drives the ACTIVE model, so open the building's model first (several can be open in one Revit; the active window is the one used).
  - Ground Floor across B1–B5 in the 20261009 export: `--lo 0 --hi 0` with `--bldg B003` (6), `B004` (2), `B2B5` (7); B001 has none. The SW00 (28) and T00O (3) GF sheets are site-wide / tower sheets, not B00x.
- **Export / BCF** — the script's CONFIG defaults to `20261009` / `2026-10-08 16_06 245 Issues-260916 to 261008.bcf` (#1209–#1527). For the two-BCF `20261008` export (#301–#1208) name the BCF that holds the issues being walked.
- **First issue** — where the last session stopped (`pending` with the same range / `--bldg` shows it).

## Commands the walkthrough uses

Each line is the CLI argv; run them through Python so the export can be overridden:

```powershell
py -3.14 -c "import sys; sys.path.insert(0, r'C:\SK\OneDrive\Netbuild\scripts'); import ProjectA_IssueWalkthrough as w; w.EXPORT_SUBDIR='<YYYYMMDD>'; w.BCF_FILE='<.... Issues.bcf>'; w.main(<argv>)"
```

```
['next','--lo','41','--hi','58']        next un-noted issue + Revit navigation
['next','--bldg','B001']                podium building: next un-noted B001-sheet issue
['show','1041']                         full text, snapshot path, precedents
['goto','47','pump|tank']               Revit -> L47 plan (VIEW_ORDER), rooms selected
['goto','0']                            B00x model -> Ground Floor_Part Plan_Linked View
['log','1041|L26|<note>']               log (a new ACC id gets a tagging row)
['bulk','--lo','26','--hi','40','--title','common path','Open. Pending design decision.']
['bulk','--bldg','B001','--title','landing','<note>']   one note for every B001 match
['pending','--lo','24','--hi','40']     what is left in a range (+N 3D-pinned issues outside every range)
['pending','--bldg','B001']             what is left for one podium building
['pending']                             every un-noted issue; 3D pins show level "?"
['next','--lo','-4','--hi','-1']        basement model: next un-noted B0x issue
```

Notes, tagging CSVs and snapshots live under `BASE` in the script's CONFIG
(`C:\SK\Projects\ProjectA\Issues\260914`) — the same folder the report pipeline
(`scripts\ProjectA_IssueReport_Pipeline.py`) reads.

Revit is reached over the pyRevit MCP listener's HTTP route (port 48884) —
the same call as `execute_revit_code` — so it works even when the MCP tools
did not load in the session. If `goto` says "no floor plan view for level N
in <doc>", the wrong model is open.

`goto` opens the first view matching the script's CONFIG `VIEW_ORDER`
(`_Part Plan_Linked\s+View$`, then `GA Plan_Linked\s+View$`), then any GA
plan, then any floor plan. So the B1–B5 models open `<level>_Part Plan_Linked
View` (not the `... Part Plan_Linked View_SK` copies), and a model without
Part Plan views opens `<level> GA Plan_Linked View`. Edit `VIEW_ORDER` to
change the view. It reads tower level names (`24th Floor`), podium B00x names
(`B1-05th Floor`) and B001's L06 (`06th Floor_…` views on `B1-Roof Level`).
Rooms are selected on the opened view's level. B001 has placed rooms only on
GF–L03, so L04–L06 select nothing.

Issues pinned in a 3D model (NWD/RVT placement, e.g. DEC's
`SW00-ZZZ-BM-922001.nwd`) have no sheet level or building code and never
come up in a level range or `--bldg`. Place them by level with
`scripts\ProjectA_BcfViewpointLevels.py` (skill `projecta-bcf-viewpoint-levels`)
before walking them.

## Working-style rules (the user corrected these twice)

- Show, navigate, take the note, log, next. Nothing else.
- Notes are the user's judgement. Offer precedents; never write a note
  unasked, never carry a measurement from one level to another.
- Bulk notes per title or level range are normal, as are standing
  addenda ("every L24/L25 issue also gets: …").
- Keep the note text exactly as given; only tidy obvious typos and say so.

## If the script is edited

`ProjectA_BcfViewpointLevels.py` imports the walkthrough's `read_csv`, `write_csv`,
`export_rows`, `level_of` and `revit()` — keep their names and signatures.
Copy the code being replaced into a new `_backups\<date>_...` folder, then
rerun the regression harness in
`C:\SK\OneDrive\Netbuild\_backups\2026-10-08_projecta-issue-scripts-pre-cleanup\`
(`regress.py` + `compare.py`; it tests show/pending/log/bulk on CSV copies)
once with the backup as code root and once with the project. `goto` is not
in the harness: test it live on each level of the open model. Last edit
2026-10-09 (`VIEW_ORDER`): pre-edit copy in
`_backups\2026-10-09_projecta-walkthrough-part-plan-view\`, 552/553 identical
(diff = help text).

# ProjectA BCF Viewpoint Levels — Reusable Prompt

Find the level and tier of ACC issues pinned in a 3D model (NWD/RVT placement,
no `-L##-` sheet), which the walkthrough's level ranges skip. Fill in the
<blanks> and paste. Skill: `projecta-bcf-viewpoint-levels`. Created 2026-10-08.

```
Using scripts\ProjectA_BcfViewpointLevels.py
(C:\SK\OneDrive\Netbuild\scripts\ProjectA_BcfViewpointLevels.py), with the Revit code
scripts\revit_dump_levels_survey.py
(C:\SK\OneDrive\Netbuild\scripts\revit_dump_levels_survey.py),
place the 3D-pinned issues of export folder <YYYYMMDD> (BCF <.... Issues.bcf | all>)
by level and tier.

<Revit has <MODEL FILE NAME> open -- refresh the levels table first with
dump-levels (read-only) and show me the route A/B check and the Ground Floor
height | Use the existing levels table.>

Then list every 3D-pinned issue with its height, basis (section cut or
camera), estimated level and tier<, only levels <LO>-<HI>>. Flag every
"camera (rough)" row and show its snapshot before calling a tier. Do not
walk or log notes unless I ask.
```

## Blanks

- **Export / BCF** — defaults to `20261009` / `2026-10-08 16_06 245 Issues-260916 to 261008.bcf`; `all` = every `*.bcf` in the folder (`BCF_FILE=None`).
- **Revit** — any ProjectA tier model works (every tier model contains every level). The levels table (`C:\SK\Projects\ProjectA\Issues\260914\projecta_levels_survey.csv`) only needs a refresh when the levels change.
- **Range** — e.g. `24-40` for Tier 02; needs the levels table.

## Commands behind the prompt

```powershell
py -3.14 "C:\SK\OneDrive\Netbuild\scripts\ProjectA_BcfViewpointLevels.py" dump-levels
py -3.14 "C:\SK\OneDrive\Netbuild\scripts\ProjectA_BcfViewpointLevels.py"
py -3.14 "C:\SK\OneDrive\Netbuild\scripts\ProjectA_BcfViewpointLevels.py" --lo 24 --hi 40
# another export:
py -3.14 -c "import sys; sys.path.insert(0, r'C:\SK\OneDrive\Netbuild\scripts'); import ProjectA_BcfViewpointLevels as v; v.EXPORT_SUBDIR='<YYYYMMDD>'; v.BCF_FILE=None; v.main(['--lo','24','--hi','40'])"
```

Output: `C:\SK\Projects\ProjectA\Issues\260914\<YYYYMMDD>\ProjectA_bcf_viewpoint_levels.csv`.

## Gotchas

- `dump-levels` had not run against a model as of 2026-10-08 — on its first
  run, route A vs B must agree within 0.01 m and Ground Floor must read about
  625–635 m (survey) before any tier is trusted.
- Sheet pins carry no BCF viewpoint; only 3D pins can be placed this way.
- A horizontal clip plane (normal +Z) is the TOP of the section box: the floor
  shown is the highest level at or below the cut. Camera-only rows read high.
- The placement model does not give the tier (#1501 in a `T00O` file is
  Tier 04 by its comment).
- The script imports `ProjectA_IssueWalkthrough.py` (same folder). After editing
  either, rerun the regression harness in
  `C:\SK\OneDrive\Netbuild\_backups\2026-10-08_projecta-issue-scripts-pre-cleanup\`.

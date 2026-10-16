# Prompt template — Align viewports + view titles to a reference sheet

Script: `C:\SK\OneDrive\Netbuild\scripts\align_viewports_from_reference_sheet.py`

Fill in the <placeholders> and paste into Claude Code:

---

Connect to Revit (`revit_select_session doc:<MODEL TITLE>`), then run
`scripts\align_viewports_from_reference_sheet.py` via `execute_revit_code`
(read the file, set the CONFIG block by string replacement, `exec` it with `doc`).

CONFIG:
- `EXPECTED_DOC_TITLE = "<MODEL TITLE>"`
- `REFERENCE_SHEET = "<e.g. 10023>"`
- `TARGET_RANGE = (<first sheet no>, <last sheet no>)` (numeric sheets; reference excluded)
- `TARGET_EXTRA = [<non-numeric sheet numbers, e.g. "10B01">]`
- `VIEW_TYPES = (ViewType.FloorPlan,)` — legends/schedules are left alone
- `ALIGN_TITLES = True`

Steps:
1. Dry run first (`DRY_RUN = True`): print per viewport the move in mm and the
   title offset old -> new; report any sheet whose plan-viewport count exceeds
   the reference's slots. Show me before applying.
2. Apply only when I say "apply" (`DRY_RUN = False`).
3. Verify: projection origins (re-read, must be 0.0 mm off). For TITLES do NOT
   trust `GetLabelOutline()` / box read-back — export 2-3 sheets to PNG
   (`ImageExportOptions`) including the reference and compare title positions.
4. Log the session in the time-saved log.

Notes: pairing is by top/bottom SLOT (box centre Y), not detail number. A long
run can exceed the MCP timeout — watch Revit's CPU go idle, then read the
(one-call-lagged) result with a marker-tagged ping.

# Prompt template -- Clear model warnings (Area Plans / Areas / separation lines, dead references, Type Marks)

Script: `C:\Users\user\OneDrive - Studio\Documents\Claude\scripts\clear_model_warnings.py`
(repository copy: `scripts\clear_model_warnings.py`)
Ribbon instead of Claude: **Netbuild -> Warnings -> Warnings Summary / Clear Warnings**
(*Clear Warnings by Netbuild*, `LevelShifter\README.md`). It runs the same six steps, adds a dry run and
a single Undo entry, and lists the manual-review items by Id.

## What it does

Six steps, each switched on or off in the script's CONFIG block (`RUN_STEP_1_...` to `RUN_STEP_6_...`):

1. Deletes the Area Plan views and the Area-related schedules.
2. Deletes all Areas.
3. Deletes all Area Separation Lines.
4. Deletes orphaned Matchlines (no owner view). A live Matchline is never touched.
5. Deletes orphaned Room Tags (dangling room reference). A tag with a valid room is never touched.
6. Fixes duplicate Type Marks (keyword prefix, thickness suffix, then a letter suffix).

The script was developed on `ProjectC-Studio-BIM-B001-ZZZ-BM-950001`, where it took 2,120 warnings to 0. Most of
them were Area-Plan / Area / separation-line warnings. Check that a new model has the same profile
before deleting its Areas.

## Prompt to use

> Connect to Revit via MCP and confirm the active document is `<BUILDING_CODE, e.g. ProjectC-Studio-BIM-B002-ZZZ-BM-950001>`.
>
> Get a warnings summary first (`doc.GetWarnings()`, grouped by description text). That gives the starting
> count and confirms the profile matches B001 (heavy Area-Plan / Area / separation-line warnings).
>
> Then run `C:\Users\user\OneDrive - Studio\Documents\Claude\scripts\clear_model_warnings.py` via
> `execute_revit_code`, with `DRY_RUN = False` and all six steps enabled:
> 1. Delete Area Plan views + Area-related schedules
> 2. Delete all Areas
> 3. Delete all Area Separation Lines
> 4. Delete orphaned Matchlines (no owner view)
> 5. Delete orphaned Room Tags (dangling room reference)
> 6. Fix duplicate Type Marks
>
> Report the warnings before and after. Flag anything Step 4 or 5 skipped as needing manual review: a
> live Matchline, or a Room Tag with a valid but mispositioned room reference. The script deliberately
> does not touch those.

## Notes

- Run with `DRY_RUN = True` first on a model you haven't cleaned before. It prints what each step would
  target and commits nothing.
- Steps 1 - 3 delete **every** Area in the model. Run them only where the areas are not needed or are kept
  in another model.
- Step 6's keyword prefixes (`KEYWORD_PREFIX_RULES`) are project-specific: `ritz -> RITZ-`,
  `dormakaba -> DK-`.
- Save / Synchronize afterwards. The MCP script commits one transaction per step. The ribbon button
  groups them into one Undo entry.

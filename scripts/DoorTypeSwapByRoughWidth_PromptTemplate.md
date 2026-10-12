# Door Type Swap by Rough Width — Reusable Prompt

Audit every door with a given rough opening width in the open Revit model,
then swap one door type for another. Fill in the blanks and paste.

```
Using scripts\DoorTypeSwapByRoughWidth.py
(C:\SK\OneDrive\Netbuild\scripts\DoorTypeSwapByRoughWidth.py),
with the <MODEL FILE NAME> model open in Revit:

1. Find every door with a <ROUGH WIDTH> mm rough opening width and show me
   the count per level and per type, with element ids and marks.
2. Select all instances of "<SOURCE TYPE NAME>" and change them to
   "<TARGET TYPE NAME>"<, on levels <LEVEL LIST> only>.

Dry run first: select and report, tell me how many are in groups (those
have to be done by hand via Edit Group), and wait for me to say "apply"
before committing. After applying, print the commit status and confirm
zero source-type instances remain.
```

## Blanks

- **Rough width** — mm, matched to ±1 mm against the type's `Rough Width`
  (`FAMILY_ROUGH_WIDTH_PARAM`, falling back to a `Rough Width` /
  `Rough Opening Width` parameter on the type, then the instance).
- **Source / target type name** — the exact door TYPE name as shown in the
  Project Browser (the script stops if the target name matches 0 or >1
  types). Step 1's output lists the names you need.
- **Levels** — optional; leave the list empty in CONFIG for the whole model.

## How it runs

Edit the CONFIG block at the top of the script (`ROUGH_WIDTH_MM`,
`SRC_TYPE`, `TGT_TYPE`, `LEVELS`, `APPLY`) and run
`python DoorTypeSwapByRoughWidth.py`. `APPLY = False` is the dry run and the
default — per the standing rule, nothing is committed until the user says so.
Revit is reached over the pyRevit MCP listener's HTTP route (port 48884), so
the MCP tools do not need to be loaded in the session.

## Gotchas

- A door inside a model group cannot be type-swapped through the API — the
  transaction silently rolls back. The script skips and lists them; do those
  with Edit Group and re-run to verify.
- Read the printed commit status: `RolledBack` is not an exception.
- Revit 2026: `ElementId` has no `.IntegerValue`, and `.value` is not
  reachable from IronPython — use `str(e.Id)`.

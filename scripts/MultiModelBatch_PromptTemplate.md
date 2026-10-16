# Multi-Model Batch — Reusable Prompt

Run one change across several Revit models that are open in the SAME Revit
session, without relying on which window is active. Fill in the blanks and
paste. Works on any PC with Revit + pyRevit + the mcp-server-for-revit-python
extension (port 48884) and Python 3 — nothing else to install.

```
Using scripts\MultiModelBatch.py
(C:\SK\OneDrive\Netbuild\scripts\MultiModelBatch.py)
with these models open in one Revit session: <MODEL TITLE 1>, <MODEL TITLE 2>, <...>:

1. Run `python scripts\MultiModelBatch.py --list` and confirm every model above
   is open, not linked, and modifiable. Tell me which one is the active window.
2. Write the task as scripts\tasks\<TASK NAME>.py following the contract in
   scripts\tasks\template_modify_parameter.py: <WHAT THE TASK SHOULD DO, e.g.
   set parameter X to Y on all doors on Basement levels / rename views matching
   Z / audit ...>. Bind everything to `doc` (the target model), never to the
   active window; bucket elements in model groups and list them instead of
   editing them; put the counts in `result`.
3. Dry run: `python scripts\MultiModelBatch.py --task scripts\tasks\<TASK NAME>.py
   --titles <MODEL TITLE 1> <MODEL TITLE 2> ...` and show me the per-model table.
4. Wait for me to say "apply". Then re-run with --apply, print the table with
   the Committed column, and list which models now hold unsynced changes.
   Do not sync or save anything yourself.
```

## Blanks

- **Model titles** — the document title as Revit shows it (`--list` prints
  them). A unique substring is enough (`B001`); an exact title wins over a
  substring; an ambiguous substring stops the run before touching anything.
- **Task name / what it does** — one IronPython 2.7 snippet, kept in
  `scripts\tasks\` so it travels with the project folder and can be re-run.
  Read-only audits are tasks too (see `tasks\example_count_elements.py`).

## How it runs

`MultiModelBatch.py` POSTs to the pyRevit listener directly, one model per
HTTP call with a 10-minute timeout (so the 60 s MCP-bridge cut-off does not
apply), binding `doc` to the requested document by title from
`doc.Application.Documents`. Each model gets its own TransactionGroup:
dry run = the task really executes and the group is rolled back (real counts);
`--apply` = the group is assimilated into one undo step. Each result comes
back tagged with a per-call nonce, so a lagged response from an earlier call
can never be read as this model's. `--list` shows open documents; `--apply`,
`--swallow-warnings`, `--stop-on-fail`, `--quiet` are the switches; the same
values live in the CONFIG block at the top of the script.

Task contract: `doc` (target model), `uidoc` (only when the target is the
active window, else None), `DB`, `revit`, `ctx` (`title`, `dry_run`,
`is_active`, `log(msg)`, `with ctx.transaction("name") as t:`), and a
`result` dict for the summary table.

## Context for a fresh machine (what my memory on the usual PC says)

- **Every pyRevit Routes call gets the ACTIVE document.** With several models
  open, whatever was clicked last is what an ordinary script edits; switching
  windows mid-run silently changes the target. This runner is the answer:
  bind by title, never by window.
- **One model per call.** The MCP bridge times a call out at ~60 s; Revit
  finishes the script anyway but the result is lost, and the next call can
  receive the previous call's output. Direct HTTP + nonce-tagged results
  avoid both.
- **Own transaction per model.** A Revit transaction belongs to one document.
  Read the commit status: a `RolledBack` is not an exception.
- **UI operations need the active window** — selection, zoom, `uidoc.ActiveView`.
  Tasks that select-and-guide (e.g. group-member fixes) need that model active.
- **Group members still roll back.** Multi-placement model-group members
  cannot be edited through the API (transaction commits, Revit silently
  reverts). Bucket them, list the group type names, fix once per type with
  Edit Group.
- **Sync is per model.** After apply, sync or save each model yourself.
- **Memory.** Two or three Podium-size models open at once is comfortable;
  more slows Revit and raises the crash risk. A crash loses unsynced work
  in every open model — sync before a long batch.
- **Dry run is the default, always** (project standing rule): nothing is
  committed until the user says "apply".

## Gotchas

- **Workshared models: even a dry run can borrow elements.** The task really
  edits and the group is rolled back, but Revit keeps the borrowed status on
  the elements it touched until you relinquish or sync. After a dry run you do
  not follow with `--apply`, do Synchronize → Relinquish All Mine (or the
  Worksets dialog) so colleagues are not locked out.
- `Document.IsModifiable` is only True while a transaction is open, so it is
  useless as a "can I edit this" check; the runner uses `IsReadOnly`.
- IronPython 2.7: `print` is a keyword, so a task namespace entry named
  `print` is a SyntaxError unless the payload starts with
  `from __future__ import print_function` (the runner does). Tasks may use
  either `print(x)` form.
- Revit 2026: `ElementId` has no `.IntegerValue`; use `str(e.Id)`. Use
  `DB.Element.Name.__get__(e)` for `.Name` in IronPython.
- `--apply` refuses read-only documents up front; a detached model opened
  "preserve worksets" is modifiable, a locked central is not.
- `SWALLOW_WARNINGS` deletes only *warnings* raised inside the task's own
  transactions; errors still fail the model.
- If the summary says "no tagged result came back", the listener call itself
  failed (Revit busy with a dialog, or the task ran past 10 minutes) — the
  model's group was rolled back on the Revit side, nothing partial was kept.

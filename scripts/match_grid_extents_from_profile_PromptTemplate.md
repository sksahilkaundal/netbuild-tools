# Prompt template — Match grid extents / bubbles / elbows across views

Script: `C:\SK\OneDrive\Netbuild\scripts\match_grid_extents_from_profile.py`
Saved profiles: `C:\SK\OneDrive\Netbuild\scripts\grid_extent_profiles\`

## What it does

Copies **2D (view-specific) grid extents, bubble visibility and elbows** from one
reference view onto every view of a given view family type. The grids' **3D /
Model extents are never modified** — only per-view overrides are written.

Two modes, both set in the CONFIG block at the top of the script:

- `MODE = "capture"` — read `REF_VIEW_NAME`, write the scope to `PROFILE_PATH` as JSON. Read-only.
- `MODE = "apply"` — read `PROFILE_PATH`, write it into every target view. `DRY_RUN = True` first.

The profile is keyed by **grid name**, so it transfers between models that share
a grid naming convention. Grids in the profile that don't exist in the target
model are listed and skipped; grids not visible in a given view are skipped, not
forced on.

## Prompt to use

> Connect to Revit (session on port `<PORT>` — use `revit_select_session` with
> `port:<PORT>`) and confirm the document.
>
> Using `C:\SK\OneDrive\Netbuild\scripts\match_grid_extents_from_profile.py`,
> apply the saved grid profile `grid_extent_profiles\<PROFILE>.json` to all views
> of view type `<VFT_NAME>`, excluding `<VIEW NAMES>`.
>
> Dry run first: show how many grids the profile matches in this model, which
> grid names are missing, and per view how many grids are visible. Do not change
> 3D extents of any grid.

To create a new profile instead:

> Capture the grid extents/bubbles/elbows of `<REF VIEW NAME>` into
> `grid_extent_profiles\<NAME>.json` using the capture mode of that script.

Target selection is `VFT_NAME` + `EXCLUDE_VIEWS` / `ONLY_VIEWS`, or set
`OPEN_VIEWS_ONLY = True` to hit exactly the views the user has open on screen
(any plan view type) — useful when the user says "just the views on my screen".

## Gotchas (learned the hard way)

- **`Grid.RemoveLeader` does not exist.** Datum leaders cannot be deleted via the
  API. Where the profile has no leader but the target view does, the script
  collapses the leader to a 2 mm stub; anything that refuses to collapse is
  reported by view/grid/end and needs a manual bubble drag in Revit.
- **`SetLeader(end, view, None)` throws** — null is rejected.
- **Toggling extent type Model → ViewSpecific does not clear a leader** either.
- **Z must come from the target view**, not from the profile: each plan view
  draws its grids at its own cut-plane elevation. The profile stores XY only.
- **`ViewFamilyType.Name`** is not reachable as a plain attribute in IronPython —
  use `SYMBOL_NAME_PARAM` (the script's `type_name()` helper).
- **Revit 2026 `ElementId` has no `.IntegerValue`** — use `.value`. The script's
  `elem_id()` helper handles both.
- Grids hidden in a view raise *"The datum plane cannot be visible in the view"* —
  counted as `skip`, which is correct behaviour, not an error.
- Run in batches (`BATCH = (start, count)`) on big models; ~20–26 views per call
  keeps each `execute_revit_code` round trip comfortable.
- **Grids are rarely exactly axis-aligned.** A grid skewed by 0.04 mm over its
  length rejects a perfectly straight profile line with *"The curve is unbound or
  not coincident with the original one of the datum plane"*. The fix is to
  **project** the profile endpoints onto that grid's own in-view line, never to
  write the raw profile coordinates. Symptom to recognise: the same handful of
  grids fail in *every* view while the rest succeed, and an identity write
  (writing the grid's current curve straight back) succeeds.
- **Curve direction varies per grid.** Some grids' in-view curve runs the
  opposite way, so `End0`/`End1` point at the opposite physical ends. Order the
  projected points along the grid's own direction and **reverse the bubble/elbow
  arrays to match**, or bubbles land on the wrong side. Verification will then
  show e.g. `TA.16 E0=True E1=False` while its neighbours read `E0=False E1=True`
  — that is correct, not a bug.
- **Check the real `t.Commit()` return value, per view.** Grids are often inside
  a group; touching them raises *"a group has been changed outside group edit
  mode"*, which in a headless MCP context silently **rolls the whole transaction
  back** while every individual operation reports success. Attach an
  `IFailuresPreprocessor` that deletes warnings, use one transaction per view,
  and print `commit=` for each.

## History

- 2026-09-22 — profile `GA_Plans_TA.json` captured from `10-024 - Level 24 GA Plan`
  in doc `3505-ProjectG-Studio-ARC-RVT-00002` (30 grids TA.1–TA.19 / TA.A–TA.L; bubbles
  End0 off, End1 on; elbows on TA.2, TA.4, TA.16 End1; TA.M not visible so out of
  scope). Applied to all 86 views of type `10 _ GA Plans` except
  `10-040- Lift Machine Room`. 4 stray TA.B End1 leaders left for manual cleanup.
- 2026-09-22 — same profile applied to doc `3505-ProjectG-Studio-ARC-RVT-00001` (port
  48886), 21 views open on screen (`10-001` … `10-021`). All 30 profile grids
  exist there; TA.20–TA.24 and TA.M are extra and were left untouched by
  instruction. TA.15–TA.19 needed the projection + direction remap, and the whole
  run needed the warning preprocessor. 1 stray TA.B End1 leader left in
  `10-013 - Level 13 GA Plan`.
- 2026-09-22 — profile `GA_Plans_TA_B001_L15.json` captured from
  `10-015 - Level 15 GA Plan` in that same doc after it was tuned by hand: 35
  grids (adds TA.20–TA.24; TA.M still not visible so still out of scope),
  horizontals 1553 mm longer, elbows on TA.2, TA.4, TA.16, TA.B, TA.21. Applied
  to the other 20 open views — exact match, no direction flips, no strays.
  **Prefer a same-model reference when there is one**: capturing in the model you
  are writing to removes the projection residual entirely.

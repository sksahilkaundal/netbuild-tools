# Level Shift by Netbuild

© 2026 Netbuild. All rights reserved. · Proprietary software owned by Netbuild · [skaec.com](https://skaec.com) · see **Licence** below

Move up to **10 levels** up or down. Every element, group and model element hosted to those levels
keeps its existing **X, Y, Z**. Its offset from the level changes by the opposite amount: when a level
goes up 300 mm, the wall base offset, floor height offset, door sill height and so on go **−300 mm**.

This is the same kind of tool as the ProjectA Plot Runner: a desktop window and a command line that talk
to Revit through the pyRevit MCP listener. No Revit add-in install is needed beyond pyRevit + the MCP
extension that Claude and the Plot Runner already use.

## Three ways to run it

| | What | Needs |
|---|---|---|
| **Level Shift** ribbon button | **Runs directly inside Revit.** Same window: 10 rows, read-only highlighted current elevation, Define new level…, Check / Trial / Apply. The engine runs in Revit's own process | pyRevit only (no exe, no MCP listener) |
| **Level Shift App** ribbon button | Opens `Level Shift by Netbuild.exe` bound to the model you clicked it from | the exe + the pyRevit MCP listener running |
| `Level Shift by Netbuild.exe` / `LevelShift.exe` | The standalone window and the command line | the pyRevit MCP listener running |

All three use the same engine (`level_shift/payload.py`), so the results are identical.

### Install the ribbon buttons (pyRevit)

1. Download `LevelShift-by-Netbuild-windows` from **Actions → Build Level Shift by Netbuild (Windows)**. Its
   `pyRevit\Netbuild.extension` folder already holds the exe in `bin\`.
2. Copy `Netbuild.extension` to a folder of your choice, for example `C:\pyRevit-Extensions\`.
3. Register that folder with pyRevit, then **Reload**. You can do this in either of two ways:
   - **pyRevit → Settings → Custom Extension Directories**;
   - `pyrevit extensions paths add "C:\pyRevit-Extensions"`.
4. A **Netbuild** tab appears with three panels:
   - **Levels**, holding **Level Shift** and **Level Shift App**;
   - **Scripts**, holding **Script Folder** and **Update Scripts** (see *Script folder* below);
   - **About**, holding **About** (product info, version, requirements) and **Licence** (the licensing page).

When **Level Shift App** can't find the exe, it asks for it once. It looks in this order:
1. the path you picked (Shift+Click to change it);
2. `Netbuild.extension\bin\`;
3. `%LOCALAPPDATA%\Netbuild\LevelShifter\`.

**Level Shift** (direct) keeps its options in the pyRevit config: units, tolerance, *move back
elements without an offset parameter*, and *undo all if anything moves*. It writes logs and element
CSVs to `%APPDATA%\Netbuild\LevelShift\logs`.

### Script folder: update every button from one place

Keep the current button folders in one place -- a network share, or a synced OneDrive / ACC / BIM 360
folder -- in whatever sub-folders you like. A button is matched by its folder name, at any depth:

```
\\server\BIM\Netbuild scripts\
    Levels\2026\Level Shift.pushbutton\script.py      <- runs when you click Level Shift
    Masters\Netbuild.extension\lib\...                 <- lib of a same-named extension (Update Scripts)
```

- **Script Folder** sets the folder (or several), turns *live scripts* on / off and looks in the folder
  again. It shows which buttons were found, and any button found more than once (the newest copy wins).
- **Live scripts on** (the default): every Netbuild button runs its `script.py` (and Shift+Click `config.py`)
  from the folder, so a change there reaches everyone on their next click -- no copying, no reload. The
  copy bundled in the extension runs when no folder is set, the folder is offline, or the button is not in
  it. A new button found in the folder is picked up within 5 minutes, or at once with *look in the folder
  again*. Library modules already loaded by pyRevit stay loaded until pyRevit reloads.
- **Update Scripts** copies the changed files of every installed button found in the folder -- and the
  `lib` folder of a same-named `.extension` there -- into the installed extensions (this one and the
  others in pyRevit's extension folders). It lists the files first, backs up the replaced ones to
  `%APPDATA%\Netbuild\pyRevit\backups\<time>`, then offers to reload pyRevit. Use it for laptops that
  work offline, or with live scripts off.

**Other extensions (e.g. Netbuild 01, Netbuild 02).** Only buttons whose `script.py` starts with the two
live-script lines (`import netbuild_scripts` / `netbuild_scripts.run_live(globals())`) run from the folder.
To add them to another extension's buttons, use **Script Folder -> Add live scripts to other extensions...**
in Revit and pick the `.extension` folder (or the folder holding several), or run

```
python LevelShifter\pyRevit\add_live_header.py "C:\pyRevit-Extensions\Netbuild 01.extension" "C:\pyRevit-Extensions\Netbuild 02.extension"
```

which lists the files, then again with `--apply` to change them. Every pushbutton / panelbutton `script.py`
and `config.py` gets the lines after its docstring and `__title__` / `__author__` lines (smartbuttons are
left alone: pyRevit runs them while loading the ribbon), `netbuild_scripts.py` is copied into the
extension's `lib`, and every changed file is backed up to `%APPDATA%\Netbuild\pyRevit\backups\<time>`
first. Running it again changes nothing. Button folder names must be unique across extensions -- a name in
the script folder matches every installed button with that name.

Which folder is used, first match wins:
1. your own choice from **Script Folder** (`%APPDATA%\Netbuild\pyRevit\script_source.json`);
2. the `NETBUILD_SCRIPT_SOURCE` environment variable (several folders separated by `;`) -- for an
   office-wide setting pushed by IT;
3. the default shipped in `Netbuild.extension\script_source.json`: both
   `%USERPROFILE%\OneDrive - Studio\Netbuild` and its `scripts` sub-folder are scanned
   (`%USERPROFILE%`-style variables are expanded; a folder inside another is searched once).

To update the extension after changing the engine, run `python LevelShifter/sync_pyrevit_lib.py`.
It copies the shared files into `Netbuild.extension\lib\level_shift`, and the tests fail while the
copies differ.

## The window

| Column | What it is |
|---|---|
| **Level** | Pick from the model's levels (sorted by elevation). Up to 10 rows |
| **Current elevation** | **Read-only, highlighted.** The level's "Elevation", as Revit shows it (relative to its Elevation Base) |
| **New elevation** | Type the absolute new elevation, e.g. `3800`, `10.5m` |
| **Move (+up / −down)** | Or type the move instead, e.g. `+300`, `-150`. Each field updates the other one |
| **Define new level…** | Opens a dialog that shows the current elevation (read-only). You choose **New elevation** or **Move by** + **Up/Down**, and it previews the result |

**Same move for every row…** applies one move to every selected level. Values without a unit use
the **Units** setting (mm or m). `3,500`, `3.5m` and `+300mm` are all accepted.

### Steps

| Step | Button | What happens in Revit |
|---|---|---|
| 1 | **Load levels** | Reads every level: name, elevation, Elevation Base, pinned, Copy/Monitor. Nothing is changed |
| 2 | **Check (plan only)** | Lists, per level, the elements it drives and how each one is compensated. Also reports blockers: an element **borrowed by another user**, an element with **no offset parameter**, members of **model groups**. Nothing is changed |
| 3 | **Trial run (rolls back)** | Does the whole move inside a Revit TransactionGroup and measures every element, then **rolls back**. You see exactly what Apply would do, and the model is untouched |
| 4 | **Apply** | Does the same thing and keeps it. It is **one Undo entry** in Revit (*Level Shift by Netbuild*). If any element still moved, everything is rolled back, unless you untick *Undo all if anything moves* on Setup |

Every run writes `logs\<timestamp>_<step>.log` and `logs\<timestamp>_<step>_elements.csv`. The CSV
has one row per element: Id, category, name, level, rule, each parameter old → new, method, drift,
and status.

## How elements keep their position

1. **Snapshot.** The bounding box (min Z, max Z) of every model element is recorded. This covers
   view-independent elements, and skips levels, grids, areas, cameras, scope boxes and links.
2. **One transaction.** For each element whose position a moved level drives, the matching offset is
   reduced by that level's move. The levels are then set to their new elevations:

   | Element | Level parameter → offset compensated |
   |---|---|
   | Walls | Base Constraint → Base Offset; Top Constraint → Top Offset (an unconnected height needs nothing) |
   | Floors, ceilings, toposolids, slab edges | Level → Height Offset From Level |
   | Structural / architectural columns | Base Level → Base Offset; Top Level → Top Offset |
   | Structural framing | Reference Level → Start **and** End Level Offset |
   | Stairs, railings | Base Level → Base Offset; Top Level → Top Offset |
   | Roofs | Base Level / Reference Level → offset; Cutoff Level → Cutoff Offset |
   | Rooms, spaces | Level → Base Offset; Upper Limit → Limit Offset |
   | Model groups | Reference Level → Origin Level Offset |
   | Ducts, pipes, cable trays, conduits | Reference Level → Middle Elevation |
   | Level-based / level-hosted families | Elevation from Level (or Offset from Host) |
   | Doors, windows | Sill Height (it is measured from the door's level, not from the wall) |

   These elements are **not** edited because they follow something else:
   - face-/wall-hosted families follow their host;
   - nested families follow their parent;
   - MEP fittings and accessories follow their connected run;
   - sketch lines (floor / opening / railing boundaries), room / area / space separation lines and
     model lines lie on their level's plane and follow it by design. The element they shape keeps
     its position through its own offset. They are reported as *Lines on the level's plane*, never
     counted as moved, and never moved back.
3. **Measure, then correct.** Every element is measured again.
   - If an element's base and top moved by different amounts (a wall whose top level moved), its base
     offset is corrected by the base's dz and its top offset by the top's dz.
   - If it moved as a whole, its offsets are corrected by −dz.
   - If it has no offset parameter (for example an in-place family), it is **moved** by (0, 0, −dz).
   - An element whose host or MEP run is still being corrected waits for the next round.

   There are up to 4 rounds.
4. **Report.** Anything that still differs is listed by Element Id. If its shape changed (min and max
   moved differently and cannot be corrected), it is reported as *changed shape*: for example, a roof
   or floor sloped by a slope arrow that ends on the moved level. The geometry decides the result,
   not the parameter edits.

### Model groups

In Revit, group members keep their **own** level constraints: a door's sill follows its level, and a
wall's top follows its top constraint. Revit also checks that every instance of a group type has
identical members relative to its origin. The tool therefore works in three steps:

1. It compensates group members **in place**, like any other element, and keeps the group origin
   fixed (Origin Level Offset). Nothing moves, so every instance stays identical.
2. In some cases the members cannot be fixed in place:
   - Revit refuses the move (*Group instances of the same type do not contain identical members*);
   - a member still moves after the move.

   When that happens, the affected group instances are **ungrouped**. Their members are fixed as free
   elements and then **regrouped**. Only the affected instances are touched; nested groups are handled
   from the innermost out.
3. The new group type is named as follows:
   - it keeps the **original name** when no other instance uses it (the old type is deleted;
     several regrouped instances become `Name`, `Name (2)`, …);
   - otherwise it is named `Name (levels moved)`, because an instance on a level that did not move
     still uses the original type.

   Element Ids of the members do not change, so their tags stay. Attached detail groups have to be
   re-attached, and Check / Apply says when that applies.

Untick **Groups: ungroup, fix and regroup** to forbid this. The move then stops with Revit's group
error, and the Element Ids are listed.

Revit **warnings** raised by the move (overlaps, room separation, …) are dismissed and listed.
Any **error** rolls the whole move back.

## What moves with the level, by design

- **Plan views** of the level keep their View Range *relative to the level*, so they cut at the new
  height. Check cut planes, depth and underlay after a big move.
- **Level heads** in sections and elevations, spot elevations, and tags that report the level
  elevation all update.
- **Area** elements are 2D and follow their area plan.
- **Linked models** are not touched. A **Copy/Monitor** level is flagged, and the other model will
  raise a Coordination Review.

## Install (portable, no installer)

1. Download `LevelShift-by-Netbuild-windows` from **Actions → Build Level Shift by Netbuild (Windows)**. It contains:
   - `Level Shift by Netbuild.exe`: the window.
   - `LevelShift.exe`: the command line.

   Put them in any folder. `settings.json` and `logs\` are created next to them. No Python is
   needed. To run from source instead, use `LevelShifter.bat` (Python 3.9+ with tkinter), or build
   the exes with `build_exe.bat`.
2. In Revit, pyRevit's **MCP Status** button must be running. This is the same listener the
   Plot Runner uses: `http://127.0.0.1:48884/revit_mcp/execute_code/`.
3. Open the model. With several models open, set **Revit title contains** (for example
   `T00O-ZZZ-BM-950001`). Leave it blank to use the active model.

For a workshared model, ask anyone who has borrowed the affected elements or levels to
**Synchronize / Relinquish** first. **Check** lists those elements and who holds them, and Apply
refuses to run while they are borrowed.

## Command line

```bat
LevelShift levels                                         :: levels + current elevations
LevelShift plan  --by "L01=+300" --to "L02=6850"          :: who is driven, blockers; no change
LevelShift trial --by "L01=+300" --to "L02=6850"          :: do it, measure, roll back
LevelShift apply --by "L01=+300" --to "Roof=14.2m"        :: do it, keep it (one Undo entry)
LevelShift apply --by "L03=-150" --keep-drift             :: keep even if an element is listed as moved
LevelShift --model T00O-ZZZ-BM-950001 levels              :: bind to a model by title
LevelShift setup --set tolerance_mm=0.5                   :: settings
LevelShift about                                          :: product info, requirements
LevelShift license                                        :: the licence: owner, website, full agreement
```

## Settings (Setup tab / `settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `tolerance_mm` | 1.0 | An element counts as unmoved when min Z and max Z each moved less than this |
| `correction_rounds` | 4 | Rounds of measure and correct after the move |
| `move_fallback` | true | An element with no offset parameter is moved back by (0, 0, −dz) |
| `rollback_on_drift` | true | Apply keeps the result only when every element kept its position |
| `fix_groups` | true | Group members that cannot be kept in place: ungroup, fix, regroup (see *Model groups*) |
| `apply_timeout_seconds` | 3600 | Trial and Apply scan and measure the whole model, so a large model can take minutes |

## Tests

```
python -m unittest discover -s LevelShifter/tests -v
```

The tests run the real Revit payload against a stand-in Revit (`tests\fake_revit.py`). In it, every
element's geometry is regenerated from its level and offsets the way Revit does it, and Transactions
and TransactionGroups really roll back. The model holds:
- walls (connected and unconnected top);
- a slab, a ceiling, a door in a wall, a level-based desk and a light hosted on the slab;
- a column, a beam, a stair, a room;
- a pipe and its elbow;
- a model group and its member;
- an in-place family with no offset parameter;
- optionally, a sloped roof that changes shape.

Both ribbon buttons are also run end to end, with pyRevit and WPF stubbed (`tests\pyrevit_stubs.py`).
The stub parses the real XAML and fires the WPF events.

The tests cover:
- that every element keeps its position when two levels move in opposite directions;
- that trial leaves the model unchanged;
- borrowed elements, Revit warnings and errors;
- shape-change rollback;
- paused, unreachable or stale Revit replies;
- the CLI and the window.

## About

Every entry point has an About screen with the product name, version, owner and requirements:
- the **About** tab in the app;
- the **About** button in the Level Shift window;
- **Netbuild → About** on the ribbon;
- `LevelShift about` on the command line (`LevelShift --version` prints the version).

The licence has its own page -- see **Licence** below.

The exes also carry this in **Properties → Details**:
- Company: Netbuild;
- Product: Level Shift by Netbuild;
- the version;
- Copyright: (c) 2026 Netbuild. All rights reserved.;
- Comments: https://skaec.com.

All of it comes from one file, `level_shift/about.py`.

### Requirements

| To run | You need |
|---|---|
| **Level Shift** ribbon button (runs inside Revit) | Windows 10 / 11 64-bit · Autodesk Revit 2019 – 2026 · pyRevit 4.8 or later with its IronPython engine (the default) |
| **Level Shift by Netbuild.exe** / **LevelShift.exe** | Windows 10 / 11 64-bit, no Python needed · Revit open with pyRevit and the Revit MCP extension, its listener running (MCP Status on) at `http://127.0.0.1:48884` |
| From source | Python 3.9 or later with tkinter |
| The model | A project model opened editable (not read-only) · when workshared, the moved levels and their elements not borrowed by other users · Save / Synchronize after Apply |

### Licence

Proprietary software -- (c) 2026 Netbuild. All rights reserved. https://skaec.com

Level Shift is licensed under the **Netbuild Software Licence Agreement**; it needs no licence key.
The full text is in [`LICENSE`](../LICENSE), shipped next to the exes and in `Netbuild.extension`.
The licensing page (owner, website, licence-key status and the full agreement) is shown by:
- the **Licence** tab in the app;
- **Netbuild → Licence** on the ribbon, and the **Licence** button in every About window;
- `LevelShift license` (or `LevelShift licence`) on the command line.

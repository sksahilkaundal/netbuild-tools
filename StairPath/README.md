# Stair Path by Netbuild

© 2026 Netbuild. All rights reserved. · Proprietary software owned by Netbuild · [skaec.com](https://skaec.com) · see **Licence** below

Places the **Up / Down stair path annotations** in plan views by the office standard. It replaces the
hand-edited `scripts/set_stair_path_direction.py` (run through Claude + the Revit MCP): the same rules,
with no CONFIG block to edit. Stair cores, levels and types are read from the model, and the per-building
distances live in the window.

## Two ways to run it

| | What | Needs |
|---|---|---|
| **Stair Path** ribbon button (**Netbuild → Stairs → Stair Path**) | **Runs inside Revit.** A window with the settings, Check / Trial run / Apply and the report | pyRevit only (no exe, no MCP listener) |
| `StairPath.exe` (command line) | `models`, `plan`, `trial`, `apply` from a console, a script or a scheduled task | the pyRevit MCP listener running |

Both run the same engine, so the results are identical. The command line sends it to Revit as text through the
listener (`stair_path/payload.py`, generated from `rules.py` + `engine.py`).

| File | What |
|---|---|
| `StairPath/stair_path/rules.py` | the standard as plain data → data (no Revit API): types, cores, Up/Down, offsets |
| `StairPath/stair_path/engine.py` | reads the model, places the annotations (Check / Trial run / Apply) |
| `StairPath/stair_path/about.py` | About / Licence information |
| `StairPath/stair_path/payload.py` | **generated**: `rules.py` + `engine.py` as text, for the command line |
| `StairPath/stair_path/revit.py`, `runner.py`, `cli.py`, `settings.py` | the command line: listener calls, runs, arguments, `settings.json` |
| `LevelShifter/pyRevit/Netbuild.extension/Netbuild.tab/Stairs.panel/Stair Path.pushbutton/script.py` | the button and its window |
| `LevelShifter/pyRevit/Netbuild.extension/lib/stair_path/` | copies of `__init__`, `about`, `rules`, `engine` for the button |
| `LevelShifter/pyRevit/Netbuild.extension/lib/stair_path_ui.py` | the window layout (XAML) |

After changing `rules.py`, `engine.py`, `about.py` or `__init__.py`, run `python StairPath/sync_pyrevit_lib.py`.
It copies them into the extension and regenerates `payload.py`; the tests fail while either is out of date.

Install the button: the same `Netbuild.extension` as Level Shift (see
[`LevelShifter/README.md`](../LevelShifter/README.md#install-the-ribbon-buttons-pyrevit)).

## The standard

| | 1:500 | 1:200 and 1:100 |
|---|---|---|
| A flight **continues upward** from the level | *Automatic Up/Down Direction*, Show Up/Down Text off | ***Fixed Up Direction***, Show Up Text **on**. This family has no Show Down Text, so it is never set |
| A flight **arrives from below** | *Automatic Up/Down Direction*, Show Up/Down Text off | *Automatic Up/Down Direction*, Show Up Text off, Show Down Text **on** |

- **Up and Down can both apply.** A level that continues upward *and* receives a flight from below gets both annotations.
- **Types are matched loosely.** The engine looks for the type of each family whose name carries the scale, such as
  `Standard 1-500`, `Standard 1:200`, `1/100` or `Standard 1-100 (Studio)`, and prefers a name containing "Standard".
  If one is missing, **Check** says so. Tick *Create missing types* to duplicate the family's plain `Standard` type
  under that name.
- **Clear first.** Existing stair paths are deleted before regenerating, either in the target views (default) or
  in the whole model.
- **Down hidden by the View Range.** Revit will not place a path on a flight it cannot show in that view. When
  the arriving flight is hidden, the engine uses a flight of the same core that passes through the level (base
  below, top above). That flight gets *Automatic Up/Down* with **both** texts on, which is what Revit itself
  draws for a through-spanning stair.
- **Gaps are reported, not fixed.** A level can have neither the arriving flight nor a passing one visible. The
  only fix then is a deeper View Range, so the level is listed as a **GAP**. When a view template controls that
  View Range, the report names the template. Stair Path **never changes view templates or View Range**: you
  decide, in Revit.
- **Sweep.** After the main Up/Down set, every stair that is visible in a target view but still has no path is
  tagged with *Automatic Up/Down*, both texts on (no text at 1:500). This covers duplicate and legacy flights, and
  split *Part 01/02* plans.
- **Room tags.** Any room tag that overlaps a stair path (with a clearance) is nudged up. A tag of a room whose name
  contains *stair* that ends up outside its room is put back at the room's own point. Paths that overlap a
  **dimension string** are listed; dimensions are not moved.

### Stair cores and levels

Flights are grouped into **cores**: flights whose plan centres are within 1500 mm, or whose plans overlap by
half or more. Each flight's base and top come from its **real elevation** (Base / Top Level + offset), snapped
to the nearest level within 300 mm. A flight whose Base Level says *Ground Floor* with a +3500 offset therefore
counts as starting on the level at 3500. **Check** lists every flight where the parameter and the elevation
disagree. When a core has duplicate flights at the same base (or top), the newest element (highest Id) is used
for Up (or Down); the others are caught by the sweep. Flights that do not climb (base = top) are left out of
the chain and listed.

### Text offset (tuned per building)

Each stair's own first step is (0, 0). The axis comes from the stair's plan proportions, and the direction from
its first flight: the run at BaseElevation 0, not the first in Revit's run list.

| Stair | Run | Text |
|---|---|---|
| Length ≥ width (travels along X) | toward +X | **-X** side, by *Directional X* (e.g. 300 mm) |
| | toward -X | the **standard** X distance, on the +X side |
| Width > length (travels along Y) | toward +Y | **-Y**, by *Directional Y* |
| | toward -Y | **+Y**, by *Directional Y* |

Standard distances: 1:200 → X 600 / Y 200 mm, 1:100 → X 400 / Y 200 mm. Untick *Directional* to use them
everywhere. The window keeps **one set of settings per model** (pyRevit config, keyed by model title), because
the distances are re-tuned for each building. *Reset settings* brings back the defaults.

## The window

1. **Views.** Choose the *open plan views*, or *every plan view whose name contains* a text (e.g. `GA Plan`).
   Only floor plans at 1:500, 1:200 or 1:100 are annotated. Others are skipped and listed.
2. **Check (plan only).** Nothing changes. Lists the cores and their flights, any level corrections, missing
   types, and what each view gets (Up ×n, Down ×n).
3. **Trial run (rolls back).** Places everything, reports the result (pass-through Downs, gaps, sweep, room tags,
   dimension overlaps), then rolls the whole run back.
4. **Apply.** The same run, kept as **one Undo entry: "Stair Path by Netbuild"**. Save / Synchronize afterwards.

Every run writes a log and a CSV of every annotation to `%APPDATA%\Netbuild\StairPath\logs`. The CSV lists
view, scale, level, core, Up/Down/through/sweep, stair Id, placed / through / gap, path Id, offset and reason.

## Install the command line (portable, no installer)

1. Download `StairPath-by-Netbuild-windows` from **Actions → Build Stair Path by Netbuild (Windows)**. It holds
   `Stair Path by Netbuild\StairPath.exe` (and the shared `pyRevit\Netbuild.extension`). Put the exe in any
   folder; `settings.json` and `logs\` are created next to it. No Python is needed. To run from source instead,
   use `StairPath.bat` (Python 3.9+), or build the exe with `build_exe.bat`.
2. In Revit, pyRevit's **MCP Status** button must be running (the listener at
   `http://127.0.0.1:48884/revit_mcp/execute_code/`, the same one Level Shift and Element Remover use).
3. With several models open, give `--model` (part of the Revit title). Leave it out to use the active model.
   *Open plan views* can only be read from the **active** window; for another model, pick the views by name
   (`--views-named`).

## Command line

```bat
StairPath models                                   :: the models open in Revit (and the active one)
StairPath plan                                     :: cores, flights, what each view gets; no change
StairPath trial                                    :: place everything, report it, roll back
StairPath apply                                    :: place everything, keep it (one Undo entry)
StairPath apply --views-named "GA Plan_Linked View" --clear-views   :: views by name, open or not
StairPath apply --clear-model --create-types       :: clear the whole model; create missing Standard 1-xxx types
StairPath apply --set dir_x_mm=300 --set dir_y_mm=350               :: tune the text offsets for this building
StairPath plan --reset                             :: back to the default settings for this model
StairPath --model B003-Studio-ARC plan                :: bind to a model by title
StairPath setup --set apply_timeout_seconds=7200   :: connection settings; lists the settings kept per model
StairPath about                                    :: product info, requirements
StairPath license                                  :: the licence: owner, website, full agreement
```

Settings given with `--set`, `--views-named`, `--clear-model` / `--clear-views` and `--create-types` are **kept
for that model** (by Revit title) in `settings.json`, so the next run on the same building starts from them, as
in the window. The command line and the button keep their settings separately (`settings.json` / the pyRevit
config). Exit code: 0 when nothing FAILed, 1 otherwise, 2 for a bad argument (or `models` with Revit unreachable).

| `--set` key | Default | Meaning |
|---|---|---|
| `views` / `name_filter` | open / `GA Plan` | `open` plan views, or `name`: every plan view whose name contains `name_filter` |
| `clear` | views | existing stair paths cleared in the target `views` or the whole `model` |
| `directional` | true | text away from each stair's first-flight direction (table above) |
| `dir_x_mm` / `dir_y_mm` | 300 / 300 | the directional distances |
| `std_x_200` / `std_y_200` / `std_x_100` / `std_y_100` | 600 / 200 / 400 / 200 | the standard distances per scale |
| `sweep` | true | tag every other visible stair (Automatic Up/Down, both texts) |
| `room_tags`, `tag_nudge_mm`, `tag_pad_mm`, `staircase_keyword` | true, 300, 400, `stair` | room tag clean-up |
| `check_dimensions` | true | list stair paths overlapping a dimension |
| `create_types` | false | duplicate missing `Standard 1-500 / 1-200 / 1-100` types |
| `core_tol_mm` / `level_tol_mm` | 1500 / 300 | same-core distance in plan; level snapping |

Connection settings (`setup --set`): `revit_url`, `model_match`, `probe_timeout_seconds` (300),
`apply_timeout_seconds` (3600 -- Trial and Apply on a large model can take minutes), `max_rows` (20000 CSV rows).

## Tests

```
python -m unittest discover -s LevelShifter/tests -v
python -m unittest discover -s StairPath/tests -v
```

`LevelShifter/tests/test_stair_path.py` runs the engine and the button against a stand-in model
(`LevelShifter/tests/fake_stairs.py`). In that model Revit refuses a path on a flight hidden from the view, a
Fixed Up path has no Show Down Text, and changes outside a transaction raise. The model holds:
- two stair cores, one of them messy: a Base Level parameter that is off by one storey, and a legacy flight
  spanning three storeys;
- a stub stair and a sketch stair;
- a template-locked view whose View Range hides two arriving flights;
- a cropped *Part Plan*, a 1:50 detail view, room tags and a dimension.

`StairPath/tests` runs the command line against a stand-in pyRevit MCP listener (`tests/fake_listener.py`) serving
that same model: plan / trial / apply through the listener, settings kept per model, a second model that is not the
active window, a read-only model, a paused or unreachable listener, the arguments, the exe's version resource, and
that `payload.py` and the extension's copies are current. `tests/smoke_exe.py` runs the built `StairPath.exe` the
same way (in the GitHub build).

## About

**Netbuild → About** and **Netbuild → Licence** list every Netbuild product in the extension; pick *Stair Path by
Netbuild*. The window's **About** button opens the same screen; `StairPath about`, `StairPath license` and
`StairPath --version` print it, and the exe's file properties carry it. The information comes from
`stair_path/about.py`.

### Requirements

- Windows 10 / 11, 64-bit; Autodesk Revit 2019 - 2026; pyRevit 4.8 or later, IronPython engine (pyRevit's default).
- Command line: the pyRevit MCP listener running (MCP Status: on) at `http://127.0.0.1:48884`; no Python for the
  .exe (Python 3.9+ to run from source). *Open plan views* needs the model to be the active window.
- A project model opened editable (not read-only); for a workshared model, the views, stair paths and room tags
  must not be borrowed by other users.
- Component stairs (Stairs by component) and the Stair Path families *Fixed Up Direction* and *Automatic Up/Down
  Direction*.

### Licence

Proprietary software owned by Netbuild, under the **Netbuild Software Licence Agreement** ([`LICENSE`](../LICENSE)).
No licence key is required for this product.

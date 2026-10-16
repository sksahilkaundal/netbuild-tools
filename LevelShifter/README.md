# Netbuild Level Shift (portable)

Move up to **10 levels** up or down. Every element, group and model element hosted to those levels
keeps its existing **X, Y, Z**. Its offset from the level changes by the opposite amount: when a level
goes up 300 mm, the wall base offset, floor height offset, door sill height and so on go **−300 mm**.

This is the same kind of tool as the ProjectA Plot Runner: a desktop window and a command line that talk
to Revit through the pyRevit MCP listener. No Revit add-in install is needed beyond pyRevit + the MCP
extension that Claude and the Plot Runner already use.

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
| 4 | **Apply** | Does the same thing and keeps it. It is **one Undo entry** in Revit (*Netbuild Level Shift*). If any element still moved, everything is rolled back, unless you untick *Undo all if anything moves* on Setup |

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
   - group members follow the group;
   - nested families follow their parent;
   - MEP fittings and accessories follow their connected run.
3. **Measure, then correct.** Every element is measured again. If one still moved as a whole (min Z
   and max Z moved by the same dz), its own offsets are corrected by −dz. If it has no offset
   parameter (for example an in-place family), it is **moved** by (0, 0, −dz). An element whose host,
   group or MEP run is still being corrected waits for the next round. There are up to 4 rounds.
4. **Report.** Anything that still differs is listed by Element Id. If its shape changed (min and max
   moved differently), it is reported as *changed shape*: for example, a roof or floor sloped by a
   slope arrow that ends on the moved level. The geometry decides the result, not the parameter edits.

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

1. Download `LevelShifter-windows` from **Actions → Build Level Shifter (Windows exe)**. It contains:
   - `LevelShifter.exe`: the window.
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
```

## Settings (Setup tab / `settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `tolerance_mm` | 1.0 | An element counts as unmoved when min Z and max Z each moved less than this |
| `correction_rounds` | 4 | Rounds of measure and correct after the move |
| `move_fallback` | true | An element with no offset parameter is moved back by (0, 0, −dz) |
| `rollback_on_drift` | true | Apply keeps the result only when every element kept its position |
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

The tests cover:
- that every element keeps its position when two levels move in opposite directions;
- that trial leaves the model unchanged;
- borrowed elements, Revit warnings and errors;
- shape-change rollback;
- paused, unreachable or stale Revit replies;
- the CLI and the window.

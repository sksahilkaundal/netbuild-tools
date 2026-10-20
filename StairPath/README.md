# Stair Path by Netbuild

© 2026 Netbuild. All rights reserved. · Proprietary software owned by Netbuild · [skaec.com](https://skaec.com) · see **Licence** below

Places the **Up / Down stair path annotations** in plan views by the office standard. It replaces the
hand-edited `scripts/set_stair_path_direction.py` (run through Claude + the Revit MCP): the same rules,
with no CONFIG block to edit. Stair cores, levels and types are read from the model, and the per-building
distances live in the window.

It is a **pyRevit ribbon button**: **Netbuild → Stairs → Stair Path**. It runs inside Revit and needs no exe and
no MCP listener. The code is in the shared extension:

| File | What |
|---|---|
| `LevelShifter/pyRevit/Netbuild.extension/Netbuild.tab/Stairs.panel/Stair Path.pushbutton/script.py` | the button and its window |
| `.../lib/stair_path/rules.py` | the standard as plain data → data (no Revit API): types, cores, Up/Down, offsets |
| `.../lib/stair_path/engine.py` | reads the model, places the annotations (Check / Trial run / Apply) |
| `.../lib/stair_path/about.py` | About / Licence information |
| `.../lib/stair_path_ui.py` | the window layout (XAML) |

Install: the same `Netbuild.extension` as Level Shift (see [`LevelShifter/README.md`](../LevelShifter/README.md#install-the-ribbon-buttons-pyrevit)).

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

## Tests

```
python -m unittest discover -s LevelShifter/tests -v
```

`LevelShifter/tests/test_stair_path.py` runs the engine and the button against a stand-in model
(`LevelShifter/tests/fake_stairs.py`). In that model Revit refuses a path on a flight hidden from the view, a
Fixed Up path has no Show Down Text, and changes outside a transaction raise. The model holds:
- two stair cores, one of them messy: a Base Level parameter that is off by one storey, and a legacy flight
  spanning three storeys;
- a stub stair and a sketch stair;
- a template-locked view whose View Range hides two arriving flights;
- a cropped *Part Plan*, a 1:50 detail view, room tags and a dimension.

## About

**Netbuild → About** and **Netbuild → Licence** list every Netbuild product in the extension; pick *Stair Path by
Netbuild*. The window's **About** button opens the same screen. The information comes from `lib/stair_path/about.py`.

### Requirements

- Windows 10 / 11, 64-bit; Autodesk Revit 2019 - 2026; pyRevit 4.8 or later, IronPython engine (pyRevit's default).
- A project model opened editable (not read-only); for a workshared model, the views, stair paths and room tags
  must not be borrowed by other users.
- Component stairs (Stairs by component) and the Stair Path families *Fixed Up Direction* and *Automatic Up/Down
  Direction*.

### Licence

Proprietary software owned by Netbuild, under the **Netbuild Software Licence Agreement** ([`LICENSE`](../LICENSE)).
No licence key is required for this product.

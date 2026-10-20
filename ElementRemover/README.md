# Element Remover by Netbuild

© 2026 Netbuild. All rights reserved. · Proprietary software owned by Netbuild · [skaec.com](https://skaec.com) · see **Licence** below

Removes the elements of a Revit model that sit on chosen **worksets** and/or pass chosen **view filters**
(rule-based filters or saved selections). You can limit it to some **categories**, for example *Walls only*.
Targets can be standalone, or **inside model groups**, including nested groups. Group members are taken
out of their group instances, and those instances are regrouped without them.

Typical uses:
- clear a *Demolition* or *Existing* workset;
- remove everything a *To Remove* filter catches (for example `Comments = REMOVE`);
- strip the walls from a workset before it is issued.

## Two ways to run it

| | What | Needs |
|---|---|---|
| **Element Remover** ribbon button | **Runs directly inside Revit.** Pick worksets / filters / categories, then Check / Trial / Apply. The engine runs in Revit's own process | pyRevit only (no exe, no MCP listener) |
| `ElementRemover.exe` | The command line: the same steps, scriptable | the pyRevit MCP listener running |

Both use the same engine (`element_remover/payload.py`), so the results are identical.

### Install the ribbon button (pyRevit)

The button lives in the shared **Netbuild** extension, next to the Level Shift buttons.

1. Download `ElementRemover-by-Netbuild-windows` from **Actions → Build Element Remover by Netbuild (Windows)**.
   Its `pyRevit\Netbuild.extension` folder is the whole Netbuild tab.
2. Copy `Netbuild.extension` to a folder of your choice, for example `C:\pyRevit-Extensions\`. If you
   already have it there from Level Shift, replace it.
3. Register that folder with pyRevit (**pyRevit → Settings → Custom Extension Directories**, or
   `pyrevit extensions paths add "C:\pyRevit-Extensions"`), then **Reload**.
4. The **Netbuild** tab shows a **Cleanup** panel with **Element Remover**. The **About** panel stays last;
   its **About** and **Licence** buttons list every Netbuild product.

The button keeps its options and your last picks in the pyRevit config. It writes logs and element
CSVs to `%APPDATA%\Netbuild\ElementRemover\logs`.

To update the extension after changing the engine, run `python ElementRemover/sync_pyrevit_lib.py`.
It copies the shared files into `Netbuild.extension\lib\element_remover`, and the tests fail while the
copies differ.

## The window

| Part | What it is |
|---|---|
| **Worksets** | The model's user worksets, with their element counts. Ctrl+Click picks several. A closed workset is marked `[closed]`: its elements are not loaded, so open it first |
| **Filters** | Rule-based view filters (`rules on Walls, Doors`) and saved selection filters (`saved selection, 12 elements`). Ctrl+Click picks several |
| **OR / AND** | With both worksets and filters picked: remove what is on a workset **or** passes a filter (the default), or only what is on a workset **and** passes a filter |
| **Only categories** | Blank = every category. Type `Walls, Doors`, click **Walls only**, or **Pick…** from the categories in use |
| **Options** | *Elements inside model groups: ungroup, remove, regroup* (on) · *Merge identical regrouped group types* (on) · *Remove pinned elements too* (off) · *Model elements only* (on) |

### Steps

| Step | Button | What happens in Revit |
|---|---|---|
| 1 | **Check (plan only)** | Lists what will be removed (by category and by workset/filter), what is skipped and why, the group instances that will be ungrouped, and blockers (elements **borrowed by another user**, names not found, closed worksets). Nothing is changed |
| 2 | **Trial run (rolls back)** | Does the whole removal inside a Revit TransactionGroup, checks every target is gone, lists what Revit deleted with them, then **rolls back**. The model is untouched |
| 3 | **Apply** | Asks first, with the numbers. Then does the same thing and keeps it. It is **one Undo entry** in Revit (*Element Remover by Netbuild*) |

Every run writes `logs\<timestamp>_<step>.log` and `logs\<timestamp>_<step>_elements.csv`. The CSV has one row
per element: Id, category, name, workset, group, what matched it (workset / filter), and status:
- `to remove` / `deleted`;
- `deleted (taken out of its group)`;
- `deleted with its group`;
- `deleted with a removed element`;
- `skipped: …`.

## What is removed, and what is not

- **Removed**: element instances that match, standalone or in groups.
- **Removed with them, by Revit**: whatever depends on a removed element. Examples: the doors and windows
  in a removed wall, tags, dimensions, and sketches. Trial and Apply list each one by Id, found by a probe
  deletion that is rolled back at once.
- **Never removed**:
  - levels, grids and reference planes;
  - Revit links;
  - project base / survey points;
  - scope boxes;
  - views, sheets and viewports;
  - sketch lines;
  - element types.

  If one of them matches, it is listed as *skipped: protected*.
- **Skipped unless you ask**:
  - **pinned** elements, and elements inside a **pinned group**. Tick *Remove pinned elements too*, which
    unpins them first;
  - annotation and view-specific elements. Untick *Model elements only*.
- **Skipped**: shared nested family components, because they go with their parent family instance.
- **Linked models** are never touched.

### Elements inside model groups

Revit keeps every instance of a group type identical, so a member cannot be deleted from one instance on
its own. The tool therefore:

1. **ungroups** every group instance that holds a target. It goes outermost first, so nested groups are
   handled too;
2. **deletes** the targets;
3. **regroups** what is left of each instance, innermost first. A nested group is regrouped before the
   group around it.

The new group type is named as follows:
- it keeps the **original name** when no other instance of the old type is left. The old type is deleted,
  and several regrouped instances become `Name`, `Name (2)`, … in Element Id order;
- otherwise it is named `Name (elements removed)`, because the instances you did not touch still use the
  original type.

Element Ids of the kept members **do not change**, so their tags and schedules stay. Attached detail groups
have to be re-attached; Trial / Apply say when that applies.

#### Merging identical regrouped group types

Regrouping gives every instance its own group type: `Toilet Core`, `Toilet Core (2)`, … So, by default,
the regrouped instances of one old type are then switched to the type of the first one (the lowest Element
Id), one at a time. Each switch is **checked member by member**, and is kept only when every member ends up
exactly as it was:
- the same category, type, workset, phase, **Mark** and **Comments**;
- the same bounding box, location, facing / hand orientation and mirror state (positions within 1 mm).

If anything differs, that switch is rolled back and the instance keeps its own type. Trial / Apply list why.
This happens, for example, with:
- a **rotated or mirrored** instance;
- members with **different Marks**;
- a group **nested** in another group, which is never switched.

A merged instance's members are rebuilt by Revit from the shared type, so they get **new Element Ids**, and
tags on them are removed. Re-tag them if they were tagged. Untick *Merge identical regrouped group types*
(or use `--no-merge`) to keep one type per instance and keep every Element Id.

A whole **group instance** can be a target too. For example, a group on the *Demolition* workset is
deleted with all its members, and nothing is ungrouped.

Untick **Elements inside model groups** to leave group members alone; they are then listed as skipped.

Revit **warnings** raised by the deletion (joins, attachments, room separation, …) are dismissed and listed.
Any **error** rolls the whole removal back.

## Install the command line (portable, no installer)

1. Download `ElementRemover-by-Netbuild-windows` (see above). It contains `ElementRemover.exe`. Put it in
   any folder; `settings.json` and `logs\` are created next to it. No Python is needed. To run from source
   instead, use `ElementRemover.bat` (Python 3.9+), or build the exe with `build_exe.bat`.
2. In Revit, pyRevit's **MCP Status** button must be running (the listener at
   `http://127.0.0.1:48884/revit_mcp/execute_code/`, the same one Level Shift and the Plot Runner use).
3. With several models open, give `--model` (part of the Revit title). Leave it out to use the active model.

For a workshared model, ask anyone who has borrowed the targets (or the group instances that hold them)
to **Synchronize / Relinquish** first. **Check** lists them and who holds them, and Apply refuses to run
while they are borrowed.

## Command line

```bat
ElementRemover sources                                          :: worksets, filters, categories in use
ElementRemover plan  --workset "Demolition"                     :: what would go, what is skipped; no change
ElementRemover plan  --workset "Demolition" --category Walls    :: walls only
ElementRemover trial --filter "To Remove"                       :: do it, check it, roll back
ElementRemover apply --filter "To Remove"                       :: do it, keep it (one Undo entry)
ElementRemover apply --workset "Demolition" --filter "All Walls" --both   :: on the workset AND passing the filter
ElementRemover apply --workset "Demolition" --include-pinned    :: pinned elements too (unpinned first)
ElementRemover apply --workset "Demolition" --no-groups         :: leave group members alone
ElementRemover apply --filter "To Remove" --no-merge            :: one group type per regrouped instance
ElementRemover --model B003-Studio-ARC sources                     :: bind to a model by title
ElementRemover setup --set skip_pinned=false                    :: settings
ElementRemover about                                            :: product info, requirements
ElementRemover license                                          :: the licence: owner, website, full agreement
```

`--workset`, `--filter` and `--category` can be repeated; `--category "Walls, Doors"` also works.

## Settings (`settings.json` / the button's options)

| Key | Default | Meaning |
|---|---|---|
| `skip_pinned` | true | Pinned targets (and targets inside pinned groups) are listed, not removed |
| `fix_groups` | true | Targets inside model groups: ungroup, remove, regroup |
| `merge_groups` | true | Regrouped instances that are identical, member by member, share one group type again (their members get new Element Ids) |
| `model_only` | true | Annotation and view-specific elements are never removed |
| `max_rows` | 20000 | Element rows returned and written to the CSV |
| `apply_timeout_seconds` | 3600 | Trial and Apply on a large model can take minutes (command line) |

## Tests

```
python -m unittest discover -s ElementRemover/tests -v
```

The tests run the real Revit payload against a stand-in Revit (`tests\fake_revit.py`). It behaves like
Revit where it matters:
- Revit refuses to delete a group member in place, and to ungroup a pinned group;
- group type names must be unique;
- Delete takes hosted doors, tags and group members with it;
- elements on a closed workset are not loaded;
- Transactions and TransactionGroups really roll back;
- borrowed elements fail at commit.

The model holds:
- worksets, one of them closed;
- a rule-based filter and a saved selection;
- standalone walls, a pinned slab and a grid;
- a group type placed twice;
- a group whose only affected instance must be renamed;
- an *Apartment* group with a nested *Bath Pod*.

The ribbon button is also run end to end, with pyRevit and WPF stubbed (the stub parses the real XAML).

The tests cover:
- workset, filter, AND/OR and category targeting;
- trial leaving the model unchanged;
- standalone, grouped, nested and whole-group removal, and the type names after regrouping;
- merging identical regrouped types, and refusing it for a mirrored instance or different Marks;
- pinned elements and groups, borrowed elements, names not found, Revit warnings and errors;
- the CLI, the listener route and the window.

## About

Every entry point has an About screen with the product name, version, owner and requirements:
- the **About** button in the Element Remover window;
- **Netbuild → About** on the ribbon (pick *Element Remover by Netbuild*);
- `ElementRemover about` on the command line (`ElementRemover --version` prints the version).

`ElementRemover.exe` also carries this in **Properties → Details**: Company Netbuild, Product Element
Remover by Netbuild, the version, Copyright (c) 2026 Netbuild. All rights reserved., Comments
https://skaec.com. All of it comes from one file, `element_remover/about.py`.

### Requirements

| To run | You need |
|---|---|
| **Element Remover** ribbon button (runs inside Revit) | Windows 10 / 11 64-bit · Autodesk Revit 2019 – 2026 · pyRevit 4.8 or later with its IronPython engine (the default) |
| **ElementRemover.exe** | Windows 10 / 11 64-bit, no Python needed · Revit open with pyRevit and the Revit MCP extension, its listener running (MCP Status on) at `http://127.0.0.1:48884` |
| From source | Python 3.9 or later |
| The model | A project model opened editable (not read-only) · when workshared, the worksets holding the targets open, and the targets and their groups not borrowed by other users · Save / Synchronize after Apply |

### Licence

Proprietary software -- (c) 2026 Netbuild. All rights reserved. https://skaec.com

Element Remover is licensed under the **Netbuild Software Licence Agreement**; it needs no licence key.
The full text is in [`LICENSE`](../LICENSE), shipped next to the exe and in `Netbuild.extension`.
The licensing page (owner, website, licence-key status and the full agreement) is shown by:
- the **Licence** button in the Element Remover window, and in every About window;
- **Netbuild → Licence** on the ribbon;
- `ElementRemover license` (or `ElementRemover licence`) on the command line.

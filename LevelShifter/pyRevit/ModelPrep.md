# Model Prep by Netbuild

Prepares a building host model in Revit in three steps. Each step was a hand-run prompt before
(`scripts/b00x_model_prep_pipeline.py` and its three step scripts). Model Prep turns them into two ribbon
buttons, with **Check** first and **Apply** only after you confirm.

| Step | What it does | What it never does |
|---|---|---|
| **01 Discipline links** | Sorts each required discipline (ST, HV, PL, FF, EL, ID, LA, WS, TC, AV) into **OK** (the building's own file), **WRONG SCOPE** (a Tower `T00O` / Site-Wide `SW00` / `PO00` / `BA00` file used instead), **OTHER BUILDING** or **MISSING**. MISSING comes with the exact ACC *Consumed* folder to link from. Removes the WRONG SCOPE links on Apply | Add a link. The Revit API cannot browse ACC, so you link by hand. It also leaves alone links of other disciplines (the host's own AR context links) |
| **02 Worksets** | Reads the workset register `.xlsx` (even while it is open in Excel), checks the tab against the model's live worksets, and creates every missing workset | Delete a workset. It also never renames a look-alike (e.g. `Link-EL` and the register's `Link-ELE`) unless you tick that pair; the register's name always wins |
| **03 Link worksets** | Puts every link **type and every instance** on its `Link-*` workset by the project's rules | Guess. A link with no confident rule is asked, and you can save your answer as a rule |

## The buttons (Netbuild tab, Models panel)

**Model Prep** opens the window:

1. **Host building** is read from the model name (`ProjectC-Studio-BIM-B001-ZZZ-BM-950001_user` gives B001, BM
   host). Check it is the building you mean; a mismatch is flagged.
2. **Workset register** is the `.xlsx` and its tab. The ProjectA default is
   `C:\SK\Projects\ProjectA\Excel\3470 ProjectA Wadi High Rise - Worksets.xlsx`, tab `Sheet Model ` (trailing space),
   column A, no header. The line beside it says how many names are already in this model; a low share warns
   that the tab may not belong to this model. If the file can't be read, the list saved in the rules is
   used, with a warning.
3. **1. Check (changes nothing)** gives the full dry-run report: Step 01 OK / WRONG SCOPE / MISSING, Step 02
   CREATE / EXTRA / LOOKS ALIKE, Step 03 MOVE / ASK, and the totals Apply would change.
4. **Decisions...** covers what only you decide:
   - which links to remove (WRONG SCOPE ticked, OTHER BUILDING not);
   - which look-alike workset pairs to rename (none ticked);
   - a workset for each link without a rule. A cross-building AR link suggests `Link-Podium Buildings`, but
     nothing is chosen for you.

   Tick **Remember** to save your answers as exact-file-name rules. OK runs Check again.
5. **2. Apply** works only after a Check, and only if the model hasn't changed since. It asks first, then runs
   one TransactionGroup (one Undo entry: **Model Prep by Netbuild**); if any step fails, everything is rolled
   back. Afterwards the model is read back (**VERIFY**: links gone, worksets there, type == instance ==
   target), and a fresh Check shows what is left. Each run is logged to `%APPDATA%\Netbuild\ModelPrep\logs`.
6. **Copy missing-link paths** puts the manual link steps on the clipboard. For each one: Insert > Link Revit >
   Autodesk Docs > `A.WIP > 01.Architecture > Consumed > <folder>`, pick the building's own file only,
   Positioning *Auto - By Shared Coordinates*.

**Place Links** is Step 03 alone, for right after you link a model by hand (a new link lands on the current
workset). It lists the moves, asks, applies and verifies. Links without a rule are listed for Model Prep.

## Link -> workset rules (checked in this order)

1. **Exact file names** (`manual_overrides`). For example, `ProjectC-Studio-BIM-SW00-ZZZ-BM-925001.rvt` goes to
   `Studio_AR-00 Link-Levels `. Your remembered answers are added here.
2. **The building's own AR model in a non-AR (BM) host** goes to `Studio_AR-00 Link-Podium Buildings`.
3. **Tower Tier models**: `...-TO-ZZZ-AR-90000X.rvt` goes to `Studio_AR-00 Link-Tower (TX)`.
4. **Discipline**: ST to Link-STR, EL to Link-ELE, PL to Link-PLB, HV to Link-MEC, FF, WS, AV, ID to Link-INT,
   LA to Link-LAN, TC, LGT.
5. **Building code**: T00O to Link-Core, PO00 to Link-Tower (PO), BA00 to Link-Basement.
6. Anything else is **ASK**. That covers a cross-building AR link, a file name outside the naming rule, and a
   target workset that won't exist.

Expected gaps: ID and TC have no building-specific model for B001-B005 yet, so their MISSING lines are
marked *expected*.

## Rules for another project

The ProjectA rules are built in (`lib/model_prep/rules.py`). **Rules...** opens your own copy,
`%APPDATA%\Netbuild\ModelPrep\rules.json`, in Notepad. Every key in it replaces the built-in one; it is read
again on every Check. Delete the file to go back to the built-in rules.

| Key | What |
|---|---|
| `name_pattern` | regex: group 1 = building, group 2 = discipline |
| `required_disciplines`, `consumed_folder`, `broad_scope_codes`, `expected_missing` | Step 01 |
| `register_path`, `register_sheet`, `register_column`, `register_skip_rows`, `register_min_match`, `worksets` | Step 02 (`worksets` = the fallback list) |
| `manual_overrides`, `own_ar_in_non_ar_host`, `tower_tier_pattern`, `tower_tier_workset`, `discipline_worksets`, `building_worksets`, `cross_building_ar_suggestion` | Step 03 |

The register path and tab you pick in the window are remembered per user (pyRevit config).

## Requirements

- Windows 10 / 11, 64-bit; Autodesk Revit 2019 - 2026; pyRevit 4.8 or later, IronPython engine. No MCP
  listener and no exe are needed.
- A **workshared** project model, opened editable (a local copy). Link types and instances must not be
  borrowed by other users; borrowed ones are reported and skipped. Synchronize after Apply.
- Merging into a register workset that already exists in the model needs Revit 2022 or later; the
  register's workset must also be empty.

## Files

- `Netbuild.extension/Netbuild.tab/Models.panel/` holds the two buttons.
- `Netbuild.extension/lib/model_prep/` holds:
  - `core.py`, the rules engine (no Revit calls);
  - `revit.py`, snapshot and apply;
  - `xlsx.py`, the register reader;
  - `rules.py`;
  - `about.py`.
- `Netbuild.extension/lib/modelprep_ui.py` holds the XAML.
- `tests/test_model_prep.py` and `tests/fake_links.py` test the engine, the reader, Apply with rollback,
  and both buttons end to end.

(c) 2026 Netbuild. All rights reserved. https://skaec.com -- Netbuild Software Licence Agreement (proprietary).

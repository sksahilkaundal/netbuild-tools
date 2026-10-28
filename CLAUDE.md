# Netbuild -- conventions for every plugin / tool in this repository

Owner and publisher: **Netbuild**. Website: **https://skaec.com**. Brand: **Netbuild**.

## Licensing
- **Every product is proprietary software owned by Netbuild** -- no MIT / open-source licence.
- One licence for all: the **Netbuild Software Licence Agreement**, the root `LICENSE`
  ("Copyright (c) 2026 Netbuild. All rights reserved.", "Website: https://skaec.com"). Products that ship
  their own `LICENSE.txt` copy it byte for byte; never edit the text in one product only.
- Every product has a **Licence page**: owner ("Proprietary software -- owned by Netbuild"), website,
  licence-key status (the real key state, or "No licence key required for this product." when there is
  none) and the full agreement, with "Copy licence" and "Open https://skaec.com".
- Never change anything existing licence keys depend on (salts, secrets, key formats, Machine ID,
  product codes in the "Netbuild Licensing" sheet, licence/activation file names and folders) as part of
  branding or renaming -- split a display name from an identifier instead.

## Naming
- Every product is named **"<Tool> by Netbuild"** -- e.g. *Level Shift by Netbuild*. Use that exact
  string for window titles (`<Tool> by Netbuild <version> -- <context>`), the main .exe file name
  (`<Tool> by Netbuild.exe`), Windows file properties (ProductName), README titles and the Revit Undo
  entry / TransactionGroup name.
- A command-line exe keeps a short name without spaces (e.g. `LevelShift.exe`).
- pyRevit: all buttons live in the shared `Netbuild.extension` (tab **Netbuild**), one panel per
  discipline (e.g. `Levels.panel`, `Stairs.panel`), plus the **About** panel (`About.panel/About.pushbutton` and
  `Licence.pushbutton`), which
  stays last (`Netbuild.tab/bundle.yaml` `layout:`). Button `__author__ = "Netbuild -- skaec.com"`.
  The same extension also holds the **Netbuild Tools 01** and **Netbuild Tools 02** tabs (Sahil's
  utility buttons, formerly Studio-Claude "Netbuild 01 / 02").
- A button that runs a saved script (Netbuild Tools wrappers) finds it **by file name** with
  `netbuild_scripts.script_path(SCRIPT_NAME, OLD_PATH)` in any sub-folder of the script folders -- never a
  hard-coded path only.
- Every button script (`script.py`, and `config.py` when there is one) starts, right after `__author__`, with
  `import netbuild_scripts` / `netbuild_scripts.run_live(globals())`, so it runs from the script folder
  (**Netbuild -> Scripts -> Script Folder**, `lib/netbuild_scripts.py`) when one is set. Tests enforce this.

## About (required in every product)
Each product has one `about.py` (see `LevelShifter/level_shift/about.py`) that is the single source for:
`PRODUCT`, `VERSION`, `PUBLISHER = OWNER = "Netbuild"`, `WEBSITE = "https://skaec.com"`,
`COPYRIGHT` ("(c) <year> Netbuild. All rights reserved.", written as `u"\u00a9 ..."` -- the escape, not the
character -- so IronPython reads it), `DESCRIPTION`, `FEATURES`, `REQUIREMENTS`,
`LICENSE_NAME = "Netbuild Software Licence Agreement (proprietary)"`, `LICENSE_KIND`, `LICENCE_KEY`,
`LICENSE_TEXT` (== the root `LICENSE` / the product's `LICENSE.txt` -- enforced by a test), `title()`,
`about_text()`, `licence_text()`.
It must be shown by:
- an **About** tab / button and a **Licence** tab / page in the product's window;
- `<cli> about`, `<cli> license` (alias `licence`) and `<cli> --version` on the command line;
- the pyRevit **Netbuild -> About** and **Netbuild -> Licence** buttons (register the module in
  `lib/netbuild_about.py` `PRODUCTS`), and an About button (with its Licence button) in the product's own
  pyRevit window;
- the exe's Windows version resource (`make_version_file.py` -> PyInstaller `--version-file`).
Ship `LICENSE` next to the exes and inside `Netbuild.extension`.

## Requirements text
State what is actually needed to run each entry point (Windows, Revit versions, pyRevit version and
engine, MCP listener, Python for source runs, model state). Do not claim versions or platforms that
the code does not support.

## Code that runs inside Revit
IronPython 2.7 under pyRevit: no f-strings, no keyword-only args, no `super()` without args, no
`print(..., end=)`, ASCII source (or a `# -*- coding: utf-8 -*-` header). Tests enforce this.

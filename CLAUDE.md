# Netbuild -- conventions for every plugin / tool in this repository

Publisher: **SKAEC.COM** (https://skaec.com). Brand: **Netbuild**. License: MIT (root `LICENSE`).

## Naming
- Every product is named **"<Tool> by Netbuild"** -- e.g. *Level Shift by Netbuild*. Use that exact
  string for window titles (`<Tool> by Netbuild <version> -- <context>`), the main .exe file name
  (`<Tool> by Netbuild.exe`), Windows file properties (ProductName), README titles and the Revit Undo
  entry / TransactionGroup name.
- A command-line exe keeps a short name without spaces (e.g. `LevelShift.exe`).
- pyRevit: all buttons live in the shared `Netbuild.extension` (tab **Netbuild**), one panel per
  discipline (e.g. `Levels.panel`), plus the **About** panel (`About.panel/About.pushbutton`), which
  stays last (`Netbuild.tab/bundle.yaml` `layout:`). Button `__author__ = "Netbuild -- SKAEC.COM"`.

## About (required in every product)
Each product has one `about.py` (see `LevelShifter/level_shift/about.py`) that is the single source for:
`PRODUCT`, `VERSION`, `PUBLISHER = "SKAEC.COM"`, `WEBSITE`, `COPYRIGHT` ("(c) <year> SKAEC.COM",
written as `u"© ..."` so IronPython reads it), `DESCRIPTION`, `FEATURES`, `REQUIREMENTS`,
`LICENSE_NAME`, `LICENSE_TEXT` (== root `LICENSE`, enforced by a test), `title()`, `about_text()`.
It must be shown by:
- an **About** tab / button in the product's window;
- `<cli> about` and `<cli> --version` on the command line;
- the pyRevit **Netbuild -> About** button (register the module in `lib/netbuild_about.py` `PRODUCTS`),
  and an About button in the product's own pyRevit window;
- the exe's Windows version resource (`make_version_file.py` -> PyInstaller `--version-file`).
Ship `LICENSE` next to the exes and inside `Netbuild.extension`.

## Requirements text
State what is actually needed to run each entry point (Windows, Revit versions, pyRevit version and
engine, MCP listener, Python for source runs, model state). Do not claim versions or platforms that
the code does not support.

## Code that runs inside Revit
IronPython 2.7 under pyRevit: no f-strings, no keyword-only args, no `super()` without args, no
`print(..., end=)`, ASCII source (or a `# -*- coding: utf-8 -*-` header). Tests enforce this.

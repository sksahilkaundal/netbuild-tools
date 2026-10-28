# netbuild

Netbuild tools for Revit / BIM coordination -- proprietary software owned by **Netbuild** (https://skaec.com).
Every product is covered by the **Netbuild Software Licence Agreement** ([`LICENSE`](LICENSE)); products
sold with licence keys ship the same agreement as their `LICENSE.txt`.

| Product | Where | Licence | What it does |
|---|---|---|---|
| **Level Shift by Netbuild** | [`LevelShifter/`](LevelShifter/README.md) | Proprietary, no key | Move up to 10 levels; every element, group and model element hosted to them keeps its X, Y, Z. pyRevit ribbon buttons (Netbuild tab), a Windows app and a command line |
| **Align Viewports by Netbuild** | [`AlignViewports/`](AlignViewports/README.md) | Proprietary, no key | Line up the viewports and view titles on many sheets with a reference sheet (by projection origin, paired by slot). pyRevit ribbon button (Netbuild tab, Sheets panel) |
| **BUA Update by Netbuild** | [`BuaUpdate/`](BuaUpdate/README.md) | Proprietary, no key | Re-feed the raw Revit Area export into the ProjectA / ProjectB Option 1 / Option 2 BUA workbooks (frozen 274-column format) and tie out every BUA / GFA total. Windows app, command line and a pyRevit ribbon button (Netbuild tab) |
| **Stair Path by Netbuild** | [`StairPath/`](StairPath/README.md) | Proprietary, no key | Up / Down stair path annotations in plan views per scale (Fixed Up / Automatic Up/Down), text set away from each stair's run, room tags cleared. pyRevit ribbon button (Netbuild tab) and a command line (`StairPath.exe`) |
| **Clear Warnings by Netbuild** | [`LevelShifter/pyRevit/Netbuild.extension`](LevelShifter/README.md#clear-warnings-by-netbuild-warnings-panel) (Netbuild tab, Warnings panel) | Proprietary, no key | Warnings summary grouped by description, then a six-step cleanup: Area Plans, Areas, Area Separation Lines, orphaned Matchlines and Room Tags, duplicate Type Marks. One Undo entry; anything left alone on purpose is listed for review |
| **Element Remover by Netbuild** | [`ElementRemover/`](ElementRemover/README.md) | Proprietary, no key | Remove the elements on chosen worksets and/or passing chosen view filters (optionally some categories, e.g. walls), standalone or inside model groups (ungrouped, removed, regrouped). pyRevit ribbon button (Netbuild tab) and a command line |
| **Plot Runner by Netbuild** | `ProjectA_PlotRunner/` (PR #5) | Proprietary, no key | ProjectA Plot GA export pass, model by model, verified on disk |
| **Revit MCP Router by Netbuild** | `scripts/RevitMcpRouter/` (PR #3) | Proprietary, licence key | Lets Claude / any MCP client drive several Revit sessions, routed per chat session |
| **Remote Router by Netbuild** | `RevitMcpRemote/` (PR #2) | Proprietary, uses the Router's key | The Router's tools from Claude on the web, over an authenticated tunnel |
| **Revit Status by Netbuild** | `scripts/` (PR #3) | Proprietary, licence key | Revit / Autodesk session status, tray app |

Every product is named "*Tool* by Netbuild" and has an About screen (product info, version,
requirements) and a Licence page (owner, website, licence-key status, the full agreement) -- see
[`CLAUDE.md`](CLAUDE.md) for the conventions.

(c) 2026 Netbuild. All rights reserved. https://skaec.com

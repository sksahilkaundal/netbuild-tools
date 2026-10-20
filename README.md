# netbuild

Netbuild tools for Revit / BIM coordination -- proprietary software owned by **Netbuild** (https://skaec.com).
Every product is covered by the **Netbuild Software Licence Agreement** ([`LICENSE`](LICENSE)); products
sold with licence keys ship the same agreement as their `LICENSE.txt`.

| Product | Where | Licence | What it does |
|---|---|---|---|
| **Level Shift by Netbuild** | [`LevelShifter/`](LevelShifter/README.md) | Proprietary, no key | Move up to 10 levels; every element, group and model element hosted to them keeps its X, Y, Z. pyRevit ribbon buttons (Netbuild tab), a Windows app and a command line |
| **Align Viewports by Netbuild** | [`AlignViewports/`](AlignViewports/README.md) | Proprietary, no key | Line up the viewports and view titles on many sheets with a reference sheet (by projection origin, paired by slot). pyRevit ribbon button (Netbuild tab, Sheets panel) |
| **Plot Runner by Netbuild** | `ProjectA_PlotRunner/` (PR #5) | Proprietary, no key | ProjectA Plot GA export pass, model by model, verified on disk |
| **Revit MCP Router by Netbuild** | `scripts/RevitMcpRouter/` (PR #3) | Proprietary, licence key | Lets Claude / any MCP client drive several Revit sessions, routed per chat session |
| **Remote Router by Netbuild** | `RevitMcpRemote/` (PR #2) | Proprietary, uses the Router's key | The Router's tools from Claude on the web, over an authenticated tunnel |
| **Revit Status by Netbuild** | `scripts/` (PR #3) | Proprietary, licence key | Revit / Autodesk session status, tray app |

Every product is named "*Tool* by Netbuild" and has an About screen (product info, version,
requirements) and a Licence page (owner, website, licence-key status, the full agreement) -- see
[`CLAUDE.md`](CLAUDE.md) for the conventions.

(c) 2026 Netbuild. All rights reserved. https://skaec.com

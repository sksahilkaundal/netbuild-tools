# netbuild

Netbuild tools for Revit / BIM coordination -- proprietary software owned by **Netbuild** (https://skaec.com).
Every product is covered by the **Netbuild Software Licence Agreement** ([`LICENSE`](LICENSE)); products
sold with licence keys ship the same agreement as their `LICENSE.txt`.

| Product | Where | Licence | What it does |
|---|---|---|---|
| **Level Shift by Netbuild** | [`LevelShifter/`](LevelShifter/README.md) | Proprietary, no key | Move up to 10 levels; every element, group and model element hosted to them keeps its X, Y, Z. pyRevit ribbon buttons (Netbuild tab), a Windows app and a command line |
| **Clear Warnings by Netbuild** | [`LevelShifter/pyRevit/Netbuild.extension`](LevelShifter/README.md#clear-warnings-by-netbuild-warnings-panel) (Netbuild tab, Warnings panel) | Proprietary, no key | Warnings summary grouped by description, then a six-step cleanup: Area Plans, Areas, Area Separation Lines, orphaned Matchlines and Room Tags, duplicate Type Marks. One Undo entry; anything left alone on purpose is listed for review |
| **Plot Runner by Netbuild** | `ProjectA_PlotRunner/` (PR #5) | Proprietary, no key | ProjectA Plot GA export pass, model by model, verified on disk |
| **Revit MCP Router by Netbuild** | `scripts/RevitMcpRouter/` (PR #3) | Proprietary, licence key | Lets Claude / any MCP client drive several Revit sessions, routed per chat session |
| **Remote Router by Netbuild** | `RevitMcpRemote/` (PR #2) | Proprietary, uses the Router's key | The Router's tools from Claude on the web, over an authenticated tunnel |
| **Revit Status by Netbuild** | `scripts/` (PR #3) | Proprietary, licence key | Revit / Autodesk session status, tray app |

Every product is named "*Tool* by Netbuild" and has an About screen (product info, version,
requirements) and a Licence page (owner, website, licence-key status, the full agreement) -- see
[`CLAUDE.md`](CLAUDE.md) for the conventions.

(c) 2026 Netbuild. All rights reserved. https://skaec.com

# Revit MCP Remote - quick start

Goal: drive Revit from Claude on the web, with everything running on **one PC you
are free to use** (your Personal PC). The Work PC is not involved.

## Important: Revit and the router run on the SAME PC

The connector talks to Revit over the PC's own loopback (ports 48884+). It can only
reach Revit instances **running on the same machine** as the router. So to steer
Revit from Claude on the web, that Revit has to be open on the PC that runs
`Start Revit MCP Remote.cmd`. There is no way to reach a Revit on a different PC
without that other PC running the software and opening a network connection.

So: open your models on the **Personal PC** and run everything there.

## One-time setup (Personal PC)

1. This PC already needs the local Revit MCP Router working: Claude Code + pyRevit +
   the Revit MCP connector add-in, and `py -3.14` with `mcp[cli]<2` + `httpx`.
2. The `RevitMcpRemote` folder syncs here via Google Drive -> OneDrive
   (`...\Netbuild\scripts\RevitMcpRemote`). Make sure it sits next to `RevitMcpRouter`.
3. Install the tunnel once:  `winget install --id Cloudflare.cloudflared`
4. Sanity check:  `py -3.14 revit_mcp_remote.py --check`  (lists the tools + routed Revit)

## Each working session

1. Open your Revit model(s) on this PC.
2. Double-click **Start Revit MCP Remote.cmd**.
   - First run: set a passphrase (12+ chars, remember it).
   - It prints:  `Connector URL for Claude:  https://xxxx.trycloudflare.com/mcp`
   - Leave this window open the whole time.
3. In claude.ai: Settings -> Connectors -> **Add custom connector** -> paste that URL
   -> **Connect** -> type your passphrase on the sign-in page.
4. New chat:
   - `revit_list_sessions`              (confirm it sees your open Revits)
   - `revit_select_session doc:B002`    (pick which model to drive)
   - then work normally.

## Notes

- **The quick-tunnel URL changes every restart.** When you restart the .cmd, edit the
  connector in Claude and paste the new URL. For a URL that never changes, set up a
  named Cloudflare tunnel on your own domain (see README.md).
- **Multiple Revits open:** that's fine - `revit_list_sessions` shows them all and
  `revit_select_session` picks one. All connected chats share the one selected Revit,
  so run `revit_list_sessions` first in each chat.
- **Closing the .cmd window** cuts Claude off until you start it again.
- This connector drives Revit. For general coding on a repo from Claude on the web,
  that's the GitHub connector / Claude Code, which is separate.

# Remote Router by Netbuild (v0.5.0)

© 2026 SKAEC.COM. All rights reserved. — https://skaec.com — proprietary, see [Licence](#licence).

Revit MCP Router by Netbuild, reachable from **Claude on the web** (and desktop / mobile) as a custom connector.
Same tools and the same session routing as the local router (`revit_list_sessions`, `revit_select_session`,
`revit_status`, the multi-model tools and every pyRevit extension tool), served as a remote MCP server
over Streamable HTTP instead of stdio.

```
Claude (claude.ai)  --HTTPS-->  Cloudflare Tunnel  -->  127.0.0.1:8765  [OAuth gate]
                                                         --> bridge_core tools --> router --> Revit 48884..
```

- **Nothing is opened on the PC's network.** The server binds `127.0.0.1` only; `cloudflared` makes an
  outbound connection to Cloudflare and is the only way in. No admin rights, no firewall rule.
- **Every MCP request needs a bearer token.** Claude gets one through OAuth 2.1 (dynamic client registration +
  PKCE S256): when you click *Connect* in Claude, a sign-in page served by this PC asks for **your passphrase**.
  Tokens last 1 h and refresh for 30 days; `--revoke-all` signs everything out.
- **The router source is not copied.** `revit_mcp_remote.py` imports `bridge_core.build_server()` from the
  existing `scripts\RevitMcpRouter` folder, so routing fixes there apply here too, and the per-PC licence
  check still applies.

## Files

| File | Role |
|---|---|
| `revit_mcp_remote.py` | entry point: loads the router's tools, serves HTTP, starts the tunnel, `--setup` / `--check` / `--revoke-all` |
| `oauth_gate.py` | OAuth 2.1 server + bearer check in front of `/mcp` (stdlib + starlette) |
| `remote_about.py` | product name, version, copyright, requirements and licence text (`--about`, `--version`, banner, sign-in page) |
| `LICENSE.txt` | the licence agreement |
| `Start Revit MCP Remote.cmd` | double-click launcher: first-run setup, then serve + quick tunnel |
| `tests/test_remote.py` | end-to-end test against `tests/fake_bridge.py` (no Revit needed) |
| `tests/test_remote_about.py` | About / licence / `--version` checks |

## About

`py -3.14 revit_mcp_remote.py --about` prints the product info, requirements and licence;
`--version` prints `Remote Router by Netbuild 0.5.0`. The startup banner and the sign-in page show the same
name and copyright. All of it comes from `remote_about.py`.

## Requirements

- **This PC:** Windows, with Autodesk Revit open on this same PC (the connector reaches Revit over loopback only),
  pyRevit with the Revit MCP extension loaded (listener on `127.0.0.1`, ports 48884 and up), and
  **Revit MCP Router by Netbuild** installed and licensed here: its `scripts\RevitMcpRouter` folder
  (`bridge_core.py`) next to this folder, or given with `--router-dir` / `RMR_ROUTER_DIR`.
- **Python (runs from source):** the same Python 3 the router uses (the launchers call `py -3.14`; `mcp` needs
  3.10 or later) with `mcp[cli]<2` (brings `starlette` and `uvicorn`) and `httpx`.
- **Reaching it from Claude:** `cloudflared` for `--tunnel quick` / `named` (a named tunnel also needs a free
  Cloudflare account and your own domain), and a Claude plan that supports custom connectors, plus the passphrase
  set with `--setup`. Claude Code can use the static bearer token instead.

## Set up on the PC (once)

1. Same Python the router uses (`py -3.14`, with `mcp[cli]<2` and `httpx`; `uvicorn`/`starlette` come with `mcp`).
2. Install cloudflared: `winget install --id Cloudflare.cloudflared`, or put `cloudflared.exe` in this folder.
3. Keep this folder next to `RevitMcpRouter` (it is synced to `Netbuild\scripts\RevitMcpRemote`), or set `RMR_ROUTER_DIR`.
4. `py -3.14 revit_mcp_remote.py --check` should list the tools and the routed Revit.

## Use it

1. Open Revit (MCP connector loaded), then double-click **Start Revit MCP Remote.cmd**.
   First run asks for a passphrase (12+ chars) and prints a static token once (only for Claude Code / scripts).
2. The window prints `Connector URL for Claude: https://<random>.trycloudflare.com/mcp`.
3. claude.ai > **Settings > Connectors > Add custom connector** > paste the URL > **Connect** > enter the passphrase.
4. In a chat: `revit_list_sessions`, then `revit_select_session doc:B002` as usual.

Keep the window open while you work; closing it cuts Claude off.

**The quick-tunnel URL changes every time you start it**, so the connector has to be edited each session.
For a fixed URL, use a named Cloudflare tunnel on your own domain (free Cloudflare account):

```
cloudflared tunnel login
cloudflared tunnel create revit-mcp
cloudflared tunnel route dns revit-mcp revit.<yourdomain>
py -3.14 revit_mcp_remote.py --tunnel named --tunnel-name revit-mcp --public-url https://revit.<yourdomain>
```

Claude Code (header auth, no browser sign-in):
`claude mcp add --transport http revit-remote https://<host>/mcp --header "Authorization: Bearer <static token>"`

## Options

| Flag / env | Default | Meaning |
|---|---|---|
| `--port` / `RMR_PORT` | 8765 | local port (loopback only) |
| `--tunnel` / `RMR_TUNNEL` | none (cmd: quick) | `quick`, `named` or `none` (bring your own tunnel) |
| `--public-url` / `RMR_PUBLIC_URL` | from Host header | fixed public origin for OAuth metadata |
| `--router-dir` / `RMR_ROUTER_DIR` | sibling `..\RevitMcpRouter`, `..\scripts\RevitMcpRouter`, then `C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter` | where `bridge_core.py` lives |
| `--instances` / `RMR_INSTANCES` | 1 | run N (1–10) independent slots, each its own connector URL and its own selected Revit |
| `--deny-tools` / `RMR_DENY_TOOLS` | none | comma list of tools hidden from remote clients (e.g. code execution) |
| `--no-exec` / `RMR_NO_EXEC` | off | hide the arbitrary-code tools (`execute_revit_code`, `revit_run_on_documents`) so proprietary code is never sent over the connector |
| `--no-log` / `RMR_NO_LOG` | off | no request/access logging from the remote layer (connector URL is still printed) |
| `--state-dir` / `RMR_STATE_DIR` | `%LOCALAPPDATA%\RevitMcpRemote` | folder for the passphrase/token store (point it at your user profile only) |
| `RMR_EXTRA_REDIRECTS` | none | extra OAuth redirect URI prefixes (Claude web + loopback are built in) |
| `RMR_TUNNEL_PROTOCOL` | quic | tunnel transport: `quic` (lowest latency, auto-falls back to http2), `http2`, or `auto` |
| `RMR_KEEPALIVE` | 90 | seconds the edge↔server connection is held open between calls |
| `RMR_TUNNEL_KEEPALIVE` / `RMR_TUNNEL_KEEPALIVE_TIMEOUT` | 8 / 90s | cloudflared origin keep-alive pool size / idle timeout |
| `RMR_TUNNEL_VERBOSE` | off | show all cloudflared output |
| `--rotate-token`, `--revoke-all` | | new static token; forget every client and token |

## Things to know

- **One routing target per connector.** A single server keeps one selected Revit, so `revit_select_session` in one
  Claude chat changes it for every chat using that connector URL. Run `revit_list_sessions` first in each chat.
- **Driving several Revits at once — `--instances N` (up to 10).** This starts N independent servers (consecutive
  ports) and N tunnels, so you get **N separate connector URLs, each with its own selected Revit**. Add each URL as its
  own custom connector in Claude; then chat A on slot 1 can hold `doc:B001` while chat B on slot 2 holds `doc:B002`,
  simultaneously. All slots share one passphrase. Example:
  `py -3.14 revit_mcp_remote.py --tunnel quick --instances 4` prints four URLs labelled "Revit slot 1 of 4", etc.
- **Permanent URLs + several Revits — `--tunnel named --instances N`.** For fixed URLs that survive restarts, one
  named tunnel can front every slot. Give `--public-url` a `{n}` placeholder (one hostname per slot) and the server
  writes a cloudflared ingress config, points DNS for each hostname, and runs a single tunnel:
  ```
  py -3.14 revit_mcp_remote.py --tunnel named --tunnel-name revit-mcp --instances 3 \
    --public-url "https://revit{n}.yourdomain.com" --no-exec --no-log
  ```
  That serves `https://revit1.yourdomain.com/mcp` … `revit3…/mcp`, each its own Revit selection. One-time prep:
  a free Cloudflare account, your own domain, and `cloudflared tunnel login && cloudflared tunnel create revit-mcp`
  (the DNS routes are created for you on first run; you can also pre-create them with `cloudflared tunnel route dns`).
  All slots share one passphrase. (For N=1 a plain `--public-url https://revit.yourdomain.com` works with no placeholder.)
- **Long calls.** Cloudflare drops an HTTP response that sends nothing for ~100 s. Responses are streamed, but a single
  very long `revit_run_on_documents` over many models may still be cut; split big batches.
- **Latency.** Most of the round trip is the hop to the nearest Cloudflare edge, so it won't match a local stdio
  connection, but the tunnel runs over QUIC and holds connections open (`RMR_TUNNEL_PROTOCOL`, `RMR_KEEPALIVE`), the
  tunnel process stays warm (no per-call cold start), and discovery is pre-warmed at startup so the first call is quick.
  A named tunnel on your own domain usually lands on a closer, more stable edge than the quick tunnel.
- **Work PC policy.** Exposing a work PC through a tunnel may need IT approval; the named-tunnel setup can also sit
  behind Cloudflare Access if your IT requires SSO in front of it.
- **Security model.** Anyone who can type your passphrase on the sign-in page can drive Revit on this PC, including any
  code-execution tool the extension provides. Use a long passphrase; 5 wrong attempts lock sign-in for 15 minutes.
- **Privacy / keeping your IP yours.** The connection is TLS 1.3 end to end, so the *content* of your calls isn't readable
  on the network; only the destination is visible as metadata (a VPN hides that too on untrusted Wi-Fi). What TLS can't
  change is that code runs on whatever PC Revit is on. To keep proprietary logic off a machine you don't own: run with
  `--no-exec` (no code strings cross the connector), keep your proprietary routines as pyRevit extensions on your own
  laptop, and drive remote Revit only through the structured tools. On a managed/Work PC see **WORK_PC_SETUP.md** for the
  full hardening checklist — and note no setting hides the tool from software that manages that PC, which this project
  does not attempt.

## Test

```
py -3.14 -m unittest discover -s tests -v
```
(`py -3.14 tests\test_remote.py` still runs the end-to-end checks on their own.)
Covers: 401 + discovery, public-host metadata, redirect allow-list, wrong/locked passphrase, PKCE, single-use codes,
MCP `tools/list` + call through the gate, refresh rotation, static token, revoke-all, deny-tools, and the About /
licence / `--version` output.

## Licence

Proprietary. **Remote Router by Netbuild** is a paid Netbuild product, licensed (not sold) by SKAEC.COM under the
terms in [`LICENSE.txt`](LICENSE.txt); it runs only alongside a licensed copy of Revit MCP Router by Netbuild.
Autodesk and Revit are registered trademarks of Autodesk, Inc.; this product is not affiliated with or endorsed by
Autodesk or Anthropic.

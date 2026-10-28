# Revit MCP Router by Netbuild — product source (v1.3.7)

Lets one Claude Code session drive **any** of several open Revit instances (2023–2026 side by side),
chosen per session, following a document across a Revit restart, refusing to guess when ambiguous.
Licensed per PC. Shipped as native-compiled binaries — no Python source leaves this folder.

Proprietary — © 2026 Netbuild. All rights reserved. https://skaec.com · Owner and publisher: **Netbuild** · see [Licence](#licence).

## Files (this folder is PRIVATE — never ship it as a whole)

| File | Role | Ships? |
|---|---|---|
| `revit_mcp_router.py` | discovery + routing core | compiled → `.pyd` |
| `multimodel_core.py` | several models in one Revit: list open docs, run a task per model by title (dry run / apply) | compiled → `.pyd` |
| `bridge_core.py` | MCP stdio server: imports the extension's `tools/` from disk, routed helpers, session tools, licence gate | compiled → `.pyd` |
| `nb_license.py` | licensing: Machine ID, per-machine HMAC keys, one-machine passwords, signed `license.json`, optional Google-Sheet allow-list | compiled → `.pyd` |
| `install_revit_mcp_router.py` | install pipeline (CLI in source mode; module for the Setup app) | compiled → `.pyd` |
| `revit_mcp_bridge.py` | 12-line entry stub → `RevitMcpBridge.exe` | stub only |
| `setup_gui.py` | tkinter Setup app: **Setup** tab + **Licence** tab = the licensing page (product, owner, website, agreement name, key status, Machine ID, activation, developer name/email, full agreement text with Copy licence / Open https://skaec.com) + **About** tab (product, version, publisher, website, requirements, licence status); `VERSION`, `REQUIREMENTS`, `LICENSE_TEXT` live here | compiled → `.pyd` |
| `RevitMcpRouterSetup.pyw` | 10-line entry stub → `Revit MCP Router Setup.exe` | stub only |
| `build_release.py` | **developer**: Nuitka(zig) compile → PyInstaller two-exe bundle → self-tests → `--deploy` | never |
| `RevitMcpRouter_KeyGen.py` | **developer**: `--this-machine`, `--key <MID>`, `--hash <pw>`, `--new-password` | never |
| `router_test.py` | 15-step end-to-end test (fake Revits); `ROUTER_TEST_BRIDGE=<.py or .exe>` | never |
| `router_branding_test.py` | product name / owner / About / `LICENSE_TEXT` == `LICENSE.txt` == root `LICENSE`, and pins every licence-critical value (salts, product ids, key/hash outputs) so a rebrand cannot break existing keys; any OS | never |
| `LICENSE.txt` | Netbuild Software Licence Agreement (proprietary; same text as the Licence tab and the repository's root `LICENSE`) | copied next to the exes |
| `extension_snapshot/` | Revit-side code of the pyRevit extension as installed (MIT upstream + our gate), with provenance | reference |
| `PRODUCT_NOTES.md`, `RevitMcpRouter_PromptTemplate.md` | brief + prompts | never |
| `legacy_in_extension_patch/` | v1.0 history | never |

Release output: `Portable\Revit MCP Router\` (+ `Portable\Revit MCP Router v<version>.zip`):
`Revit MCP Router Setup.exe`, `RevitMcpBridge.exe`, shared `_internal\`, `README.txt`, `LICENSE.txt`.

## Requirements
- **Windows 10 or 11 (64-bit).** No admin rights; no Python needed for the exes.
- **Autodesk Revit 2023–2026** (several can be open side by side), each with **pyRevit** and the Revit MCP connector extension
  (`mcp-server-for-revit-python`) loaded — pyRevit's Routes server gives every Revit a port from 48884 up.
- **Claude Code** (Install / Reset edits `~/.claude.json`); Codex is connected too when `~/.codex` exists; any other stdio
  MCP client can start `RevitMcpBridge.exe` by hand.
- **Internet** to activate (live licence-sheet read / password claim) and at every bridge start for the licence check;
  7-day offline grace after the last successful check. One licence per computer (Machine ID).
- **Source mode (developer only):** Python 3.10+ with `mcp[cli]<2` and `httpx` (the extension venv works), tkinter for the
  Setup window. Release build: Python 3.14.7 + Nuitka/zig + PyInstaller (see Build + release).

## Licence
Proprietary — © 2026 Netbuild. All rights reserved. https://skaec.com — **Revit MCP Router by Netbuild** is owned by
Netbuild. The licence agreement is the **Netbuild Software Licence Agreement**,
`LICENSE.txt` (shipped next to the exes and shown on the Setup app's Licence tab; `setup_gui.LICENSE_TEXT` must equal it —
`router_branding_test.py` checks). `extension_snapshot/` is third-party MIT code and keeps its own `LICENSE`.

## How the product is protected
1. **No source / bytecode of the four core modules ships** — Nuitka compiles them to native `.pyd`
   (zig backend, no MSVC needed). `build_release.py` aborts if a `.py`/`.pyc` of them lands in the bundle.
2. **Signing secret is not a literal** — rebuilt at run time from two XOR arrays inside the compiled module
   (a hex-editor search for it finds nothing). The salt is public by design.
3. **Per-PC licence** — Machine ID = SHA-256(MachineGuid + hostname + product). A key is `HMAC(secret, MID)`
   and only works on that PC; a password binds to the first PC it is used on and is refused elsewhere.
4. **Signed activation file** — `%LOCALAPPDATA%\RevitMcpRouter\license.json` records carry an HMAC over
   (hash, machine_id); a copied, edited or hand-written file is ignored (verified: forged + tampered → unactivated).
5. **Enforced in the bridge, not only the installer** — unlicensed → every Revit tool returns the activation
   message with the Machine ID; `revit_status` reports `license`.
6. **Revocation (optional)** — set `LICENSE_SHEET_URL` in `nb_license.py` to a Google Sheet published as CSV
   (columns `Key, Type, Status, Machine_ID, Note`); every start re-checks, 7-day offline grace. Empty URL = offline
   mode (built-in password hashes + machine keys, no revocation). **Set since v1.1.1** → Google Sheet "Netbuild Licensing" (your Drive; one sheet for every Netbuild app), first tab published as CSV. Revoke = set `Status` to `revoked`; takes effect at the customer's next Claude session (bridge start), within the 7-day offline grace if they are offline.

7. **Import guard (v1.2.1, from the adversarial audit)** — the compiled module yields a *decoy* secret unless it runs inside one of our own frozen executables, so `import nb_license` from a stock interpreter cannot mint keys or signatures. `_K2` is derived at run time (not stored next to `_K1`).
8. **Cache and activation hardening (v1.2.1)** — `license_cache.json` is HMAC-bound to the machine and future timestamps are rejected; activation needs a LIVE sheet read (never from cache); with a sheet configured there is no offline fallback for a never-verified machine; garbage signatures are ignored, not crashed on.

Still open (see PRODUCT_NOTES): asymmetric (server-signed) keys so no secret ships at all; slow KDF for password rows; ship customer zips from a clean build only (the Portable copy holds the developer's own licence files).

Honest limit: a determined engineer with a disassembler can still reverse a native binary. This stops copying,
sharing and casual key forging — not a funded reverse-engineering effort.

## Issuing licences (developer) — one sheet, one KeyGen for both products
The sheet also holds **Revit Status** rows; use `--product rs` for that app (its keys/hashes use its own secret).

```bash
python "C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\RevitMcpRouter_KeyGen.py" --key XXXX-XXXX-XXXX-XXXX
```
Customer sends the Machine ID shown in the Setup app → you send back the key. `--new-password` makes a
one-PC password (add its hash to `ALLOWED_PASSWORD_HASHES` + rebuild, or to the sheet). `--this-machine` for this PC. `--sheet` lists the live rows, `--check <secret>` tests one against this PC.

## Build + release (developer)
```bash
py -3.14 "C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\build_release.py" --deploy
```
Bump `VERSION` in `setup_gui.py` first. Needs Python 3.14.7 (`py -3.14`; the build refuses older) with nuitka, ziglang, pyinstaller,
`mcp[cli]<2`, httpx. ~3 min. Runs Setup `--selftest`, `RevitMcpBridge --check` and the 11-step test over the exe
before deploying. Build gotchas: `.pyd` modules importing each other must be listed as hidden imports (PyInstaller
cannot see inside them); `bridge_core` keeps docstrings (they are the MCP tool descriptions), the others are built
with `no_docstrings`; never run any bridge from inside a PyInstaller bundle folder of another Python version.

## Install on a customer PC
Unzip → `Revit MCP Router Setup.exe` → licence dialog (Machine ID, Copy, Email developer) → **Install / Reset**
copies the app to `%LOCALAPPDATA%\RevitMcpRouter\app-<version>` and points every `revit` entry in `~/.claude.json`
at that `RevitMcpBridge.exe` (backup first). An entry under a backslash project key (`C:\...`), which Claude Code
never reads, is copied to the forward-slash key (`C:/...`) → new Claude session. Needs Claude Code + pyRevit + the
mcp-server-for-revit-python extension (its venv is NOT needed — the bridge is self-contained).

## This PC (developer)
`~/.claude.json` runs the **source-mode** bridge: extension venv python + `revit_mcp_bridge.py` here
(edits take effect on the next session, no rebuild). It is licensed via a machine key (offline mode).

## Using it from a Claude session
```
revit_list_sessions                      → every Revit + which one this session is routed to
revit_select_session  target="doc:B002"  → follow the Revit whose ACTIVE document contains "B002"
revit_select_session  target="version:2026" | "port:48885" | "pid:31204" | "auto"
revit_select_session  target="off"       → disconnect (alias "disconnect"/"none"): every Revit tool refuses until a new target
```
`doc:` follows the document across restarts and refuses when it is no longer the active window.
`pid:` / `version:` refuse once that Revit closes, even if a new Revit takes over its port (v1.3.6); `port:` follows the port.

Several models in ONE Revit (v1.3.0, `multimodel_core.py`; same engine as `scripts\MultiModelBatch.py`):
```
revit_list_documents                                  → every open model (active / linked / workshared / read-only)
revit_run_on_documents titles=["B001","B002"] code=…  → DRY RUN per model, bound by title (not the active window)
revit_run_on_documents … apply=true                   → commit, one undo step per model; lists unsynced_models
```
Task contract = MultiModelBatch's (`doc`, `uidoc`, `ctx.transaction`, `result`); 600 s per model; never syncs.

## Codex / other MCP clients (v1.3.0)
The bridge is a plain stdio MCP server. Setup's **Install / Reset** also writes `[mcp_servers.revit]` to
`~/.codex/config.toml` when `~/.codex` exists (backup first, only that table touched, `tool_timeout_sec = 1800`);
**Restore** points it back. Source mode: `install_revit_mcp_router.py --codex --apply`.
Claude Desktop: add the same command to `%APPDATA%\Claude\claude_desktop_config.json` → `mcpServers.revit`.

## How routing works
pyRevit's Routes engine gives every running Revit its own port (48884, 48885, …; registry =
`%APPDATA%\pyRevit\<ver>\pyRevit_<ver>_<pid>_serverinfo.pickle`). Each call: registry (live pids) ∪ probe 48884–48887
in parallel (Bitdefender drops closed-port SYNs) → pick by target → sticky → on death rescan and follow the last
document title → error if none/ambiguous. Every re-check (3 s) re-reads the routed port's pid/version from the live
registry, never from the cache; a different pid on that port = a different Revit → full rescan. `call_revit_route` retries once after a ConnectError. Env knobs:
`REVIT_MCP_TARGET`, `REVIT_MCP_BASE_PORT`, `REVIT_MCP_SCAN_PORTS`, `REVIT_MCP_PROBE_TIMEOUT`, `REVIT_MCP_EXTENSION_DIR`,
`REVIT_MCP_REGISTRY_DIR` / `RMR_LICENSE_DIR` (tests). State for the Revit Status tray: `%LOCALAPPDATA%\RevitStatus\router\<pid>.json`.

## Verified 2026-09-24 (v1.3.0, built on Developer PC 2 with Python 3.12 + Nuitka 4.2.2 --zig)
Setup `--selftest` OK, bridge `--check` 25 tools, `router_test.py` over the exe ALL PASSED (incl. new multi-model
steps 5a–5c). Deployed `Portable\Revit MCP Router` + `Revit MCP Router v1.3.0.zip` (37 MB). Not yet tried on a live Revit.

## Verified 2026-09-21 (v1.2.1, built from C:\SK\OneDrive\Netbuild)
- Adversarial audit (31 agents) reproduced two HIGH findings (importable secret; forgeable cache) — both closed and re-tested: from stock Python the shipped `.pyd` gives unstable decoy keys; forged cache + offline → activation refused; hand-signed record + server unreachable → `offline`; garbage sig → ignored; genuine online activation still OK.

## Verified 2026-09-21 (v1.1.0)
11/11 test steps over source bridge AND over `RevitMcpBridge.exe`; Setup `--selftest` OK from Portable; licence dialog
opens on an unlicensed PC; unlicensed bridge refuses all three tool kinds; forged/tampered `license.json` rejected;
two real Revits (2025/2026) routed by version/port; no `.py` in the bundle; secret literal absent from the `.pyd`.

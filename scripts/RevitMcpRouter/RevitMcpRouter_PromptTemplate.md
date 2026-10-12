# Revit MCP Router — prompt templates (v1.1.0)

Product folder (PRIVATE): `C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\`
Pipeline: `install_revit_mcp_router.py` · Bridge: `revit_mcp_bridge.py` → `bridge_core.py` · Router: `revit_mcp_router.py`
Licence: `nb_license.py` · Keys: `RevitMcpRouter_KeyGen.py` · Release: `build_release.py` · Test: `router_test.py`

---

## A. Use in a session with several Revits open

```
Run revit_list_sessions. Then route this session with revit_select_session doc:<MODEL TITLE SUBSTRING>
(or version:<YYYY> / port:<n>) and confirm with revit_status before doing anything else.
```
Rules the tools enforce: auto-route only when ONE Revit is up; `doc:` refuses if that document is not the active
window in its Revit; a Revit restart on another port is followed automatically; `pid:` / `version:` refuse once that
Revit closes even if a new Revit takes its port (v1.3.6). `revit_select_session off` disconnects the session (every
Revit tool refuses until a new target is selected).

## B. Install / re-install on THIS PC via Claude (source mode)

```
Run the Revit MCP Router pipeline:
"C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\install_revit_mcp_router.py"
Dry run first, show me the plan, then --apply. Then remind me to start a new Claude session.
```
`--add-project "<folder>"` for a project with no revit entry yet · `--verify` = check only · `--uninstall --apply` = back to main.py.

## C. A customer's PC (no Python, nothing edited by hand)

Give them `Portable\Revit MCP Router v1.1.1.zip`. Unzip → `Revit MCP Router Setup.exe` → licence dialog:
they send you the Machine ID shown there, you reply with the key from
```
python "C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\RevitMcpRouter_KeyGen.py" --key <MACHINE ID>
```
→ Activate → **Install / Reset** → new Claude Code session. (`README.txt` sits beside the exe.)

## D. Rebuild + release (after changing any file in this folder)

```
Bump VERSION in "C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\setup_gui.py",
then run  py -3.14 "C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\build_release.py" --deploy
and confirm: SELFTEST OK, bridge --check lists 25 tools, router_test ALL PASSED, zip written to Portable.
```

## E. Run the end-to-end test only (no Revit needed)

```
Run "C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\router_test.py" with the extension's
venv python; set ROUTER_TEST_BRIDGE to the source stub revit_mcp_bridge.py (or to Portable\Revit MCP Router\RevitMcpBridge.exe).
Expect "ALL PASSED" (15 steps, ports 48890-48893, temp registry).
```

## F. Revocation (Google Sheet allow-list — LIVE since v1.1.1)

Sheet: "Netbuild Licensing" in Sahil's Google Drive (https://docs.google.com/spreadsheets/d/1dPDDkNepE4NMPBvsaw48J0EknHujS72MicIYyBYxEhI/edit),
first tab published as CSV — ONE sheet for every Netbuild app (`--product rs` Revit Status, `--product bua` BUA Workbook Builder; the Product column says which). Revoke a customer = set their row's Status to `revoked`. New customer = paste the
TAB-separated row from `RevitMcpRouter_KeyGen.py --key <MID> --note "<customer>"`. To move to a NEW sheet:

```
Publish a new Google Sheet tab to the web as CSV with columns Key, Type, Status, Machine_ID, Note; paste the
/pub?...output=csv URL into LICENSE_SHEET_URL in
"C:\SK\OneDrive\Netbuild\scripts\RevitMcpRouter\nb_license.py",
rebuild with build_release.py --deploy, then add this PC's row (RevitMcpRouter_KeyGen.py --this-machine prints it
TAB-separated) before starting a new session.
```

## G. Fresh-machine context (memory is per-PC; this folder is OneDrive-synced)

- Developer PC needs: Python 3.14.7 (`py -3.14`; the build scripts refuse older) with nuitka, ziglang, pyinstaller, `mcp[cli]<2`, httpx; the pyRevit
  `mcp-server-for-revit-python` extension (+ its uv venv, only for source-mode runs); Claude Code with a `revit`
  MCP entry per project in `~/.claude.json`, keyed `C:/...` with forward slashes. Claude Code ignores a `C:\...`
  key; `--verify` shows such an entry as IGNORED and `--apply` copies it to the right key.
- uv on this PC is NOT on PATH: `%USERPROFILE%\uv-portable\uv.exe`.
- Bitdefender drops SYNs to closed loopback ports (timeout instead of refused) — the router probes in parallel for that reason.
- Related: `scripts\MultiModelBatch.py` (several models inside ONE Revit, by title), `Portable\Revit Status` (tray monitor;
  the router writes `%LOCALAPPDATA%\RevitStatus\router\<bridge pid>.json` for it — not yet displayed).

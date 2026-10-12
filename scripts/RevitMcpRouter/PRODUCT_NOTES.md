# Revit MCP Router — product notes (working name)

Intent (2026-09-21): turn this into a program / plugin to sell. This file is the starting brief.

## What the product does (one sentence)
Lets Claude (or any MCP client) drive **any** of several Revit sessions on a machine, chosen per
chat session by document / version / port, reconnecting automatically after a Revit restart and
never running a command on the wrong model.

## What is ours vs. third-party
| Part | Origin | Licence | Packaging implication |
|---|---|---|---|
| `revit_mcp_router.py`, `revit_mcp_bridge.py`, `install_revit_mcp_router.py`, `router_test.py` | ours | — | core IP |
| `extension_snapshot/revit_mcp/*`, `tools/*`, `startup.py` | upstream mcp-server-for-revit-python + our gate mods | MIT | can be bundled; keep the MIT notice |
| pyRevit (Routes server, IronPython host) | third-party | GPL-3 | do NOT bundle; require it as an install prerequisite; our bridge talks to it over HTTP from a separate process |
| `mcp`, `httpx`, `anyio` (bridge venv) | PyPI | MIT/BSD | bundle or pip-install at first run (the launcher already self-installs) |

## Status 2026-09-21 late - v1.1.0 built and deployed (see README.md 'How the product is protected')
- Native-compiled core (Nuitka/zig -> .pyd), two-exe PyInstaller bundle sharing _internal, per-PC licensing with
  signed activation file and split secret, unlicensed bridge refuses every tool, KeyGen CLI, release pipeline with
  three self-tests. Sheet revocation LIVE from v1.1.1 (Google Sheet "Netbuild Licensing" - one sheet for every Netbuild app - published CSV, 7-day grace).
- Not done: code-signing certificate (SmartScreen warning on customer PCs), KeyGen desktop app, Revit Status
  tray integration, licence expiry dates / subscription model.

## Changelog
- **v1.3.6 (2026-10-02) — routing-identity fix + disconnect.** Field bug, reproduced twice on the developer PC:
  a session pinned with `pid:19540` (port 48884) kept routing after that Revit closed and a NEW Revit (pid 28568)
  bound the same port, and `revit_status` / `revit_list_sessions` still showed `revit_pid: 19540`; second case
  `pid:48048` → pid 18176 on 48885 (an `execute_revit_code` dry run landed on the new Revit with no error). Cause:
  `RevitRouter.resolve()` re-probed the cached port and copied pid/version/host from the CACHED session onto the
  probe, so a `pid:` (and equally a `version:`) target always matched whatever process now owned the port. Fix:
  identity always comes from the live pyRevit registry (`_stamp`); a changed pid on the routed port forces a full
  rescan (→ `RouterError` for a pid target, naming the new pid); within the 3 s cache the routed pid is checked with
  `_pid_alive`; a failed rescan clears `current` and the tray state file (new `routed` field); `revit_list_sessions`
  re-verifies the route before reporting; the newest registry pickle owns a port (stale pickle + reused pid).
  `port:` targets still follow the port, now reporting the new pid. **New:** `revit_select_session("off")`
  (aliases `disconnect`, `unbind`, `none`) unbinds — every Revit tool refuses until a new target is set.
  Behaviour change: `none` used to mean `auto`. `bridge_core.py` has no routing logic of its own (every tool goes
  through `router.resolve()`); only the tool description changed. `router_test.py` steps 12–15 cover it (v1.3.5's
  exe fails step 13).
  **Build hardening (same day):** the first v1.3.6 build shipped 5 of the 6 protected modules (incl. `nb_license`)
  as plain bytecode inside `PYZ.pyz` — their `.pyd`s had vanished from the stage (cause not reproduced) and
  PyInstaller, run with SRC as cwd, silently packed the `.py` instead; self-tests passed and the old leak check only
  looked for loose `.py`/`.pyc`. `build_release.py` now fails if any `.pyd` is missing after compile or in the bundle,
  or if a protected module is inside either exe's PYZ, and runs PyInstaller from SCRATCH. Rebuilt + redeployed clean
  (archive `v1.3.6_2026-10-02_112731`); the first archive `v1.3.6_2026-10-02\release\` holds the leaky zip — never ship it.
  v1.3.0–v1.3.5 zips verified: all 6 modules as `.pyd`.

## Audit 2026-09-21 late (31-agent adversarial pass on the compiled builds) — what remains open
- HIGH (mitigated, not solved): any symmetric secret inside the client can be recovered by disassembly. v1.2.1 adds an import guard + derived key half; the real fix is **asymmetric keys**: the developer signs (Machine ID, expiry) with a private key, the app verifies with an embedded public key (pure-Python ECDSA P-256 or RSA-2048 verify is ~100 lines; key text becomes ~100-350 chars → paste, not type).
- MEDIUM: password rows use one SHA-256 with a public salt → use PBKDF2/scrypt (breaks existing rows; only the developer's so far).
- LOW: ship customer zips only from the clean build output (the Portable folder carries the developer's license.json/cache); add licence expiry / subscription dates; code-signing certificate.

## Packaging path (reuse what already exists in this project)
1. **One-folder exe** of the bridge (PyInstaller `--onedir`, as done for `Revit Status` — `--onefile` costs
   ~19 s per launch under Bitdefender). The exe replaces `python.exe + revit_mcp_bridge.py` in `~/.claude.json`.
2. **Installer GUI** = `install_revit_mcp_router.py` behind a small tkinter window (same pattern as
   `Title Block Fix.exe`): detect extension, write config, self-test, "start a new Claude session" notice.
3. **Licensing** = lift the `Revit Status` framework as-is: salted-hash password gate, one-machine lock
   (`license.json` + Machine ID), Google-Sheet allow-list with 7-day offline grace, KeyGen desktop app.
4. **Status UI** = `Revit Status` tray app reads `%LOCALAPPDATA%\RevitStatus\router\<pid>.json` and shows
   "Claude session X → Revit 2026 / B002" per row (follow-up, not built yet).
5. **pyRevit-side** ships as a pyRevit extension folder (our snapshot + gate) so the product does not depend
   on the user pulling the upstream repo; or stay compatible with upstream and only ship the bridge.

## Selling points to keep testable
- Works with Revit 2023–2026 side by side (pyRevit per-version ports).
- Zero config when one Revit is open; one command when several are.
- Survives Revit restart (follows the document), extension updates (launcher lives outside), venv rebuilds (self-install).
- Refuses ambiguity → no "edited the wrong model" incidents. This is the line that sells to BIM managers.

## Open questions before a first release
- Name / branding (Netbuild2026 © line already used by Revit Status).
- Does it target only Claude Code, or any MCP client (Cursor, VS Code)? The bridge is client-agnostic;
  only the installer's `~/.claude.json` step is Claude-specific.
- Support for a second machine: the router reads pyRevit's registry pickles — verify on a clean PC that the
  `%APPDATA%\pyRevit\<ver>\` layout is identical (it is pyRevit-versioned, not user-specific).

# Running Revit MCP Remote on the Work PC (the above-board way)

You can run the connector on the Work PC. The one condition is that it's done with
your IT/security team's awareness, not around them. A stable **named Cloudflare
tunnel**, optionally behind your company's SSO (Cloudflare Access), is a normal,
auditable way to get this approved — and it also gives you a URL that never changes.

This doc has two parts: what to send IT, and the setup once they say yes.

## 1. What to send IT (template)

> Subject: Request to enable remote access to Revit on my workstation (Claude MCP)
>
> Hi [IT/security],
>
> I'd like to drive Revit on my work workstation from Claude (Anthropic) using a small
> local tool (Revit MCP Remote). It runs only on my machine and exposes a single Revit
> automation endpoint. To reach it from Claude's cloud I'd use a **named Cloudflare
> Tunnel** (outbound only; no inbound firewall change), and I'm happy to put it behind
> **Cloudflare Access with our SSO** so only I can reach it.
>
> What it exposes: one HTTPS endpoint that forwards MCP tool calls to Revit on my PC,
> protected by a passphrase (and SSO if you prefer). What it does not do: open any
> inbound port, change firewall rules, or touch other machines.
>
> Could you approve this, or tell me the preferred way to expose an internal tool like
> this? Happy to walk through it. — SK

Adjust to your company's wording. If they prefer their own remote-access method (VPN,
Tailscale, an internal reverse proxy, Cloudflare Access on a corp domain), use that
instead — the connector just needs some approved public HTTPS URL that reaches
`127.0.0.1:8765` on this PC.

## 2. Setup once approved (named tunnel, fixed URL)

On the Work PC:

1. Make sure the local Revit MCP Router already works here (Claude Code + pyRevit + the
   MCP connector add-in; `py -3.14` with `mcp[cli]<2` + `httpx`).
2. The `RevitMcpRemote` folder syncs here via Drive -> OneDrive; keep it next to
   `RevitMcpRouter`.
3. Install cloudflared: `winget install --id Cloudflare.cloudflared`
4. Create the tunnel (free Cloudflare account, your own or a domain IT gives you):
   ```
   cloudflared tunnel login
   cloudflared tunnel create revit-mcp
   cloudflared tunnel route dns revit-mcp revit.<yourdomain>
   ```
5. (Recommended, for SSO) In the Cloudflare dashboard, add a **Cloudflare Access**
   application on `revit.<yourdomain>` restricted to your identity / company IdP.
6. Start it:
   ```
   py -3.14 revit_mcp_remote.py --tunnel named --tunnel-name revit-mcp --public-url https://revit.<yourdomain>
   ```
   First run sets your passphrase. The connector URL is `https://revit.<yourdomain>/mcp`
   and it stays the same every time.

Then in claude.ai: Settings -> Connectors -> Add custom connector -> that URL ->
Connect -> passphrase (and SSO if you enabled Access).

### Permanent URLs for several Revits at once

To drive multiple Revit instances in parallel, each from its own Claude chat, with fixed
URLs, add `--instances N` and give `--public-url` a `{n}` placeholder. One named tunnel
then fronts every slot (the server writes the cloudflared ingress config and points DNS
for each hostname on first run):

```
py -3.14 revit_mcp_remote.py --tunnel named --tunnel-name revit-mcp --instances 3 ^
  --public-url "https://revit{n}.<yourdomain>" --no-exec --no-log --state-dir "%USERPROFILE%\.rmr"
```

This serves `https://revit1.<yourdomain>/mcp` … `revit3…/mcp` — add each as its own custom
connector in Claude; each holds its own `revit_select_session`, so chat A can drive one
Revit while chat B drives another, simultaneously. All slots share the one passphrase.

## 3. Privacy hardening on a managed PC

The Work PC is owned by your company, so be clear-eyed about what "private" can and
cannot mean on it:

- **On the wire:** the MCP connection is TLS 1.3 end to end, so the *content* of your
  calls is not readable on the corporate network — same as webmail. The *destination*
  (an outbound connection to Cloudflare) is visible as metadata, not payload.
- **On the machine itself:** anything the company installs to manage the PC (MDM, EDR,
  DLP, screen recording) can see processes, files on disk, and what's in memory while a
  tool runs. That's true of **any** software you run on their hardware, including Claude
  Code Desktop. No setting here changes that, and this tool does not try to hide itself
  from that monitoring.

What you *can* do is keep your footprint small and keep your IP off the machine:

| Flag | What it does |
|---|---|
| `--no-exec` | Hides the arbitrary-code tools (`execute_revit_code`, `revit_run_on_documents`). Your proprietary code is then **never shipped over the connector** — only the structured Revit tools run. |
| `--no-log` | Turns off request/access logging from the remote layer (the connector URL is still printed). |
| `--state-dir D` | Keeps the passphrase/token store in a folder you choose (e.g. your own user profile), not a shared location. |

Recommended Work-PC command:

```
py -3.14 revit_mcp_remote.py --tunnel named --tunnel-name revit-mcp ^
  --public-url https://revit.<yourdomain> --no-exec --no-log --state-dir "%USERPROFILE%\.rmr"
```

### The real way to keep proprietary logic off the Work PC

The one thing a connector can't do is un-run code: whatever executes in Revit runs on the
PC Revit is on. So if your high-value logic must never materialize on the Work PC:

1. Keep your proprietary routines as **pyRevit extensions installed on your own laptop**,
   not on the Work PC.
2. Run with `--no-exec` on the Work PC so no code string can be sent through the connector.
3. Drive the Work PC's Revit only through the **generic, structured tools** (open document,
   list/set elements and parameters, run a named command). Those carry no proprietary logic —
   just instructions to Revit's own API.

That way the Work PC runs ordinary Revit automation and your IP stays on hardware you own.
If a model physically has to be open on the Work PC and your logic has to run *in* it, there
is no configuration that keeps that logic off the machine — that's a property of where Revit
runs, not of this tool.

## Notes

- `--deny-tools execute_revit_code` (or any tool name) hides individual tools from the remote
  connector if IT wants the surface reduced further. `--no-exec` is the shortcut for the whole
  code-execution set.
- `--revoke-all` signs out every connected client immediately.
- Everything else (multiple Revits, `revit_select_session`, URL behaviour) is in
  README.md / QUICKSTART.md.

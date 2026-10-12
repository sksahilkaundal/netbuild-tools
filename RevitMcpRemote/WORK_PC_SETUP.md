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

## Notes

- `--deny-tools execute_revit_code` (or any tool name) hides risky tools from the remote
  connector if IT wants the surface reduced. Example:
  `py -3.14 revit_mcp_remote.py --tunnel named --tunnel-name revit-mcp --public-url https://revit.<yourdomain> --deny-tools execute_revit_code`
- `--revoke-all` signs out every connected client immediately.
- Everything else (multiple Revits, `revit_select_session`, URL behaviour) is in
  README.md / QUICKSTART.md.

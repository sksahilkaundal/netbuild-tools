# -*- coding: utf-8 -*-
"""Product information shown by every About screen (`--about`, `--version`, `--license`, the startup
banner, the sign-in page, GET /license). LICENSE_TEXT must equal LICENSE.txt in this folder -- a test
checks it.
"""

BRAND = "Netbuild"
NAME = "Remote Router"
PRODUCT = NAME + " by " + BRAND                      # "Remote Router by Netbuild"
VERSION = __version__ = "0.5.0"
PUBLISHER = "Netbuild"
OWNER = "Netbuild"
WEBSITE = "https://skaec.com"
YEAR = "2026"
COPYRIGHT = u"\u00a9 %s %s. All rights reserved." % (YEAR, OWNER)   # (c) 2026 Netbuild. All rights reserved.
LICENSE_NAME = "Netbuild Software Licence Agreement (proprietary)"
# This tool has no key of its own: it loads the router's tools (bridge_core), and the router checks
# its own per-PC licence when they load and refuses every Revit call while unlicensed.
LICENCE_KEY = ("No separate key: uses the licence of Revit MCP Router by Netbuild on this PC "
               "(checked by the router; unlicensed, every Revit call returns the router's licence message)")

DESCRIPTION = ("The remote / web front end of Revit MCP Router by Netbuild: the same Revit tools and the "
               "same session routing, served as a remote MCP server (Streamable HTTP) so Claude on the web, "
               "desktop and mobile can drive Revit on this PC through a custom connector. The server binds "
               "127.0.0.1 only; a Cloudflare Tunnel (outbound) is the way in, and every MCP request needs a "
               "bearer token obtained by signing in with your passphrase (OAuth 2.1 + PKCE).")

FEATURES = [
    "Loads the router's own tools (bridge_core.build_server()) -- revit_list_sessions, "
    "revit_select_session, revit_status and every pyRevit extension tool",
    "OAuth 2.1 sign-in (dynamic client registration, PKCE S256, refresh rotation) with your passphrase; "
    "5 wrong attempts lock sign-in for 15 minutes; static bearer token for Claude Code / scripts",
    "Quick tunnel (new URL each start) or named Cloudflare tunnel on your own domain (fixed URL)",
    "--instances N (1-10): independent slots, each its own connector URL and its own selected Revit",
    "Privacy flags: --no-exec (no code strings over the connector), --no-log, --state-dir, --deny-tools",
]

REQUIREMENTS = [
    ("This PC", [
        "Windows, with Autodesk Revit open on this same PC (the connector reaches Revit over loopback only)",
        "pyRevit with the Revit MCP extension loaded (its listener on 127.0.0.1, ports 48884 and up)",
        "Revit MCP Router by Netbuild installed and licensed here: its scripts\\RevitMcpRouter folder "
        "(bridge_core.py) next to this folder, or given with --router-dir / RMR_ROUTER_DIR",
    ]),
    ("Python (runs from source)", [
        "The same Python 3 the router uses (the launchers call py -3.14); mcp needs Python 3.10 or later",
        "Packages: mcp[cli] below 2.0 (brings starlette and uvicorn) and httpx",
    ]),
    ("Reaching it from Claude", [
        "--tunnel quick / named: cloudflared (winget install --id Cloudflare.cloudflared, "
        "or cloudflared.exe in this folder)",
        "--tunnel named: a free Cloudflare account and your own domain",
        "A Claude plan that supports custom connectors (Settings > Connectors > Add custom connector), "
        "and the passphrase set with --setup; Claude Code can use the static bearer token instead",
    ]),
]

LICENSE_TEXT = u"""Netbuild Software Licence Agreement

Copyright (c) 2026 Netbuild. All rights reserved.
Website: https://skaec.com

This agreement covers every Netbuild software product -- including Level Shift by
Netbuild, Model Prep by Netbuild, Align Viewports by Netbuild, BUA Update by
Netbuild, Stair Path by Netbuild, Clear Warnings by Netbuild, Element Remover by
Netbuild, Plot Runner by Netbuild, Revit MCP Router by Netbuild, Remote Router by
Netbuild and Revit Status by Netbuild -- together with its updates and documentation
(the "Software").

1. Ownership. The Software is proprietary. It is owned by Netbuild and protected by
   copyright and other intellectual property laws. It is licensed, not sold.

2. Licence. Netbuild grants you a non-exclusive, non-transferable licence to install
   and use the Software for your own work, on the terms under which you obtained it
   from Netbuild or https://skaec.com (including any licence key, number of computers
   and licence period).

3. Restrictions. You may not: (a) copy the Software, except to install it and to keep
   one backup; (b) sell, rent, lease, lend, sublicense, publish or otherwise
   distribute the Software or its licence keys; (c) modify, adapt, decompile,
   disassemble or reverse engineer the Software, or bypass or disable its licence
   checks, except where the law expressly allows it; (d) remove or alter any
   copyright, trademark or licence notice.

4. Licence keys. Where the Software requires a licence key, the key is valid only for
   the computer(s) and period it was issued for. Moving a licence to another computer
   requires a transfer from Netbuild. Netbuild may revoke a licence key if this
   agreement is breached.

5. Termination. This licence ends automatically if you breach this agreement. You
   must then stop using the Software and delete all copies.

6. No warranty. The Software is provided "as is", without warranty of any kind,
   express or implied, including fitness for a particular purpose. You are
   responsible for checking its results and for keeping backups of your models and
   files.

7. Limitation of liability. To the extent permitted by law, Netbuild is not liable
   for any indirect, incidental or consequential damages, or for loss of data, of
   work in Autodesk Revit models, of profit or of business, arising from the use of
   or inability to use the Software.

8. Third parties. Autodesk and Revit are registered trademarks of Autodesk, Inc.
   pyRevit, the Model Context Protocol SDK and other third-party components are used
   under their own licences. Netbuild is not affiliated with or endorsed by Autodesk
   or Anthropic.

Contact: https://skaec.com
"""


def title(extra=""):
    """'Remote Router by Netbuild 0.5.0' (+ ' -- extra')."""
    return u"%s %s%s" % (PRODUCT, VERSION, (u" -- " + extra) if extra else u"")


def requirements_text():
    lines = []
    for head, items in REQUIREMENTS:
        lines.append(head)
        lines.extend(u"  - " + i for i in items)
    return u"\n".join(lines)


def about_text(license=True):
    """The whole About screen as plain text (license=False: the one-line licence summary only)."""
    parts = [u"%s  version %s" % (PRODUCT, VERSION), COPYRIGHT + u"  |  " + WEBSITE, u"", DESCRIPTION, u"",
             u"Features"] + [u"  - " + f for f in FEATURES] + [u"", u"Requirements", requirements_text(), u"",
                                                                u"Licence: %s -- full text: --license (LICENSE.txt)"
                                                                % LICENSE_NAME,
                                                                u"Licence key: " + LICENCE_KEY]
    if license:
        parts += [u"", LICENSE_TEXT.rstrip()]
    return u"\n".join(parts)


def license_lines():
    """The Licence page header (before the agreement), shared by --license and GET /license."""
    return [u"%s  version %s" % (PRODUCT, VERSION),
            u"Proprietary software -- owned by %s" % OWNER,
            COPYRIGHT,
            u"Website: " + WEBSITE,
            u"Licence key: " + LICENCE_KEY]


def license_text():
    """The whole Licence page as plain text: header + the full agreement (LICENSE.txt)."""
    return u"\n".join(license_lines() + [u"", LICENSE_TEXT.rstrip()])

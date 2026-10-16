# -*- coding: utf-8 -*-
"""Product information shown by every About screen (`--about`, `--version`, the startup banner,
the sign-in page). LICENSE_TEXT must equal LICENSE.txt in this folder -- a test checks it.
"""

BRAND = "Netbuild"
NAME = "Remote Router"
PRODUCT = NAME + " by " + BRAND                      # "Remote Router by Netbuild"
VERSION = __version__ = "0.5.0"
PUBLISHER = "SKAEC.COM"
WEBSITE = "https://skaec.com"
YEAR = "2026"
COPYRIGHT = u"© %s %s. All rights reserved." % (YEAR, PUBLISHER)   # (c) 2026 SKAEC.COM. ...
LICENSE_NAME = "Proprietary -- SKAEC.COM licence agreement"

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

LICENSE_TEXT = u"""Remote Router by Netbuild -- Licence Agreement

Copyright (c) 2026 SKAEC.COM. All rights reserved.

This software is licensed, not sold. SKAEC.COM grants you a non-exclusive, non-transferable licence to install and use this software on the computer(s) for which a valid licence was issued, for the term of that licence.

You may not: copy or distribute the software except for your own backup; sell, rent, lease, sublicense or share the software or its licence keys; modify, decompile, disassemble or reverse engineer it, or bypass its licence checks, except where the law expressly allows it; or remove copyright or licence notices.

SKAEC.COM may revoke a licence if these terms are broken. Moving a licence to another computer requires a transfer from SKAEC.COM.

The software is provided "as is", without warranty of any kind. To the extent permitted by law, SKAEC.COM is not liable for any damages arising from its use, including loss of data or of work in Autodesk Revit models. Keep backups of your models.

Autodesk and Revit are registered trademarks of Autodesk, Inc. pyRevit, the Model Context Protocol SDK and other third-party components are used under their own licences. This product is not affiliated with or endorsed by Autodesk or Anthropic.

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
    """The whole About screen as plain text."""
    parts = [u"%s  version %s" % (PRODUCT, VERSION), COPYRIGHT + u"  |  " + WEBSITE, u"", DESCRIPTION, u"",
             u"Features"] + [u"  - " + f for f in FEATURES] + [u"", u"Requirements", requirements_text(), u"",
                                                                u"Licence: " + LICENSE_NAME + u" (LICENSE.txt)"]
    if license:
        parts += [u"", LICENSE_TEXT.rstrip()]
    return u"\n".join(parts)

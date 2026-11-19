"""Create netbuild_secrets.py -- the licence secrets of BUA Workbook Builder, Revit Status and Revit MCP Router.

The repository is public, so the secrets never go into git (.gitignore lists netbuild_secrets.py). This writes
fresh random ones on YOUR PC:

    python scripts/make_netbuild_secrets.py --sheet-url <published CSV url> --api-url <Apps Script /exec url>
        [--password BUA=<pw> --password RS=<pw> --password RMR=<pw>]   (passwords that unlock without a key)
        [--force]                                                       (replace existing secrets)

It writes scripts/netbuild_secrets.py and scripts/RevitMcpRouter/netbuild_secrets.py (the same file), then
prints what to do with it:
  * GitHub: Settings > Secrets and variables > Actions > New repository secret NETBUILD_SECRETS = the whole file;
  * the Apps Script: Script Properties SALT_BUA / SALT_RS / SALT_RMR = the pw_salt values printed below.
New secrets invalidate every key, password and activation made with the old ones: re-issue them.
Keep a copy somewhere safe (a password manager); without it you cannot issue keys for builds made with it.
"""
import argparse
import hashlib
import os
import pprint
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = [os.path.join(HERE, "netbuild_secrets.py"), os.path.join(HERE, "RevitMcpRouter", "netbuild_secrets.py")]
PRODUCTS = ("BUA", "RS", "RMR")


def build(sheet_url, api_url, passwords):
    out = {}
    for code in PRODUCTS:
        salt = secrets.token_urlsafe(24)
        pws = passwords.get(code, [])
        out[code] = {
            "pw_salt": salt,
            "k1": secrets.token_hex(32),
            "password_hashes": sorted(hashlib.sha256((salt + "\x1f" + pw).encode("utf-8")).hexdigest() for pw in pws),
            "sheet_url": sheet_url,
            "api_url": api_url,
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sheet-url", default="", help="the licence sheet tab published as CSV")
    ap.add_argument("--api-url", default="", help="the licence sheet's Apps Script /exec URL")
    ap.add_argument("--password", action="append", default=[], metavar="CODE=PW",
                    help="a password that unlocks product CODE (BUA, RS or RMR); repeatable")
    ap.add_argument("--force", action="store_true", help="overwrite existing netbuild_secrets.py")
    a = ap.parse_args(argv)
    passwords = {}
    for item in a.password:
        code, sep, pw = item.partition("=")
        if not sep or code.upper() not in PRODUCTS or not pw:
            ap.error("--password must be CODE=PW with CODE one of %s" % ", ".join(PRODUCTS))
        passwords.setdefault(code.upper(), []).append(pw)
    existing = [p for p in TARGETS if os.path.exists(p)]
    if existing and not a.force:
        sys.exit("%s already exists -- pass --force to replace it (every existing key stops working)" % existing[0])
    text = ('"""Netbuild licence secrets -- NEVER commit this file (made by make_netbuild_secrets.py)."""\n'
            "SECRETS = " + pprint.pformat(build(a.sheet_url, a.api_url, passwords), width=110) + "\n")
    for p in TARGETS:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote " + p)
    ns = {}
    exec(text, ns)
    print("\nApps Script > Project Settings > Script Properties:")
    for code in PRODUCTS:
        print("  SALT_%-4s = %s" % (code, ns["SECRETS"][code]["pw_salt"]))
    print("\nGitHub repository secret NETBUILD_SECRETS = the whole contents of %s" % TARGETS[0])
    print("Re-issue every licence key / password: the old ones do not match these secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

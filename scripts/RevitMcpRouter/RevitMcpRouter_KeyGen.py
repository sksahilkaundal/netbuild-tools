# -*- coding: utf-8 -*-
"""Developer-only key generator for the Netbuild apps (never ship this file).

One sheet ("Netbuild Licensing", first tab published as CSV) holds the rows of EVERY
product; each product has its own secret/salt, so pick the product first:

  --product rmr   Revit MCP Router   (default)   crypto from nb_license.py (beside this file)
  --product rs    Revit Status                   crypto from ..\\revitstatus_core.py
  --product bua   BUA Workbook Builder           crypto from ..\\bua_license.py
                  (--kill-row prints its KILL SWITCH row; set that row's Status to "revoked"
                   in the sheet to disable every copy - BuaLicenceAdmin.pyw has a button for it)

  python RevitMcpRouter_KeyGen.py --this-machine                       -> this PC's Machine ID + key + row
  python RevitMcpRouter_KeyGen.py --key XXXX-XXXX-XXXX-XXXX --note "Customer"   -> key for a customer PC + row
  python RevitMcpRouter_KeyGen.py --hash "<password>"                  -> hash + row for an existing password
  python RevitMcpRouter_KeyGen.py --new-password --note "Customer"     -> random one-PC password + hash + row
  python RevitMcpRouter_KeyGen.py --sheet                              -> list what the published sheet says now
  python RevitMcpRouter_KeyGen.py --check <password or key>            -> is it accepted on THIS machine?

Rows are TAB-separated: paste into the sheet and each value lands in its own column.
"""
import argparse
import os
import secrets
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load_product(code):
    if code == "rmr":
        import nb_license as L
        return L, "Revit MCP Router"
    if code == "rs":
        sys.path.insert(0, os.path.dirname(HERE))
        import revitstatus_core as mod
        return mod, "Revit Status"
    if code == "bua":
        sys.path.insert(0, os.path.dirname(HERE))
        import bua_license as mod
        return mod, "BUA Workbook Builder"
    sys.exit("unknown product %r (rmr | rs | bua)" % code)


def row(key, typ, mid="", note="", product=""):
    return "\t".join([key, typ, "active", mid, note, product])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--product", choices=["rmr", "rs", "bua"], default="rmr")
    ap.add_argument("--kill-row", action="store_true", help="bua only: print the kill switch row")
    ap.add_argument("--this-machine", action="store_true")
    ap.add_argument("--key", metavar="MACHINE_ID")
    ap.add_argument("--hash", metavar="PASSWORD")
    ap.add_argument("--new-password", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--check", metavar="SECRET")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    L, name = load_product(a.product)
    note = a.note or name
    did = False
    if a.this_machine:
        mid = L.machine_id()
        print("[%s] Machine ID: %s" % (name, mid)); print("Key:       ", L.machine_key(mid)); print("Sheet row: ", row(L.machine_key(mid), "key", mid, note, name)); did = True
    if a.key:
        mid = a.key.strip().upper()
        if len(mid.replace("-", "")) != 16:
            sys.exit("Machine ID must look like XXXX-XXXX-XXXX-XXXX")
        print("[%s] Key:  %s" % (name, L.machine_key(mid))); print("Sheet row: ", row(L.machine_key(mid), "key", mid, note, name)); did = True
    if a.hash:
        print("[%s] Hash: %s" % (name, L.password_hash(a.hash))); print("Sheet row: ", row(L.password_hash(a.hash), "password", "", note, name)); did = True
    if a.new_password:
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14))
        print("[%s] Password: %s" % (name, pw)); print("Hash:      ", L.password_hash(pw)); print("Sheet row: ", row(L.password_hash(pw), "password", "", note, name)); did = True
    if a.kill_row:
        if not hasattr(L, "KILL_KEY"):
            sys.exit("--kill-row is only for --product bua")
        print("[%s] kill switch now: %s" % (name, L.kill_row_state(L.fetch_allow_list()[0])))
        print("Sheet row: ", "\t".join([L.KILL_KEY, "kill", "active", "", "KILL SWITCH - set Status to revoked to disable ALL copies", name]))
        did = True
    if a.sheet:
        rows, src, err = L.fetch_allow_list()
        print("[%s] sheet source=%s%s" % (name, src, (" (" + err + ")") if err else ""))
        for k, r in (rows or {}).items():
            print("  %-64s %-8s %-8s %-19s %s" % (k, r["type"], r["status"], r.get("machine_id", ""), r.get("note", "")))
        did = True
    if a.check:
        mid = L.machine_id()
        rows, src, err = L.fetch_allow_list()
        sec = a.check.strip()
        is_key = sec.replace("-", "").upper() == L.machine_key(mid).replace("-", "")
        lookup = L.machine_key(mid).replace("-", "") if is_key else L.password_hash(sec)
        r = (rows or {}).get(lookup)
        print("[%s] %s for this machine (%s): %s" % (name, "key" if is_key else "password", mid,
              ("row %s" % r["status"]) if r else "no row in sheet (%s)" % src)); did = True
    if not did:
        ap.print_help()


if __name__ == "__main__":
    main()

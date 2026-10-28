"""
RevitStatus_KeyGen.py -- developer tool for Revit Status licensing.
Keep this file private; it holds the same secret as the app.

Licences live in ONE Google Sheet for every Netbuild app ("Netbuild Licensing",
LICENCE_SHEET_URL in revitstatus_sheet_client.py), whose first tab is published as CSV (LICENSE_SHEET_URL in
revitstatus_core.py), columns:  Key, Type, Status, Machine_ID, Note, Product
Only rows with Status = active are accepted; change it to revoked to lock
that PC on its next launch. This tool prints paste-ready rows.

  python RevitStatus_KeyGen.py --password "<new password>" --note "who"
      row for a new password (Key = its salted hash; the plain password is
      NEVER stored). Give the plain password to the user; each password
      activates one PC.

  python RevitStatus_KeyGen.py --key XXXX-XXXX-XXXX-XXXX --note "who"
      row + the key to email to a user whose PC shows that Machine ID (from
      the licence popup / the app footer). The key works only on that PC.

  python RevitStatus_KeyGen.py --this-machine
      this PC's Machine ID and key.

  python RevitStatus_KeyGen.py --sheet
      fetch the live sheet and list its rows (what the app will accept now).

  python RevitStatus_KeyGen.py --check "<password>"
      is this password active in the sheet (or in the built-in fallback)?

Writing to the sheet (needs the Apps Script web app deployed, url+token in
revitstatus_sheet_api.json / sheet_api.json beside this file):
  --password "<pw>" --note "who" --add      generate AND append the row
  --key <Machine ID> --note "who" --add     generate the key AND append the row
  --revoke <key or hash>   --activate <key or hash>   --delete <key or hash>
  --rows                                    list rows straight from the sheet (not the published copy)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revitstatus_sheet_client as api  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
import revitstatus_core as rs  # noqa: E402


def row(key, typ, note, machine_id=""):
    return "\t".join([key, typ, "active", machine_id, note, "Revit Status"])


def main():
    ap = argparse.ArgumentParser(description="Revit Status licence key generator")
    ap.add_argument("--password", metavar="PASSWORD", help="sheet row for a new password")
    ap.add_argument("--key", metavar="MACHINE_ID", help="key + sheet row for a Machine ID")
    ap.add_argument("--note", default="", help="Note column text (who it is for)")
    ap.add_argument("--this-machine", action="store_true", help="print this PC's Machine ID and key")
    ap.add_argument("--sheet", action="store_true", help="fetch and list the live sheet")
    ap.add_argument("--check", metavar="PASSWORD", help="is this password accepted right now?")
    ap.add_argument("--hash", metavar="PASSWORD", help="(legacy) print only the salted hash")
    ap.add_argument("--add", action="store_true", help="with --password/--key: also append the row to the sheet")
    ap.add_argument("--revoke", metavar="KEY", help="set Status=revoked on that key/hash in the sheet")
    ap.add_argument("--activate", metavar="KEY", help="set Status=active on that key/hash in the sheet")
    ap.add_argument("--delete", metavar="KEY", help="delete that key/hash row from the sheet")
    ap.add_argument("--rows", action="store_true", help="list the sheet's rows via the API")
    a = ap.parse_args()
    did = False

    def show_api(r):
        if r.get("ok"):
            print("sheet updated: ok (row %s)" % r.get("row", "-"))
        else:
            print("sheet update FAILED: %s" % r.get("error"))
    if a.password:
        did = True
        print("Paste this row into the licence sheet %s (Key, Type, Status, Machine_ID, Note, Product):" % api.LICENCE_SHEET_URL)
        print("  " + row(rs.password_hash(a.password), "password", a.note))
        print("Give the user the plain password: %s" % a.password)
        if a.add:
            show_api(api.add_row(rs.password_hash(a.password), "password", a.note, product="Revit Status"))
    if a.key:
        did = True
        k = rs.machine_key(a.key)
        print("Key to email the user (works only on Machine ID %s):" % a.key.upper())
        print("  " + k)
        print("Paste this row into the licence sheet %s:" % api.LICENCE_SHEET_URL)
        print("  " + row(k.replace("-", ""), "key", a.note, a.key.upper()))
        if a.add:
            show_api(api.add_row(k.replace("-", ""), "key", a.note, a.key.upper(), product="Revit Status"))
    if a.hash:
        did = True
        print(rs.password_hash(a.hash))
    if a.this_machine:
        did = True
        mid = rs.machine_id()
        print("Machine ID: %s" % mid)
        print("Key:        %s" % rs.machine_key(mid))
    if a.sheet:
        did = True
        rows, source, err = rs.fetch_allow_list()
        print("source=%s err=%s" % (source, err))
        if rows:
            print("%-66s %-9s %-8s %-20s %s" % ("Key", "Type", "Status", "Machine_ID", "Note"))
            for k, r in rows.items():
                print("%-66s %-9s %-8s %-20s %s" % (k, r["type"], r["status"], r["machine_id"], r["note"]))
        else:
            print("(no rows)")
    if a.check:
        did = True
        rows, source, err = rs.fetch_allow_list()
        h = rs.password_hash(a.check)
        if rows is not None:
            r = rows.get(h)
            print("sheet (%s): %s" % (source, ("ACTIVE" if r and r["status"] == "active" else ("revoked" if r else "not listed"))))
        else:
            print("sheet unreachable (%s); built-in fallback: %s" % (err, "accepted" if h in rs.ALLOWED_PASSWORD_HASHES else "NOT accepted"))
    if a.revoke:
        did = True
        show_api(api.revoke(a.revoke))
    if a.activate:
        did = True
        show_api(api.activate(a.activate))
    if a.delete:
        did = True
        show_api(api.delete(a.delete))
    if a.rows:
        did = True
        r = api.list_rows()
        if not r.get("ok"):
            print("FAILED:", r.get("error"))
        else:
            print("%-66s %-9s %-8s %-20s %s" % ("Key", "Type", "Status", "Machine_ID", "Note"))
            for x in r["rows"]:
                print("%-66s %-9s %-8s %-20s %s" % (x["key"], x["type"], x["status"], x["machine_id"], x["note"]))
            if r.get("sheet_id") != api.LICENCE_SHEET_ID:
                print("WARNING: these rows come from another sheet, not Netbuild Licensing - "
                      "deploy NetbuildLicensing_SheetApi.gs from that sheet (steps in its header).")
    if not did:
        ap.print_help()


if __name__ == "__main__":
    sys.exit(main())

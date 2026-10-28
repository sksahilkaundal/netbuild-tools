# -*- coding: utf-8 -*-
"""
Revit Status KeyGen -- developer-only desktop tool for issuing Revit Status licences.
KEEP PRIVATE: it embeds the same secret as the app, so anyone with it can mint keys.

  New password  -> salted hash + paste-ready sheet row (the plain password is only shown
                   to you, never stored)
  Machine key   -> key for one Machine ID (from a user's licence popup / app footer) + row
  Live sheet    -> what the licence sheet currently holds; check a password

Every Google call runs off the UI thread, so the window never freezes while the sheet answers.
Rows go to the ONE licence sheet every Netbuild app reads ("Netbuild Licensing"); "Open licence sheet"
opens it, and "Add to sheet" refuses to write through a sheet script that points anywhere else.

Imports revitstatus_core (the compiled .pyd in the frozen build, the source module beside this file otherwise),
so hashes and keys can never drift from what the app expects.
"""
import os
import queue
import secrets
import string
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

APP = "Revit Status KeyGen"


sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
import revitstatus_core as rs  # noqa: E402  (compiled .pyd in the frozen build, source beside this file otherwise)
import revitstatus_sheet_client as api  # noqa: E402

SHEET_HEADER = "Key\tType\tStatus\tMachine_ID\tNote"


def row_text(key, typ, note, machine_id=""):
    # tab-separated: pasting into Google Sheets fills one column per value
    return "\t".join([key, typ, "active", machine_id, note.replace("\t", " ")])


def suggest_password(n=12):
    alphabet = string.ascii_letters + string.digits + "@#%+=!"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.isupper() for c in pw) and any(c.isdigit() for c in pw) and any(c in "@#%+=!" for c in pw):
            return pw


def fetch_rows():
    """(rows, source, err) in the app's format: the live sheet through the Apps Script when it is the
    licence sheet, otherwise the published CSV the apps themselves read."""
    if (api.load_config() or {}).get("url"):
        r = api.list_rows()
        if r.get("ok") and r.get("sheet_id") == api.LICENCE_SHEET_ID:
            rows = {}
            for x in r["rows"]:
                compact = x["key"].replace("-", "")
                k = compact.upper() if len(compact) == 20 else x["key"].lower()
                rows[k] = {"type": x["type"], "status": x["status"].lower(), "machine_id": x["machine_id"], "note": x["note"]}
            return rows, "licence sheet (live)", None
    rows, source, err = rs.fetch_allow_list()
    return rows, "published copy the apps read (%s; edits appear within ~5 min)" % source, err


def main():
    root = tk.Tk()
    root.title(APP + "  (developer only)")
    root.geometry("760x600")
    root.minsize(640, 520)
    rt = rs._rt()                        # shared Revit Tools theme, light / dark following Windows
    rt.apply(root)                       # saved choice: As per system / Light / Dark
    ttk.Style(root).configure("Mono.TLabel", font=("Consolas", 10, "bold"))

    jobs = queue.Queue()
    busy = {"on": False}
    net_buttons = []                     # disabled while a sheet request is running

    def run_bg(work, done, label):
        """work() runs on a worker thread (sheet calls can take many seconds); done(result) back on the UI thread."""
        if busy["on"]:
            status.set("Still waiting for the sheet - one request at a time.")
            return
        busy["on"] = True
        for b in net_buttons:
            b.state(["disabled"])
        status.set(label + " ...")

        def worker():
            try:
                res = work()
            except Exception as e:           # never leave the window stuck in "busy"
                res = e
            jobs.put((done, res))
        threading.Thread(target=worker, daemon=True).start()

    def pump():
        try:
            while True:
                done, res = jobs.get_nowait()
                busy["on"] = False
                for b in net_buttons:
                    b.state(["!disabled"])
                if isinstance(res, Exception):
                    status.set("Error: %s" % res)
                else:
                    done(res)
        except queue.Empty:
            pass
        root.after(100, pump)

    def copy(text):
        root.clipboard_clear()
        root.clipboard_append(text)
        status.set("Copied to clipboard.")
        root.after(2500, lambda: status.set(""))

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=10, pady=(10, 4))

    # ---------------------------------------------------------- password ---
    p1 = ttk.Frame(nb, padding=14)
    nb.add(p1, text="  New password  ")
    p1.columnconfigure(1, weight=1)
    ttk.Label(p1, text="Issue a password. It activates ONE PC, the first one it is used on.", style="Dim.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
    ttk.Label(p1, text="Password:").grid(row=1, column=0, sticky="w")
    pw_var = tk.StringVar()
    ttk.Entry(p1, textvariable=pw_var, width=40, font=("Consolas", 10)).grid(row=1, column=1, sticky="we", padx=6)
    ttk.Button(p1, text="Suggest", command=lambda: pw_var.set(suggest_password())).grid(row=1, column=2)
    ttk.Label(p1, text="Note (who):").grid(row=2, column=0, sticky="w", pady=(6, 0))
    pw_note = tk.StringVar()
    ttk.Entry(p1, textvariable=pw_note, width=40).grid(row=2, column=1, sticky="we", padx=6, pady=(6, 0))
    pw_out = rt.text_box(p1, height=6, font=("Consolas", 9), wrap="none", state="disabled")
    pw_out.grid(row=4, column=0, columnspan=3, sticky="we", pady=(12, 6))
    pw_row = {"text": ""}

    def gen_pw():
        pw = pw_var.get().strip()
        if not pw:
            status.set("Type or suggest a password first.")
            return
        h = rs.password_hash(pw)
        pw_row["text"] = row_text(h, "password", pw_note.get().strip())
        show(pw_out, "Give the user this password (case-sensitive):\n  %s\n\nPaste this row into the licence sheet (one value per column):\n%s\n%s" % (pw, SHEET_HEADER, pw_row["text"]))

    btns = ttk.Frame(p1)
    btns.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Button(btns, text="Generate", command=gen_pw).pack(side="left")
    ttk.Button(btns, text="Copy sheet row", command=lambda: pw_row["text"] and copy(pw_row["text"])).pack(side="left", padx=(8, 0))
    ttk.Button(btns, text="Copy password", command=lambda: pw_var.get().strip() and copy(pw_var.get().strip())).pack(side="left", padx=(8, 0))

    def add_pw():
        pw = pw_var.get().strip()
        if not pw:
            status.set("Type or suggest a password first.")
            return
        gen_pw()
        h, note = rs.password_hash(pw), pw_note.get().strip()
        run_bg(lambda: api.add_row(h, "password", note, product="Revit Status"),
               lambda r: status.set("Added to the licence sheet (row %s). Give the user the password." % r.get("row")
                                    if r.get("ok") else "Sheet: %s" % r.get("error")),
               "Adding the row to the licence sheet")

    b = ttk.Button(btns, text="Add to sheet", command=add_pw)
    b.pack(side="left", padx=(16, 0))
    net_buttons.append(b)

    # --------------------------------------------------------------- key ---
    p2 = ttk.Frame(nb, padding=14)
    nb.add(p2, text="  Key for a Machine ID  ")
    p2.columnconfigure(1, weight=1)
    ttk.Label(p2, text="A user's PC shows its Machine ID in the licence popup and the app footer. The key works only there.", style="Dim.TLabel", wraplength=680).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
    ttk.Label(p2, text="Machine ID:").grid(row=1, column=0, sticky="w")
    mid_var = tk.StringVar()
    ttk.Entry(p2, textvariable=mid_var, width=28, font=("Consolas", 10)).grid(row=1, column=1, sticky="w", padx=6)
    ttk.Button(p2, text="This PC", command=lambda: mid_var.set(rs.machine_id())).grid(row=1, column=2, sticky="w")
    ttk.Label(p2, text="Note (who):").grid(row=2, column=0, sticky="w", pady=(6, 0))
    key_note = tk.StringVar()
    ttk.Entry(p2, textvariable=key_note, width=40).grid(row=2, column=1, sticky="we", padx=6, pady=(6, 0))
    key_out = rt.text_box(p2, height=6, font=("Consolas", 9), wrap="none", state="disabled")
    key_out.grid(row=4, column=0, columnspan=3, sticky="we", pady=(12, 6))
    key_res = {"key": "", "row": "", "mid": ""}

    def gen_key():
        mid = mid_var.get().strip().upper().replace(" ", "")
        compact = mid.replace("-", "")
        if len(compact) != 16 or not all(c in "0123456789ABCDEF" for c in compact):
            key_res.update(key="", row="", mid="")
            status.set("A Machine ID looks like XXXX-XXXX-XXXX-XXXX (16 hex characters).")
            return
        mid = "-".join(compact[i:i + 4] for i in range(0, 16, 4))
        k = rs.machine_key(mid)
        key_res.update(key=k, mid=mid, row=row_text(k.replace("-", ""), "key", key_note.get().strip(), mid))
        show(key_out, "Email the user this key (works only on %s):\n  %s\n\nPaste this row into the licence sheet:\n%s\n%s" % (mid, k, SHEET_HEADER, key_res["row"]))

    kb = ttk.Frame(p2)
    kb.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Button(kb, text="Generate", command=gen_key).pack(side="left")
    ttk.Button(kb, text="Copy sheet row", command=lambda: key_res["row"] and copy(key_res["row"])).pack(side="left", padx=(8, 0))
    ttk.Button(kb, text="Copy key", command=lambda: key_res["key"] and copy(key_res["key"])).pack(side="left", padx=(8, 0))

    def add_key():
        gen_key()
        if not key_res["key"]:
            return
        k, mid, note = key_res["key"].replace("-", ""), key_res["mid"], key_note.get().strip()
        run_bg(lambda: api.add_row(k, "key", note, mid, product="Revit Status"),
               lambda r: status.set("Added to the licence sheet (row %s). Email the user the key." % r.get("row")
                                    if r.get("ok") else "Sheet: %s" % r.get("error")),
               "Adding the row to the licence sheet")

    b = ttk.Button(kb, text="Add to sheet", command=add_key)
    b.pack(side="left", padx=(16, 0))
    net_buttons.append(b)

    # ------------------------------------------------------------- sheet ---
    p3 = ttk.Frame(nb, padding=14)
    nb.add(p3, text="  Live sheet  ")
    p3.columnconfigure(0, weight=1)
    p3.rowconfigure(2, weight=1)
    top3 = ttk.Frame(p3)
    top3.grid(row=0, column=0, sticky="we")
    b = ttk.Button(top3, text="Fetch now", command=lambda: load_sheet())
    b.pack(side="left")
    net_buttons.append(b)

    def _selected_key():
        sel = tree.selection()
        if not sel:
            status.set("Select a row first.")
            return None
        return tree.item(sel[0], "values")[0]

    def do(action):
        k = _selected_key()
        if not k:
            return

        def done(r):
            status.set(("%s: ok" % action) if r.get("ok") else "Sheet: %s" % r.get("error"))
            if r.get("ok"):
                load_sheet()
        run_bg(lambda: api.call(action, key=k), done, "%s %s" % (action.capitalize(), k))

    for text, action in (("Revoke selected", "revoke"), ("Re-activate", "activate"), ("Delete row", "delete")):
        b = ttk.Button(top3, text=text, command=lambda a=action: do(a))
        b.pack(side="left", padx=(8, 0))
        net_buttons.append(b)
    sheet_info = tk.StringVar(value="Not fetched yet.")
    ttk.Label(p3, textvariable=sheet_info, style="Dim.TLabel", wraplength=700).grid(row=3, column=0, sticky="w", pady=(6, 0))
    chk = ttk.Frame(p3)
    chk.grid(row=1, column=0, sticky="we", pady=(8, 6))
    ttk.Label(chk, text="Check a password:").pack(side="left")
    chk_var = tk.StringVar()
    ttk.Entry(chk, textvariable=chk_var, width=28, font=("Consolas", 10)).pack(side="left", padx=6)
    chk_res = tk.StringVar()

    def check_pw():
        h = rs.password_hash(chk_var.get().strip())

        def verdict(rows):
            if rows is None:
                chk_res.set("sheet unreachable")
                return
            r = rows.get(h)
            chk_res.set("ACTIVE" if r and r["status"] == "active" else ("revoked" if r else "not listed"))
        if sheet_rows["rows"] is not None:
            verdict(sheet_rows["rows"])
        else:
            load_sheet(then=verdict)

    b = ttk.Button(chk, text="Check", command=check_pw)
    b.pack(side="left")
    net_buttons.append(b)
    ttk.Label(chk, textvariable=chk_res, style="Mono.TLabel").pack(side="left", padx=(10, 0))
    cols = ("key", "type", "status", "mid", "note")
    tree = ttk.Treeview(p3, columns=cols, show="headings")
    for c, txt, w in (("key", "Key", 250), ("type", "Type", 70), ("status", "Status", 70), ("mid", "Machine_ID", 150), ("note", "Note", 160)):
        tree.heading(c, text=txt)
        tree.column(c, width=w, anchor="w", stretch=(c in ("key", "note")))
    tree.grid(row=2, column=0, sticky="nsew")
    rt.tag_tree(tree)
    sheet_rows = {"rows": None}

    def load_sheet(then=None):
        def done(res):
            rows, source, err = res
            sheet_rows["rows"] = rows
            tree.delete(*tree.get_children())
            if rows is None:
                sheet_info.set("Unreachable: %s" % err)
                status.set("")
            else:
                n_act = sum(1 for r in rows.values() if r["status"] == "active")
                sheet_info.set("%s: %d rows, %d active%s" % (source, len(rows), n_act, ("  (%s)" % err) if err else ""))
                status.set("Fetched.")
                for k, r in rows.items():
                    tree.insert("", "end", values=(k, r["type"], r["status"], r["machine_id"], r["note"]), tags=(r["status"],))
            if then:
                then(rows)
        run_bg(fetch_rows, done, "Fetching the licence sheet")

    # ------------------------------------------------------------ footer ---
    status = tk.StringVar(value="")
    foot = ttk.Frame(root, padding=(10, 0, 10, 8))
    foot.pack(fill="x")
    ttk.Button(foot, text="Open licence sheet", command=lambda: webbrowser.open(api.LICENCE_SHEET_URL)).pack(side="left")
    ttk.Label(foot, textvariable=status, style="Dim.TLabel").pack(side="left", padx=(10, 0))
    ttk.Label(foot, text=rs.COPYRIGHT, style="Faint.TLabel").pack(side="right")
    rt.theme_picker(foot).pack(side="right", padx=(0, 16))

    def show(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    root.after(100, pump)
    root.mainloop()


if __name__ == "__main__":
    main()

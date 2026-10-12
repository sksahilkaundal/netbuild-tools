# -*- coding: utf-8 -*-
"""
BUA Licence Admin - DEVELOPER ONLY, never ship or share (it can mint keys).

  * KILL SWITCH: one button disables every copy of BUA Workbook Builder on every PC
    (sets the "BUA-KILL-SWITCH" row of the licence sheet to revoked); Re-enable undoes it.
    Copies stop at their next start or next Run - usually within 1-10 min (Google's
    publish delay); a copy kept offline stops when its 3-day grace runs out.
  * Issue a key for a customer's Machine ID (they see it in the app's Licence dialog), or a
    one-PC password (no Machine ID needed: it locks itself to the first PC that activates it).
  * Revoke / re-activate one PC's key or password; release a password so it can move to a new PC.

Writes go through the licence-sheet Apps Script (revitstatus_sheet_client.py +
revitstatus_sheet_api.json). While that script is still bound to the retired sheet,
every write falls back to opening the licence sheet with the exact edit to make.
Run:  pythonw BuaLicenceAdmin.pyw   (from this scripts folder)
"""
import os
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import revittools_theme as rt
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "design"))
    import revittools_theme as rt

import bua_license as lic
import revitstatus_sheet_client as sc

APP = "BUA Licence Admin"
VERSION = "1.0"


def sheet_write(action, key, **fields):
    """(ok, message). Tries the Sheet API; on any failure returns ok=False with the reason."""
    r = sc.call(action, key=key, **fields)
    if r.get("ok"):
        return True, "Sheet updated through the API."
    return False, r.get("error") or "no reply"


class Admin:
    def __init__(self, root):
        self.root = root
        root.title(APP)
        root.geometry("900x640")
        root.minsize(760, 520)
        rt.apply(root)
        rt.footer(root, APP, VERSION, lic.COPYRIGHT, right_text="Developer only - do not share")
        self.rows = {}
        self._build()
        self.refresh()

    # ---------------------------------------------------------------- layout
    def _build(self):
        top = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text="BUA Workbook Builder - licence control", style="Big.TLabel").pack(side="left")
        rt.theme_picker(top).pack(side="right")

        ks = ttk.LabelFrame(self.root, text="  Kill switch (all copies, all PCs)  ", padding=12)
        ks.pack(fill="x", padx=12, pady=(10, 0))
        self.kill_state = ttk.Label(ks, text="Checking...", font=rt.FONTS["ui-title"])
        self.kill_state.grid(row=0, column=0, columnspan=4, sticky="w")
        self.kill_detail = ttk.Label(ks, text="", style="Dim.TLabel", wraplength=820)
        self.kill_detail.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 8))
        self.kill_btn = ttk.Button(ks, text="KILL ALL COPIES", command=self.kill)
        self.kill_btn.grid(row=2, column=0, sticky="w")
        self.enable_btn = ttk.Button(ks, text="Re-enable all copies", command=self.enable)
        self.enable_btn.grid(row=2, column=1, sticky="w", padx=8)
        ttk.Button(ks, text="Refresh", command=self.refresh).grid(row=2, column=2, sticky="w")
        ttk.Button(ks, text="Open licence sheet", command=lambda: webbrowser.open(sc.LICENCE_SHEET_URL)).grid(
            row=2, column=3, sticky="w", padx=8)

        kg = ttk.LabelFrame(self.root, text="  Issue a key (needs Machine ID) or a one-PC password  ", padding=12)
        kg.pack(fill="x", padx=12, pady=(10, 0))
        kg.columnconfigure(1, weight=1)
        ttk.Label(kg, text="Machine ID").grid(row=0, column=0, sticky="w")
        self.mid_var = tk.StringVar()
        ttk.Entry(kg, textvariable=self.mid_var, width=26).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(kg, text="This PC", command=lambda: self.mid_var.set(lic.machine_id())).grid(row=0, column=2, sticky="w")
        ttk.Label(kg, text="Note (who / which PC)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.note_var = tk.StringVar()
        ttk.Entry(kg, textvariable=self.note_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=8, pady=(6, 0))
        btns = ttk.Frame(kg)
        btns.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(btns, text="Generate key", command=self.generate).pack(side="left")
        ttk.Button(btns, text="Copy key", command=lambda: self._copy(self.key_var.get())).pack(side="left", padx=8)
        ttk.Button(btns, text="Copy sheet row", command=lambda: self._copy(self.row_var.get())).pack(side="left")
        ttk.Button(btns, text="Add to sheet", command=self.add_key).pack(side="left", padx=8)
        ttk.Button(btns, text="Generate one-PC password", command=self.new_password).pack(side="left", padx=(16, 0))
        self.key_var = tk.StringVar()
        self.row_var = tk.StringVar()
        ttk.Label(kg, textvariable=self.key_var, style="Mono.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        pcs = ttk.LabelFrame(self.root, text="  BUA keys and passwords (live from the sheet)  ", padding=12)
        pcs.pack(fill="both", expand=True, padx=12, pady=10)
        self.tree = ttk.Treeview(pcs, columns=("kind", "mid", "status", "note"), show="headings", height=6)
        for col, txt, w in (("kind", "Type", 80), ("mid", "Locked to PC (Machine ID)", 190), ("status", "Status", 80),
                            ("note", "Note", 400)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        rt.on_change(self.tree, lambda p: (self.tree.tag_configure("active", foreground=p["state-connected"]),
                                           self.tree.tag_configure("revoked", foreground=p["state-down"])))
        pb = ttk.Frame(pcs)
        pb.pack(fill="x", pady=(8, 0))
        ttk.Button(pb, text="Revoke selected", command=lambda: self.set_selected("revoke")).pack(side="left")
        ttk.Button(pb, text="Re-activate selected", command=lambda: self.set_selected("activate")).pack(side="left", padx=8)
        ttk.Button(pb, text="Release password (move to a new PC)", command=self.release_selected).pack(side="left")
        self.status = ttk.Label(pb, text="", style="Dim.TLabel")
        self.status.pack(side="left", padx=8)

    # ---------------------------------------------------------------- helpers
    def _copy(self, text):
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status.configure(text="Copied.")

    def _manual(self, why, instruction):
        messagebox.showinfo(APP, "Could not write through the Sheet API:\n%s\n\nDo it by hand - the licence sheet opens now:\n\n%s"
                            % (why, instruction))
        webbrowser.open(sc.LICENCE_SHEET_URL)

    def _bg(self, fn, done):
        """Run fn off the UI thread; done(result) runs on the UI thread (workers never touch Tk)."""
        import queue
        q = queue.Queue()
        threading.Thread(target=lambda: q.put(fn()), daemon=True).start()

        def poll():
            try:
                res = q.get_nowait()
            except queue.Empty:
                self.root.after(100, poll)
                return
            done(res)
        self.root.after(100, poll)

    # ---------------------------------------------------------------- live state
    def refresh(self):
        self.kill_state.configure(text="Checking the sheet...", style="TLabel")
        self._bg(lambda: (lic.fetch_allow_list(), lic.fetch_kill_live(), sc.list_rows()), self._show)

    def _show(self, res):
        (rows, src, err), live, api = res
        self.rows = rows or {}
        state = live or lic.kill_row_state(rows)          # live answer = what copies see right now
        if rows is None and live is None:
            self.kill_state.configure(text="Sheet unreachable", style=rt.style_for("state-partial"))
            self.kill_detail.configure(text=err or "")
        elif state == "killed":
            self.kill_state.configure(text="KILLED - every copy is disabled", style=rt.style_for("state-down"))
            self.kill_detail.configure(text="Copies refuse to start or run. Press Re-enable to undo.")
        elif state == "active":
            self.kill_state.configure(text="ACTIVE - licensed copies run normally", style=rt.style_for("state-connected"))
            self.kill_detail.configure(text="Pressing KILL disables every copy at its next start or next Run - "
                                            "instantly (offline copies within %d days)." % lic.LICENSE_CACHE_GRACE_DAYS)
        else:
            self.kill_state.configure(text="NOT SET UP - no kill row in the sheet yet", style=rt.style_for("state-partial"))
            self.kill_detail.configure(text="Copies run normally. Add the kill row once (KILL adds it for you when the "
                                            "Sheet API works; otherwise paste the row it shows).")
        self.tree.delete(*self.tree.get_children())
        if api.get("ok"):
            items = [(x["key"], x) for x in api.get("rows", [])]
        else:
            items = [(k, dict(v, key=k)) for k, v in (rows or {}).items()]
        for key, r in sorted(items):
            typ, mid = r.get("type", "").lower(), r.get("machine_id", "")
            if typ not in ("key", "password"):
                continue
            ours = r.get("product", "") == lic.PRODUCT
            if not ours and typ == "key" and mid:
                try:
                    ours = lic.machine_key(mid).replace("-", "") == key.replace("-", "").upper()
                except Exception:
                    ours = False
            if not ours:
                continue                          # another product's row
            shown = mid or ("(not used yet)" if typ == "password" else "")
            self.tree.insert("", "end", iid=key, values=(typ, shown, r.get("status", ""), r.get("note", "")),
                             tags=("active" if r.get("status") == "active" else "revoked",))
        self.status.configure(text="Sheet: %s%s" % (src, (" (%s)" % err) if err else ""))

    # ---------------------------------------------------------------- kill switch
    def kill(self):
        if not messagebox.askyesno(APP, "Disable EVERY copy of BUA Workbook Builder on every PC?\n\n"
                                        "Nobody can use it until you press Re-enable.", icon="warning"):
            return
        self._set_kill("revoked")

    def enable(self):
        self._set_kill("active")

    def _set_kill(self, status):
        missing = lic.kill_row_state(self.rows) == "missing"

        def do():
            if missing:
                ok, msg = sheet_write("add", lic.KILL_KEY, type="kill", note="KILL SWITCH - set Status to revoked to disable ALL copies", product=lic.PRODUCT)
                if not ok:
                    return ok, msg
            return sheet_write("revoke" if status == "revoked" else "activate", lic.KILL_KEY)

        def done(res):
            ok, msg = res
            if ok:
                self.status.configure(text="Kill switch set to %s - copies see it at their next start or Run." % status)
                self.root.after(3000, self.refresh)
                return
            if missing:
                row = "\t".join([lic.KILL_KEY, "kill", status, "", "KILL SWITCH - set Status to revoked to disable ALL copies", lic.PRODUCT])
                self._copy(row)
                self._manual(msg, "Paste a new row (already on your clipboard, TAB-separated):\n%s" % row)
            else:
                self._copy(status)
                self._manual(msg, "In the row whose Key is %s, set Status to:  %s\n(also on your clipboard)"
                             % (lic.KILL_KEY, status))
        self.status.configure(text="Writing to the sheet...")
        self._bg(do, done)

    # ---------------------------------------------------------------- keys
    def generate(self):
        mid = self.mid_var.get().strip().upper()
        if len(mid.replace("-", "")) != 16:
            messagebox.showwarning(APP, "Machine ID must look like XXXX-XXXX-XXXX-XXXX.")
            return
        key = lic.machine_key(mid)
        note = self.note_var.get().strip() or "BUA Workbook Builder"
        self.key_var.set("Key for %s:   %s" % (mid, key))
        self.row_var.set("\t".join([key, "key", "active", mid, note, lic.PRODUCT]))
        self._copy(key)
        self.status.configure(text="Key generated and copied. Send it to the user, then 'Add to sheet'.")

    def add_key(self):
        row = self.row_var.get()
        if not row:
            self.generate()
            row = self.row_var.get()
            if not row:
                return
        key, typ, _st, mid, note, _prod = row.split("\t")

        def done(res):
            ok, msg = res
            if ok:
                self.status.configure(text="Key added to the sheet.")
                self.root.after(3000, self.refresh)
            else:
                self._copy(row)
                self._manual(msg, "Paste this row (already on your clipboard, TAB-separated):\n%s" % row)
        self._bg(lambda: sheet_write("add", key, type=typ, note=note, machine_id=mid, product=lic.PRODUCT), done)

    def set_selected(self, action):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP, "Select a row in the list first.")
            return
        key = sel[0]
        mid = self.tree.set(key, "mid")
        if action == "revoke" and not messagebox.askyesno(APP, "Revoke this %s (%s)?" % (self.tree.set(key, "kind"), mid)):
            return
        status = "revoked" if action == "revoke" else "active"

        def done(res):
            ok, msg = res
            if ok:
                self.status.configure(text="%s set to %s." % (mid, status))
                self.root.after(3000, self.refresh)
            else:
                self._copy(status)
                self._manual(msg, "In the row with Machine_ID %s, set Status to:  %s" % (mid, status))
        self._bg(lambda: sheet_write(action, key), done)

    def release_selected(self):
        sel = self.tree.selection()
        if not sel or self.tree.set(sel[0], "kind") != "password":
            messagebox.showinfo(APP, "Select a password row first.")
            return
        key = sel[0]
        if not messagebox.askyesno(APP, "Release this password from %s?\n\nThat PC stops working at its next "
                                        "start, and the next PC to enter the password takes it over."
                                        % self.tree.set(key, "mid")):
            return

        def done(res):
            ok, msg = res
            self.status.configure(text="Password released." if ok else "Sheet: %s" % msg)
            self.root.after(2000, self.refresh)
        self._bg(lambda: sheet_write("set", key, machine_id=""), done)

    def new_password(self):
        import secrets
        import string
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14))
        note = self.note_var.get().strip() or "BUA - one-PC password"

        def done(res):
            ok, msg = res
            if ok:
                self.key_var.set("Password (works on the first PC that uses it):   %s" % pw)
                self._copy(pw)
                self.status.configure(text="Password added to the sheet and copied - send it to the user.")
                self.root.after(2000, self.refresh)
            else:
                self.status.configure(text="Could not add the password: %s" % msg)
        self._bg(lambda: sheet_write("add", lic.password_hash(pw), type="password", note=note, machine_id="",
                                     product=lic.PRODUCT), done)


if __name__ == "__main__":
    r = tk.Tk()
    Admin(r)
    r.mainloop()

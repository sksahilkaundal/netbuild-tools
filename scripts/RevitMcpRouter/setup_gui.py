# -*- coding: utf-8 -*-
"""Revit MCP Router - Setup desktop app (compiled to a .pyd for release; RevitMcpRouterSetup.pyw is the stub).

Tabs: Setup (check / install / restore / find Revits) and Licence (status, Machine ID,
developer contact, copyright). No implementation details are shown to the customer.
"""
import os
import queue
import sys
import threading
import traceback
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import install_revit_mcp_router as inst
import nb_license

APP = "Revit MCP Router"
VERSION = "1.3.6"
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))


def _mailto(subject, body):
    from urllib.parse import quote
    webbrowser.open("mailto:%s?subject=%s&body=%s" % (nb_license.DEVELOPER_EMAIL, quote(subject), quote(body)))


class SetupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("%s  v%s" % (APP, VERSION))
        self.geometry("880x620")
        self.minsize(760, 500)
        self.rt = nb_license._rt()
        self.rt.apply(self)                  # saved choice: As per system / Light / Dark
        self.q = queue.Queue()
        self.busy = False
        inst.LOG = self._log_threadsafe
        self._build()
        self.after(150, self._pump)
        self.after(200, self._gate)

    def _gate(self):
        self.withdraw()
        if not nb_license.ensure_activated(self):
            self.destroy()
            return
        self.deiconify()
        self.refresh_licence()
        self._run(self.do_check)

    # ------------------------------------------------------------------ UI
    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.tab_setup = ttk.Frame(nb)
        self.tab_lic = ttk.Frame(nb)
        nb.add(self.tab_setup, text="  Setup  ")
        nb.add(self.tab_lic, text="  Licence  ")
        self._build_setup(self.tab_setup)
        self._build_licence(self.tab_lic)
        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(foot, text="%s v%s   %s" % (APP, VERSION, nb_license.COPYRIGHT), style="Dim.TLabel").pack(side="left")
        self.lic_label = ttk.Label(foot, text="", style="Dim.TLabel")
        self.lic_label.pack(side="right")
        self.rt.theme_picker(foot).pack(side="right", padx=(0, 16))

    def _build_setup(self, root):
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Revit connector:").grid(row=0, column=0, sticky="w")
        self.ext_var = tk.StringVar(value=inst.EXT_DIR)
        self.ext_state = ttk.Label(top, text="")
        self.ext_state.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(top, text="Change folder…", command=self._browse_ext).grid(row=0, column=2)
        self._update_ext_state()
        ttk.Label(top, text="Claude config file:").grid(row=1, column=0, sticky="w")
        self.cfg_var = tk.StringVar(value=inst.CLAUDE_JSON)
        ttk.Entry(top, textvariable=self.cfg_var, width=90).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Label(top, text="Add a project folder (optional):").grid(row=2, column=0, sticky="w")
        self.proj_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.proj_var, width=90).grid(row=2, column=1, sticky="we", padx=4)
        ttk.Button(top, text="Browse…", command=self._browse_proj).grid(row=2, column=2)
        top.columnconfigure(1, weight=1)

        bar = ttk.Frame(root)
        bar.pack(fill="x", **pad)
        self.btns = []
        for text, fn in (("Check", self.do_check), ("Install / Reset", self.do_install),
                         ("Restore default connection", self.do_restore), ("Find Revit sessions", self.do_test)):
            b = ttk.Button(bar, text=text, command=lambda f=fn: self._run(f))
            b.pack(side="left", padx=4)
            self.btns.append(b)
        self.status = ttk.Label(bar, text="", style="Dim.TLabel")
        self.status.pack(side="left", padx=12)

        self.log = self.rt.console(root, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=4)
        self.rt.on_change(self.log, lambda p: (self.log.tag_config("fail", foreground=p["console-err"]),
                                               self.log.tag_config("head", foreground=p["console-head"])))
        ttk.Label(root, text="After Install / Reset: start a NEW Claude Code session, then use revit_list_sessions / revit_select_session.",
                  style="Dim.TLabel").pack(anchor="w", padx=10, pady=(0, 6))

    def _build_licence(self, root):
        f = ttk.Frame(root, padding=16)
        f.pack(fill="both", expand=True)
        self.lic_state = ttk.Label(f, text="", style="Big.TLabel")
        self.lic_state.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
        self.lic_detail = ttk.Label(f, text="", style="Dim.TLabel", wraplength=700, justify="left")
        self.lic_detail.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(f, text="Machine ID:").grid(row=2, column=0, sticky="w", pady=3)
        self.mid_var = tk.StringVar(value=nb_license.machine_id())
        ttk.Entry(f, textvariable=self.mid_var, width=26, state="readonly", font=("Consolas", 11)).grid(row=2, column=1, sticky="w")
        ttk.Button(f, text="Copy", command=lambda: self._copy(self.mid_var.get())).grid(row=2, column=2, sticky="w", padx=6)
        ttk.Label(f, text="Computer:").grid(row=3, column=0, sticky="w", pady=3)
        self.pc_var = tk.StringVar()
        ttk.Label(f, textvariable=self.pc_var).grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Label(f, text="Activated:").grid(row=4, column=0, sticky="w", pady=3)
        self.act_var = tk.StringVar()
        ttk.Label(f, textvariable=self.act_var).grid(row=4, column=1, columnspan=2, sticky="w")
        ttk.Label(f, text="Licence terms:").grid(row=5, column=0, sticky="nw", pady=3)
        ttk.Label(f, text="Licensed for use on this computer only (the Machine ID above). Keys are issued per machine by the developer "
                          "and are not transferable. Redistribution, copying or reverse engineering of this software is prohibited.",
                  wraplength=560, justify="left").grid(row=5, column=1, columnspan=2, sticky="w")

        ttk.Separator(f, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="we", pady=14)
        ttk.Label(f, text="Developer", style="Big.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Name:").grid(row=8, column=0, sticky="w", pady=3)
        ttk.Label(f, text=nb_license.DEVELOPER_NAME).grid(row=8, column=1, columnspan=2, sticky="w")
        ttk.Label(f, text="Email:").grid(row=9, column=0, sticky="w", pady=3)
        ttk.Label(f, text=nb_license.DEVELOPER_EMAIL).grid(row=9, column=1, sticky="w")
        ttk.Button(f, text="Copy", command=lambda: self._copy(nb_license.DEVELOPER_EMAIL)).grid(row=9, column=2, sticky="w", padx=6)
        ttk.Label(f, text="For a licence key, a transfer to a new computer, or support, email the developer with your Machine ID.",
                  style="Dim.TLabel", wraplength=560, justify="left").grid(row=10, column=1, columnspan=2, sticky="w", pady=(0, 8))

        btns = ttk.Frame(f)
        btns.grid(row=11, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(btns, text="Email developer", command=self._email_dev).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Enter / change key…", command=self._change_key).pack(side="left", padx=6)
        ttk.Button(btns, text="Re-check licence", command=self.refresh_licence).pack(side="left", padx=6)

        ttk.Separator(f, orient="horizontal").grid(row=12, column=0, columnspan=3, sticky="we", pady=14)
        ttk.Label(f, text="%s  v%s" % (APP, VERSION)).grid(row=13, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=nb_license.COPYRIGHT, style="Dim.TLabel").grid(row=14, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="This software and its licence keys are the property of the developer. Unauthorised use is prohibited.",
                  style="Dim.TLabel", wraplength=700, justify="left").grid(row=15, column=0, columnspan=3, sticky="w")
        f.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------ licence tab actions
    def refresh_licence(self):
        state, info = nb_license.license_state()
        mid = nb_license.machine_id()
        mine = [a for a in nb_license.load_activations() if a.get("machine_id") == mid]
        lic_style = self.rt.licence_style(state)
        text = {"ok": "Licensed", "unactivated": "Not activated", "locked": "Licence belongs to another computer",
                "revoked": "Licence revoked", "taken": "Password in use on another PC",
                "offline": "Licence check pending (offline)"}.get(state, state)
        self.lic_state.configure(text=text, style=lic_style, font=self.rt.FONTS["ui-title"])
        mode = (info or {}).get("mode")
        detail = {"fetched": "Verified online just now.", "cache": "Verified from the last online check (offline grace period).",
                  "offline": "Offline licence.", "unverified": "Could not reach the licence server; using the built-in licence."}.get(mode, "")
        if state == "offline":
            detail = (info or {}).get("error", "")
        elif state == "revoked":
            detail = "This computer's licence has been revoked. Contact the developer."
        elif state == "taken":
            detail = "The password used here is now activated on another PC. Each password works on one PC only."
        elif state == "unactivated":
            detail = "Enter your password or key to activate this computer."
        self.lic_detail.configure(text=detail)
        import socket
        self.pc_var.set(socket.gethostname())
        if mine:
            a = mine[0]
            self.act_var.set("%s  (%s)" % (a.get("activated", "?"), "machine key" if a.get("hash", "").startswith("key:") else "password"))
        else:
            self.act_var.set("-")
        self.lic_label.configure(text=nb_license.status_text())

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text="copied")

    def _email_dev(self):
        _mailto("%s licence - Machine ID %s" % (APP, nb_license.machine_id()),
                "Hello,\n\nProduct: %s v%s\nMachine ID: %s\nComputer: %s\n\n" % (APP, VERSION, nb_license.machine_id(), self.pc_var.get()))

    def _change_key(self):
        nb_license.activation_dialog(self)
        self.refresh_licence()

    # ------------------------------------------------------------------ setup tab plumbing
    def _update_ext_state(self):
        ok = os.path.isfile(os.path.join(self.ext_var.get(), "tools", "__init__.py"))
        self.ext_state.configure(text="detected" if ok else "NOT FOUND - install the Revit MCP connector add-in, or pick its folder",
                                 style=self.rt.style_for("licence-ok" if ok else "licence-error"))

    def _browse_ext(self):
        d = filedialog.askdirectory(title="Revit connector folder", initialdir=self.ext_var.get())
        if d:
            self.ext_var.set(d)
            self._update_ext_state()

    def _browse_proj(self):
        d = filedialog.askdirectory(title="Project folder to connect to Revit")
        if d:
            self.proj_var.set(d)

    def _log_threadsafe(self, msg):
        self.q.put(str(msg))

    def _pump(self):
        try:
            while True:
                self._append(self.q.get_nowait())
        except queue.Empty:
            pass
        self.after(150, self._pump)

    def _append(self, msg):
        tag = "ok" if msg.startswith("ok ") else "fail" if msg.startswith("FAIL") else "head" if msg.startswith("==") else None
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _apply_paths(self):
        inst.EXT_DIR = os.path.normpath(self.ext_var.get().strip())
        inst.CLAUDE_JSON = os.path.normpath(self.cfg_var.get().strip())
        if FROZEN:
            installed = os.path.join(inst.INSTALL_ROOT, "app-" + VERSION)
            inst.use_exe_bridge(installed if os.path.isfile(os.path.join(installed, "RevitMcpBridge.exe")) else APP_DIR)
        else:
            inst.use_source_bridge(APP_DIR)

    def _run(self, fn):
        if self.busy:
            return
        self.busy = True
        for b in self.btns:
            b.configure(state="disabled")
        self.status.configure(text="working…")

        def worker():
            try:
                self._apply_paths()
                fn()
            except inst.InstallError as e:
                self.q.put("FAIL  " + str(e))
            except Exception:
                self.q.put("FAIL  unexpected error:\n" + traceback.format_exc())
            finally:
                self.q.put("__done__")
        threading.Thread(target=worker, daemon=True).start()
        self.after(150, self._await_done)

    def _await_done(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg == "__done__":
                    self.busy = False
                    for b in self.btns:
                        b.configure(state="normal")
                    self.status.configure(text="ready")
                    return
                self._append(msg)
        except queue.Empty:
            pass
        self.after(150, self._await_done)

    # ------------------------------------------------------------------ actions
    def do_check(self):
        self.q.put("== Check")
        inst.check_files()
        inst.bridge_check()
        inst.report(inst.load_config())
        self.q.put("ok    check complete")

    def do_install(self):
        self.q.put("== Install / Reset")
        dest = inst.install_app(APP_DIR, VERSION) if FROZEN else None
        inst.check_files()
        inst.bridge_check()
        cfg = inst.load_config()
        extra = [self.proj_var.get().strip()] if self.proj_var.get().strip() else []
        changes = inst.plan(cfg, False, extra)
        if not changes:
            self.q.put("ok    every Revit connection already routed - nothing to change")
        else:
            for label, entry, want in changes:
                self.q.put("      %s" % label)
            inst.apply(cfg, changes)
        inst.write_config()
        if inst.codex_present():
            inst.codex_apply()
        if dest:
            inst.cleanup_old_apps(dest)
        inst.report(inst.load_config())
        self.q.put("ok    done - start a NEW Claude Code session for it to take effect")
        self.after(0, lambda: messagebox.showinfo(APP, "Installed.\n\nStart a NEW Claude Code session, then run revit_list_sessions."))

    def do_restore(self):
        self.q.put("== Restore default connection")
        cfg = inst.load_config()
        changes = inst.plan(cfg, True, [])
        if not changes:
            self.q.put("ok    nothing to restore")
        else:
            inst.apply(cfg, changes)
        if inst.codex_present():
            inst.codex_apply(uninstall=True)
        inst.report(inst.load_config())

    def do_test(self):
        self.q.put("== Find Revit sessions")
        inst.bridge_check()


def selftest():
    out = os.path.join(APP_DIR, "selftest_result.txt")
    lines = []
    inst.LOG = lines.append
    try:
        inst.EXT_DIR = os.environ.get("REVIT_MCP_EXTENSION_DIR") or inst.EXT_DIR
        if FROZEN:
            inst.use_exe_bridge(APP_DIR)
        else:
            inst.use_source_bridge(APP_DIR)
        lines.append("licence: " + nb_license.status_text())
        inst.check_files()
        inst.bridge_check()
        inst.report(inst.load_config())
        lines.append("SELFTEST OK")
    except Exception as e:
        lines.append("SELFTEST FAIL: %s" % e)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main(argv):
    if "--selftest" in argv:
        selftest()
        return 0
    SetupApp().mainloop()
    return 0

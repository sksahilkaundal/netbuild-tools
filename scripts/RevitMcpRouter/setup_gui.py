# -*- coding: utf-8 -*-
"""Revit MCP Router - Setup desktop app (compiled to a .pyd for release; RevitMcpRouterSetup.pyw is the stub).

Tabs: Setup (check / install / restore / find Revits), Licence (the licensing page: product, owner,
website, licence agreement, key status, Machine ID, activation, developer contact) and About
(product, publisher, requirements).
No implementation details are shown to the customer.
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

APP = nb_license.PRODUCT_DISPLAY      # "Revit MCP Router by Netbuild" (display only; paths use their own names)
VERSION = "1.3.7"
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))

DESCRIPTION = ("Lets Claude Code (or another MCP client) drive any of several open Revit sessions on this computer, "
               "chosen per chat session by document, Revit version or port. It follows a document across a Revit "
               "restart and refuses to guess when the choice is ambiguous, so a command never runs on the wrong model.")

REQUIREMENTS = (
    "Windows 10 or 11 (64-bit). No admin rights and no Python needed for the app.",
    "Autodesk Revit 2023-2026 (several can be open side by side), each with pyRevit and the Revit MCP connector "
    "extension (mcp-server-for-revit-python) loaded; pyRevit's Routes server gives every Revit a port from 48884 up.",
    "Claude Code: Install / Reset connects it through ~/.claude.json (and Codex through ~/.codex/config.toml when "
    "Codex is installed). Other MCP clients can start RevitMcpBridge.exe as a stdio server.",
    "An internet connection to activate, and at every start of the bridge for the licence check; it keeps working "
    "offline for up to %d days after the last successful check. One licence per computer (Machine ID)." % nb_license.LICENSE_CACHE_GRACE_DAYS,
    "From source instead of the .exe files (developer only): Python 3.10 or later with mcp[cli]<2 and httpx "
    "(tkinter for the Setup window).",
)

# Same text as LICENSE.txt beside this file (router_branding_test.py checks it).
LICENSE_TEXT = """Netbuild Software Licence Agreement

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


def _mailto(subject, body):
    from urllib.parse import quote
    webbrowser.open("mailto:%s?subject=%s&body=%s" % (nb_license.DEVELOPER_EMAIL, quote(subject), quote(body)))


class SetupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("%s v%s" % (APP, VERSION))
        self.geometry("1180x720")            # wide enough for the Licence tab's agreement text beside the key status
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
        self.tab_about = ttk.Frame(nb)
        nb.add(self.tab_setup, text="  Setup  ")
        nb.add(self.tab_lic, text="  Licence  ")
        nb.add(self.tab_about, text="  About  ")
        self._build_setup(self.tab_setup)
        self._build_licence(self.tab_lic)
        self._build_about(self.tab_about)
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
        page = ttk.Frame(root, padding=16)
        page.pack(fill="both", expand=True)
        # licensing page header: product, owner, website, agreement
        ttk.Label(page, text="%s v%s" % (APP, VERSION), style="Big.TLabel").pack(anchor="w")
        ttk.Label(page, text="Proprietary software -- owned by %s   |   Website: %s" % (nb_license.OWNER, nb_license.WEBSITE)).pack(anchor="w")
        ttk.Label(page, text="Licence agreement: %s   |   %s" % (nb_license.LICENSE_NAME, nb_license.COPYRIGHT),
                  style="Dim.TLabel").pack(anchor="w")
        ttk.Label(page, text="This software and its licence keys are the property of %s. Unauthorised use is prohibited." % nb_license.OWNER,
                  style="Dim.TLabel", wraplength=820, justify="left").pack(anchor="w")
        ttk.Separator(page, orient="horizontal").pack(fill="x", pady=8)
        # body: key status / activation / developer (left), the licence agreement text (right)
        body = ttk.Frame(page)
        body.pack(fill="both", expand=True)
        f = ttk.Frame(body)
        f.pack(side="left", fill="y", anchor="n", padx=(0, 16))
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
                          "and are not transferable. Redistribution, copying or reverse engineering of this software is prohibited. "
                          "Full licence agreement: on the right (LICENSE.txt).",
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

        f.columnconfigure(1, weight=1)

        # the full licence agreement (moved here from the About tab)
        txt = ttk.Frame(body)
        txt.pack(side="left", fill="both", expand=True)
        ttk.Label(txt, text="Licence agreement (LICENSE.txt)", style="Big.TLabel").pack(anchor="w", pady=(0, 2))
        btns = ttk.Frame(txt)
        btns.pack(side="bottom", fill="x", pady=(6, 0))       # packed before the text box so it is never squeezed out
        ttk.Button(btns, text="Copy licence", command=lambda: self._copy(LICENSE_TEXT)).pack(side="left")
        ttk.Button(btns, text="Open %s" % nb_license.WEBSITE, command=lambda: webbrowser.open(nb_license.WEBSITE)).pack(side="left", padx=6)
        box = self.rt.console(txt, wrap="word")
        box.configure(height=6)
        box.insert("1.0", LICENSE_TEXT)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, pady=(2, 0))

    def _build_about(self, root):
        f = ttk.Frame(root, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=APP, style="Big.TLabel").pack(anchor="w")
        ttk.Label(f, text="Version %s   |   %s   |   %s" % (VERSION, nb_license.COPYRIGHT, nb_license.WEBSITE),
                  style="Dim.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Label(f, text="Publisher: %s   |   Developer: %s   |   %s" % (nb_license.PUBLISHER, nb_license.DEVELOPER_NAME,
                                                                         nb_license.DEVELOPER_EMAIL),
                  style="Dim.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(f, text=DESCRIPTION, wraplength=820, justify="left").pack(anchor="w", pady=(0, 8))
        ttk.Label(f, text="Requirements", style="Big.TLabel").pack(anchor="w")
        for line in REQUIREMENTS:
            ttk.Label(f, text="•  " + line, wraplength=820, justify="left").pack(anchor="w", padx=(8, 0), pady=1)
        ttk.Label(f, text="Licence: %s -- see the Licence tab" % nb_license.LICENSE_NAME).pack(anchor="w", pady=(8, 0))
        self.about_lic = ttk.Label(f, text="Licence status: checking…", style="Dim.TLabel", wraplength=820, justify="left")
        self.about_lic.pack(anchor="w", pady=(2, 4))

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
        status = nb_license.status_text()
        self.lic_label.configure(text=status)
        self.about_lic.configure(text="Licence status: " + status)

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

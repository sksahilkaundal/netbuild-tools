"""Tkinter window: Run tab (model-by-model export pass), Setup tab (link local paths) and About tab."""

import os
import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import about
from .runner import MODE_LABELS, Job, Runner, log_time_saved, open_folder, static_checks, today
from .settings import SCRIPT_KEYS, Settings
from .sheets import SheetSpecError, parse_sheet_spec

PAD = {"padx": 6, "pady": 3}

# (key, label, kind) -- kind: dir | py | save | text
SETUP_FIELDS = [("netbuild_root", "Netbuild folder", "dir")] + \
    [(k, label, "py") for k, label in SCRIPT_KEYS] + [
    ("plot_root", "Plot root (BASE_OUTPUT_FOLDER = <root>\\<YYYYMMDD>)", "dir"),
    ("time_saved_log", "Time-saved log (.csv)", "save"),
    ("revit_url", "Revit listener URL", "text"),
]
COLUMNS = [("model", "Model", 110), ("script", "Routing", 90), ("open", "Open in Revit", 300),
           ("date", "Date filter", 100), ("sheets", "Sheets", 70), ("pdf", "PDF", 70),
           ("dwg", "DWG", 70), ("result", "Result", 160)]


def routing(mdl):
    return "browser filter" if mdl["kind"] == "master" else "view type"


def format_folders(mapping):
    return "; ".join("%s = %s" % kv for kv in (mapping or {}).items())


def parse_folders(text):
    """'FloorPlan = 06_Tower Plans; AreaPlan = 09_Area Plans' -> dict (bad pieces ignored)."""
    out = {}
    for piece in (text or "").split(";"):
        key, sep, folder = piece.partition("=")
        if sep and key.strip() and folder.strip():
            out[key.strip()] = folder.strip()
    return out


class SheetDialog(object):
    """Feed sheets three ways: a single sheet, a series (from - to), or a list with any separator."""

    def __init__(self, app):
        self.app = app
        d = self.d = tk.Toplevel(app.root)
        d.title("Sheets to plot")
        d.transient(app.root)
        d.columnconfigure(1, weight=1)

        ttk.Label(d, text="Single sheet").grid(row=0, column=0, sticky="w", **PAD)
        self.single = tk.StringVar()
        e = ttk.Entry(d, textvariable=self.single)
        e.grid(row=0, column=1, sticky="ew", **PAD)
        e.bind("<Return>", lambda ev: self.add_single())
        ttk.Button(d, text="Add", command=self.add_single).grid(row=0, column=2, **PAD)

        ttk.Label(d, text="Series").grid(row=1, column=0, sticky="w", **PAD)
        sf = ttk.Frame(d)
        sf.grid(row=1, column=1, sticky="w")
        self.s_from, self.s_to = tk.StringVar(), tk.StringVar()
        ttk.Label(sf, text="from").pack(side="left")
        ttk.Entry(sf, textvariable=self.s_from, width=22).pack(side="left", padx=4)
        ttk.Label(sf, text="to").pack(side="left")
        ttk.Entry(sf, textvariable=self.s_to, width=22).pack(side="left", padx=4)
        ttk.Button(d, text="Add", command=self.add_series).grid(row=1, column=2, **PAD)

        ttk.Label(d, text="List\n(paste; separate with\ncomma ; | tab, space\nor new line)").grid(
            row=2, column=0, sticky="nw", **PAD)
        self.paste = tk.Text(d, height=5, width=60)
        self.paste.grid(row=2, column=1, sticky="ew", **PAD)
        ttk.Button(d, text="Add", command=self.add_list).grid(row=2, column=2, sticky="n", **PAD)

        ttk.Separator(d).grid(row=3, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(d, text="Sheets to plot").grid(row=4, column=0, sticky="nw", **PAD)
        self.lb = tk.Listbox(d, height=10, selectmode="extended")
        self.lb.grid(row=4, column=1, sticky="nsew", **PAD)
        d.rowconfigure(4, weight=1)
        side = ttk.Frame(d)
        side.grid(row=4, column=2, sticky="n")
        ttk.Button(side, text="Remove", command=self.remove).pack(fill="x", **PAD)
        ttk.Button(side, text="Clear", command=lambda: self.lb.delete(0, "end")).pack(fill="x", **PAD)
        ttk.Label(d, foreground="#555", justify="left", text=(
            "A sheet can be its Sheet Number, its drawing number (SBFX 01-07, with or without _<rev>),\n"
            "or just the last field, e.g. 210001. A series needs the same prefix at both ends.")).grid(
            row=5, column=0, columnspan=3, sticky="w", **PAD)
        bar = ttk.Frame(d)
        bar.grid(row=6, column=0, columnspan=3, sticky="e")
        ttk.Button(bar, text="Use these sheets", command=self.ok).pack(side="left", **PAD)
        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="left", **PAD)

        for item in [x.strip() for x in app.sheet_text().replace(";", "\n").replace(",", "\n").splitlines()]:
            if item:
                self.lb.insert("end", item)
        e.focus_set()

    def _add(self, items):
        try:
            for it in items:
                parse_sheet_spec(it)
        except SheetSpecError as e:
            messagebox.showwarning("Sheets", str(e), parent=self.d)
            return False
        have = set(self.lb.get(0, "end"))
        for it in items:
            if it not in have:
                self.lb.insert("end", it)
                have.add(it)
        return True

    def add_single(self):
        v = self.single.get().strip()
        if v and self._add([v]):
            self.single.set("")

    def add_series(self):
        a, b = self.s_from.get().strip(), self.s_to.get().strip()
        if not a or not b:
            messagebox.showinfo("Series", "Fill both 'from' and 'to'.", parent=self.d)
            return
        if self._add(["%s to %s" % (a, b)]):
            self.s_from.set("")
            self.s_to.set("")

    def add_list(self):
        sels = []
        try:
            sels = parse_sheet_spec(self.paste.get("1.0", "end"))
        except SheetSpecError as e:
            messagebox.showwarning("List", str(e), parent=self.d)
            return
        if sels and self._add([s.text for s in sels]):
            self.paste.delete("1.0", "end")

    def remove(self):
        for i in reversed(self.lb.curselection()):
            self.lb.delete(i)

    def ok(self):
        items = list(self.lb.get(0, "end"))
        self.app.set_sheets("\n".join(items))
        self.d.destroy()


class App(object):
    def __init__(self, root):
        self.root = root
        self.s = Settings()
        self.q = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self.session_start = time.time()
        self.rows = []          # files verified this session
        self.state = {}         # model name -> column values

        root.title(about.title())
        root.geometry("1180x860")
        root.minsize(980, 640)
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        self.run_tab, self.setup_tab, self.about_tab = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.run_tab, text="  Run  ")
        nb.add(self.setup_tab, text="  Setup / Paths  ")
        nb.add(self.about_tab, text="  About  ")
        self._build_run_tab()
        self._build_setup_tab()
        self._build_about_tab()
        self.status = tk.StringVar(value="Open the first model in Revit, select it below, then click "
                                         "'Model is open'.")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x")
        self._restore_last()
        self.root.after(100, self._poll)
        if not all(ok for _, _, ok in self.s.check_paths()[:4]):
            nb.select(self.setup_tab)
            self.status.set("Some paths are not found -- link them on this tab, then Save.")

    # ------------------------------------------------------------ Run tab
    def _build_run_tab(self):
        f = ttk.LabelFrame(self.run_tab, text="Export")
        f.pack(fill="x", **PAD)
        f.columnconfigure(1, weight=1)

        self.plot_root = tk.StringVar(value=self.s["plot_root"])
        ttk.Label(f, text="Plot root").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Entry(f, textvariable=self.plot_root).grid(row=0, column=1, columnspan=2, sticky="ew", **PAD)
        ttk.Button(f, text="Browse...", command=self._pick_root).grid(row=0, column=3, **PAD)

        self.out_date = tk.StringVar(value=today())
        ttk.Label(f, text="Output folder").grid(row=1, column=0, sticky="w", **PAD)
        of = ttk.Frame(f)
        of.grid(row=1, column=1, columnspan=3, sticky="ew")
        ttk.Entry(of, textvariable=self.out_date, width=12).pack(side="left", **PAD)
        self.out_label = ttk.Label(of, foreground="#555")
        self.out_label.pack(side="left", **PAD)

        self.date = tk.StringVar()
        ttk.Label(f, text="Revision date").grid(row=2, column=0, sticky="w", **PAD)
        df = ttk.Frame(f)
        df.grid(row=2, column=1, columnspan=3, sticky="ew")
        ttk.Entry(df, textvariable=self.date, width=16).pack(side="left", **PAD)
        ttk.Label(df, foreground="#555", text="any spelling (06-Sep-2026 / 06/09/2026) -- each model's own format "
                                             "is read live; only sheets whose \"Current Revision Date\" "
                                             "includes it").pack(side="left", **PAD)

        self.mode = tk.StringVar(value="pdf")
        ttk.Label(f, text="Export").grid(row=3, column=0, sticky="w", **PAD)
        mf = ttk.Frame(f)
        mf.grid(row=3, column=1, columnspan=3, sticky="w")
        for key in ("pdf", "cad", "pdf+cad"):
            ttk.Radiobutton(mf, text=MODE_LABELS[key], value=key, variable=self.mode).pack(side="left", **PAD)
        ttk.Label(mf, foreground="#555", text="A0 - Center - 100%;  all PDFs first, then all DWGs").pack(
            side="left", **PAD)

        self.sheet_mode = tk.StringVar(value="all")
        ttk.Label(f, text="Sheets").grid(row=4, column=0, sticky="nw", **PAD)
        sf = ttk.Frame(f)
        sf.grid(row=4, column=1, columnspan=3, sticky="ew")
        sf.columnconfigure(2, weight=1)
        ttk.Radiobutton(sf, text="All sheets with that revision date", value="all",
                        variable=self.sheet_mode).grid(row=0, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Radiobutton(sf, text="Only these sheets:", value="list",
                        variable=self.sheet_mode).grid(row=1, column=0, sticky="nw", **PAD)
        self.sheets = tk.Text(sf, height=3, width=50, wrap="word")
        self.sheets.grid(row=1, column=2, sticky="ew", **PAD)
        self.sheets.bind("<KeyRelease>", lambda e: self.sheet_mode.set("list"))
        bf = ttk.Frame(sf)
        bf.grid(row=1, column=3, sticky="n")
        ttk.Button(bf, text="Feed sheets...", command=lambda: SheetDialog(self)).pack(fill="x", **PAD)
        ttk.Button(bf, text="Load .txt...", command=self._load_sheets).pack(fill="x", **PAD)
        ttk.Label(sf, foreground="#555", text="single 210001  |  list 210001, 210004; 210007  |  "
                                             "series 210001 to 210012  (Sheet Number, drawing number "
                                             "or its last field)").grid(row=2, column=2, columnspan=2,
                                                                        sticky="w", **PAD)
        for v in (self.plot_root, self.out_date):
            v.trace_add("write", lambda *a: self._show_out())
        self._show_out()

        m = ttk.LabelFrame(self.run_tab, text="Models -- open each in Revit, then tell the runner it is open")
        m.pack(fill="x", **PAD)
        self.tree = ttk.Treeview(m, columns=[c[0] for c in COLUMNS], show="headings", height=9,
                                 selectmode="browse")
        for key, label, width in COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=key in ("open", "result"))
        self.tree.pack(fill="x", **PAD)
        self._fill_models()

        b = ttk.Frame(m)
        b.pack(fill="x")
        self.buttons = []

        def btn(text, cmd):
            w = ttk.Button(b, text=text, command=cmd)
            w.pack(side="left", **PAD)
            self.buttons.append(w)
            return w
        btn("1. Model is open - check", self.do_check)
        btn("2. Export", self.do_export)
        btn("Next model >", self.do_next)
        ttk.Button(b, text="Cancel", command=self.do_cancel).pack(side="left", **PAD)
        b2 = ttk.Frame(m)
        b2.pack(fill="x")
        for text, cmd in (("List open models", self.do_list), ("Verify output folder", self.do_verify),
                          ("Open output folder", self.do_open), ("Log time saved...", self.do_log_time)):
            w = ttk.Button(b2, text=text, command=cmd)
            w.pack(side="left", **PAD)
            if text != "Open output folder" and text != "Log time saved...":
                self.buttons.append(w)

        pw = ttk.PanedWindow(self.run_tab, orient="vertical")
        pw.pack(fill="both", expand=True, **PAD)
        cf = ttk.LabelFrame(pw, text="Checks")
        self.checks = tk.Text(cf, height=8, wrap="word", state="disabled")
        self.checks.pack(fill="both", expand=True)
        for tag, colour in (("ok", "#1b7f2a"), ("warn", "#b26a00"), ("fail", "#c62828"), ("head", "#000")):
            self.checks.tag_config(tag, foreground=colour)
        self.checks.tag_config("head", font=("Segoe UI", 9, "bold"))
        lf = ttk.LabelFrame(pw, text="Revit / runner output  (read-only log -- set options above, not here)")
        self.out = ScrolledText(lf, height=14, wrap="none", font=("Consolas", 9), state="disabled")
        self.out.pack(fill="both", expand=True)
        pw.add(cf, weight=1)
        pw.add(lf, weight=3)

    def _fill_models(self):
        self.tree.delete(*self.tree.get_children())
        for mdl in self.s["models"]:
            st = self.state.setdefault(mdl["name"], {})
            vals = [mdl["name"], routing(mdl)] + [st.get(k, "") for k, _, _ in COLUMNS[2:]]
            self.tree.insert("", "end", iid=mdl["name"], values=vals)
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])

    def _set_state(self, name, **kw):
        self.state.setdefault(name, {}).update(kw)
        if self.tree.exists(name):
            for k, v in kw.items():
                self.tree.set(name, k, v)

    def _show_out(self):
        self.out_label.config(text="BASE_OUTPUT_FOLDER = %s" % os.path.join(self.plot_root.get(),
                                                                          self.out_date.get().strip()))

    # ------------------------------------------------------------ Setup tab
    def _build_setup_tab(self):
        f = ttk.LabelFrame(self.setup_tab, text="Local paths (saved in settings.json next to the app)")
        f.pack(fill="x", **PAD)
        f.columnconfigure(1, weight=1)
        self.path_vars, self.path_marks = {}, {}
        for i, (key, label, kind) in enumerate(SETUP_FIELDS):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", **PAD)
            var = tk.StringVar(value=self.s[key])
            self.path_vars[key] = var
            ttk.Entry(f, textvariable=var).grid(row=i, column=1, sticky="ew", **PAD)
            if kind != "text":
                ttk.Button(f, text="Browse...", command=lambda k=key, kd=kind: self._browse(k, kd)
                           ).grid(row=i, column=2, **PAD)
            mark = ttk.Label(f, width=10)
            mark.grid(row=i, column=3, sticky="w", **PAD)
            self.path_marks[key] = mark
            var.trace_add("write", lambda *a: self._check_paths())

        o = ttk.LabelFrame(self.setup_tab, text="Models -- Revit title must contain one of the match texts "
                                                "(comma-separated); folders: view type = folder; ...")
        o.pack(fill="x", **PAD)
        o.columnconfigure(2, weight=1)
        o.columnconfigure(3, weight=1)
        self.match_vars, self.folder_vars = {}, {}
        ttk.Label(o, text="Match text", foreground="#555").grid(row=0, column=2, sticky="w", **PAD)
        ttk.Label(o, text="Output folders (blank = the script's own)", foreground="#555").grid(
            row=0, column=3, sticky="w", **PAD)
        for i, mdl in enumerate(self.s["models"], 1):
            ttk.Label(o, text=mdl["name"]).grid(row=i, column=0, sticky="w", **PAD)
            ttk.Label(o, text=routing(mdl), foreground="#555").grid(row=i, column=1, sticky="w", **PAD)
            v = tk.StringVar(value=", ".join(mdl["match"]))
            self.match_vars[mdl["name"]] = v
            ttk.Entry(o, textvariable=v).grid(row=i, column=2, sticky="ew", **PAD)
            if mdl["kind"] != "master":
                f = tk.StringVar(value=format_folders(mdl.get("subfolders")))
                self.folder_vars[mdl["name"]] = f
                ttk.Entry(o, textvariable=f).grid(row=i, column=3, sticky="ew", **PAD)

        t = ttk.LabelFrame(self.setup_tab, text="Timing")
        t.pack(fill="x", **PAD)
        self.num_vars = {}
        for i, (key, label) in enumerate((
                ("stall_seconds", "Batch stalled after (s) with nothing new on disk -> one sheet per call"),
                ("sheet_timeout_seconds", "One-sheet call gives up after (s)"),
                ("settle_seconds", "After Revit answers, wait (s) for the last file"))):
            ttk.Label(t, text=label).grid(row=i, column=0, sticky="w", **PAD)
            v = tk.StringVar(value=str(self.s[key]))
            self.num_vars[key] = v
            ttk.Entry(t, textvariable=v, width=8).grid(row=i, column=1, sticky="w", **PAD)
        self.sweep = tk.BooleanVar(value=bool(self.s["sweep_byproducts"]))
        ttk.Checkbutton(t, text="Sweep DWG byproducts (FP_*.pat, *.pcp, *.jpg, *.png) written during each CAD "
                                "batch", variable=self.sweep).grid(row=3, column=0, columnspan=2, sticky="w", **PAD)

        bar = ttk.Frame(self.setup_tab)
        bar.pack(fill="x", **PAD)
        ttk.Button(bar, text="Check paths + scripts", command=self._check_scripts).pack(side="left", **PAD)
        ttk.Button(bar, text="Save", command=self._save_settings).pack(side="left", **PAD)
        self.script_checks = tk.Text(self.setup_tab, height=12, wrap="word", state="disabled")
        self.script_checks.pack(fill="both", expand=True, **PAD)
        for tag, colour in (("ok", "#1b7f2a"), ("warn", "#b26a00"), ("fail", "#c62828")):
            self.script_checks.tag_config(tag, foreground=colour)
        ttk.Label(self.setup_tab, foreground="#555", justify="left", text=(
            "Scripts may be absolute paths or relative to the Netbuild folder. They are read, never edited: "
            "BASE_OUTPUT_FOLDER, REVISION_DATE_FILTER, EXPORT_PDF/CAD,\nDRY_RUN and the model binding are set "
            "in memory per call. Revit needs pyRevit + the MCP listener (the same one Claude uses).")
        ).pack(anchor="w", **PAD)
        self._check_paths()

    # ------------------------------------------------------------ About tab
    def _build_about_tab(self):
        f = ttk.Frame(self.about_tab)
        f.pack(fill="both", expand=True, padx=14, pady=10)
        ttk.Label(f, text=about.PRODUCT, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(f, text="Version %s   |   %s   |   %s" % (about.VERSION, about.COPYRIGHT, about.WEBSITE),
                  foreground="#555").pack(anchor="w", pady=(2, 8))
        ttk.Label(f, text=about.DESCRIPTION, wraplength=1000, justify="left").pack(anchor="w", pady=(0, 8))
        cols = ttk.Frame(f)
        cols.pack(fill="x")
        left, right = ttk.LabelFrame(cols, text="Features"), ttk.LabelFrame(cols, text="Requirements")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(left, justify="left", wraplength=480,
                  text="\n".join("- " + x for x in about.FEATURES)).pack(anchor="w", **PAD)
        ttk.Label(right, justify="left", wraplength=480, text=about.requirements_text()).pack(anchor="w", **PAD)
        lf = ttk.LabelFrame(f, text="License -- %s" % about.LICENSE_NAME)
        lf.pack(fill="both", expand=True, pady=(8, 0))
        self.license_box = ScrolledText(lf, height=12, wrap="word", font=("Consolas", 9))
        self.license_box.insert("1.0", about.LICENSE_TEXT)
        self.license_box.config(state="disabled")
        self.license_box.pack(fill="both", expand=True)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Copy product info", command=self._copy_about).pack(side="left", **PAD)
        ttk.Button(bar, text="Open %s" % about.WEBSITE,
                   command=lambda: webbrowser.open(about.WEBSITE)).pack(side="left", **PAD)

    def _copy_about(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(about.about_text())
        self.status.set("Product info, requirements and license copied to the clipboard.")

    def _browse(self, key, kind):
        cur = self.path_vars[key].get()
        start = cur if os.path.isdir(cur) else os.path.dirname(cur) or self.path_vars["netbuild_root"].get()
        if kind == "dir":
            p = filedialog.askdirectory(initialdir=start, title="Select folder")
        elif kind == "py":
            p = filedialog.askopenfilename(initialdir=start, filetypes=[("Python", "*.py"), ("All", "*.*")])
        else:
            p = filedialog.asksaveasfilename(initialdir=start, defaultextension=".csv",
                                             confirmoverwrite=False, filetypes=[("CSV", "*.csv")])
        if p:
            self.path_vars[key].set(os.path.normpath(p))

    def _apply_setup(self):
        for key, var in self.path_vars.items():
            self.s[key] = var.get().strip()
        for mdl in self.s["models"]:
            v = self.match_vars.get(mdl["name"])
            if v:
                mdl["match"] = [x.strip() for x in v.get().split(",") if x.strip()] or mdl["match"]
            f = self.folder_vars.get(mdl["name"])
            if f:
                folders = parse_folders(f.get())
                if folders:
                    mdl["subfolders"] = folders
                else:
                    mdl.pop("subfolders", None)
        for key, v in self.num_vars.items():
            try:
                self.s[key] = float(v.get())
            except ValueError:
                pass
        self.s["sweep_byproducts"] = bool(self.sweep.get())

    def _check_paths(self):
        self._apply_setup()
        rows = self.s.check_paths()
        oks = {"netbuild_root": rows[0][2], "master_script": rows[1][2], "podium_script": rows[2][2],
               "plot_root": rows[3][2], "time_saved_log": rows[4][2]}
        for key, mark in self.path_marks.items():
            if key in oks:
                mark.config(text="found" if oks[key] else "NOT FOUND",
                            foreground="#1b7f2a" if oks[key] else "#c62828")

    def _check_scripts(self):
        self._check_paths()
        w = self.script_checks
        w.config(state="normal")
        w.delete("1.0", "end")
        for key, _ in SCRIPT_KEYS:
            path = self.s.script(key)
            if not os.path.isfile(path):
                w.insert("end", "[FAIL] not found: %s\n" % path, "fail")
                continue
            for c in static_checks(path, "master" if key == "master_script" else "podium"):
                w.insert("end", str(c) + "\n", "ok" if c.ok is True else ("warn" if c.ok is None else "fail"))
        w.config(state="disabled")

    def _save_settings(self):
        self._apply_setup()
        try:
            self.s.save()
        except OSError as e:
            messagebox.showerror("Save", str(e))
            return
        if self.plot_root.get() != self.s["plot_root"] and messagebox.askyesno(
                "Plot root", "Use the new plot root on the Run tab?"):
            self.plot_root.set(self.s["plot_root"])
        self.status.set("Settings saved to %s" % self.s.path)

    # ------------------------------------------------------------ form helpers
    def _pick_root(self):
        p = filedialog.askdirectory(initialdir=self.plot_root.get())
        if p:
            self.plot_root.set(os.path.normpath(p))

    def sheet_text(self):
        return self.sheets.get("1.0", "end").strip()

    def set_sheets(self, text):
        self.sheets.delete("1.0", "end")
        self.sheets.insert("1.0", text)
        self.sheet_mode.set("list" if text.strip() else "all")

    def _load_sheets(self):
        p = filedialog.askopenfilename(filetypes=[("Text / CSV", "*.txt *.csv"), ("All", "*.*")])
        if p:
            with open(p, "r", encoding="utf-8-sig") as f:
                self.set_sheets(f.read().strip())

    def _model(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Model", "Select a model in the list first.")
            return None
        return self.s.model(sel[0])

    def _job(self):
        self._apply_setup()
        spec = self.sheet_text() if self.sheet_mode.get() == "list" else ""
        try:
            job = Job(self.plot_root.get().strip(), self.out_date.get().strip(), self.date.get(),
                      self.mode.get(), spec)
        except SheetSpecError as e:
            messagebox.showwarning("Sheets", str(e))
            return None
        problems = job.problems()
        if problems:
            messagebox.showwarning("Inputs", "\n".join(problems))
            return None
        self.s.save_last(job.as_dict())
        return job

    def _restore_last(self):
        last = self.s.load_last()
        if last.get("plot_root"):
            self.plot_root.set(last["plot_root"])
        if last.get("date_text"):
            self.date.set(last["date_text"])
        if last.get("mode") in MODE_LABELS:
            self.mode.set(last["mode"])
        if last.get("sheet_spec"):
            self.set_sheets(last["sheet_spec"])

    # ------------------------------------------------------------ worker plumbing
    def _start(self, label, fn, done):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        for w in self.buttons:
            w.state(["disabled"])
        self.status.set("Running: %s ..." % label)
        self._log("\n===== %s  %s =====" % (label, time.strftime("%H:%M:%S")))
        runner = Runner(self.s, on_line=lambda line: self.q.put(("line", line)), cancel=self.cancel)

        def work():
            try:
                res = fn(runner)
                self.q.put(("done", (done, res, None)))
            except Exception as e:  # shown, never swallowed
                self.q.put(("done", (done, None, e)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    self._log(payload)
                else:
                    done, res, err = payload
                    self.busy = False
                    for w in self.buttons:
                        w.state(["!disabled"])
                    if err:
                        self.status.set("Error")
                        messagebox.showerror("Error", "%s: %s" % (type(err).__name__, err))
                    else:
                        self.status.set("%s: %s" % (res.name, "OK" if res.ok else "needs attention"))
                        done(res)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _log(self, text):
        self.out.config(state="normal")
        self.out.insert("end", text + "\n")
        self.out.config(state="disabled")
        self.out.see("end")

    def _show_checks(self, title, res, clear=True):
        self.checks.config(state="normal")
        if clear:
            self.checks.delete("1.0", "end")
        self.checks.insert("end", title + "\n", "head")
        for c in res.checks:
            tag = "ok" if c.ok is True else ("warn" if c.ok is None else "fail")
            self.checks.insert("end", str(c) + "\n", tag)
        if res.log_path:
            self.checks.insert("end", "log: %s\n" % res.log_path)
        if res.info.get("summary_csv"):
            self.checks.insert("end", "file list: %s\n" % res.info["summary_csv"])
        self.checks.config(state="disabled")
        self.checks.see("end")

    # ------------------------------------------------------------ actions
    def do_check(self):
        mdl = self._model()
        if not mdl:
            return
        self._apply_setup()

        def done(res):
            doc = res.info.get("doc")
            self._set_state(mdl["name"], open=(doc["title"] + ("" if doc.get("active") else "  (not active)"))
                            if doc else "NOT OPEN")
            self._show_checks("%s -- is it open?" % mdl["name"], res)
            if res.ok:
                self.status.set("%s is open -- click Export." % mdl["name"])
        self._start("Check %s" % mdl["name"], lambda r: r.check_model(mdl), done)

    def _after_dry(self, mdl, res):
        info = res.info
        if "date_filter" in info:
            self._set_state(mdl["name"], date=info["date_filter"] or "(none)")
        if "chosen" in info:
            self._set_state(mdl["name"], sheets=str(len(info["chosen"])))

    def do_export(self, allow_unmatched=False):
        mdl, job = self._model(), self._job()
        if not mdl or not job:
            return
        if not allow_unmatched and not messagebox.askyesno(
                "Export", "Export %s from %s to\n%s ?\n\nRevit must have %s open (bound by title)."
                % (MODE_LABELS[job.mode], mdl["name"], job.out_dir, mdl["name"])):
            return

        def done(res):
            self._after_dry(mdl, res)
            rows = res.info.get("files") or []
            self.rows = [r for r in self.rows if r["model"] != mdl["name"]] + rows
            for kind, col in (("PDF", "pdf"), ("CAD", "dwg")):
                mine = [r for r in rows if r["kind"] == kind]
                if mine:
                    self._set_state(mdl["name"], **{col: "%d/%d" % (
                        sum(1 for r in mine if r["status"] == "OK"), len(mine))})
            self._set_state(mdl["name"], result="OK" if res.ok else "needs attention")
            self._show_checks("%s -- export" % mdl["name"], res)
            unmatched = res.info.get("unmatched")
            if res.aborted and unmatched and not allow_unmatched and res.info.get("chosen"):
                if messagebox.askyesno("Sheets not found", "Not found in %s: %s\n\nExport the %d sheet(s) "
                                       "that were found?" % (mdl["name"], ", ".join(unmatched),
                                                             len(res.info["chosen"]))):
                    self.do_export(allow_unmatched=True)
            elif res.ok:
                self.status.set("%s done and verified on disk -- open the next model, then 'Next model'."
                                % mdl["name"])
        self._start("Export %s" % mdl["name"], lambda r: r.export(mdl, job, allow_unmatched), done)

    def do_next(self):
        kids = list(self.tree.get_children())
        sel = self.tree.selection()
        i = kids.index(sel[0]) + 1 if sel else 0
        if i < len(kids):
            self.tree.selection_set(kids[i])
            self.tree.see(kids[i])
            self.status.set("Open %s in Revit, then click 'Model is open'." % kids[i])
        else:
            self.status.set("Last model done -- click 'Verify output folder'.")

    def do_cancel(self):
        if self.busy:
            self.cancel.set()
            self.status.set("Cancelling after the current call -- Revit may still finish the sheet it is on.")

    def do_list(self):
        self._apply_setup()

        class R(object):
            name, checks, log_path, info, ok = "List open models", [], None, {}, True

        def work(r):
            for d in r.list_docs():
                r.say("  %s%s" % (d.get("title"), "   (active)" if d.get("active") else ""))
            return R()
        self._start("List open models", work, lambda res: None)

    def do_verify(self):
        self._apply_setup()
        out = os.path.join(self.plot_root.get().strip(), self.out_date.get().strip())
        mode = self.mode.get()
        rows = [r for r in self.rows if r["path"].startswith(out)]
        self._start("Verify", lambda r: r.verify_output(out, mode, rows),
                    lambda res: self._show_checks("Output folder -- %s" % out, res))

    def do_open(self):
        out = os.path.join(self.plot_root.get().strip(), self.out_date.get().strip())
        if os.path.isdir(out):
            open_folder(out)
        elif os.path.isdir(self.plot_root.get()):
            open_folder(self.plot_root.get())

    def do_log_time(self):
        self._apply_setup()
        d = tk.Toplevel(self.root)
        d.title("Log time saved")
        d.transient(self.root)
        elapsed = round((time.time() - self.session_start) / 60.0)
        fields = [("Output folder", self.out_date.get()),
                  ("Sheets", str(sum(1 for r in self.rows if r["status"] == "OK"))),
                  ("Actual minutes", str(elapsed)),
                  ("Manual minutes", str(self.s["time_saved_manual_minutes"])), ("Notes", "")]
        vars_ = {}
        for i, (label, val) in enumerate(fields):
            ttk.Label(d, text=label).grid(row=i, column=0, sticky="w", **PAD)
            v = tk.StringVar(value=val)
            ttk.Entry(d, textvariable=v, width=50).grid(row=i, column=1, **PAD)
            vars_[label] = v

        def save():
            try:
                actual, manual = float(vars_["Actual minutes"].get()), float(vars_["Manual minutes"].get())
                log_time_saved(self.s["time_saved_log"], {
                    "date": today(), "task": self.s["time_saved_task"], "project": self.s["project_title"],
                    "export": vars_["Output folder"].get(), "issues": vars_["Sheets"].get(),
                    "manual_minutes": manual, "actual_minutes": actual,
                    "minutes_saved": manual - actual, "notes": vars_["Notes"].get()})
            except (ValueError, OSError) as e:
                messagebox.showerror("Time log", str(e), parent=d)
                return
            self.status.set("Logged to %s" % self.s["time_saved_log"])
            d.destroy()
        ttk.Button(d, text="Append to log", command=save).grid(row=len(fields), column=1, sticky="e", **PAD)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0

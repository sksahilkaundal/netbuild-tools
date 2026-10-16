"""Tkinter window: Run tab (up to 10 levels, current -> new) and Setup tab."""

import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from . import about
from .core import MAX_LEVELS, MoveSpec, counterpart, define_value
from .runner import Runner, open_folder
from .settings import DEFAULTS, Settings
from .units import fmt, from_ft, parse_length

PAD = {"padx": 6, "pady": 3}
CURRENT_BG = "#fff3bf"      # the read-only "current elevation" field
UP, DOWN = "#1b7f2a", "#c62828"
DIGITS = {"mm": 1, "m": 4}


def current_field(parent, var, width):
    """Read-only, highlighted. A classic tk.Entry: the Windows themes ignore a ttk field background."""
    return tk.Entry(parent, textvariable=var, state="readonly", readonlybackground=CURRENT_BG, fg="#000",
                    width=width, justify="right", relief="solid", bd=1)


class Row(object):
    """One level: [level v] [current (read-only)] [new elevation] [move] [Define new level...]."""

    def __init__(self, app, parent, i):
        self.app, self.i = app, i
        self.level = tk.StringVar()
        self.current = tk.StringVar()
        self.new = tk.StringVar()
        self.delta = tk.StringVar()
        self.mode = None            # "to" | "by": the field the user typed in last
        self._guard = False
        r = i + 1
        ttk.Label(parent, text="%d" % (i + 1)).grid(row=r, column=0, **PAD)
        self.combo = ttk.Combobox(parent, textvariable=self.level, state="readonly", width=30)
        self.combo.grid(row=r, column=1, sticky="ew", **PAD)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.on_level())
        current_field(parent, self.current, 18).grid(row=r, column=2, **PAD)
        e_new = ttk.Entry(parent, textvariable=self.new, width=16, justify="right")
        e_new.grid(row=r, column=3, **PAD)
        e_new.bind("<KeyRelease>", lambda e: self.on_edit("to"))
        e_by = ttk.Entry(parent, textvariable=self.delta, width=14, justify="right")
        e_by.grid(row=r, column=4, **PAD)
        e_by.bind("<KeyRelease>", lambda e: self.on_edit("by"))
        self.arrow = ttk.Label(parent, width=8)
        self.arrow.grid(row=r, column=5, sticky="w", **PAD)
        self.btn = ttk.Button(parent, text="Define new level...", command=lambda: DefineDialog(self))
        self.btn.grid(row=r, column=6, **PAD)

    def lv(self):
        return self.app.level_by_name(self.level.get())

    def cur_value(self):
        lv = self.lv()
        return from_ft(lv["elev"], self.app.units()) if lv else None

    def on_level(self):
        lv = self.lv()
        self.current.set(fmt(self.cur_value(), self.app.units()) if lv else "")
        if self.mode:
            self.on_edit(self.mode)

    def on_edit(self, mode):
        if self._guard:
            return
        self.mode = mode
        cur, u = self.cur_value(), self.app.units()
        self._guard = True
        try:
            src = self.new if mode == "to" else self.delta
            dst = self.delta if mode == "to" else self.new
            if not src.get().strip():
                self.mode = None
            try:
                dst.set(counterpart(cur, mode, src.get(), u))
            except ValueError:
                dst.set("?")
                self.arrow.config(text="")
                return
            self._arrow()
        finally:
            self._guard = False

    def _arrow(self):
        try:
            d = parse_length(self.delta.get(), self.app.units())
        except ValueError:
            self.arrow.config(text="")
            return
        self.arrow.config(text=("UP" if d > 0 else "DOWN") if d else "--",
                          foreground=UP if d > 0 else (DOWN if d < 0 else "#555"))

    def set_values(self, mode, value):
        n = DIGITS[self.app.units()]
        (self.new if mode == "to" else self.delta).set("%.*f" % (n, value) if mode == "to" else "%+.*f" % (n, value))
        self.on_edit(mode)

    def clear(self):
        self._guard = True
        for v in (self.new, self.delta):
            v.set("")
        self._guard = False
        self.mode = None
        self.arrow.config(text="")

    def spec(self):
        """MoveSpec or None; raises ValueError on a bad number."""
        if not self.level.get() or not self.mode:
            return None
        text = (self.new if self.mode == "to" else self.delta).get()
        return MoveSpec(self.level.get(), self.mode, parse_length(text, self.app.units()))


class DefineDialog(object):
    """Define the new level: an absolute elevation, or a move up / down from the current one."""

    def __init__(self, row):
        self.row = row
        app = row.app
        if not row.lv():
            messagebox.showinfo("Define new level", "Pick the level in row %d first (Load levels if the list "
                                "is empty)." % (row.i + 1))
            return
        u = app.units()
        d = self.d = tk.Toplevel(app.root)
        d.title("Define new level -- %s" % row.level.get())
        d.transient(app.root)
        d.columnconfigure(1, weight=1)
        ttk.Label(d, text="Level").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Label(d, text=row.level.get(), font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", **PAD)
        ttk.Label(d, text="Current elevation").grid(row=1, column=0, sticky="w", **PAD)
        cur = tk.StringVar(value=fmt(row.cur_value(), u))
        current_field(d, cur, 20).grid(row=1, column=1, sticky="w", **PAD)
        ttk.Separator(d).grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)

        self.how = tk.StringVar(value="by" if row.mode == "by" else "to")
        self.abs = tk.StringVar(value=row.new.get() if row.mode == "to" else "")
        self.amount = tk.StringVar()
        self.dir = tk.StringVar(value="up")
        if row.mode == "by":
            try:
                v = parse_length(row.delta.get(), u)
                self.amount.set("%.*f" % (DIGITS[u], abs(v)))
                self.dir.set("up" if v >= 0 else "down")
            except ValueError:
                pass
        ttk.Radiobutton(d, text="New elevation (%s)" % u, value="to", variable=self.how).grid(
            row=3, column=0, sticky="w", **PAD)
        ttk.Entry(d, textvariable=self.abs, width=20, justify="right").grid(row=3, column=1, sticky="w", **PAD)
        ttk.Radiobutton(d, text="Move by (%s)" % u, value="by", variable=self.how).grid(
            row=4, column=0, sticky="w", **PAD)
        mf = ttk.Frame(d)
        mf.grid(row=4, column=1, sticky="w")
        ttk.Entry(mf, textvariable=self.amount, width=12, justify="right").pack(side="left", **PAD)
        ttk.Radiobutton(mf, text="Up (+)", value="up", variable=self.dir).pack(side="left", **PAD)
        ttk.Radiobutton(mf, text="Down (-)", value="down", variable=self.dir).pack(side="left", **PAD)
        self.result = ttk.Label(d, foreground="#333")
        self.result.grid(row=5, column=0, columnspan=3, sticky="w", **PAD)
        ttk.Label(d, foreground="#555", justify="left", text=(
            "The level moves; every element hosted to it keeps its X, Y, Z\n"
            "(its offset from the level changes by the opposite amount).")).grid(
            row=6, column=0, columnspan=3, sticky="w", **PAD)
        bar = ttk.Frame(d)
        bar.grid(row=7, column=0, columnspan=3, sticky="e")
        ttk.Button(bar, text="OK", command=self.ok).pack(side="left", **PAD)
        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="left", **PAD)
        for v in (self.how, self.abs, self.amount, self.dir):
            v.trace_add("write", lambda *a: self.preview())
        self.preview()

    def _value(self):
        return define_value(self.how.get(), self.abs.get(), self.amount.get(), self.dir.get() == "up",
                            self.row.app.units())

    def preview(self):
        u, cur = self.row.app.units(), self.row.cur_value()
        try:
            mode, v = self._value()
        except ValueError:
            self.result.config(text="New elevation: --")
            return
        new, delta = (v, v - cur) if mode == "to" else (cur + v, v)
        self.result.config(text="New elevation: %s     move: %s %s" % (
            fmt(new, u), fmt(delta, u, signed=True), "(up)" if delta > 0 else ("(down)" if delta < 0 else "")))

    def ok(self):
        try:
            mode, v = self._value()
        except ValueError as e:
            messagebox.showwarning("Define new level", str(e), parent=self.d)
            return
        self.row.clear()
        self.row.set_values(mode, v)
        self.d.destroy()


class App(object):
    def __init__(self, root):
        self.root = root
        self.s = Settings()
        self.q = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self.levels = []

        root.title(about.title())
        root.geometry("1120x900")
        root.minsize(980, 680)
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        self.run_tab, self.setup_tab, self.about_tab = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.run_tab, text="  Run  ")
        nb.add(self.setup_tab, text="  Setup  ")
        nb.add(self.about_tab, text="  About  ")
        self._build_run_tab()
        self._build_setup_tab()
        self._build_about_tab()
        self.status = tk.StringVar(value="Open the model in Revit, then click '1. Load levels'.")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x")
        self._restore_last()
        self.root.after(100, self._poll)

    def units(self):
        return self.unit_var.get() if self.unit_var.get() in ("mm", "m") else "mm"

    def level_by_name(self, name):
        for lv in self.levels:
            if lv["name"] == name:
                return lv
        return None

    # ------------------------------------------------------------ Run tab
    def _build_run_tab(self):
        f = ttk.LabelFrame(self.run_tab, text="Model")
        f.pack(fill="x", **PAD)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Revit title contains").grid(row=0, column=0, sticky="w", **PAD)
        self.match = tk.StringVar(value=self.s["model_match"])
        ttk.Entry(f, textvariable=self.match).grid(row=0, column=1, sticky="ew", **PAD)
        ttk.Label(f, foreground="#555", text="blank = the active model").grid(row=0, column=2, sticky="w", **PAD)
        ttk.Label(f, text="Units").grid(row=1, column=0, sticky="w", **PAD)
        uf = ttk.Frame(f)
        uf.grid(row=1, column=1, sticky="w")
        self.unit_var = tk.StringVar(value=self.s["units"] if self.s["units"] in ("mm", "m") else "mm")
        for u in ("mm", "m"):
            ttk.Radiobutton(uf, text=u, value=u, variable=self.unit_var, command=self._units_changed).pack(
                side="left", **PAD)
        self.base_label = ttk.Label(f, foreground="#555")
        self.base_label.grid(row=2, column=1, columnspan=3, sticky="w", **PAD)
        bf = ttk.Frame(f)
        bf.grid(row=0, column=3, rowspan=2, sticky="e")
        self.buttons = []

        def btn(parent, text, cmd, side="left"):
            w = ttk.Button(parent, text=text, command=cmd)
            w.pack(side=side, **PAD)
            self.buttons.append(w)
            return w
        btn(bf, "List open models", self.do_models)
        btn(bf, "1. Load levels", self.do_levels)

        g = ttk.LabelFrame(self.run_tab, text="Levels to move (up to %d) -- every element hosted to them keeps "
                                              "its X, Y, Z" % MAX_LEVELS)
        g.pack(fill="x", **PAD)
        g.columnconfigure(1, weight=1)
        for c, text in enumerate(("#", "Level", "Current elevation", "New elevation", "Move (+up / -down)", "",
                                  "")):
            ttk.Label(g, text=text, font=("Segoe UI", 9, "bold")).grid(row=0, column=c, sticky="w", **PAD)
        self.rows = [Row(self, g, i) for i in range(MAX_LEVELS)]
        tools = ttk.Frame(g)
        tools.grid(row=MAX_LEVELS + 1, column=0, columnspan=7, sticky="w")
        ttk.Button(tools, text="Same move for every row...", command=self.do_same_move).pack(side="left", **PAD)
        ttk.Button(tools, text="Clear values", command=lambda: [r.clear() for r in self.rows]).pack(side="left", **PAD)
        ttk.Button(tools, text="Clear rows", command=self.clear_rows).pack(side="left", **PAD)
        ttk.Label(tools, foreground="#555", text="type a new elevation OR a move; values may carry mm / m "
                                                "(3500, +300, -150, 10.5m)").pack(side="left", **PAD)

        a = ttk.Frame(self.run_tab)
        a.pack(fill="x", **PAD)
        btn(a, "2. Check (plan only)", lambda: self.do_run("plan"))
        btn(a, "3. Trial run (rolls back)", lambda: self.do_run("trial"))
        btn(a, "4. Apply", lambda: self.do_run("apply"))
        ttk.Button(a, text="Cancel", command=self.do_cancel).pack(side="left", **PAD)
        ttk.Button(a, text="Open logs folder", command=lambda: open_folder(self.s.logs_dir())).pack(
            side="right", **PAD)

        pw = ttk.PanedWindow(self.run_tab, orient="vertical")
        pw.pack(fill="both", expand=True, **PAD)
        cf = ttk.LabelFrame(pw, text="Checks")
        self.checks = tk.Text(cf, height=9, wrap="word", state="disabled")
        self.checks.pack(fill="both", expand=True)
        for tag, colour in (("ok", "#1b7f2a"), ("warn", "#b26a00"), ("fail", "#c62828"), ("head", "#000")):
            self.checks.tag_config(tag, foreground=colour)
        self.checks.tag_config("head", font=("Segoe UI", 9, "bold"))
        lf = ttk.LabelFrame(pw, text="Revit / runner output  (read-only log)")
        self.out = ScrolledText(lf, height=10, wrap="none", font=("Consolas", 9), state="disabled")
        self.out.pack(fill="both", expand=True)
        pw.add(cf, weight=1)
        pw.add(lf, weight=2)

    def _units_changed(self):
        for r in self.rows:
            r.clear()
            r.on_level()

    def clear_rows(self):
        for r in self.rows:
            r.clear()
            r.level.set("")
            r.current.set("")

    def _fill_levels(self, levels):
        self.levels = levels
        names = [""] + [lv["name"] for lv in levels]
        for r in self.rows:
            r.combo["values"] = names
            if r.level.get() and not self.level_by_name(r.level.get()):
                r.level.set("")
                r.clear()
            r.on_level()
        bases = sorted(set(lv.get("base") or "?" for lv in levels))
        self.base_label.config(text="Elevations as shown in Revit -- Elevation Base: %s" % ", ".join(bases))

    # ------------------------------------------------------------ Setup tab
    def _build_setup_tab(self):
        f = ttk.LabelFrame(self.setup_tab, text="Settings (saved in settings.json next to the app)")
        f.pack(fill="x", **PAD)
        f.columnconfigure(1, weight=1)
        self.vars = {}
        for i, (key, label) in enumerate((
                ("revit_url", "Revit listener URL"),
                ("tolerance_mm", "Position tolerance (mm) -- bounding box min / max Z"),
                ("correction_rounds", "Measure -> correct rounds after the move"),
                ("probe_timeout_seconds", "Load levels / Check timeout (s)"),
                ("apply_timeout_seconds", "Trial / Apply timeout (s)"),
                ("max_rows", "Element rows per CSV"))):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", **PAD)
            v = tk.StringVar(value=str(self.s[key]))
            self.vars[key] = v
            ttk.Entry(f, textvariable=v).grid(row=i, column=1, sticky="ew", **PAD)
        self.bools = {}
        for j, (key, label) in enumerate((
                ("move_fallback", "An element with no offset parameter that still moved is moved back by (0, 0, -dz)"),
                ("rollback_on_drift", "Undo all if anything moves: Apply keeps the result only when every element "
                                      "kept its position"),
                ("fix_groups", "Model groups: when members cannot be kept in place, ungroup them, fix them and "
                               "regroup (keeps the group type name where no other instance uses it)"))):
            v = tk.BooleanVar(value=bool(self.s[key]))
            self.bools[key] = v
            ttk.Checkbutton(f, text=label, variable=v).grid(row=10 + j, column=0, columnspan=2, sticky="w", **PAD)
        bar = ttk.Frame(self.setup_tab)
        bar.pack(fill="x", **PAD)
        ttk.Button(bar, text="Save", command=self._save_settings).pack(side="left", **PAD)
        ttk.Label(self.setup_tab, foreground="#555", justify="left", text=(
            "Revit needs pyRevit + the MCP listener (the same one the ProjectA Plot Runner and Claude use).\n"
            "Each run binds to the model whose title contains the 'Revit title contains' text (blank = active).\n"
            "Apply is one Revit transaction group: Ctrl+Z in Revit ('Level Shift by Netbuild') undoes all of it.")
        ).pack(anchor="w", **PAD)

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

    def _apply_setup(self):
        for key, v in self.vars.items():
            val = v.get().strip()
            if key == "revit_url":
                self.s[key] = val
                continue
            try:
                self.s[key] = int(float(val)) if isinstance(DEFAULTS[key], int) else float(val)
            except ValueError:
                pass
        for key, v in self.bools.items():
            self.s[key] = bool(v.get())
        self.s["model_match"] = self.match.get().strip()
        self.s["units"] = self.units()

    def _save_settings(self):
        self._apply_setup()
        try:
            self.s.save()
        except OSError as e:
            messagebox.showerror("Save", str(e))
            return
        self.status.set("Settings saved to %s" % self.s.path)

    def _restore_last(self):
        last = self.s.load_last()
        self.match.set(last.get("model_match", self.match.get()))
        for r, sp in zip(self.rows, last.get("specs") or []):
            r.level.set(sp.get("level", ""))

    def _specs(self):
        specs = []
        for r in self.rows:
            try:
                sp = r.spec()
            except ValueError as e:
                messagebox.showwarning("Row %d" % (r.i + 1), str(e))
                return None
            if sp:
                specs.append(sp)
        if not specs:
            messagebox.showinfo("Levels", "Pick a level and type its new elevation (or a move) in at least one row.")
            return None
        self.s.save_last({"model_match": self.match.get().strip(), "specs": [sp.as_dict() for sp in specs]})
        return specs

    # ------------------------------------------------------------ worker plumbing
    def _start(self, label, fn, done):
        if self.busy:
            return
        self._apply_setup()
        self.busy = True
        self.cancel.clear()
        for w in self.buttons:
            w.state(["disabled"])
        self.status.set("Running: %s ..." % label)
        self._log("\n===== %s  %s =====" % (label, time.strftime("%H:%M:%S")))
        runner = Runner(self.s, on_line=lambda line: self.q.put(("line", line)), cancel=self.cancel)

        def work():
            try:
                self.q.put(("done", (done, fn(runner), None)))
            except Exception as e:  # shown, never swallowed
                self.q.put(("done", (done, None, e)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    self._log(payload)
                    continue
                done, res, err = payload
                self.busy = False
                for w in self.buttons:
                    w.state(["!disabled"])
                if err:
                    self.status.set("Error")
                    messagebox.showerror("Error", "%s: %s" % (type(err).__name__, err))
                else:
                    if res is not None:
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

    def _show_checks(self, title, res):
        self.checks.config(state="normal")
        self.checks.delete("1.0", "end")
        self.checks.insert("end", title + "\n", "head")
        for c in res.checks:
            self.checks.insert("end", str(c) + "\n", "ok" if c.ok is True else ("warn" if c.ok is None else "fail"))
        if res.log_path:
            self.checks.insert("end", "log: %s\n" % res.log_path)
        if res.info.get("rows_csv"):
            self.checks.insert("end", "element list: %s\n" % res.info["rows_csv"])
        self.checks.config(state="disabled")
        self.checks.see("end")

    # ------------------------------------------------------------ actions
    def do_models(self):
        def work(r):
            for d in r.list_docs():
                r.say("  %s%s" % (d.get("title"), "   (active)" if d.get("active") else ""))
        self._start("List open models", work, lambda res: None)

    def do_levels(self, then=None):
        def done(res):
            self._show_checks("Levels", res)
            if res.ok:
                self._fill_levels(res.info["levels"])
                self.status.set("%d levels loaded from %s -- pick up to %d, define the new elevation, then Check."
                                % (len(self.levels), res.info["doc"]["title"], MAX_LEVELS))
            if then:
                then(res)
        self._start("Load levels", lambda r: r.read_levels(), done)

    def do_same_move(self):
        text = simpledialog.askstring("Same move", "Move every selected level by (+up / -down, %s):" % self.units(),
                                      parent=self.root)
        if not text:
            return
        try:
            v = parse_length(text, self.units())
        except ValueError as e:
            messagebox.showwarning("Same move", str(e))
            return
        for r in self.rows:
            if r.level.get():
                r.clear()
                r.set_values("by", v)

    def do_run(self, action):
        if not self.levels:
            messagebox.showinfo("Levels", "Click '1. Load levels' first.")
            return
        specs = self._specs()
        if not specs:
            return
        if action == "apply":
            lines = []
            for sp in specs:
                lv = self.level_by_name(sp.level)
                cur = from_ft(lv["elev"], self.units())
                new = sp.value if sp.mode == "to" else cur + sp.value
                lines.append("%s:  %s  ->  %s   (%s)" % (sp.level, fmt(cur, self.units()), fmt(new, self.units()),
                                                       fmt(new - cur, self.units(), True)))
            if not messagebox.askyesno("Apply", "Move these levels in %s?\n\n%s\n\nEvery element hosted to them keeps "
                                       "its position. One Undo entry in Revit." % (
                                           self.match.get().strip() or "the active model", "\n".join(lines))):
                return
        levels = self.levels

        def done(res):
            self._show_checks({"plan": "Check", "trial": "Trial run", "apply": "Apply"}[action], res)
            if action == "apply" and (res.info.get("result") or {}).get("committed"):
                for r in self.rows:
                    r.clear()
                self.do_levels()
        self._start({"plan": "Check", "trial": "Trial run", "apply": "Apply"}[action],
                    lambda r: r.run(action, levels, specs), done)

    def do_cancel(self):
        if self.busy:
            self.cancel.set()
            self.status.set("Cancelling -- Revit finishes (or rolls back) the call it is on.")


def main(argv=None):
    """``--model TEXT`` binds to the model whose title contains TEXT (the pyRevit button passes the
    model it was clicked from)."""
    argv = sys.argv[1:] if argv is None else argv
    model = argv[argv.index("--model") + 1] if "--model" in argv[:-1] else None
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    app = App(root)
    if model:
        app.match.set(model)
    root.mainloop()
    return 0

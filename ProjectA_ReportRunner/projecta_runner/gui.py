"""Tkinter window: Run tab (the 4-step workflow) and Setup tab (link local paths)."""

import os
import queue
import shlex
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .runner import (Runner, RunInputs, dated_folders,
                     export_files, guess_previous, log_time_saved, open_folder, today)
from .settings import PATH_KEYS, Settings

PAD = {"padx": 6, "pady": 3}

# (key, label, kind) -- kind: dir | py | exe | save
SETUP_FIELDS = [("netbuild_root", "Netbuild folder", "dir")] + \
    [(k, label, "py") for k, label in PATH_KEYS] + [
    ("python_exe", "Python (blank = auto)", "exe"),
    ("base_dir", "Issues BASE folder", "dir"),
    ("time_saved_log", "Time-saved log (.csv)", "save"),
]


class App(object):
    def __init__(self, root):
        self.root = root
        self.s = Settings()
        self.q = queue.Queue()
        self.busy = False
        self.extracted = None      # inputs dict of the last good extract
        self.session_start = time.time()
        self.output_folder = None

        root.title("ProjectA Issue Report Runner %s" % __version__)
        root.geometry("1100x780")
        root.minsize(900, 600)
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        self.run_tab = ttk.Frame(nb)
        self.setup_tab = ttk.Frame(nb)
        nb.add(self.run_tab, text="  Run  ")
        nb.add(self.setup_tab, text="  Setup / Paths  ")
        self._build_run_tab()
        self._build_setup_tab()
        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x")

        self._restore_last()
        self.root.after(100, self._poll)
        if not all(ok for _, _, ok in self.s.check_paths()[:6]):
            nb.select(self.setup_tab)
            self.status.set("Some script paths are not found -- link them on this tab, then Save.")

    # ------------------------------------------------------------ Run tab
    def _build_run_tab(self):
        f = ttk.LabelFrame(self.run_tab, text="Export")
        f.pack(fill="x", **PAD)
        f.columnconfigure(1, weight=1)

        self.base = tk.StringVar(value=self.s["base_dir"])
        ttk.Label(f, text="BASE").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Entry(f, textvariable=self.base).grid(row=0, column=1, sticky="ew", **PAD)
        ttk.Button(f, text="Browse...", command=self._pick_base).grid(row=0, column=2, **PAD)
        ttk.Button(f, text="Refresh", command=self._refresh_exports).grid(row=0, column=3, **PAD)

        self.export = tk.StringVar()
        ttk.Label(f, text="New export folder").grid(row=1, column=0, sticky="w", **PAD)
        self.export_cb = ttk.Combobox(f, textvariable=self.export, width=14)
        self.export_cb.grid(row=1, column=1, sticky="w", **PAD)
        self.export_cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_files(True))
        self.export_cb.bind("<FocusOut>", lambda e: self._refresh_files(False))

        self.acc_pdf = tk.StringVar()
        ttk.Label(f, text="ACC PDF").grid(row=2, column=0, sticky="w", **PAD)
        self.pdf_cb = ttk.Combobox(f, textvariable=self.acc_pdf, state="readonly")
        self.pdf_cb.grid(row=2, column=1, columnspan=3, sticky="ew", **PAD)

        ttk.Label(f, text="BCF(s)\n(select every BCF --\nACC caps at 250)").grid(
            row=3, column=0, sticky="nw", **PAD)
        self.bcf_lb = tk.Listbox(f, selectmode="multiple", height=4, exportselection=False)
        self.bcf_lb.grid(row=3, column=1, columnspan=3, sticky="ew", **PAD)

        ttk.Label(f, text="Issues").grid(row=4, column=0, sticky="w", **PAD)
        iss = ttk.Frame(f)
        iss.grid(row=4, column=1, sticky="w")
        self.issues_mode = tk.StringVar(value="all")
        self.max_id = tk.StringVar()
        ttk.Radiobutton(iss, text="All", value="all", variable=self.issues_mode).pack(side="left")
        ttk.Radiobutton(iss, text="Up to #", value="upto", variable=self.issues_mode).pack(side="left", padx=(12, 0))
        ttk.Entry(iss, textvariable=self.max_id, width=8).pack(side="left")

        self.previous = tk.StringVar(value="none")
        ttk.Label(f, text="Previous EXPORT folder\n(for 'movement since')").grid(row=5, column=0, sticky="w", **PAD)
        self.prev_cb = ttk.Combobox(f, textvariable=self.previous, width=14)
        self.prev_cb.grid(row=5, column=1, sticky="w", **PAD)
        ttk.Label(f, foreground="#666",
                  text="the export folder, not the report date (report 20261008_... was built from 20261009)"
                  ).grid(row=5, column=1, columnspan=3, sticky="e", **PAD)

        self.expected = tk.StringVar()
        ttk.Label(f, textvariable=self.expected, foreground="#555").grid(
            row=6, column=0, columnspan=4, sticky="w", **PAD)

        b = ttk.LabelFrame(self.run_tab, text="Steps")
        b.pack(fill="x", **PAD)
        self.buttons = []

        def btn(parent, text, cmd, **kw):
            w = ttk.Button(parent, text=text, command=cmd, **kw)
            self.buttons.append(w)
            return w

        r1 = ttk.Frame(b)
        r1.pack(fill="x")
        btn(r1, "1. Extract  (RUN_BUILD=False)", self.do_extract).pack(side="left", **PAD)
        btn(r1, "List issues with no Studio note", self.do_pending).pack(side="left", **PAD)
        btn(r1, "2. Build + 3. Verify  (RUN_EXTRACT=False)", self.do_build).pack(side="left", **PAD)
        btn(r1, "Verify only", self.do_verify).pack(side="left", **PAD)

        r2 = ttk.Frame(b)
        r2.pack(fill="x")
        ttk.Label(r2, text="Walkthrough args:").pack(side="left", **PAD)
        self.walk_args = tk.StringVar()
        e = ttk.Entry(r2, textvariable=self.walk_args)
        e.pack(side="left", fill="x", expand=True, **PAD)
        e.bind("<Return>", lambda ev: self.do_walk())
        btn(r2, "Run walkthrough (log Studio notes)", self.do_walk).pack(side="left", **PAD)
        ttk.Button(r2, text="Open output folder", command=self.do_open).pack(side="left", **PAD)
        ttk.Button(r2, text="Log time saved...", command=self.do_log_time).pack(side="left", **PAD)

        pw = ttk.PanedWindow(self.run_tab, orient="vertical")
        pw.pack(fill="both", expand=True, **PAD)
        cf = ttk.LabelFrame(pw, text="Checks")
        self.checks = tk.Text(cf, height=8, wrap="word", state="disabled")
        self.checks.pack(fill="both", expand=True)
        for tag, colour in (("ok", "#1b7f2a"), ("warn", "#b26a00"), ("fail", "#c62828"), ("head", "#000")):
            self.checks.tag_config(tag, foreground=colour)
        self.checks.tag_config("head", font=("Segoe UI", 9, "bold"))
        lf = ttk.LabelFrame(pw, text="Script output")
        self.out = ScrolledText(lf, height=16, wrap="none", font=("Consolas", 9))
        self.out.pack(fill="both", expand=True)
        pw.add(cf, weight=1)
        pw.add(lf, weight=3)

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
            ttk.Button(f, text="Browse...", command=lambda k=key, kd=kind: self._browse(k, kd)
                       ).grid(row=i, column=2, **PAD)
            mark = ttk.Label(f, width=10)
            mark.grid(row=i, column=3, sticky="w", **PAD)
            self.path_marks[key] = mark
            var.trace_add("write", lambda *a: self._check_paths())

        o = ttk.LabelFrame(self.setup_tab, text="Options")
        o.pack(fill="x", **PAD)
        o.columnconfigure(1, weight=1)
        self.pending_args = tk.StringVar(value=" ".join(self.s["walkthrough_pending_args"]))
        self.manual_min = tk.StringVar(value=str(self.s["time_saved_manual_minutes"]))
        self.by_model = tk.BooleanVar(value=bool(self.s["extra_globals"].get("BY_MODEL", True)))
        ttk.Label(o, text="Walkthrough 'pending' args").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Entry(o, textvariable=self.pending_args).grid(row=0, column=1, sticky="ew", **PAD)
        ttk.Label(o, text="Manual process (minutes)").grid(row=1, column=0, sticky="w", **PAD)
        ttk.Entry(o, textvariable=self.manual_min, width=8).grid(row=1, column=1, sticky="w", **PAD)
        ttk.Checkbutton(o, text="BY_MODEL=True  (also write the 'by Tier-Model' report)",
                        variable=self.by_model).grid(row=2, column=0, columnspan=2, sticky="w", **PAD)

        bar = ttk.Frame(self.setup_tab)
        bar.pack(fill="x", **PAD)
        ttk.Button(bar, text="Auto-find scripts in Netbuild folder", command=self._autofind).pack(side="left", **PAD)
        ttk.Button(bar, text="Check paths", command=self._check_paths).pack(side="left", **PAD)
        ttk.Button(bar, text="Save", command=self._save_settings).pack(side="left", **PAD)
        ttk.Label(self.setup_tab, foreground="#555", justify="left", text=(
            "Scripts may be absolute paths or relative to the Netbuild folder.\n"
            "Python must be the interpreter that has the scripts' packages installed "
            "(leave blank to use the one running this app).\n"
            "The runner reads these scripts but never edits them; CONFIG globals are set in memory per run."
        )).pack(anchor="w", **PAD)
        self._check_paths()

    def _browse(self, key, kind):
        cur = self.path_vars[key].get()
        start = cur if os.path.isdir(cur) else os.path.dirname(cur) or self.path_vars["netbuild_root"].get()
        if kind == "dir":
            p = filedialog.askdirectory(initialdir=start, title="Select folder")
        elif kind == "py":
            p = filedialog.askopenfilename(initialdir=start, filetypes=[("Python", "*.py"), ("All", "*.*")])
        elif kind == "exe":
            p = filedialog.askopenfilename(initialdir=start, filetypes=[("python.exe", "python*.exe"), ("All", "*.*")])
        else:
            p = filedialog.asksaveasfilename(initialdir=start, defaultextension=".csv",
                                             confirmoverwrite=False, filetypes=[("CSV", "*.csv")])
        if p:
            self.path_vars[key].set(os.path.normpath(p))

    def _apply_setup(self):
        for key, var in self.path_vars.items():
            self.s[key] = var.get().strip()
        self.s["walkthrough_pending_args"] = shlex.split(self.pending_args.get(), posix=False)
        try:
            self.s["time_saved_manual_minutes"] = float(self.manual_min.get())
        except ValueError:
            pass
        extra = dict(self.s["extra_globals"])
        extra["BY_MODEL"] = bool(self.by_model.get())
        self.s["extra_globals"] = extra

    def _check_paths(self):
        self._apply_setup()
        rows = dict((label, ok) for label, _, ok in self.s.check_paths())
        labels = dict((k, l) for k, l, _ in SETUP_FIELDS)
        names = {"netbuild_root": "Netbuild folder", "base_dir": "Issues BASE folder",
                 "python_exe": "Python", "time_saved_log": "Time-saved log (folder)"}
        for key, mark in self.path_marks.items():
            ok = rows.get(names.get(key, labels[key]))
            mark.config(text="found" if ok else "NOT FOUND", foreground="#1b7f2a" if ok else "#c62828")

    def _autofind(self):
        root = self.path_vars["netbuild_root"].get()
        if not os.path.isdir(root):
            messagebox.showwarning("Auto-find", "Link the Netbuild folder first.")
            return
        wanted = dict((os.path.basename(self.s.script(k)).lower(), k) for k, _ in PATH_KEYS)
        found = {}
        for dirpath, dirs, files in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            dirs[:] = [d for d in dirs if not d.startswith((".", "_")) and depth < 3]
            for fn in files:
                k = wanted.get(fn.lower())
                if k and k not in found:
                    found[k] = os.path.relpath(os.path.join(dirpath, fn), root)
        for k, rel in found.items():
            self.path_vars[k].set(rel)
        missing = [l for k, l in PATH_KEYS if k not in found]
        messagebox.showinfo("Auto-find", "Found %d of %d scripts.%s" % (
            len(found), len(PATH_KEYS), ("\nNot found: " + ", ".join(missing)) if missing else ""))

    def _save_settings(self):
        self._apply_setup()
        try:
            self.s.save()
        except OSError as e:
            messagebox.showerror("Save", str(e))
            return
        if self.base.get() != self.s["base_dir"] and messagebox.askyesno(
                "BASE", "Use the new BASE folder on the Run tab?"):
            self.base.set(self.s["base_dir"])
            self._refresh_exports()
        self.status.set("Settings saved to %s" % self.s.path)

    # ------------------------------------------------------------ form helpers
    def _pick_base(self):
        p = filedialog.askdirectory(initialdir=self.base.get())
        if p:
            self.base.set(os.path.normpath(p))
            self._refresh_exports()

    def _refresh_exports(self):
        folders = dated_folders(self.base.get())
        self.export_cb["values"] = folders
        if folders and self.export.get() not in folders:
            self.export.set(folders[0])
        self._refresh_files(True)

    def _refresh_files(self, reset_previous):
        exp = self.export.get().strip()
        pdfs, bcfs = export_files(os.path.join(self.base.get(), exp))
        self.pdf_cb["values"] = pdfs
        if self.acc_pdf.get() not in pdfs:
            self.acc_pdf.set(pdfs[0] if pdfs else "")
        self.bcf_lb.delete(0, "end")
        for b in bcfs:
            self.bcf_lb.insert("end", b)
        self.bcf_lb.select_set(0, "end")
        older = [n for n in dated_folders(self.base.get()) if n < exp]
        self.prev_cb["values"] = ["none"] + older
        if reset_previous:
            self.previous.set(guess_previous(self.base.get(), exp) or "none")
        self.expected.set("Output: BASE\\%s_ProjectA_ACC Issue detail (Issues <first>-<last>)\\  ->  complete report%s"
                          % (today(), " + by Tier-Model" if self.s["extra_globals"].get("BY_MODEL")
                             else "  (BY_MODEL off)"))

    def _inputs(self):
        sel = [self.bcf_lb.get(i) for i in self.bcf_lb.curselection()]
        upto = self.issues_mode.get() == "upto"
        if upto and not self.max_id.get().strip().lstrip("#").isdigit():
            raise ValueError("Enter the highest ACC issue id after 'Up to #'.")
        return RunInputs(self.base.get().strip(), self.export.get().strip(), self.acc_pdf.get(), sel,
                         self.max_id.get().strip().lstrip("#") if upto else None, self.previous.get())

    def _restore_last(self):
        last = self.s.load_last()
        if last.get("base"):
            self.base.set(last["base"])
        self._refresh_exports()
        if last.get("export_subdir") in self.export_cb["values"]:
            self.export.set(last["export_subdir"])
            self._refresh_files(False)
            self.previous.set(last.get("previous_subdir") or "none")
            if last.get("acc_pdf") in self.pdf_cb["values"]:
                self.acc_pdf.set(last["acc_pdf"])
            names = self.bcf_lb.get(0, "end")
            if set(last.get("bcf_files") or []) & set(names):
                self.bcf_lb.selection_clear(0, "end")
                for i, n in enumerate(names):
                    if n in last["bcf_files"]:
                        self.bcf_lb.select_set(i)
        if last.get("max_issue_id"):
            self.issues_mode.set("upto")
            self.max_id.set(str(last["max_issue_id"]))

    # ------------------------------------------------------------ worker plumbing
    def _start(self, label, fn, done):
        if self.busy:
            return
        self.busy = True
        for w in self.buttons:
            w.state(["disabled"])
        self.status.set("Running: %s ..." % label)
        self.out.insert("end", "\n===== %s  %s =====\n" % (label, time.strftime("%H:%M:%S")))
        self.out.see("end")
        runner = Runner(self.s, on_line=lambda line: self.q.put(("line", line)))

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
                    self.out.insert("end", payload + "\n")
                    self.out.see("end")
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
        self.checks.config(state="disabled")
        self.checks.see("end")

    def _validated_inputs(self):
        self._apply_setup()
        try:
            inp = self._inputs()
        except ValueError as e:
            messagebox.showwarning("Inputs", str(e))
            return None
        problems = inp.problems()
        if problems:
            messagebox.showwarning("Inputs", "\n".join(problems))
            return None
        self.s.save_last(inp.as_dict())
        return inp

    # ------------------------------------------------------------ actions
    def do_extract(self):
        inp = self._validated_inputs()
        if not inp:
            return

        def done(res):
            self._show_checks("Step 1 -- extract (%s)" % inp.export_subdir, res)
            if res.ok:
                self.extracted = inp.as_dict()
                self.status.set("Extract OK -- list issues with no Studio note, give notes or leave blank, then Build.")
        self._start("Extract", lambda r: r.extract(inp), done)

    def do_pending(self):
        self._apply_setup()
        self._start("Walkthrough pending", lambda r: r.pending(),
                    lambda res: self._show_checks("Issues with no Studio note -- see Script output", res, clear=False))

    def do_walk(self):
        self._apply_setup()
        args = shlex.split(self.walk_args.get(), posix=True)
        if not args:
            messagebox.showinfo("Walkthrough", "Type the walkthrough arguments first, e.g.  pending  or your note command.")
            return
        self._start("Walkthrough " + " ".join(args), lambda r: r.walkthrough(args),
                    lambda res: self._show_checks("Walkthrough " + " ".join(args), res, clear=False))

    def do_build(self):
        inp = self._validated_inputs()
        if not inp:
            return
        if self.extracted != inp.as_dict() and not messagebox.askyesno(
                "Build", "Step 1 (extract) has not run for these inputs in this session.\nBuild anyway?"):
            return
        locked = Runner(self.s).locked_pdfs(inp.base)
        if locked:
            messagebox.showwarning("Close PDFs first", "These PDFs are open in your viewer, so the move to "
                                   "%s would stop:\n\n%s\n\nClose them, then click Build again."
                                   % (self.s["superseded_dir"], "\n".join(locked)))
            return

        def done(res):
            self._show_checks("Step 2 -- build", res)
            self.output_folder = res.info.get("output_folder")
            if res.info.get("locked"):
                messagebox.showwarning("Close PDFs", "The move to %s stopped because a PDF is open in your "
                                       "viewer. Close it, then click Build again." % self.s["superseded_dir"])
            elif res.ok and self.output_folder:
                self.do_verify(clear=False)
        self._start("Build", lambda r: r.build(inp), done)

    def do_verify(self, clear=True):
        self._apply_setup()
        folder = self.output_folder or Runner(self.s).output_folder(self.base.get())
        if not folder:
            folder = filedialog.askdirectory(initialdir=self.base.get(), title="Report folder to verify")
            if not folder:
                return
        folder = os.path.normpath(folder)
        self.output_folder = folder

        def done(res):
            self._show_checks("Step 3 -- verify  %s" % folder, res, clear=clear)
            self.checks.config(state="normal")
            self.checks.insert("end", "Spot-check the After image on issues with 2-3 attachment photos "
                                      "(Open output folder). Close the PDFs afterwards.\n", "warn")
            self.checks.config(state="disabled")
        self._start("Verify", lambda r: r.verify(folder), done)

    def do_open(self):
        folder = self.output_folder or Runner(self.s).output_folder(self.base.get()) or self.base.get()
        if os.path.isdir(folder):
            open_folder(folder)

    def do_log_time(self):
        self._apply_setup()
        d = tk.Toplevel(self.root)
        d.title("Log time saved")
        d.transient(self.root)
        elapsed = round((time.time() - self.session_start) / 60.0)
        fields = [("Export", self.export.get()), ("Issues", ""), ("Actual minutes", str(elapsed)),
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
                    "export": vars_["Export"].get(), "issues": vars_["Issues"].get(),
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

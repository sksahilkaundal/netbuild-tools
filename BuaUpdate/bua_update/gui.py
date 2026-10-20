"""Tkinter window: Update tab (folder, files, Check / Update, the checks), About and Licence tabs."""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import about
from .engine import AUTO, PROFILES, UpdateError, find_files, update
from .settings import Settings

PAD = {"padx": 6, "pady": 3}
COLOURS = {"ok": "#1b7f2a", "warn": "#b26a00", "fail": "#c62828", "head": "#000"}
BANNER = {"done": ("#e6f4ea", COLOURS["ok"]), "checked": ("#e8eef7", "#1f4e8c"),
          "new_items": ("#fff4e0", COLOURS["warn"]), "skipped": ("#fdecea", COLOURS["fail"]),
          "mismatch": ("#fdecea", COLOURS["fail"]), "error": ("#fdecea", COLOURS["fail"])}
TYPICAL_CHOICES = [AUTO] + list(PROFILES)


def open_path(path):
    if not path:
        return
    if os.name == "nt":
        os.startfile(path)  # noqa -- Windows only
    else:
        subprocess.Popen(["xdg-open", path])


def advice(res):
    """What to do next, in the words of the project's prompt."""
    if res.status == "done":
        return ("Both workbooks updated and every BUA / GFA total ties out to the raw.\n"
                "Overall BUA %s SQM   |   GFA %s SQM" % ("{:,.2f}".format(res.totals["bua"]),
                                                       "{:,.2f}".format(res.totals["gfa"])))
    if res.status == "new_items":
        items = []
        if res.new_components:
            items.append("GFA Components: " + ", ".join(res.new_components))
        if res.new_cats:
            items.append("Space/Room Categories: " + ", ".join(res.new_cats))
        return ("The raw has items that are NOT in the frozen format -- %s.\n%s SQM BUA is excluded from the "
                "workbooks. Nothing is added to the frozen lists automatically: fix the rows in Revit (listed "
                "below), or decide to add them and tell the other disciplines." % (
                    "; ".join(items), "{:,.2f}".format(res.excluded_bua)))
    if res.status == "skipped":
        return ("Close this workbook in Excel, then click Retry:\n" +
                "\n".join("  %s" % os.path.basename(p) for _, p in res.skipped))
    if res.status == "mismatch":
        return ("*** MISMATCH *** -- the totals do not tie out (see below). Stop here: check the raw and the "
                "Levels in Revit before changing the workbooks." +
                ("\nThe typical-floor set leaves some levels out -- try the other set."
                 if res.level_conflicts else ""))
    if res.status == "checked":
        return res.summary()
    return "Error: %s" % res.error


class App(object):
    def __init__(self, root):
        self.root = root
        self.s = Settings()
        self.q = queue.Queue()
        self.busy = False
        self.last = None

        root.title(about.title())
        root.geometry("1100x820")
        root.minsize(900, 600)
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self.run_tab, self.about_tab, self.licence_tab = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.run_tab, text="  Update  ")
        nb.add(self.about_tab, text="  About  ")
        nb.add(self.licence_tab, text="  Licence  ")
        self._build_run_tab()
        self._build_about_tab()
        self._build_licence_tab()
        self.status = tk.StringVar(value="Close both Option workbooks in Excel (the raw may stay open), then Update.")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x")
        self.detect()
        self.root.after(100, self._poll)

    # ------------------------------------------------------------ Update tab
    def _build_run_tab(self):
        f = ttk.LabelFrame(self.run_tab, text="Project folder and files")
        f.pack(fill="x", **PAD)
        f.columnconfigure(1, weight=1)
        self.vars = {}
        for i, (key, label, browse) in enumerate((
                ("folder", "Folder", self.pick_folder),
                ("raw", "Raw Revit export", lambda: self.pick_file("raw")),
                ("option1", "Option 1 workbook", lambda: self.pick_file("option1")),
                ("option2", "Option 2 workbook", lambda: self.pick_file("option2")))):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", **PAD)
            v = tk.StringVar(value=self.s.project_folder() if key == "folder" else self.s[key])
            self.vars[key] = v
            ttk.Entry(f, textvariable=v).grid(row=i, column=1, sticky="ew", **PAD)
            ttk.Button(f, text="Browse...", command=browse).grid(row=i, column=2, **PAD)
        ttk.Label(f, foreground="#555", text="files left blank are found in the folder").grid(
            row=4, column=1, sticky="w", **PAD)
        o = ttk.Frame(f)
        o.grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Label(o, text="Typical floors").pack(side="left", **PAD)
        self.typical = tk.StringVar(value=self.s["typical"] if self.s["typical"] in TYPICAL_CHOICES else AUTO)
        ttk.Combobox(o, textvariable=self.typical, values=TYPICAL_CHOICES, state="readonly", width=10).pack(
            side="left", **PAD)
        ttk.Label(o, foreground="#555", text="auto picks the set that fits the raw:   %s" % "   |   ".join(
            "%s = %s" % (k, p["label"].split(" (")[0]) for k, p in PROFILES.items())).pack(side="left", **PAD)
        self.backup = tk.BooleanVar(value=bool(self.s["backup"]))
        ttk.Checkbutton(f, text="Back up both workbooks to <folder>\\Backup\\<date_time>\\ before writing",
                        variable=self.backup).grid(row=6, column=0, columnspan=3, sticky="w", **PAD)

        a = ttk.Frame(self.run_tab)
        a.pack(fill="x", **PAD)
        self.buttons = []
        for text, cmd in (("Check (writes nothing)", lambda: self.run(False)),
                          ("Update workbooks", lambda: self.run(True))):
            b = ttk.Button(a, text=text, command=cmd)
            b.pack(side="left", **PAD)
            self.buttons.append(b)
        self.retry_btn = ttk.Button(a, text="Retry", command=lambda: self.run(True))
        self.buttons.append(self.retry_btn)
        ttk.Button(a, text="Open folder", command=lambda: open_path(self.vars["folder"].get())).pack(
            side="right", **PAD)
        self.open1 = ttk.Button(a, text="Open Option 1", command=lambda: self.open_file("option1"))
        self.open2 = ttk.Button(a, text="Open Option 2", command=lambda: self.open_file("option2"))
        self.open2.pack(side="right", **PAD)
        self.open1.pack(side="right", **PAD)

        self.banner = tk.Label(self.run_tab, text="", anchor="w", justify="left", font=("Segoe UI", 10, "bold"),
                               padx=10, pady=8, wraplength=1000)
        self.banner.pack(fill="x", **PAD)
        lf = ttk.LabelFrame(self.run_tab, text="Checks (read-only log)")
        lf.pack(fill="both", expand=True, **PAD)
        self.out = ScrolledText(lf, height=18, wrap="none", font=("Consolas", 9), state="disabled")
        self.out.pack(fill="both", expand=True)
        for tag, colour in COLOURS.items():
            self.out.tag_config(tag, foreground=colour)
        self.out.tag_config("head", font=("Consolas", 9, "bold"))

    def pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.vars["folder"].get() or None, title="Project folder")
        if d:
            self.vars["folder"].set(os.path.normpath(d))
            for k in ("raw", "option1", "option2"):
                self.vars[k].set("")
            self.detect()

    def pick_file(self, key):
        p = filedialog.askopenfilename(initialdir=self.vars["folder"].get() or None,
                                       filetypes=[("Excel workbook", "*.xlsx")])
        if p:
            self.vars[key].set(os.path.normpath(p))

    def files(self):
        """(folder, raw, option1, option2) as typed -- blanks are found by the engine."""
        return tuple(self.vars[k].get().strip() or None for k in ("folder", "raw", "option1", "option2"))

    def detect(self):
        """Show which files a run would use."""
        folder, raw, o1, o2 = self.files()
        if not folder:
            self.set_banner("error", "Pick the project folder (the one with the raw export and both workbooks).")
            return None
        try:
            found = find_files(folder, raw, o1, o2)
        except UpdateError as e:
            self.set_banner("error", str(e))
            return None
        self.set_banner("checked", "Ready:\n  %s\n  %s\n  %s" % tuple(os.path.basename(found[k]) for k in
                                                                    ("raw", "option1", "option2")))
        return found

    def open_file(self, key):
        found = self.detect()
        if found:
            open_path(found[key])

    def set_banner(self, status, text):
        bg, fg = BANNER[status]
        self.banner.config(text=text, bg=bg, fg=fg)
        if status == "skipped":
            self.retry_btn.pack(side="left", **PAD)
        else:
            self.retry_btn.pack_forget()

    def _save(self):
        for k in ("folder", "raw", "option1", "option2"):
            self.s[k] = self.vars[k].get().strip()
        self.s["typical"] = self.typical.get()
        self.s["backup"] = bool(self.backup.get())
        try:
            self.s.save()
        except OSError:
            pass

    def run(self, write):
        if self.busy:
            return
        folder, raw, o1, o2 = self.files()
        if not folder and not (raw and o1 and o2):
            messagebox.showinfo(about.PRODUCT, "Pick the project folder first.")
            return
        self._save()
        self.busy = True
        for b in self.buttons:
            b.state(["disabled"])
        label = "Update" if write else "Check"
        self.status.set("Running: %s ..." % label)
        self._log("\n===== %s  %s =====" % (label, time.strftime("%H:%M:%S")), "head")
        typical, make_backup = self.typical.get(), bool(self.backup.get())

        def work():
            try:
                res = update(folder, raw, o1, o2, typical=typical, make_backup=make_backup, write=write,
                             log=lambda text, tag=None: self.q.put(("line", (text, tag))))
                self.q.put(("done", (res, None)))
            except Exception as e:  # shown, never swallowed
                self.q.put(("done", (None, e)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    self._log(*payload)
                    continue
                res, err = payload
                self.busy = False
                for b in self.buttons:
                    b.state(["!disabled"])
                if err:
                    self.status.set("Error")
                    self.set_banner("error", "%s: %s" % (type(err).__name__, err))
                    messagebox.showerror(about.PRODUCT, "%s: %s" % (type(err).__name__, err))
                else:
                    self.last = res
                    self.status.set(res.summary())
                    self.set_banner(res.status, advice(res))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _log(self, text, tag=None):
        self.out.config(state="normal")
        self.out.insert("end", text + "\n", tag or ())
        self.out.config(state="disabled")
        self.out.see("end")

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
        ttk.Label(f, text="Licence: %s -- see the Licence tab" % about.LICENSE_NAME).pack(anchor="w", pady=(8, 0))
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Copy product info", command=self._copy_about).pack(side="left", **PAD)
        ttk.Button(bar, text="Licence", command=lambda: self.nb.select(self.licence_tab)).pack(side="left", **PAD)
        ttk.Button(bar, text="Open %s" % about.WEBSITE,
                   command=lambda: webbrowser.open(about.WEBSITE)).pack(side="left", **PAD)

    def _copy_about(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(about.about_text())
        self.status.set("Product info, requirements and licence copied to the clipboard.")

    # ------------------------------------------------------------ Licence tab
    def _build_licence_tab(self):
        f = ttk.Frame(self.licence_tab)
        f.pack(fill="both", expand=True, padx=14, pady=10)
        ttk.Label(f, text="Licence", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(f, text="%s  version %s" % (about.PRODUCT, about.VERSION)).pack(anchor="w", pady=(2, 0))
        ttk.Label(f, text=about.LICENSE_KIND, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 0))
        ttk.Label(f, text="%s   |   Website: %s" % (about.COPYRIGHT, about.WEBSITE),
                  foreground="#555").pack(anchor="w")
        ttk.Label(f, text=about.LICENCE_KEY).pack(anchor="w", pady=(2, 8))
        lf = ttk.LabelFrame(f, text=about.LICENSE_NAME)
        lf.pack(fill="both", expand=True)
        self.license_box = ScrolledText(lf, height=20, wrap="word", font=("Consolas", 9))
        self.license_box.insert("1.0", about.LICENSE_TEXT)
        self.license_box.config(state="disabled")
        self.license_box.pack(fill="both", expand=True)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Copy licence", command=self._copy_licence).pack(side="left", **PAD)
        ttk.Button(bar, text="Open %s" % about.WEBSITE,
                   command=lambda: webbrowser.open(about.WEBSITE)).pack(side="left", **PAD)

    def _copy_licence(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(about.LICENSE_TEXT)
        self.status.set("Licence agreement copied to the clipboard.")


def main(argv=None):
    """``--folder DIR`` opens on that project folder (the pyRevit button passes none)."""
    argv = sys.argv[1:] if argv is None else argv
    folder = argv[argv.index("--folder") + 1] if "--folder" in argv[:-1] else None
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    app = App(root)
    if folder:
        app.vars["folder"].set(folder)
        app.detect()
    root.mainloop()
    return 0

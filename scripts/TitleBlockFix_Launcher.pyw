# -*- coding: utf-8 -*-
"""
Desktop launcher for the Title Block Fix pipeline.

Pick an issue folder, choose PDF only / CAD only / both, run. Corrected copies go to an
"Updated" subfolder inside the project's PDF and DWG folders;
originals are never touched. Project specifics come from a JSON profile.

Runs the same three scripts as TitleBlockFix_Pipeline.py -- this only
adds a UI and wires the folders through, so there is one implementation of
the actual logic, not two.

Launch with TitleBlockFix.bat (or pythonw TitleBlockFix_Launcher.pyw).
"""
import json
import os
import queue
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

if getattr(sys, "frozen", False):
    # PyInstaller: modules live in the unpacked bundle, but settings must
    # sit next to the .exe -- the bundle dir is a temp folder that is
    # deleted on exit.
    HERE = sys._MEIPASS
    BESIDE_EXE = os.path.dirname(sys.executable)
else:
    HERE = BESIDE_EXE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SETTINGS = os.path.join(BESIDE_EXE, "TitleBlockFix_settings.json")

import TitleBlockFix_Config as cfg

try:
    import revittools_theme as rt          # bundled when frozen
except ImportError:                        # running from source: project\design
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "design"))
    import revittools_theme as rt


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Title Block Fix")
        self.geometry("880x600")
        self.minsize(720, 480)
        rt.apply(self)                      # light / dark, following Windows
        self.q = queue.Queue()
        self.worker = None
        self._build()
        self._reload_profiles()
        self._load_settings()
        # wide enough for the profile row (Helvetica runs wider than the old UI font)
        self.update_idletasks()
        self.geometry("%dx600" % max(960, self.winfo_reqwidth() + 20))
        self.after(100, self._drain)

    # ---------------------------------------------------------------- UI
    def _build(self):
        pad = dict(padx=10, pady=6)

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Issue folder").pack(side="left")
        self.folder = tk.StringVar()
        ttk.Entry(top, textvariable=self.folder).pack(
            side="left", fill="x", expand=True, padx=8)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left")

        prow = ttk.Frame(self)
        prow.pack(fill="x", padx=10)
        ttk.Label(prow, text="Project").pack(side="left")
        self.profile = tk.StringVar()
        self.profile_box = ttk.Combobox(prow, textvariable=self.profile,
                                        state="readonly", width=28)
        self.profile_box.pack(side="left", padx=8)
        self.profile_box.bind("<<ComboboxSelected>>", lambda e: self._describe_profile())
        ttk.Button(prow, text="Edit…", command=self._edit_profile).pack(side="left")
        ttk.Button(prow, text="New…", command=self._new_profile).pack(side="left", padx=4)
        ttk.Button(prow, text="Reload", command=self._reload_profiles).pack(side="left")
        self.profile_desc = ttk.Label(prow, text="", style=rt.style_for("ink-muted"))
        self.profile_desc.pack(side="left", padx=10)

        self.status = ttk.Label(self, text="", style=rt.style_for("ink-muted"))
        self.status.pack(fill="x", padx=10)

        opts = ttk.LabelFrame(self, text="What to fix")
        opts.pack(fill="x", **pad)

        self.mode = tk.StringVar(value="both")
        self.do_ver = tk.BooleanVar(value=True)
        self.do_plot = tk.BooleanVar(value=False)   # slow; opt in
        self.dry = tk.BooleanVar(value=True)

        mrow = ttk.Frame(opts)
        mrow.pack(anchor="w", padx=10, pady=(8, 2))
        for text, val in (("PDF only", "pdf"),
                          ("CAD only", "cad"),
                          ("PDF + CAD", "both")):
            ttk.Radiobutton(mrow, text=text, value=val, variable=self.mode,
                            style="Mode.Toolbutton", command=self._mode_changed
                            ).pack(side="left", padx=(0, 6))
        self.mode_hint = ttk.Label(opts, text="", style=rt.style_for("ink-muted"))
        self.mode_hint.pack(anchor="w", padx=10, pady=(0, 4))

        ttk.Separator(opts).pack(fill="x", pady=4)
        ttk.Checkbutton(opts, text="Verify afterwards   (PDF geometry vs original, and PDF vs CAD values)",
                        variable=self.do_ver).pack(anchor="w", padx=10, pady=2)
        self.plot_cb = ttk.Checkbutton(
            opts, text="Also plot PDFs from the corrected CAD   "
                       "(slow — for visual checking, not the deliverable)",
            variable=self.do_plot)
        self.plot_cb.pack(anchor="w", padx=10, pady=2)
        ttk.Checkbutton(opts, text="Dry run — report only, write nothing",
                        variable=self.dry).pack(anchor="w", padx=10, pady=(0, 6))
        self._mode_changed()

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.run_btn = ttk.Button(bar, text="Run", command=self._run)
        self.run_btn.pack(side="left")
        ttk.Button(bar, text="Open output folder",
                   command=self._open_out).pack(side="left", padx=8)
        ttk.Button(bar, text="Clear log",
                   command=lambda: self.log.delete("1.0", "end")).pack(side="left")
        rt.theme_picker(bar).pack(side="right")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=(0, 16))

        self.log = rt.console(self)          # tags: ok / err / hdr
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        sb = ttk.Scrollbar(self.log, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)

    # ---------------------------------------------------------------- mode
    def _pdf_on(self):
        return self.mode.get() in ("pdf", "both")

    def _cad_on(self):
        return self.mode.get() in ("cad", "both")

    def _mode_changed(self):
        hints = {
            "pdf": "Fixes the exported PDFs only. Needs nothing but this app.",
            "cad": "Fixes the exported DWGs only. AutoCAD must be running "
                   "with NO drawings open.",
            "both": "Fixes both, then cross-checks them against each other. "
                    "AutoCAD must be running with NO drawings open.",
        }
        self.mode_hint.config(text=hints[self.mode.get()])
        # Verify compares the two formats, so it only makes sense after both
        # have run. Still leave it tickable: a PDF-only run can verify against
        # a CAD log from an earlier session.
        self.do_ver.set(self.mode.get() == "both")
        # Plotting reads Step 2's output, so there is nothing to plot on a
        # PDF-only run.
        if self._cad_on():
            self.plot_cb.state(["!disabled"])
        else:
            self.do_plot.set(False)
            self.plot_cb.state(["disabled"])

    def _browse(self):
        d = filedialog.askdirectory(title="Select the issue folder (the one CONTAINING the PDF and DWG folders)",
                                    initialdir=self.folder.get() or os.path.expanduser("~"))
        if d:
            self.folder.set(os.path.normpath(d))
            self._check_folder()

    # ------------------------------------------------------------ profiles
    def _reload_profiles(self):
        cfg.ensure_profiles(BESIDE_EXE)
        names = cfg.list_profiles(BESIDE_EXE)
        self.profile_box["values"] = names
        if self.profile.get() not in names:
            self.profile.set(names[0] if names else "")
        self._describe_profile()
        self._check_folder()

    def _active_profile(self):
        """Load the selected profile and make it active. Returns it, or None."""
        name = self.profile.get()
        if not name:
            return None
        try:
            prof = cfg.load(BESIDE_EXE, name)
        except Exception as exc:
            messagebox.showerror("Profile problem", "%s.json:\n\n%s" % (name, exc))
            return None
        cfg.set_active(prof)
        return prof

    def _describe_profile(self):
        prof = self._active_profile()
        if not prof:
            self.profile_desc.config(text="no profile — click New…", style=rt.style_for("state-down"))
            return
        f = prof["folders"]
        self.profile_desc.config(
            text="%s / %s  ->  %s   (%d model-ref rules)"
                 % (f["pdf"], f["dwg"], f["output"], len(prof["model_ref"]["rules"])),
            style=rt.style_for("ink-muted"))
        self._check_folder()

    def _edit_profile(self):
        name = self.profile.get()
        if not name:
            return
        os.startfile(os.path.join(cfg.profiles_dir(BESIDE_EXE), name + ".json"))
        self._emit("Opened %s.json — save it, then click Reload." % name, "hdr")

    def _new_profile(self):
        name = simpledialog.askstring("New project profile",
                                      "Name for the new profile (e.g. the project code):",
                                      parent=self)
        if not name:
            return
        name = "".join(c for c in name if c.isalnum() or c in " _-").strip()
        path = os.path.join(cfg.ensure_profiles(BESIDE_EXE), name + ".json")
        if os.path.exists(path):
            messagebox.showerror("Already exists", "%s.json already exists." % name)
            return
        prof = json.loads(json.dumps(cfg.DEFAULT_PROFILE))   # deep copy
        prof["name"] = name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prof, f, indent=2)
        self._reload_profiles()
        self.profile.set(name)
        self._describe_profile()
        os.startfile(path)
        messagebox.showinfo(
            "Edit the new profile",
            "%s.json was created from the example and opened for editing.\n\n"
            "Change the folder names, filename positions, skip zones, revision "
            "wording and model-ref rules to match this project, save, then click "
            "Reload." % name)

    def _check_folder(self):
        root = self.folder.get()
        prof = cfg.active()
        PDF_SUB, DWG_SUB = prof["folders"]["pdf"], prof["folders"]["dwg"]
        pdf_n = dwg_n = 0
        if os.path.isdir(os.path.join(root, PDF_SUB)):
            pdf_n = len([f for f in os.listdir(os.path.join(root, PDF_SUB))
                         if f.lower().endswith(".pdf")])
        if os.path.isdir(os.path.join(root, DWG_SUB)):
            dwg_n = len([f for f in os.listdir(os.path.join(root, DWG_SUB))
                         if f.lower().endswith(".dwg")])
        if pdf_n or dwg_n:
            self.status.config(text="Found %d PDF and %d DWG" % (pdf_n, dwg_n),
                               style=rt.style_for("success-text"))
        else:
            self.status.config(
                text="No %s\\*.pdf or %s\\*.dwg here — pick the folder that CONTAINS those two."
                     % (PDF_SUB, DWG_SUB), style=rt.style_for("state-down"))
        return pdf_n, dwg_n

    def _open_out(self):
        root = self.folder.get()
        f = cfg.active()["folders"]
        candidates = [os.path.join(root, sub, cfg.folder("output"))
                      for sub in (f["pdf"], f["dwg"])]
        if self.do_plot.get():
            candidates.insert(0, os.path.join(root, cfg.folder("plot")))
        for p in candidates:
            if os.path.isdir(p):
                os.startfile(p)
                return
        messagebox.showinfo("Nothing yet", "No Updated folder yet — run the pipeline first.")

    # ------------------------------------------------------------ plumbing
    def _load_settings(self):
        try:
            with open(SETTINGS) as f:
                data = json.load(f)
                self.folder.set(data.get("folder", ""))
                if data.get("profile") in (self.profile_box["values"] or ()):
                    self.profile.set(data["profile"])
                    self._describe_profile()
                if data.get("mode") in ("pdf", "cad", "both"):
                    self.mode.set(data["mode"])
                    self._mode_changed()      # may disable+clear do_plot
                if self._cad_on():
                    self.do_plot.set(bool(data.get("plot", False)))
            self._check_folder()
        except Exception:
            pass

    def _save_settings(self):
        try:
            with open(SETTINGS, "w") as f:
                json.dump({"folder": self.folder.get(),
                           "profile": self.profile.get(),
                           "mode": self.mode.get(),
                           "plot": self.do_plot.get()}, f)
        except Exception:
            pass

    def _emit(self, text, tag=None):
        self.q.put((text, tag))

    def _drain(self):
        try:
            while True:
                text, tag = self.q.get_nowait()
                if text is None:                      # worker finished
                    self.run_btn.config(state="normal")
                    self.progress.stop()
                    continue
                self.log.insert("end", text + "\n", tag or ())
                self.log.see("end")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _run(self):
        root = self.folder.get()
        if not os.path.isdir(root):
            messagebox.showerror("Pick a folder", "Choose the issue folder first.")
            return
        pdf_n, dwg_n = self._check_folder()
        if self._pdf_on() and not pdf_n:
            messagebox.showerror("No PDFs", "No PDFs found in %s." % cfg.active()["folders"]["pdf"])
            return
        if self._cad_on() and not dwg_n:
            messagebox.showerror("No DWGs", "No DWGs found in %s." % cfg.active()["folders"]["dwg"])
            return
        if not self.dry.get():
            what = [n for n, on in (("PDFs", self._pdf_on()), ("DWGs", self._cad_on())) if on]
            if what and not messagebox.askyesno(
                    "Write files?",
                    "This will WRITE corrected %s into the '%s' subfolders.\n\n"
                    "Originals are not modified. Continue?" % (" and ".join(what), cfg.active()["folders"]["output"])):
                return
        self._save_settings()
        self.run_btn.config(state="disabled")
        self.progress.start(12)
        self.worker = threading.Thread(target=self._work, args=(root,), daemon=True)
        self.worker.start()

    # -------------------------------------------------------------- worker
    def _work(self, root):
        class Tee:
            def __init__(self, emit): self.emit, self.buf = emit, ""
            def write(self, s):
                self.buf += s
                while "\n" in self.buf:
                    line, self.buf = self.buf.split("\n", 1)
                    tag = "err" if ("ERROR" in line or "Traceback" in line) else None
                    self.emit(line, tag)
            def flush(self): pass

        f = cfg.active()["folders"]
        pdf_dir = os.path.join(root, f["pdf"])
        dwg_dir = os.path.join(root, f["dwg"])
        out_sub = f["output"]
        cad_log = os.path.join(root, "_titleblockfix_cad.log")
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = Tee(self._emit)
        try:
            dry = self.dry.get()
            if dry:
                self._emit("DRY RUN — nothing will be written.", "hdr")

            if self._pdf_on():
                self._emit("\n=== Step 1  PDF titleblock fix ===", "hdr")
                import TitleBlockFix_PDF as pdffix
                pdffix.SRC_FOLDER = pdf_dir
                pdffix.OUT_FOLDER = os.path.join(pdf_dir, out_sub)
                pdffix.DRY_RUN = dry
                pdffix.main()

            if self._cad_on():
                self._emit("\n=== Step 2  CAD titleblock fix ===", "hdr")
                import pythoncom
                pythoncom.CoInitialize()          # COM must be init'd per thread
                try:
                    import TitleBlockFix_DWG as dwgfix
                    dwgfix.SRC_FOLDER = dwg_dir
                    dwgfix.OUT_FOLDER = os.path.join(dwg_dir, out_sub)
                    dwgfix.DRY_RUN = dry
                    buf = []
                    real = sys.stdout
                    class Cap:
                        def write(self, s): buf.append(s); real.write(s)
                        def flush(self): pass
                    sys.stdout = Cap()
                    try:
                        dwgfix.main()
                    finally:
                        sys.stdout = real
                    if not dry:
                        # the verifier reads this log to learn what CAD wrote
                        with open(cad_log, "w", encoding="utf-8") as f:
                            f.write("".join(buf))
                except Exception:
                    self._emit(traceback.format_exc(), "err")
                    self._emit("Is AutoCAD running with no drawings open?", "err")
                finally:
                    pythoncom.CoUninitialize()

            if self.do_plot.get() and self._cad_on():
                self._emit("\n=== Step 2b  Plot PDFs from corrected CAD ===", "hdr")
                import pythoncom
                pythoncom.CoInitialize()
                try:
                    import TitleBlockFix_Plot as plot
                    plot.SRC_FOLDER = os.path.join(dwg_dir, out_sub)
                    plot.OUT_FOLDER = os.path.join(root, cfg.folder("plot"))
                    plot.DRY_RUN = dry
                    plot.main()
                except Exception:
                    self._emit(traceback.format_exc(), "err")
                finally:
                    pythoncom.CoUninitialize()

            if self.do_ver.get():
                # 3a. geometry of the edited PDFs vs the untouched originals:
                # no line lost, no shift, no overflow, no collision. Needs
                # only the PDF step. This is the check that caught text
                # spilled over a divider on 110 sheets that the value
                # check below had passed.
                self._emit("\n=== Step 3a  Verify PDF geometry vs original ===", "hdr")
                edited = os.path.join(pdf_dir, out_sub)
                if not os.path.isdir(edited):
                    self._emit("No edited PDFs yet — run Step 1 (not as a dry run) first.", "err")
                else:
                    try:
                        import TitleBlockFix_VerifyGeometry as geo
                        geo.ORIG_DIR = pdf_dir
                        geo.EDIT_DIR = edited
                        plot_dir = os.path.join(root, cfg.folder("plot"))
                        geo.PLOT_DIR = plot_dir if os.path.isdir(plot_dir) else ""
                        geo.main()
                    except Exception:
                        self._emit(traceback.format_exc(), "err")

                # 3b. values agree between PDF and CAD. Needs the CAD log.
                self._emit("\n=== Step 3b  Verify PDF vs CAD values ===", "hdr")
                if not os.path.exists(cad_log):
                    self._emit("No CAD log yet — run Step 2 (not as a dry run) first.", "err")
                else:
                    import pythoncom
                    pythoncom.CoInitialize()
                    try:
                        import TitleBlockFix_Verify as ver
                        ver.PDF_DIR = edited
                        ver.DWG_DIR = os.path.join(dwg_dir, out_sub)
                        ver.CAD_LOG = cad_log
                        ver.main()
                    except Exception:
                        self._emit(traceback.format_exc(), "err")
                    finally:
                        pythoncom.CoUninitialize()

            self._emit("\nDone.", "ok")
        except Exception:
            self._emit(traceback.format_exc(), "err")
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            self.q.put((None, None))


def selftest():
    """--selftest: confirm the bundled step modules import in the frozen
    app and write the result next to the exe. The GUI is windowed, so
    there is no console to print to."""
    lines = []
    for mod in ("fitz", "win32com.client", "pythoncom", "TitleBlockFix_Config",
                "TitleBlockFix_PDF", "TitleBlockFix_DWG",
                "TitleBlockFix_Verify", "TitleBlockFix_VerifyGeometry",
                "TitleBlockFix_Plot", "revittools_theme"):
        try:
            __import__(mod)
            lines.append("OK      " + mod)
        except Exception as exc:
            lines.append("FAILED  %s -> %s" % (mod, exc))
    try:
        cfg.ensure_profiles(BESIDE_EXE)
        names = cfg.list_profiles(BESIDE_EXE)
        lines.append("OK      profiles folder -> %s" % (names or "(empty)"))
        # a profile must actually drive routing, not just parse
        cfg.set_active(cfg.load(BESIDE_EXE, names[0]))
        val, why = cfg.model_ref_for_filename("A-B-C-SW00-ZZZ-E-750001_B.pdf")
        lines.append("OK      routing sample -> %s%s" % (val, "" if val else " (%s)" % why))
    except Exception as exc:
        lines.append("FAILED  profiles -> %s" % exc)
    lines.append("frozen=%s" % getattr(sys, "frozen", False))
    out = os.path.join(BESIDE_EXE, "selftest_result.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        Launcher().mainloop()

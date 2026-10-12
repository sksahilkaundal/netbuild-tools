# -*- coding: utf-8 -*-
"""
BUA Workbook Builder - app core (GUI + licence gate). Compiled to a .pyd for
release; BuaWorkbookBuilder_Launcher.pyw is only a 3-line entry stub.

Pick a raw Area export and build the pivot workbook, FROZEN component/category
columns throughout. Two output layouts (default Option 1):
    Option 1 - one combined "Overall BUA" sheet, all Building Assets stacked
               (section header, that asset's own levels, "<Asset> Total"
               subtotal, blank separator), Grand Total row at the end.
    Option 2 - one sheet per Building Asset, own levels only.
Parameter checks (new-item banner + BUA/GFA tie-out) print to the log before
you open the result. No install, no admin rights, no separate Python needed
once built with PyInstaller --onefile --windowed.

    "BUA Workbook Builder.exe" --selftest      writes selftest_result.txt beside
                                                the exe and exits (used by the
                                                build script after every rebuild)
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP = "BUA Workbook Builder"
VERSION = "1.5"

HERE = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
SETTINGS_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "BuaWorkbookBuilder_settings.json")

# revittools_theme ships bundled when frozen (--hidden-import); when run from
# source, fall back to the sibling design\ folder.
try:
    import revittools_theme as rt
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "design"))
    import revittools_theme as rt

import BuaWorkbookBuilder_Engine as engine
import bua_license as lic

COPYRIGHT = lic.COPYRIGHT


# ------------------------------------------------------------------ settings
def load_settings():
    import json
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    import json
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


MODE_LABEL = {"option1": "Option 1 (combined 'Overall BUA' sheet)", "option2": "Option 2 (one sheet per Building Asset)"}
MODE_SUFFIX = {"option1": "Option 1 (Overall BUA)", "option2": "Option 2 (BUA by Asset)"}


def default_output_path(raw_path, mode="option1"):
    folder = os.path.dirname(raw_path) or "."
    stem = os.path.splitext(os.path.basename(raw_path))[0]
    return os.path.join(folder, "%s - %s.xlsx" % (stem, MODE_SUFFIX[mode]))


# ------------------------------------------------------------------ GUI
class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP)
        self.root.geometry("880x560")
        self.root.minsize(720, 460)
        rt.apply(root)

        self.settings = load_settings()
        self.raw_var = tk.StringVar(value=self.settings.get("last_raw", ""))
        self.out_var = tk.StringVar(value=self.settings.get("last_out", ""))
        self.mode_var = tk.StringVar(value=self.settings.get("last_mode", "option1"))
        self.q = queue.Queue()
        self.worker = None
        self.last_out_path = None
        self._last_auto_out = None   # last value WE put in out_var, so switching mode can update it

        rt.footer(root, APP, VERSION, COPYRIGHT, right_text="Machine ID %s" % lic.machine_id())
        self._build()
        self.root.after(80, self._poll_queue)

    def _build(self):
        top = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text=APP, style="Big.TLabel").pack(side="left")
        rt.theme_picker(top).pack(side="right")

        form = ttk.Frame(self.root, padding=(10, 6, 10, 0))
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Raw Input").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.raw_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(form, text="Browse...", command=self._pick_raw).grid(row=0, column=2)

        ttk.Label(form, text="Output layout").grid(row=1, column=0, sticky="w", pady=4)
        modebar = ttk.Frame(form)
        modebar.grid(row=1, column=1, columnspan=2, sticky="w", padx=(8, 0))
        ttk.Radiobutton(modebar, text="Option 1 (combined sheet)", value="option1",
                        variable=self.mode_var, command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(modebar, text="Option 2 (one sheet per asset)", value="option2",
                        variable=self.mode_var, command=self._mode_changed).pack(side="left", padx=(16, 0))

        ttk.Label(form, text="Final Output").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.out_var).grid(row=2, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(form, text="Save as...", command=self._pick_out).grid(row=2, column=2)
        self.mode_note = ttk.Label(form, text="", style="Dim.TLabel")
        self.mode_note.grid(row=3, column=1, sticky="w", padx=(8, 0))
        self._update_mode_note()

        bar = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Run", command=self._run)
        self.run_btn.pack(side="left")
        self.open_btn = ttk.Button(bar, text="Open output folder", command=self._open_folder, state="disabled")
        self.open_btn.pack(side="left", padx=8)
        self.status = ttk.Label(bar, text="", style="Dim.TLabel")
        self.status.pack(side="left", padx=8)
        ttk.Button(bar, text="Licence...", command=self._licence).pack(side="right")

        logframe = ttk.Frame(self.root, padding=(10, 8, 10, 8))
        logframe.pack(fill="both", expand=True)
        ttk.Label(logframe, text="Checks & log", style="Heading.TLabel").pack(anchor="w")
        self.log = rt.console(logframe, height=18)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        sb = ttk.Scrollbar(logframe, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)

    # ---------------------------------------------------------- actions
    def _update_mode_note(self):
        self.mode_note.configure(text=MODE_LABEL[self.mode_var.get()] + ".")

    def _mode_changed(self):
        self._update_mode_note()
        raw_path = self.raw_var.get().strip()
        # only auto-update the output path if it's still the one WE generated
        # (i.e. the user hasn't typed/picked something of their own)
        if raw_path and self.out_var.get().strip() == (self._last_auto_out or object()):
            new_default = default_output_path(raw_path, self.mode_var.get())
            self.out_var.set(new_default)
            self._last_auto_out = new_default

    def _pick_raw(self):
        path = filedialog.askopenfilename(
            title="Select the raw Area export",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
            initialdir=os.path.dirname(self.raw_var.get()) or None)
        if not path:
            return
        self.raw_var.set(path)
        if not self.out_var.get().strip():
            default = default_output_path(path, self.mode_var.get())
            self.out_var.set(default)
            self._last_auto_out = default

    def _pick_out(self):
        initial = self.out_var.get() or (
            default_output_path(self.raw_var.get(), self.mode_var.get()) if self.raw_var.get() else "")
        path = filedialog.asksaveasfilename(
            title="Save the Final Output as",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            initialdir=os.path.dirname(initial) or None,
            initialfile=os.path.basename(initial) or "Output.xlsx")
        if path:
            self.out_var.set(path)
            self._last_auto_out = None   # user chose explicitly - stop auto-tracking

    def _open_folder(self):
        if self.last_out_path and os.path.isfile(self.last_out_path):
            subprocess.run(["explorer", "/select,", self.last_out_path])

    def _log(self, msg, tag=None):
        self.q.put((msg, tag))

    def _poll_queue(self):
        try:
            while True:
                msg, tag = self.q.get_nowait()
                self.log.insert("end", msg + "\n", tag if tag else ())
                self.log.see("end")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _run(self):
        if self.worker and self.worker.is_alive():
            return
        raw_path = self.raw_var.get().strip()
        out_path = self.out_var.get().strip()
        mode = self.mode_var.get()
        if not raw_path:
            messagebox.showwarning(APP, "Pick the raw Area export first.")
            return
        if not out_path:
            out_path = default_output_path(raw_path, mode)
            self.out_var.set(out_path)
        self.log.delete("1.0", "end")
        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.status.configure(text="Running...")
        save_settings({"last_raw": raw_path, "last_out": out_path, "last_mode": mode})

        def work():
            try:
                self._log("=== BUA Workbook Builder - %s ===" % MODE_LABEL[mode], tag="hdr")
                _eng, ok, _report = engine.build_and_save(raw_path, out_path, mode=mode, log=self._log)
                if ok:
                    self._log("ALL TOTALS TIE OUT - DONE", tag="ok")
                else:
                    self._log("CHECK MISMATCHES ABOVE - output was still written", tag="err")
                self.last_out_path = out_path
                self.root.after(0, lambda: self.open_btn.configure(state="normal"))
                self.root.after(0, lambda: self.status.configure(
                    text="Done - totals tied out" if ok else "Done - see mismatches in the log"))
            except engine.LicenceError as e:
                self._log("BLOCKED - %s" % e, tag="err")
                self.root.after(0, lambda: self.status.configure(text="Blocked by licence"))
                if e.state in ("killed", "revoked", "taken", "locked", "unactivated"):
                    self.root.after(0, lambda: self._licence(e.state))
            except engine.RawParseError as e:
                self._log("ERROR: %s" % e, tag="err")
                self.root.after(0, lambda: self.status.configure(text="Failed - see log"))
            except Exception as e:
                self._log("UNEXPECTED ERROR: %s" % e, tag="err")
                self.root.after(0, lambda: self.status.configure(text="Failed - see log"))
            finally:
                self.root.after(0, lambda: self.run_btn.configure(state="normal"))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _licence(self, state=None):
        lic.activation_dialog(self.root, state)


# ------------------------------------------------------------------ self-test / main
def _selftest():
    result_path = os.path.join(SETTINGS_DIR, "selftest_result.txt")
    lines = ["frozen=%s" % getattr(sys, "frozen", False)]
    ok = True
    for mod in ("buawb_core", "BuaWorkbookBuilder_Engine", "bua_license"):
        m = sys.modules.get(mod)
        lines.append("%s compiled=%s" % (mod, bool(m is not None and "__compiled__" in vars(m))))
    try:
        st, _info = lic.license_state(retries=1)
        rows, src, err = lic.fetch_allow_list()
        lines.append("licence=%s sheet=%s kill_switch=%s kill_live=%s"
                     % (st, src, lic.kill_row_state(rows), lic.fetch_kill_live()))
    except Exception as e:
        lines.append("licence=ERROR (%s)" % e)
        ok = False
    try:
        import openpyxl  # noqa: F401
        lines.append("openpyxl import: OK")
    except Exception as e:
        lines.append("openpyxl import: FAILED (%s)" % e)
        ok = False
    try:
        import BuaWorkbookBuilder_Engine as _e  # noqa: F401
        lines.append("BuaWorkbookBuilder_Engine import: OK")
    except Exception as e:
        lines.append("BuaWorkbookBuilder_Engine import: FAILED (%s)" % e)
        ok = False
    try:
        import revittools_theme as _rt  # noqa: F401
        lines.append("revittools_theme import: OK")
    except Exception as e:
        lines.append("revittools_theme import: FAILED (%s)" % e)
        ok = False
    lines.append("RESULT: %s" % ("PASSED" if ok else "FAILED"))
    with open(result_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    if not ok:
        sys.exit(1)


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    root = tk.Tk()
    root.withdraw()
    rt.apply(root)
    if not lic.ensure_activated(root):      # unactivated / revoked / killed / offline past grace -> no app
        root.destroy()
        return
    root.deiconify()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

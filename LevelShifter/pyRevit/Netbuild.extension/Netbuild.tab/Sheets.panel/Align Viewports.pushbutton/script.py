# -*- coding: utf-8 -*-
"""Align Viewports by Netbuild -- line up the viewports and view titles on many sheets with a reference sheet.

Runs directly inside Revit (no exe, no MCP listener).
Check (plan only) -> Trial run (rolls back) -> Apply (one Undo entry: 'Align Viewports by Netbuild').
(c) 2026 Netbuild. All rights reserved. https://skaec.com
About / Licence: the About and Licence buttons in the window, or Netbuild > About, Licence.
"""

__title__ = "Align\nViewports"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import datetime
import io
import os
import time

from pyrevit import forms, revit, script

from System.Diagnostics import Process
from System.Windows.Controls import ListBoxItem
from System.Windows.Input import Cursors, Mouse
from System.Windows.Media import BrushConverter

from align_viewports import about, core
import alignviewports_ui as ui
import netbuild_about

CFG = script.get_config()
_BRUSHES = BrushConverter()
DEFAULT_TIME_LOG = r"%USERPROFILE%\OneDrive - Studio\Documents\Claude\time_saved_log.csv"
DEFAULT_MINUTES = 2.0                       # by hand, per viewport: move it, nudge it, fix its title


def brush(colour):
    return _BRUSHES.ConvertFromString(colour)


def as_bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")


def expand(path):
    return os.path.expandvars(os.path.expanduser(path or ""))


def default_time_log():
    """The usual time-saved log when its folder exists on this computer, else blank (no row)."""
    path = expand(DEFAULT_TIME_LOG)
    return DEFAULT_TIME_LOG if "%" not in path and os.path.isdir(os.path.dirname(path)) else ""


def logs_dir():
    d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Netbuild", "AlignViewports", "logs")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


class AlignViewportsWindow(forms.WPFWindow):
    def __init__(self, doc):
        forms.WPFWindow.__init__(self, ui.window_xaml(), literal_string=True)
        self.doc = doc
        self.opened = time.time()
        self.labels = {}                    # list label -> sheet number
        self.Title = about.title(doc.Title)
        self.model_tb.Text = doc.Title
        types = [t for t in CFG.get_option("view_types", ",".join(core.DEFAULT_VIEW_TYPES)).split(",") if t]
        for key, _ in core.VIEW_TYPES:
            box = getattr(self, "vt_" + key)
            box.IsChecked = key in types
            box.Click += lambda s_, e: self.show_reference()
        self.titles_cb.IsChecked = as_bool(CFG.get_option("titles", True))
        self.from_tb.Text = CFG.get_option("range_from", "")
        self.to_tb.Text = CFG.get_option("range_to", "")
        self.extra_tb.Text = CFG.get_option("extra", "")
        self.log_tb.Text = CFG.get_option("time_log", default_time_log())
        self.minutes_tb.Text = str(CFG.get_option("minutes_per_viewport", DEFAULT_MINUTES))
        self.ref_cb.SelectionChanged += lambda s_, e: self.show_reference()
        self.tgt_lb.SelectionChanged += lambda s_, e: self.show_count()
        self.range_btn.Click += lambda s_, e: self.select_range()
        self.all_btn.Click += lambda s_, e: self.select_numbers(list(self.labels.values()))
        self.none_btn.Click += lambda s_, e: self.select_numbers([])
        self.check_btn.Click += lambda s_, e: self.run("plan")
        self.trial_btn.Click += lambda s_, e: self.run("trial")
        self.apply_btn.Click += lambda s_, e: self.run("apply")
        self.images_btn.Click += lambda s_, e: self.export_images()
        self.log_btn.Click += self.on_pick_log
        self.logs_btn.Click += lambda s_, e: Process.Start(logs_dir())
        self.about_btn.Click += lambda s_, e: netbuild_about.show(about, owner=self)
        self.licence_btn.Click += lambda s_, e: netbuild_about.show_licence(about, owner=self)
        self.close_btn.Click += lambda s_, e: self.Close()
        self.load_sheets()

    # ------------------------------------------------------------ helpers
    def status(self, text):
        self.status_tb.Text = text

    def show(self, title, checks, lines=()):
        self.report_lb.Items.Clear()
        for colour, text in [("#000000", title)] + ui.report_lines(checks, list(lines)):
            item = ListBoxItem()
            item.Content = text
            item.Foreground = brush(colour)
            self.report_lb.Items.Add(item)

    def view_types(self):
        return [k for k, _ in core.VIEW_TYPES if getattr(self, "vt_" + k).IsChecked]

    def reference(self):
        return self.labels.get(self.ref_cb.SelectedItem)

    def targets(self):
        ref = self.reference()
        return sorted((self.labels[l] for l in list(self.tgt_lb.SelectedItems) if self.labels.get(l) != ref),
                      key=core.natural_key)

    # ------------------------------------------------------------ sheets
    def load_sheets(self):
        self.sheets = core.read_sheets(self.doc)
        numbers = sorted(self.sheets, key=core.natural_key)
        self.labels = dict((ui.sheet_label(n, self.sheets[n].Name), n) for n in numbers)
        self.ref_cb.Items.Clear()
        self.tgt_lb.Items.Clear()
        for n in numbers:
            label = ui.sheet_label(n, self.sheets[n].Name)
            self.ref_cb.Items.Add(label)
            self.tgt_lb.Items.Add(label)
        remembered = CFG.get_option("reference", "")
        if remembered in self.sheets:
            self.ref_cb.SelectedItem = ui.sheet_label(remembered, self.sheets[remembered].Name)
        if self.from_tb.Text or self.extra_tb.Text:
            self.select_range(quiet=True)
        self.show_reference()
        self.status("%d sheets in %s. Pick the reference, then the target sheets." % (len(numbers), self.doc.Title))

    def show_reference(self):
        ref = self.reference()
        if not ref:
            self.ref_info_tb.Text = "Pick the sheet whose viewports are already where you want them."
            return
        vps = core.slot_viewports(self.doc, self.sheets[ref], self.view_types())
        self.ref_info_tb.Text = ui.ref_info([self.doc.GetElement(vp.ViewId).Name for vp in vps])
        self.show_count()

    def show_count(self):
        n = len(self.targets())
        self.count_tb.Text = "%d target sheet%s picked" % (n, "" if n == 1 else "s")

    def select_numbers(self, numbers):
        want = set(numbers)
        self.tgt_lb.SelectedItems.Clear()
        for label in list(self.tgt_lb.Items):
            if self.labels.get(label) in want:
                self.tgt_lb.SelectedItems.Add(label)
        self.show_count()

    def select_range(self, quiet=False):
        try:
            rng = core.parse_range(self.from_tb.Text, self.to_tb.Text)
        except ValueError as e:
            if not quiet:
                forms.alert(str(e), title="Target sheets")
            return
        extra = core.split_numbers(self.extra_tb.Text)
        targets, missing = core.pick_targets(list(self.sheets), self.reference(), rng, extra)
        self.select_numbers(targets)
        if missing and not quiet:
            forms.alert("Not in this model: %s" % ", ".join(missing), title="Target sheets")

    def on_pick_log(self, sender, args):
        folder = os.path.dirname(expand(self.log_tb.Text.strip()))
        path = forms.pick_file(file_ext="csv", init_dir=folder if os.path.isdir(folder) else "")
        if path:
            self.log_tb.Text = path

    def save_options(self):
        CFG.view_types = ",".join(self.view_types())
        CFG.titles = bool(self.titles_cb.IsChecked)
        CFG.reference = self.reference() or ""
        CFG.range_from, CFG.range_to = self.from_tb.Text.strip(), self.to_tb.Text.strip()
        CFG.extra = self.extra_tb.Text.strip()
        CFG.time_log = self.log_tb.Text.strip()
        CFG.minutes_per_viewport = self.minutes_tb.Text.strip()
        script.save_config()

    # ------------------------------------------------------------ steps
    def run(self, action):
        title = {"plan": "Check", "trial": "Trial run", "apply": "Apply"}[action]
        ref, targets, types = self.reference(), self.targets(), self.view_types()
        why = ("Pick the reference sheet." if not ref else
               "Tick at least one kind of viewport to align." if not types else
               "Pick at least one target sheet (or type a range and click 'Select these')." if not targets else "")
        if why:
            forms.alert(why, title=title)
            return
        self.save_options()
        titles = bool(self.titles_cb.IsChecked)
        try:
            plan = core.make_plan(self.doc, ref, targets, types)
        except ValueError as e:
            self.show(title, [core.Check("Stopped", False, str(e))])
            self.status("%s: needs attention -- see the FAIL lines" % title)
            return
        checks, lines = core.plan_checks(plan, titles)
        if action != "plan" and plan["moves"]:
            sheets = sorted(set(m.sheet for m in plan["moves"]), key=core.natural_key)
            if action == "apply" and not forms.alert(
                    "Align %d viewport(s) on %d sheet(s) in %s to sheet %s?\n\n%s\n\n%s One Undo entry in Revit."
                    % (len(plan["moves"]), len(sheets), self.doc.Title, ref, ", ".join(sheets[:40]) +
                       (" ..." if len(sheets) > 40 else ""),
                       "View titles follow the reference too." if titles else "View titles are left as they are."),
                    title="Apply", yes=True, no=True):
                return
            self.status("%s running in Revit ..." % title)
            Mouse.OverrideCursor = Cursors.Wait
            try:
                result = core.run(self.doc, plan, action == "apply", titles)
                c2, l2 = core.result_checks(action, plan, result, titles)
            except Exception as e:
                result = None
                c2, l2 = [core.Check("Stopped", False, "%s: %s" % (type(e).__name__, e))], []
            finally:
                Mouse.OverrideCursor = None
            checks += c2
            lines += l2
        else:
            result = None
        committed = bool(result and result["committed"])
        if committed:
            checks.append(self.log_time(plan))
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if plan["moves"]:
            path = core.write_moves_csv(os.path.join(logs_dir(), "%s_%s_viewports.csv" % (stamp, action)),
                                        plan, result, titles)
            lines.append("viewport list: %s" % path)
        log = os.path.join(logs_dir(), "%s_%s.log" % (stamp, action))
        with io.open(log, "w", encoding="utf-8") as f:
            f.write(u"%s -- %s -- %s\n" % (about.title(), title, self.doc.Title))
            for c in checks:
                f.write(u"%s\n" % c)
            for l in lines:
                f.write(u"%s\n" % l)
        lines.append("log: %s" % log)
        self.show(title, checks, lines)
        ok = not [c for c in checks if c.ok is False]
        self.status("%s: %s" % (title, "OK" if ok else "needs attention -- see the FAIL lines"))
        if committed:
            self.status("Applied. Click 'Export check images' to compare the view titles with sheet %s; "
                        "Ctrl+Z in Revit undoes it ('%s')." % (ref, about.PRODUCT))

    def log_time(self, plan):
        """After Apply: one row in the time-saved log, when one is set."""
        path = expand(self.log_tb.Text.strip())
        if not path:
            return core.Check("Time-saved log", None, "no file set -- nothing logged")
        try:
            per = float(self.minutes_tb.Text.strip() or DEFAULT_MINUTES)
        except ValueError:
            per = DEFAULT_MINUTES
        moves = plan["moves"]
        sheets = sorted(set(m.sheet for m in moves), key=core.natural_key)
        manual = round(per * len(moves), 1)
        actual = round((time.time() - self.opened) / 60.0, 1)
        row = {"date": datetime.date.today().isoformat(), "task": core.TIME_LOG_TASK, "project": self.doc.Title,
               "export": "reference %s" % plan["reference"],
               "issues": "%d sheets / %d viewports" % (len(sheets), len(moves)),
               "manual_minutes": manual, "actual_minutes": actual, "minutes_saved": round(manual - actual, 1),
               "notes": "%s; sheets %s" % (about.title(), ", ".join(sheets[:60]))}
        try:
            core.log_time_saved(path, row)
        except (IOError, OSError, ValueError) as e:
            return core.Check("Time-saved log", None, "not logged: %s" % e)
        return core.Check("Time-saved log", True, "%s min saved -- %s" % (row["minutes_saved"], path))

    def export_images(self):
        ref = self.reference()
        if not ref:
            forms.alert("Pick the reference sheet first.", title="Export check images")
            return
        try:                                # the picked sheets that are aligned (not skipped / empty)
            plan = core.make_plan(self.doc, ref, self.targets(), self.view_types())
            aligned = sorted(set(m.sheet for m in plan["moves"]), key=core.natural_key)
        except ValueError:
            aligned = self.targets()
        numbers = [ref] + core.check_image_sheets(aligned)
        folder = os.path.join(logs_dir(), datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_images")
        self.status("Exporting %s to PNG ..." % ", ".join(numbers))
        Mouse.OverrideCursor = Cursors.Wait
        try:
            files = core.export_images(self.doc, [self.sheets[n] for n in numbers], folder)
            checks = [core.Check("Check images", True if files else None, "%d PNG file(s) in %s -- compare the "
                                 "view titles with sheet %s" % (len(files), folder, ref))]
        except Exception as e:
            files = []
            checks = [core.Check("Check images", False, "%s: %s" % (type(e).__name__, e))]
        finally:
            Mouse.OverrideCursor = None
        self.show("Export check images", checks, ["  " + os.path.basename(p) for p in files])
        self.status("Check images: %s" % ("open the folder and flick through them" if files else "none written"))
        if files:
            Process.Start(folder)


doc = revit.doc
if doc is None or doc.IsFamilyDocument:
    forms.alert("Open a project model first.", title="Align Viewports", exitscript=True)
if doc.IsReadOnly:
    forms.alert("%s is read-only -- open it editable (detach / local copy) to move viewports." % doc.Title,
                title="Align Viewports", exitscript=True)
AlignViewportsWindow(doc).show_dialog()

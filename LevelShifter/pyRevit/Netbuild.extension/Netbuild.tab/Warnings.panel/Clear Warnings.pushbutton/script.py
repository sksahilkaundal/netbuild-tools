# -*- coding: utf-8 -*-
"""Clear Warnings by Netbuild -- clear the Area / dead-reference / duplicate Type Mark warnings of the active model.

Warnings summary (grouped by description, B001 profile) -> Dry run (counts only) -> Run (one Undo entry:
'Clear Warnings by Netbuild'). Six steps, each optional: Area Plans + Area schedules, Areas, Area Separation
Lines, orphaned Matchlines, orphaned Room Tags, duplicate Type Marks. Live Matchlines and Room Tags with a
valid room are never touched -- they are listed for manual review.
(c) 2026 Netbuild. All rights reserved. https://skaec.com
About / Licence: the About button in the window, or Netbuild > About, Licence.
"""

__title__ = "Clear\nWarnings"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import datetime
import io
import os

from pyrevit import DB, forms, revit, script

from System.Diagnostics import Process
from System.Windows import Clipboard
from System.Windows.Controls import ListBoxItem
from System.Windows.Input import Cursors, Mouse
from System.Windows.Media import BrushConverter

from clear_warnings import about, core
import clearwarnings_ui as ui
import netbuild_about

CFG = script.get_config()
_BRUSHES = BrushConverter()


def logs_dir():
    d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Netbuild", "ClearWarnings", "logs")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


class ClearWarningsWindow(forms.WPFWindow):
    def __init__(self, doc):
        forms.WPFWindow.__init__(self, ui.window_xaml(), literal_string=True)
        self.doc = doc
        self.lines = []
        self.Title = about.title(doc.Title)
        self.model_tb.Text = "Active model: %s" % doc.Title
        off = set(k for k in (CFG.get_option("steps_off", "") or "").split(",") if k)
        for i, key in enumerate(core.STEP_KEYS):
            self.step(i).IsChecked = key not in off
        self.rules_tb.Text = CFG.get_option("type_mark_rules", core.DEFAULT_RULES)
        self.summary_btn.Click += lambda s_, e: self.show_summary()
        self.dry_btn.Click += lambda s_, e: self.run(False)
        self.run_btn.Click += lambda s_, e: self.run(True)
        self.copy_btn.Click += self.copy
        self.logs_btn.Click += lambda s_, e: Process.Start(logs_dir())
        self.about_btn.Click += lambda s_, e: netbuild_about.show(about, owner=self)
        self.close_btn.Click += lambda s_, e: self.Close()
        self.show_summary()

    def step(self, i):
        return self.FindName("step_%d" % i)

    def steps(self):
        return [key for i, key in enumerate(core.STEP_KEYS) if self.step(i).IsChecked]

    def status(self, text):
        self.status_tb.Text = text

    def show(self, lines):
        self.lines = lines
        self.report_lb.Items.Clear()
        for colour, text in lines:
            item = ListBoxItem()
            item.Content = text
            item.Foreground = _BRUSHES.ConvertFromString(core.COLOURS[colour])
            self.report_lb.Items.Add(item)

    def show_summary(self):
        s = core.summary(self.doc, DB)
        ok, text = core.profile(s)
        self.profile_tb.Text = "%d warnings. %s" % (s["total"], text)
        self.profile_tb.Foreground = _BRUSHES.ConvertFromString(core.COLOURS["ok" if ok else "warn"])
        self.show(core.summary_lines(s, "Warnings now"))
        self.status("Pick the steps, Dry run to see what each one targets, then Run.")

    def copy(self, sender, args):
        Clipboard.SetText(u"\n".join(text for _, text in self.lines))
        self.copy_btn.Content = "Copied"

    def save_options(self, rules_text):
        CFG.steps_off = ",".join(k for k in core.STEP_KEYS if k not in self.steps())
        CFG.type_mark_rules = rules_text
        script.save_config()

    def run(self, apply):
        title = "Run" if apply else "Dry run"
        steps = self.steps()
        if not steps:
            forms.alert("Tick at least one step.", title=title)
            return
        try:
            rules = core.parse_rules(self.rules_tb.Text)
        except ValueError as e:
            forms.alert(str(e), title=title)
            return
        self.save_options(self.rules_tb.Text)
        if apply and not forms.alert(
                "Run these steps on %s?\n\n%s\n\nLive Matchlines and Room Tags with a valid room are left alone "
                "and listed for review. One Undo entry in Revit ('%s')." % (
                    self.doc.Title, "\n".join(core.LABELS[k] for k in steps), core.UNDO_NAME),
                title=title, yes=True, no=True):
            return
        self.status("%s running in Revit ..." % title)
        Mouse.OverrideCursor = Cursors.Wait
        try:
            result = core.run(self.doc, DB, steps, apply, rules)
            lines = core.report_lines(result)
            ok = True
        except Exception as e:
            result = None
            lines = [("fail", "%s stopped -- nothing was changed: %s: %s" % (title, type(e).__name__, e))]
            ok = False
        finally:
            Mouse.OverrideCursor = None
        log = os.path.join(logs_dir(), "%s_%s.log" % (datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
                                                     "run" if apply else "dry_run"))
        with io.open(log, "w", encoding="utf-8") as f:
            f.write(u"%s -- %s\n" % (about.title(), self.doc.Title))
            for _, text in lines:
                f.write(u"%s\n" % text)
        self.show(lines + [("", "log: %s" % log)])
        if not ok:
            self.status("%s stopped -- see the report." % title)
            return
        review = len(core.review_items(result))
        if apply:
            self.profile_tb.Text = "%d warnings now (was %d)." % (result["after"]["total"], result["before"]["total"])
            self.status("Done: %d -> %d warnings, %d item(s) for manual review. Ctrl+Z in Revit undoes it ('%s')."
                        % (result["before"]["total"], result["after"]["total"], review, core.UNDO_NAME))
        else:
            self.status("Dry run: nothing changed. %d item(s) would need manual review." % review)


doc = revit.doc
if doc is None or doc.IsFamilyDocument:
    forms.alert("Open a project model first.", title=about.PRODUCT, exitscript=True)
if doc.IsReadOnly:
    forms.alert("%s is read-only -- open it editable (detach / local copy) to clear warnings." % doc.Title,
                title=about.PRODUCT, exitscript=True)
ClearWarningsWindow(doc).show_dialog()

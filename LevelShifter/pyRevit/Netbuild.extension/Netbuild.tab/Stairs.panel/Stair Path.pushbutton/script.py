# -*- coding: utf-8 -*-
"""Stair Path by Netbuild -- Up / Down stair path annotations in plan views, per scale, by the office standard.

Runs directly inside Revit (no exe, no MCP listener).
Check (plan only) -> Trial run (rolls back) -> Apply (one Undo entry: 'Stair Path by Netbuild').
Settings (text offsets, tolerances) are kept per model: they are tuned per building.
(c) 2026 Netbuild. All rights reserved. https://skaec.com
About / Licence: the About button in the window, or Netbuild > About, Licence.
"""

__title__ = "Stair\nPath"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import datetime
import io
import json
import os

from pyrevit import forms, revit, script

from System.Diagnostics import Process
from System.Windows.Controls import ListBoxItem
from System.Windows.Input import Cursors, Mouse
from System.Windows.Media import BrushConverter

from stair_path import about, engine, rules
import netbuild_about
import stair_path_ui as ui

CFG = script.get_config()
_BRUSHES = BrushConverter()
CSV_FIELDS = ["view", "scale", "level", "core", "kind", "stair", "result", "path", "offset_mm", "why"]


def logs_dir():
    d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Netbuild", "StairPath", "logs")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def write_csv(path, rows):
    """UTF-8 CSV (Excel reads the BOM) of the engine's annotation rows -- by hand: IronPython's csv is bytes-only."""
    def cell(v):
        v = u"%s" % v
        return u'"%s"' % v.replace(u'"', u'""') if [c for c in u',"\n' if c in v] else v
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(u",".join(CSV_FIELDS) + u"\r\n")
        for row in rows:
            f.write(u",".join(cell(row[k]) for k in CSV_FIELDS) + u"\r\n")
    return path


def saved_models():
    try:
        data = json.loads(CFG.get_option("models", "") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def load_settings(title):
    return rules.settings(saved_models().get(title))


def save_settings(title, s):
    data = saved_models()
    data[title] = dict((k, s[k]) for k in rules.DEFAULTS)
    CFG.models = json.dumps(data, sort_keys=True)
    script.save_config()


class StairPathWindow(forms.WPFWindow):
    def __init__(self, doc, uidoc):
        forms.WPFWindow.__init__(self, ui.window_xaml(), literal_string=True)
        self.doc, self.uidoc = doc, uidoc
        self.Title = about.title(doc.Title)
        self.model_tb.Text = doc.Title
        self.show_settings(load_settings(doc.Title))
        self.defaults_btn.Click += self.on_defaults
        self.check_btn.Click += lambda s_, e: self.run("plan")
        self.trial_btn.Click += lambda s_, e: self.run("trial")
        self.apply_btn.Click += lambda s_, e: self.run("apply")
        self.logs_btn.Click += lambda s_, e: Process.Start(logs_dir())
        self.close_btn.Click += lambda s_, e: self.Close()
        self.about_btn.Click += lambda s_, e: netbuild_about.show(about, owner=self)
        self.status("Settings for %s. Check first: it lists the stair cores and what each view gets." % doc.Title)

    def status(self, text):
        self.status_tb.Text = text

    # ------------------------------------------------------------ settings <-> controls
    def show_settings(self, s):
        for key in ui.TEXT_KEYS:
            v = s[key]
            self.FindName(key + "_tb").Text = ("%g" % v) if isinstance(v, float) else v
        for key in ui.BOOL_KEYS:
            self.FindName(key + "_cb").IsChecked = s[key]
        self.open_rb.IsChecked = s["views"] == "open"
        self.name_rb.IsChecked = s["views"] == "name"
        self.clear_views_rb.IsChecked = s["clear"] == "views"
        self.clear_model_rb.IsChecked = s["clear"] == "model"

    def values(self):
        """The window's settings; raises ValueError naming a distance that is not a number."""
        v = {"views": "name" if self.name_rb.IsChecked else "open",
             "clear": "model" if self.clear_model_rb.IsChecked else "views"}
        for key in ui.TEXT_KEYS:
            text = self.FindName(key + "_tb").Text.strip()
            if key in rules.NUMBERS:
                try:
                    float(text)
                except ValueError:
                    raise ValueError("'%s' is not a number (%s)" % (text, key))
            v[key] = text
        for key in ui.BOOL_KEYS:
            v[key] = bool(self.FindName(key + "_cb").IsChecked)
        return rules.settings(v)

    def on_defaults(self, sender, args):
        self.show_settings(rules.settings())
        self.status("Default settings shown -- they are saved for this model on the next run.")

    # ------------------------------------------------------------ run
    def show(self, title, checks, lines):
        self.report_lb.Items.Clear()
        for colour, text in [("#000000", title)] + ui.report_lines(checks, lines):
            item = ListBoxItem()
            item.Content = text
            item.Foreground = _BRUSHES.ConvertFromString(colour)
            self.report_lb.Items.Add(item)

    def run(self, action):
        title = {"plan": "Check", "trial": "Trial run", "apply": "Apply"}[action]
        try:
            s = self.values()
        except ValueError as e:
            forms.alert(str(e), title=title)
            return
        save_settings(self.doc.Title, s)
        if action == "apply" and not forms.alert(
                "Place the stair path annotations in %s?\n\nExisting stair paths in the %s are deleted first. "
                "View templates and View Range are not changed. One Undo entry in Revit." % (
                    self.doc.Title, "target views" if s["clear"] == "views" else "WHOLE MODEL"),
                title="Apply", yes=True, no=True):
            return
        self.status("%s running in Revit ..." % title)
        r = engine.Run(self.doc, self.uidoc, s)
        Mouse.OverrideCursor = Cursors.Wait
        try:
            r.run(action)
        except Exception as e:
            r.checks.append(rules.Check("Stopped", False, "%s: %s -- nothing was changed" % (type(e).__name__, e)))
        finally:
            Mouse.OverrideCursor = None
        lines = list(r.lines)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if r.rows:
            path = write_csv(os.path.join(logs_dir(), "%s_%s_stair_paths.csv" % (stamp, action)), r.rows)
            lines.append("annotation list: %s" % path)
        log = os.path.join(logs_dir(), "%s_%s.log" % (stamp, action))
        with io.open(log, "w", encoding="utf-8") as f:
            f.write(u"%s -- %s -- %s\n" % (about.title(), title, self.doc.Title))
            for c in r.checks:
                f.write(u"%s\n" % c)
            for l in lines:
                f.write(u"%s\n" % l)
        lines.append("log: %s" % log)
        self.show(title, r.checks, lines)
        self.status("%s: %s" % (title, "OK" if r.ok() else "needs attention -- see the FAIL lines"))


doc = revit.doc
if doc is None or doc.IsFamilyDocument:
    forms.alert("Open a project model first.", title="Stair Path", exitscript=True)
if doc.IsReadOnly:
    forms.alert("%s is read-only -- open it editable to place stair paths." % doc.Title,
                title="Stair Path", exitscript=True)
StairPathWindow(doc, revit.uidoc).show_dialog()

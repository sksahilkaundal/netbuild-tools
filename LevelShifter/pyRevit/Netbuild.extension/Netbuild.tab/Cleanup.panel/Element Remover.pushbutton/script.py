# -*- coding: utf-8 -*-
"""Element Remover by Netbuild -- remove the elements on chosen worksets and / or passing chosen view filters,
standalone or inside model groups (ungrouped, removed, regrouped).

Runs directly inside Revit (no exe, no MCP listener).
Check (plan only) -> Trial run (rolls back) -> Apply (one Undo entry: 'Element Remover by Netbuild').
(c) 2026 Netbuild. All rights reserved. https://skaec.com
About / Licence: the About and Licence buttons in the window, or Netbuild > About, Licence.
"""

__title__ = "Element\nRemover"
__author__ = "Netbuild -- skaec.com"

import datetime
import io
import os

from pyrevit import forms, revit, script

from System.Diagnostics import Process
from System.Windows.Controls import ListBoxItem
from System.Windows.Input import Cursors, Mouse
from System.Windows.Media import BrushConverter

from element_remover import about, core
import elementremover_ui as ui
import netbuild_about

CFG = script.get_config()
_BRUSHES = BrushConverter()
SEP = "|"                                   # joins the remembered workset / filter names in the config


def brush(colour):
    return _BRUSHES.ConvertFromString(colour)


def as_bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")


def options():
    """Engine options from this button's pyRevit config (defaults from core.ENGINE_DEFAULTS)."""
    s = dict(core.ENGINE_DEFAULTS)
    for key, default in core.ENGINE_DEFAULTS.items():
        v = CFG.get_option(key, default)
        try:
            s[key] = as_bool(v) if isinstance(default, bool) else type(default)(float(v))
        except (TypeError, ValueError):
            s[key] = default
    return s


def logs_dir():
    d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Netbuild", "ElementRemover", "logs")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


class ElementRemoverWindow(forms.WPFWindow):
    def __init__(self, doc):
        forms.WPFWindow.__init__(self, ui.window_xaml(), literal_string=True)
        self.doc = doc
        self.ws_names, self.flt_names, self.categories = {}, {}, []
        self.Title = about.title(doc.Title)
        self.model_tb.Text = doc.Title
        s = options()
        self.groups_cb.IsChecked = s["fix_groups"]
        self.pinned_cb.IsChecked = not s["skip_pinned"]
        self.model_cb.IsChecked = s["model_only"]
        self.all_rb.IsChecked = CFG.get_option("combine", "any") == "all"
        self.any_rb.IsChecked = not self.all_rb.IsChecked
        self.cat_tb.Text = CFG.get_option("categories", "")
        self.cats_btn.Click += self.on_pick_categories
        self.walls_btn.Click += lambda s_, e: setattr(self.cat_tb, "Text", "Walls")
        self.all_cats_btn.Click += lambda s_, e: setattr(self.cat_tb, "Text", "")
        self.check_btn.Click += lambda s_, e: self.run("plan")
        self.trial_btn.Click += lambda s_, e: self.run("trial")
        self.apply_btn.Click += lambda s_, e: self.run("apply")
        self.reload_btn.Click += lambda s_, e: self.load_sources()
        self.logs_btn.Click += lambda s_, e: Process.Start(logs_dir())
        self.about_btn.Click += lambda s_, e: netbuild_about.show(about, owner=self)
        self.licence_btn.Click += lambda s_, e: netbuild_about.show_licence(about, owner=self)
        self.close_btn.Click += lambda s_, e: self.Close()
        self.load_sources(remembered=True)

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

    @staticmethod
    def picked(lb, names):
        return [names[label] for label in list(lb.SelectedItems) if label in names]

    def targets(self):
        return core.Targets(self.picked(self.ws_lb, self.ws_names), self.picked(self.flt_lb, self.flt_names),
                            core.split_names(self.cat_tb.Text), "all" if self.all_rb.IsChecked else "any")

    # ------------------------------------------------------------ lists
    def load_sources(self, remembered=False):
        if remembered:
            keep_ws = [n for n in CFG.get_option("worksets", "").split(SEP) if n]
            keep_flt = [n for n in CFG.get_option("filters", "").split(SEP) if n]
        else:
            keep_ws, keep_flt = self.picked(self.ws_lb, self.ws_names), self.picked(self.flt_lb, self.flt_names)
        try:
            src = core.run_local(self.doc, "sources")["SOURCES"]
        except Exception as e:
            self.show("Worksets and filters", [core.Check("Stopped", False, "%s: %s" % (type(e).__name__, e))])
            return
        self.ws_names = dict((ui.workset_label(w), w["name"]) for w in src["worksets"])
        self.flt_names = dict((ui.filter_label(f), f["name"]) for f in src["filters"])
        self.categories = src["categories"]
        for lb, rows, label, keep in ((self.ws_lb, src["worksets"], ui.workset_label, keep_ws),
                                      (self.flt_lb, src["filters"], ui.filter_label, keep_flt)):
            lb.Items.Clear()
            lb.SelectedItems.Clear()
            for r in rows:
                lb.Items.Add(label(r))
                if r["name"] in keep:
                    lb.SelectedItems.Add(label(r))
        closed = [w["name"] for w in src["worksets"] if not w["open"]]
        self.info_tb.Text = ("%d user workset(s)%s, %d filter(s)" % (
            len(src["worksets"]), (" -- closed: " + ", ".join(closed)) if closed else "", len(src["filters"]))
            if src["workshared"] else "Not workshared -- pick filters (rule-based or saved selections).")
        self.status("Pick worksets and / or filters (optionally categories), then Check.")

    def on_pick_categories(self, sender, args):
        picked = forms.SelectFromList.show(self.categories, title="Only these categories", multiselect=True,
                                           button_name="Use these")
        if picked:
            self.cat_tb.Text = ", ".join(picked)

    # ------------------------------------------------------------ run
    def save_options(self, t):
        CFG.fix_groups = bool(self.groups_cb.IsChecked)
        CFG.skip_pinned = not self.pinned_cb.IsChecked
        CFG.model_only = bool(self.model_cb.IsChecked)
        CFG.combine = t.combine
        CFG.categories = ", ".join(t.categories)
        CFG.worksets = SEP.join(t.worksets)
        CFG.filters = SEP.join(t.filters)
        script.save_config()

    def confirm(self, plan):
        """Ask before Apply, with the numbers the plan found."""
        return forms.alert(
            "Remove %d element(s) from %s?\n\n%d standalone, %d inside %d model group instance(s) (ungrouped and "
            "regrouped without them)%s.\n\nRevit also deletes what is hosted on or depends on them (doors, "
            "windows, tags, dimensions ...); Check / Trial run list them.\nOne Undo entry in Revit." % (
                plan["targets"], self.doc.Title, plan["standalone"], plan["in_groups"], plan["groups"],
                (", plus %d inside group instances removed as a whole" % plan["with_group"])
                if plan["with_group"] else ""),
            title="Apply", yes=True, no=True)

    def run(self, action):
        title = {"plan": "Check", "trial": "Trial run", "apply": "Apply"}[action]
        t = self.targets()
        checks, lines = t.checks(), [u"Targets: " + t.describe()]
        if [c for c in checks if c.ok is False]:
            self.show(title, checks)
            self.status("Pick at least one workset or filter.")
            return
        self.save_options(t)
        s = options()
        out = {}
        Mouse.OverrideCursor = Cursors.Wait
        try:
            if action == "apply":
                plan = core.run_local(self.doc, "plan", t, s)["PLAN"]
                c2, l2 = core.plan_checks(plan)
                if [c for c in c2 if c.ok is False] or not plan["targets"]:
                    self.show(title, checks + c2, lines + l2)
                    self.status("Apply: nothing removed -- see the report.")
                    return
                Mouse.OverrideCursor = None
                if not self.confirm(plan):
                    return
                Mouse.OverrideCursor = Cursors.Wait
            self.status("%s running in Revit ..." % title)
            out = core.run_local(self.doc, action, t, s)
            c2, l2 = core.plan_checks(out["PLAN"])
            checks += c2
            lines += l2
            if action != "plan":
                c3, l3 = core.result_checks(action, out["RESULT"])
                checks += c3
                lines += l3
        except Exception as e:
            checks.append(core.Check("Stopped", False, "%s: %s" % (type(e).__name__, e)))
        finally:
            Mouse.OverrideCursor = None
        rows = (out.get("RESULT") or {}).get("rows") or (out.get("PLAN") or {}).get("rows") or []
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if rows:
            path = core.write_rows_csv(os.path.join(logs_dir(), "%s_%s_elements.csv" % (stamp, action)), rows)
            lines.append("element list: %s" % path)
        log = os.path.join(logs_dir(), "%s_%s.log" % (stamp, action))
        with io.open(log, "w", encoding="utf-8") as f:
            f.write(u"%s -- %s\n" % (title, self.doc.Title))
            for c in checks:
                f.write(u"%s\n" % c)
            for l in lines:
                f.write(u"%s\n" % l)
        lines.append("log: %s" % log)
        self.show(title, checks, lines)
        ok = not [c for c in checks if c.ok is False]
        self.status("%s: %s" % (title, "OK" if ok else "needs attention -- see the FAIL lines"))
        if action == "apply" and (out.get("RESULT") or {}).get("committed"):
            self.load_sources()
            self.status("Applied -- lists re-read. Ctrl+Z in Revit undoes it ('Element Remover by Netbuild').")


doc = revit.doc
if doc is None or doc.IsFamilyDocument:
    forms.alert("Open a project model first.", title="Element Remover", exitscript=True)
if doc.IsReadOnly:
    forms.alert("%s is read-only -- open it editable (detach / local copy) to remove elements." % doc.Title,
                title="Element Remover", exitscript=True)
ElementRemoverWindow(doc).show_dialog()

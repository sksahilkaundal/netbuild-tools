# -*- coding: utf-8 -*-
"""Move up to 10 levels up or down. Every element hosted to them keeps its X, Y, Z.

Runs directly inside Revit -- no exe, no MCP listener.
Check (plan only) -> Trial run (rolls back) -> Apply (one Undo entry: 'Netbuild Level Shift').
"""

__title__ = "Level\nShift"
__author__ = "Netbuild"

import datetime
import io
import os

from pyrevit import forms, revit, script

from System.Diagnostics import Process
from System.Windows.Controls import ListBoxItem
from System.Windows.Input import Cursors, Mouse
from System.Windows.Media import BrushConverter

from level_shift import __version__, core
from level_shift.units import fmt, from_ft, parse_length
import levelshift_ui as ui

N = core.MAX_LEVELS
CFG = script.get_config()
_BRUSHES = BrushConverter()


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
    d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Netbuild", "LevelShift", "logs")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


class DefineWindow(forms.WPFWindow):
    """Define the new level: an absolute elevation, or a move up / down from the current one."""

    def __init__(self, name, cur, units, mode, text):
        forms.WPFWindow.__init__(self, ui.define_xaml(units), literal_string=True)
        self.cur, self.units, self.result = cur, units, None
        self.name_tb.Text = name
        self.cur_tb.Text = fmt(cur, units)
        self.to_rb.IsChecked = mode != "by"
        self.by_rb.IsChecked = mode == "by"
        self.up_rb.IsChecked = True
        if mode == "to":
            self.abs_tb.Text = text
        elif mode == "by":
            try:
                v = parse_length(text, units)
                self.amount_tb.Text = ("%." + ("1" if units == "mm" else "4") + "f") % abs(v)
                self.down_rb.IsChecked = v < 0
            except ValueError:
                pass
        for w in (self.to_rb, self.by_rb, self.up_rb, self.down_rb):
            w.Checked += self.preview
        for w in (self.abs_tb, self.amount_tb):
            w.TextChanged += self.preview
        self.ok_btn.Click += self.ok
        self.cancel_btn.Click += self.cancel
        self.preview(None, None)

    def value(self):
        return core.define_value("to" if self.to_rb.IsChecked else "by", self.abs_tb.Text, self.amount_tb.Text,
                                 bool(self.up_rb.IsChecked), self.units)

    def preview(self, sender, args):
        try:
            mode, v = self.value()
        except ValueError:
            self.result_tb.Text = "New elevation: --"
            return
        new, delta = (v, v - self.cur) if mode == "to" else (self.cur + v, v)
        self.result_tb.Text = "New elevation: %s     move: %s %s" % (
            fmt(new, self.units), fmt(delta, self.units, True),
            "(up)" if delta > 0 else ("(down)" if delta < 0 else ""))

    def ok(self, sender, args):
        try:
            self.result = self.value()
        except ValueError as e:
            forms.alert(str(e), title="Define new level")
            return
        self.Close()

    def cancel(self, sender, args):
        self.Close()


class LevelShiftWindow(forms.WPFWindow):
    def __init__(self, doc):
        forms.WPFWindow.__init__(self, ui.window_xaml(N), literal_string=True)
        self.doc = doc
        self.levels = []
        self.mode = [None] * N          # per row: "to" | "by" -- the field typed in last
        self.guard = False
        self.Title = "Netbuild Level Shift %s (direct) -- %s" % (__version__, doc.Title)
        self.model_tb.Text = doc.Title
        units = CFG.get_option("units", "mm")
        self.m_rb.IsChecked = units == "m"
        self.mm_rb.IsChecked = units != "m"
        self.mm_rb.Checked += self.on_units
        self.m_rb.Checked += self.on_units
        s = options()
        self.tol_tb.Text = "%s" % s["tolerance_mm"]
        self.fallback_cb.IsChecked = s["move_fallback"]
        self.rollback_cb.IsChecked = s["rollback_on_drift"]
        self.groups_cb.IsChecked = s["fix_groups"]
        for i in range(N):
            self.w("lvl", i).SelectionChanged += self._handler(self.on_level, i)
            self.w("new", i).TextChanged += self._handler(self.on_edit, i, "to")
            self.w("by", i).TextChanged += self._handler(self.on_edit, i, "by")
            self.w("def", i).Click += self._handler(self.on_define, i)
        self.same_btn.Click += self.on_same
        self.clear_btn.Click += lambda s_, e: self.clear_values()
        self.clear_rows_btn.Click += self.on_clear_rows
        self.check_btn.Click += lambda s_, e: self.run("plan")
        self.trial_btn.Click += lambda s_, e: self.run("trial")
        self.apply_btn.Click += lambda s_, e: self.run("apply")
        self.logs_btn.Click += lambda s_, e: Process.Start(logs_dir())
        self.close_btn.Click += lambda s_, e: self.Close()
        self.load_levels()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _handler(fn, *bound):
        return lambda sender, args: fn(*bound)

    def w(self, kind, i):
        return self.FindName("%s_%d" % (kind, i))

    def units(self):
        return "m" if self.m_rb.IsChecked else "mm"

    def level(self, i):
        name = self.w("lvl", i).SelectedItem
        for lv in self.levels:
            if name and lv["name"] == name:
                return lv
        return None

    def cur(self, i):
        lv = self.level(i)
        return from_ft(lv["elev"], self.units()) if lv else None

    def status(self, text):
        self.status_tb.Text = text

    def show(self, title, checks, lines=()):
        self.report_lb.Items.Clear()
        for colour, text in [("#000000", title)] + ui.report_lines(checks, list(lines)):
            item = ListBoxItem()
            item.Content = text
            item.Foreground = brush(colour)
            self.report_lb.Items.Add(item)

    # ------------------------------------------------------------ rows
    def load_levels(self):
        try:
            out = core.run_local(self.doc, "levels")
        except Exception as e:
            self.show("Levels", [core.Check("Stopped", False, str(e))])
            return
        self.levels = out["LEVELS"]
        names = [lv["name"] for lv in self.levels]
        for i in range(N):
            cb = self.w("lvl", i)
            keep = cb.SelectedItem
            cb.Items.Clear()
            cb.Items.Add("")
            for n in names:
                cb.Items.Add(n)
            cb.SelectedItem = keep if keep in names else ""
            self.on_level(i)
        bases = sorted(set(lv.get("base") or "?" for lv in self.levels))
        self.base_tb.Text = "Elevations as shown in Revit -- Elevation Base: %s" % ", ".join(bases)
        self.status("%d levels in %s -- pick up to %d, define the new elevation, then Check." % (
            len(self.levels), self.doc.Title, N))

    def on_units(self, sender, args):
        CFG.units = self.units()
        script.save_config()
        self.clear_values()
        for i in range(N):
            self.on_level(i)

    def on_level(self, i):
        cur = self.cur(i)
        self.w("cur", i).Text = fmt(cur, self.units()) if cur is not None else ""
        if self.mode[i]:
            self.on_edit(i, self.mode[i])

    def on_edit(self, i, mode):
        if self.guard:
            return
        self.guard = True
        try:
            src, dst = (self.w("new", i), self.w("by", i)) if mode == "to" else (self.w("by", i), self.w("new", i))
            self.mode[i] = mode if src.Text.strip() else None
            try:
                dst.Text = core.counterpart(self.cur(i), mode, src.Text, self.units())
            except ValueError:
                dst.Text = "?"
            self._arrow(i)
        finally:
            self.guard = False

    def _arrow(self, i):
        d = None
        try:
            d = parse_length(self.w("by", i).Text, self.units())
        except ValueError:
            pass
        tb = self.w("dir", i)
        tb.Text = "" if d is None else ("UP" if d > 0 else ("DOWN" if d < 0 else "--"))
        tb.Foreground = brush(ui.UP if d and d > 0 else (ui.DOWN if d and d < 0 else ui.NONE))

    def set_value(self, i, mode, value):
        n = 1 if self.units() == "mm" else 4
        text = ("%." + str(n) + "f") % value if mode == "to" else ("%+." + str(n) + "f") % value
        self.guard = True
        self.w("new", i).Text = ""
        self.w("by", i).Text = ""
        self.guard = False
        self.w("new" if mode == "to" else "by", i).Text = text      # fires on_edit -> fills the other

    def clear_values(self):
        self.guard = True
        for i in range(N):
            self.w("new", i).Text = ""
            self.w("by", i).Text = ""
            self.w("dir", i).Text = ""
            self.mode[i] = None
        self.guard = False

    def on_clear_rows(self, sender, args):
        self.clear_values()
        for i in range(N):
            self.w("lvl", i).SelectedItem = ""

    def on_define(self, i):
        lv = self.level(i)
        if lv is None:
            forms.alert("Pick the level in row %d first." % (i + 1), title="Define new level")
            return
        mode = self.mode[i]
        text = (self.w("new", i) if mode == "to" else self.w("by", i)).Text if mode else ""
        dlg = DefineWindow(lv["name"], self.cur(i), self.units(), mode, text)
        dlg.Owner = self                    # centred on, and kept in front of, this window
        dlg.show_dialog()
        if dlg.result:
            self.set_value(i, *dlg.result)

    def on_same(self, sender, args):
        text = forms.ask_for_string(prompt="Move every selected level by (+up / -down, %s):" % self.units(),
                                    title="Same move for every row")
        if not text:
            return
        try:
            v = parse_length(text, self.units())
        except ValueError as e:
            forms.alert(str(e), title="Same move")
            return
        for i in range(N):
            if self.level(i):
                self.set_value(i, "by", v)

    def specs(self):
        out = []
        for i in range(N):
            lv, mode = self.level(i), self.mode[i]
            if not lv or not mode:
                continue
            text = (self.w("new", i) if mode == "to" else self.w("by", i)).Text
            out.append(core.MoveSpec(lv["name"], mode, parse_length(text, self.units())))
        return out

    # ------------------------------------------------------------ run
    def save_options(self):
        try:
            CFG.tolerance_mm = float(self.tol_tb.Text)
        except ValueError:
            pass
        CFG.move_fallback = bool(self.fallback_cb.IsChecked)
        CFG.rollback_on_drift = bool(self.rollback_cb.IsChecked)
        CFG.fix_groups = bool(self.groups_cb.IsChecked)
        script.save_config()

    def run(self, action):
        title = {"plan": "Check", "trial": "Trial run", "apply": "Apply"}[action]
        try:
            specs = self.specs()
        except ValueError as e:
            forms.alert(str(e), title=title)
            return
        if not specs:
            forms.alert("Pick a level and type its new elevation (or a move) in at least one row.", title=title)
            return
        self.save_options()
        s, u = options(), self.units()
        moves, checks = core.resolve(self.levels, specs, u, s["tolerance_mm"])
        lines = []
        if [c for c in checks if c.ok is False]:
            self.show(title, checks)
            self.status("Fix the FAIL lines first.")
            return
        if action == "apply" and not forms.alert(
                "Move these levels in %s?\n\n%s\n\nEvery element hosted to them keeps its position. "
                "One Undo entry in Revit." % (self.doc.Title, "\n".join(
                    "%s:  %s -> %s" % (m["name"], fmt_ft(m["elev"], u), fmt_ft(m["new"], u)) for m in moves)),
                title="Apply", yes=True, no=True):
            return
        self.status("%s running in Revit ..." % title)
        Mouse.OverrideCursor = Cursors.Wait
        try:
            out = core.run_local(self.doc, action, moves, s)
            c2, l2 = core.plan_checks(out["PLAN"], moves)
            checks += c2
            lines += l2
            if action != "plan":
                c3, l3 = core.result_checks(action, out["RESULT"], u, s["tolerance_mm"])
                checks += c3
                lines += l3
        except Exception as e:
            out = {}
            checks.append(core.Check("Stopped", False, "%s: %s" % (type(e).__name__, e)))
        finally:
            Mouse.OverrideCursor = None
        result = out.get("RESULT") or {}
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if result.get("rows"):
            path = core.write_rows_csv(os.path.join(logs_dir(), "%s_%s_elements.csv" % (stamp, action)),
                                       result["rows"], u)
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
        if action == "apply" and result.get("committed"):
            self.clear_values()
            self.load_levels()
            self.status("Applied -- levels re-read. Ctrl+Z in Revit undoes it ('Netbuild Level Shift').")


def fmt_ft(feet, units):
    return fmt(from_ft(feet, units), units)


doc = revit.doc
if doc is None or doc.IsFamilyDocument:
    forms.alert("Open a project model first.", title="Level Shift", exitscript=True)
if doc.IsReadOnly:
    forms.alert("%s is read-only -- open it editable (detach / local copy) to move levels." % doc.Title,
                title="Level Shift", exitscript=True)
LevelShiftWindow(doc).show_dialog()

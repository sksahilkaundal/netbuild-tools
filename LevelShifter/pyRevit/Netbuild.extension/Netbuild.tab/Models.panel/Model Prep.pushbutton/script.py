# -*- coding: utf-8 -*-
"""Model Prep by Netbuild -- prepare a building host model in three steps.

01 audit the discipline links (building-specific only; wrong-scope Tower / Site-Wide links removed),
02 create the workset register's missing worksets (none deleted; look-alike spellings renamed only when ticked),
03 put every link type AND instance on its Link-* workset (anything without a confident rule is asked).
Check (changes nothing) -> Decisions... -> Apply (one Undo entry: 'Model Prep by Netbuild'), verified afterwards.
Runs directly inside Revit (no exe, no MCP listener).
(c) 2026 Netbuild. All rights reserved. https://skaec.com
About / Licence: the About button in the window, or Netbuild > About, Licence.
"""

__title__ = "Model\nPrep"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

import datetime
import io
import os

from pyrevit import forms, revit, script

from System.Diagnostics import Process, ProcessStartInfo
from System.Windows import Clipboard
from System.Windows.Controls import ListBoxItem
from System.Windows.Input import Cursors, Mouse
from System.Windows.Media import BrushConverter

from model_prep import about, core, xlsx
from model_prep import revit as prep
from model_prep import rules as rules_mod
import modelprep_ui as ui
import netbuild_about

CFG = script.get_config()
_BRUSHES = BrushConverter()
SAVED_LIST = "(the list saved in the rules)"


def brush(colour):
    return _BRUSHES.ConvertFromString(colour)


def label(text):
    """CheckBox text: WPF reads '_' as an access key (Studio_AR -> StudioAR), '__' shows one underscore."""
    return text.replace(u"_", u"__")


def logs_dir():
    d = os.path.join(rules_mod.user_dir(), "logs")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


class DecisionsWindow(forms.WPFWindow):
    """What only the user decides: links to remove, look-alike worksets to rename, links without a rule."""

    def __init__(self, plan):
        s1 = plan["step01"]
        self.wrong = s1["wrong"] if s1 else []
        d = plan["decisions"]
        answered = d["answers"]
        self.pairs = list(plan["suggest"])
        ticked = set(tuple(p) for p in d["pairs"])
        for old, new in d["pairs"]:                         # a ticked pair no longer suggested stays listed
            if not [p for p in self.pairs if (p["old"], p["new"]) == (old, new)]:
                self.pairs.append({"old": old, "new": new, "score": 0, "both": False})
        self.asks = [r for r in (plan["step03"] or []) if r["status"] == "ASK" or r["name"] in answered]
        forms.WPFWindow.__init__(self, ui.decisions_xaml(len(self.wrong), len(self.pairs), len(self.asks)),
                                 literal_string=True)
        self.result = None
        removing = set(w["link"]["id"] for w in plan["remove"])
        for i, w in enumerate(self.wrong):
            cb = self.FindName("rm_%d" % i)
            cb.Content = label(u"%s [%s] %s -- a %s file%s" % (
                w["kind"], w["disc"], w["link"]["name"], w["code"],
                u"" if w["kind"] == "WRONG SCOPE" else u" (check: is this cross-reference wanted?)"))
            cb.IsChecked = w["link"]["id"] in removing
        for i, p in enumerate(self.pairs):
            cb = self.FindName("pair_%d" % i)
            cb.Content = label(u"Rename model workset '%s'  ->  register '%s'%s" % (
                p["old"], p["new"], u"   (both are in the model: the register's one must be empty)" if p["both"] else u""))
            cb.IsChecked = (p["old"], p["new"]) in ticked
        final = plan["final"]
        for i, r in enumerate(self.asks):
            q = r["question"] or {}
            self.FindName("ask_name_%d" % i).Text = u"%s\n%s -- now on %s%s" % (
                r["name"], q.get("why") or u"your earlier answer", core.where(r),
                (u"\nsuggested: '%s'" % q["suggest"]) if q.get("suggest") else u"")
            cb = self.FindName("ask_ws_%d" % i)
            suggest = q.get("suggest")
            items = [ui.LEAVE] + ([suggest] if suggest in final else []) + [n for n in final if n != suggest]
            for n in items:
                cb.Items.Add(n)
            cb.SelectedItem = answered.get(r["name"]) or ui.LEAVE
        self.ok_btn.Click += self.ok
        self.cancel_btn.Click += lambda s_, e: self.Close()

    def ok(self, sender, args):
        answers = {}
        for i, r in enumerate(self.asks):
            ws = self.FindName("ask_ws_%d" % i).SelectedItem
            if ws and ws != ui.LEAVE:
                answers[r["name"]] = ws
        self.result = {
            "remove_ids": set(w["link"]["id"] for i, w in enumerate(self.wrong)
                              if self.FindName("rm_%d" % i).IsChecked),
            "pairs": [(p["old"], p["new"]) for i, p in enumerate(self.pairs) if self.FindName("pair_%d" % i).IsChecked],
            "answers": answers,
            "remember": bool(self.remember_cb.IsChecked)}
        self.Close()


class ModelPrepWindow(forms.WPFWindow):
    def __init__(self, doc):
        forms.WPFWindow.__init__(self, ui.window_xaml(), literal_string=True)
        self.doc = doc
        self.rules = rules_mod.load()
        self.decisions = core.default_decisions()
        self.plan = None
        self.tabs = []
        self.register = None
        self.register_source = None
        self.guard = False
        self.Title = about.title(doc.Title)
        self.model_tb.Text = doc.Title
        det = core.host(doc.Title, self.rules)
        self.building_tb.Text = det["building"] or ""
        self.host_tb.Text = (u"read from the model name: %s, %s host -- check it is the building you mean" % (
            det["building"], det["disc"] or "?") if det["building"] else
            u"could not read a building code from the model name -- type it (e.g. B001)")
        self.register_tb.Text = CFG.get_option("register_path", "") or self.rules["register_path"]
        self.building_tb.TextChanged += self.changed
        self.sheet_cb.SelectionChanged += self.on_sheet
        for cb in (self.step1_cb, self.step2_cb, self.step3_cb):
            cb.Checked += self.changed
            cb.Unchecked += self.changed
        self.browse_btn.Click += self.on_browse
        self.reload_btn.Click += lambda s_, e: self.read_register()
        self.check_btn.Click += lambda s_, e: self.check()
        self.decide_btn.Click += self.on_decide
        self.apply_btn.Click += lambda s_, e: self.apply()
        self.paths_btn.Click += self.on_paths
        self.rules_btn.Click += self.on_rules
        self.logs_btn.Click += lambda s_, e: Process.Start(logs_dir())
        self.about_btn.Click += lambda s_, e: netbuild_about.show(about, owner=self)
        self.close_btn.Click += lambda s_, e: self.Close()
        self.read_register()
        self.status(u"Check first: it changes nothing and shows the full report. Then Decisions... and Apply.")

    # ------------------------------------------------------------ helpers
    def status(self, text):
        self.status_tb.Text = text

    def show(self, lines):
        self.report_lb.Items.Clear()
        for level, text in lines:
            item = ListBoxItem()
            item.Content = (u"[%s] %s" % (level, text)) if level not in (core.INFO, core.HEAD) else (
                (u"== %s" % text) if level == core.HEAD else u"       " + text)
            item.Foreground = brush(ui.COLOURS.get(level, "#333333"))
            self.report_lb.Items.Add(item)

    def live_names(self):
        return [w.Name for w in prep.user_worksets(self.doc)]

    def steps(self):
        return set(n for n, cb in ((1, self.step1_cb), (2, self.step2_cb), (3, self.step3_cb)) if cb.IsChecked)

    def changed(self, sender=None, args=None):
        """Anything changed since the last Check: Apply waits for a new Check."""
        if self.guard:
            return
        self.plan = None
        self.apply_btn.IsEnabled = False

    # ------------------------------------------------------------ the register
    def read_register(self):
        path = self.register_tb.Text.strip()
        try:
            self.tabs = xlsx.read_register(path, self.rules.get("register_column") or "A",
                                           int(self.rules.get("register_skip_rows") or 0))
            self.read_error = None
        except Exception as e:
            self.tabs, self.read_error = [], u"%s" % e
        live = self.live_names()
        wanted = CFG.get_option("register_sheet", None) or self.rules["register_sheet"]
        pick = core.best_tab(self.tabs, live, wanted)
        self.guard = True
        self.sheet_cb.Items.Clear()
        for name, names in self.tabs:
            self.sheet_cb.Items.Add(name)
        self.sheet_cb.Items.Add(SAVED_LIST)
        self.guard = False
        if self.sheet_cb.SelectedItem == (pick or SAVED_LIST):
            self.on_sheet()
        self.sheet_cb.SelectedItem = pick or SAVED_LIST

    def on_sheet(self, sender=None, args=None):
        if self.guard:
            return
        sel = self.sheet_cb.SelectedItem
        live = self.live_names()
        tabs = dict(self.tabs)
        if sel in tabs:
            names = tabs[sel]
            n, hit, share = core.check_register(names, live)
            fits = share >= float(self.rules.get("register_min_match") or 0)
            text = u"Register tab '%s': %d names, %d already in this model (%d%%)%s%s" % (
                sel, n, hit, int(round(share * 100)),
                u"" if fits else u" -- few match: check this tab belongs to this model before trusting it",
                u"" if sel == self.rules["register_sheet"] else u"  (the rules name tab '%s')" % self.rules["register_sheet"])
            level = core.OK if fits and n else core.WARN
            CFG.register_sheet = sel
            script.save_config()
        else:
            names = list(self.rules.get("worksets") or [])
            text = u"Register %s -- using the list saved in the rules (%d names)" % (
                (u"not read: %s" % self.read_error) if self.read_error else u"tab not chosen", len(names))
            level = core.WARN
        self.register, self.register_source = names, (text, level)
        self.register_info_tb.Text = text
        self.changed()

    def on_browse(self, sender, args):
        cur = self.register_tb.Text.strip()
        path = forms.pick_file(file_ext="xlsx", init_dir=os.path.dirname(cur) if cur else "",
                               title="Workset register (.xlsx)")
        if not path:
            return
        self.register_tb.Text = path
        CFG.register_path = path
        script.save_config()
        self.read_register()

    # ------------------------------------------------------------ check / decide / apply
    def make_plan(self):
        self.rules = rules_mod.load()                     # Rules... edits count from the next Check
        self.decisions["steps"] = self.steps()
        snap = prep.snapshot(self.doc)
        live = set(w["name"] for w in snap["worksets"])
        counts = dict((new, prep.count_elements(self.doc, new)) for old, new in self.decisions["pairs"] if new in live)
        return core.make_plan(snap, self.rules, self.building_tb.Text.strip().upper(), self.register,
                              self.decisions, counts)

    def check(self):
        if not self.steps():
            forms.alert("Tick at least one step.", title="Check")
            return None
        Mouse.OverrideCursor = Cursors.Wait
        try:
            plan = self.make_plan()
        finally:
            Mouse.OverrideCursor = None
        lines = core.report(plan, self.rules, self.register_source)
        self.show(lines)
        self.plan = plan
        blocked = [l for l in core.preflight(plan, self.rules) if l[0] == core.FAIL]
        a = core.actions(plan)
        todo = a["remove"] + a["create"] + a["rename"] + a["move"]
        self.apply_btn.IsEnabled = bool(todo) and not blocked
        asks = len(core.questions(plan)) + len([p for p in plan["suggest"]
                                                if (p["old"], p["new"]) not in set(self.decisions["pairs"])])
        if blocked:
            self.status(u"Fix the FAIL line at the top first.")
        elif not todo:
            self.status(u"Nothing to change%s." % (u" -- %d item(s) to decide: Decisions..." % asks if asks else u""))
        else:
            self.status(u"Check done -- nothing changed yet. Apply would: remove %d link(s), create %d workset(s), "
                        u"rename %d, set %d placement(s).%s" % (a["remove"], a["create"], a["rename"], a["move"], (
                            u" %d item(s) to decide first: Decisions..." % asks) if asks else u""))
        return plan

    def on_decide(self, sender, args):
        plan = self.plan or self.check()
        if plan is None:
            return
        dlg = DecisionsWindow(plan)
        dlg.Owner = self
        dlg.show_dialog()
        r = dlg.result
        if not r:
            return
        self.decisions.update({"remove_ids": r["remove_ids"], "pairs": r["pairs"], "answers": r["answers"]})
        if r["remember"] and r["answers"]:
            path = rules_mod.remember(r["answers"])
            self.status(u"Answers saved as rules in %s" % path)
        self.check()

    def apply(self):
        if self.plan is None:
            forms.alert("Check first -- Apply runs what the last Check showed.", title="Apply")
            return
        before = core.report(self.plan, self.rules, self.register_source)
        plan = self.make_plan()
        if core.report(plan, self.rules, self.register_source) != before:
            self.plan = plan
            self.show(core.report(plan, self.rules, self.register_source))
            self.status(u"The model changed since Check -- this is the new report. Apply again to run it.")
            return
        a = core.actions(plan)
        s2 = plan["step02"]
        msg = [u"Apply to %s (host building %s)?" % (self.doc.Title, plan["building"]), u""]
        if a["remove"]:
            msg.append(u"Remove %d link(s): %s" % (a["remove"], u", ".join(w["link"]["name"] for w in plan["remove"])))
        if a["create"]:
            msg.append(u"Create %d workset(s)" % a["create"])
        if a["rename"]:
            msg.append(u"Rename: %s" % u"; ".join(u"'%s' -> '%s'" % (r["old"], r["new"]) for r in s2["renames"]))
        if a["move"]:
            msg.append(u"Set %d link type / instance workset(s)" % a["move"])
        msg += [u"", u"One Undo entry in Revit: '%s'. Synchronize afterwards." % about.PRODUCT]
        if not forms.alert(u"\n".join(msg), title="Apply", yes=True, no=True):
            return
        self.status(u"Applying ...")
        log = []
        Mouse.OverrideCursor = Cursors.Wait
        try:
            done = prep.apply(self.doc, plan, log)
            error = None
        except Exception as e:
            done, error = None, u"%s: %s" % (type(e).__name__, e)
        finally:
            Mouse.OverrideCursor = None
        lines = [(core.HEAD, u"APPLY -- %s" % self.doc.Title)]
        if error:
            lines.append((core.FAIL, u"Stopped and rolled back -- nothing changed: %s" % error))
        else:
            lines.append((core.OK, u"Removed %d link(s), created %d workset(s), renamed %d, set %d placement(s)" % (
                done["removed"], done["created"], done["renamed"], done["set"])))
            lines += [(core.WARN, s) for s in done["skipped"]]
            lines.append((core.HEAD, u"VERIFY -- the model read back"))
            lines += core.verify(plan, prep.snapshot(self.doc))
            self.decisions.update({"remove_ids": None, "pairs": []})
        after = self.check()
        lines += core.report(after, self.rules, self.register_source) if after else []
        path = self.write_log(before, log, lines)
        lines.append((core.INFO, u"log: %s" % path))
        self.show(lines)
        self.status(u"Applied -- Ctrl+Z in Revit undoes it ('%s'). Synchronize to keep it." % about.PRODUCT
                    if not error else u"Apply stopped -- see the FAIL line; the model is unchanged.")

    def write_log(self, before, log, lines):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(logs_dir(), u"%s_%s.log" % (stamp, self.building_tb.Text.strip() or "model"))
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(u"%s -- %s\n\nCHECK\n" % (about.title(), self.doc.Title))
            for level, text in before:
                f.write(u"[%s] %s\n" % (level, text))
            f.write(u"\nCHANGES\n")
            for text in log:
                f.write(u"%s\n" % text)
            f.write(u"\nRESULT\n")
            for level, text in lines:
                f.write(u"[%s] %s\n" % (level, text))
        return path

    # ------------------------------------------------------------ the other buttons
    def on_paths(self, sender, args):
        plan = self.plan or self.check()
        missing = plan["step01"]["missing"] if plan and plan["step01"] else []
        if not missing:
            forms.alert("No discipline is missing (or Step 01 is not ticked).", title="Missing links")
            return
        text = u"\n".join(core.link_instructions(missing, self.rules, plan["building"]))
        Clipboard.SetText(text)
        forms.alert(text, title="Copied -- link these by hand")

    def on_rules(self, sender, args):
        path = rules_mod.ensure_user_file()
        Process.Start(ProcessStartInfo("notepad.exe", u'"%s"' % path))
        forms.alert(u"The rules open in Notepad:\n%s\n\nSave them, then press Check -- they are read again on every "
                    u"Check. Delete the file to go back to the built-in rules." % path, title="Rules")


doc = revit.doc
problem = prep.model_problem(doc)
if problem:
    forms.alert(problem, title=about.PRODUCT, exitscript=True)
ModelPrepWindow(doc).show_dialog()

# -*- coding: utf-8 -*-
"""Place Links (Model Prep by Netbuild) -- right after linking a model by hand: put every link type AND instance on
its Link-* workset (Model Prep's Step 03 alone). A new link lands on the current workset; this moves it.

Shows what it will move and asks first; links without a confident rule are listed, never guessed (resolve them in
Model Prep > Decisions...). One Undo entry: 'Model Prep by Netbuild'.
(c) 2026 Netbuild. All rights reserved. https://skaec.com
"""

__title__ = "Place\nLinks"
__author__ = "Netbuild -- skaec.com"

import netbuild_scripts
netbuild_scripts.run_live(globals())       # the script folder's copy of this button, when there is one

from pyrevit import forms, revit

from model_prep import about, core
from model_prep import revit as prep
from model_prep import rules as rules_mod

TITLE = "Place Links -- " + about.PRODUCT
MAX_LINES = 25


def short(lines):
    return lines[:MAX_LINES] + ([u"... and %d more" % (len(lines) - MAX_LINES)] if len(lines) > MAX_LINES else [])


doc = revit.doc
problem = prep.model_problem(doc)
if problem:
    forms.alert(problem, title=TITLE, exitscript=True)
rules = rules_mod.load()
building = core.host(doc.Title, rules)["building"]
if not building:
    building = (forms.ask_for_string(prompt="Host building code of %s (e.g. B001):" % doc.Title, title=TITLE) or
                "").strip().upper()
    if not building:
        forms.alert("No host building -- nothing changed.", title=TITLE, exitscript=True)

plan = core.make_plan(prep.snapshot(doc), rules, building, None, {"steps": set([3])})
rows = plan["step03"]
moves = [r for r in rows if r["status"] == "MOVE"]
asks = [u"%s -- %s" % (r["name"], r["question"]["why"]) for r in rows if r["status"] == "ASK"]
borrowed = [u"%s -- owned by %s" % (r["name"], ", ".join(r["borrowed"])) for r in rows if r["status"] == "BORROWED"]
notes = ([u"", u"Not placed -- no confident rule (resolve in Model Prep > Decisions...):"] + short(asks) if asks else []) + (
    [u"", u"Not placed -- borrowed by another user:"] + short(borrowed) if borrowed else [])

if not moves:
    forms.alert(u"\n".join([u"%s (host %s): %d link(s), none to move." % (doc.Title, building, len(rows))] + notes),
                title=TITLE, exitscript=True)

msg = [u"Put these links on their worksets in %s (host %s)?" % (doc.Title, building), u""]
msg += short([u"%s: %s -> '%s'" % (r["name"], core.where(r), r["target"]) for r in moves])
msg += notes + [u"", u"One Undo entry: '%s'." % about.PRODUCT]
if forms.alert(u"\n".join(msg), title=TITLE, yes=True, no=True):
    try:
        done = prep.apply(doc, plan)
    except Exception as e:
        forms.alert(u"Stopped and rolled back -- nothing changed.\n\n%s: %s" % (type(e).__name__, e), title=TITLE,
                    exitscript=True)
    checks = core.verify(plan, prep.snapshot(doc))
    forms.alert(u"\n".join([u"Placed %d link(s): %d workset assignment(s) set." % (len(moves), done["set"])] +
                           [u"[%s] %s" % (level, text) for level, text in checks] + done["skipped"] + notes),
                title=TITLE)

# -*- coding: utf-8 -*-
"""
Revit MCP Router - multi-model core (compiled to a .pyd for release).

Runs one IronPython task against SEVERAL models open in the SAME Revit, one
model per HTTP call, binding each model by document title (never by whichever
window is active). Same payloads and rules as scripts\\MultiModelBatch.py:
nonce-tagged results, own TransactionGroup per model, dry run = the task really
runs and is rolled back, apply = assimilated into one undo step per model.

The transport is injected (`post(code, description, timeout) -> (output, error)`)
so the bridge can hand it the routed call and tests can hand it a fake.
"""
import json
import os
import time
import uuid

CALL_TIMEOUT_S = 600.0   # per model; long tasks are fine, the bridge call is not cut at 60 s

DISCOVER_CODE = r'''from __future__ import print_function
import json
NONCE = %(nonce)r
# doc is None on the Home screen / with only families closed; the Application is still there
app = doc.Application if doc is not None else revit.HOST_APP.app
active = (doc.Title, doc.PathName) if doc is not None else None
docs = []
for d in app.Documents:
    try:
        # IsModifiable is only True while a transaction is open; IsReadOnly is the real flag.
        docs.append({"title": d.Title, "path": d.PathName, "linked": bool(d.IsLinked),
                     "family": bool(d.IsFamilyDocument), "modifiable": not bool(d.IsReadOnly),
                     "workshared": bool(d.IsWorkshared), "active": (d.Title, d.PathName) == active})
    except Exception as e:
        docs.append({"title": "?", "error": str(e)})
print("@@RESULT:%%s@@ %%s" %% (NONCE, json.dumps(docs)))
'''

RUNNER_CODE = r'''from __future__ import print_function
# (IronPython 2.7: without the future import, `print` is a keyword and the
#  "print": print entry in the task namespace below is a SyntaxError)
import json, time, traceback
NONCE = %(nonce)r
TARGET = %(title)r
APPLY = %(apply)r
SWALLOW = %(swallow)r
TASK_SRC = %(task)r
result = {"ok": False, "title": TARGET, "nonce": NONCE}
_t0 = time.time()

def _emit():
    result["elapsed_s"] = round(time.time() - _t0, 2)
    print("@@RESULT:%%s@@ %%s" %% (NONCE, json.dumps(result)))

try:
    active_key = (doc.Title, doc.PathName) if doc is not None else None
    target = None
    for d in (doc.Application if doc is not None else revit.HOST_APP.app).Documents:
        if d.IsLinked or d.IsFamilyDocument:
            continue
        if d.Title == TARGET:
            target = d
            break
    if target is None:
        raise Exception("no open (non-linked) document titled %%r" %% TARGET)
    is_active = (target.Title, target.PathName) == active_key
    if APPLY and target.IsReadOnly:
        raise Exception("document was opened read-only; nothing can be committed to it")

    class _Pre(DB.IFailuresPreprocessor):
        def PreprocessFailures(self, fa):
            for f in fa.GetFailureMessages():
                if f.GetSeverity() == DB.FailureSeverity.Warning:
                    fa.DeleteWarning(f)
            return DB.FailureProcessingResult.Continue

    class _Tx(object):
        def __init__(self, name):
            self.name = name
            self.t = DB.Transaction(target, name)
        def __enter__(self):
            if SWALLOW:
                o = self.t.GetFailureHandlingOptions()
                o.SetFailuresPreprocessor(_Pre())
                self.t.SetFailureHandlingOptions(o)
            self.t.Start()
            return self.t
        def __exit__(self, et, ev, tb):
            if et is not None:
                if self.t.HasStarted() and not self.t.HasEnded():
                    self.t.RollBack()
                return False
            st = self.t.Commit()
            if st != DB.TransactionStatus.Committed:
                raise Exception("transaction %%r ended as %%s, not Committed" %% (self.name, st))
            return False

    _log = []
    class _Ctx(object):
        def transaction(self, name):
            return _Tx(name)
        def log(self, msg):
            _log.append(str(msg))
            print(str(msg))
    ctx = _Ctx()
    ctx.title = TARGET
    ctx.dry_run = not APPLY
    ctx.is_active = is_active

    ns = {"doc": target, "uidoc": uidoc if is_active else None, "DB": DB, "revit": revit,
          "ctx": ctx, "print": print, "result": {}}
    tg = DB.TransactionGroup(target, "Revit MCP multi-model " + ("apply" if APPLY else "dry run"))
    tg.Start()
    committed = False
    try:
        exec(TASK_SRC, ns)
        data = ns.get("result", {})
        if APPLY:
            committed = (tg.Assimilate() == DB.TransactionStatus.Committed)
            if not committed:
                raise Exception("TransactionGroup did not assimilate as Committed")
        else:
            tg.RollBack()
    except Exception:
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
        raise
    result.update({"ok": True, "committed": committed, "dry_run": not APPLY, "is_active": is_active,
                   "read_only": bool(target.IsReadOnly), "workshared": bool(target.IsWorkshared),
                   "data": data, "log": _log[-50:]})
except Exception as e:
    result["error"] = str(e)
    result["traceback"] = traceback.format_exc()[-2000:]
_emit()
'''


class MultiModelError(Exception):
    """User-facing: nothing was run."""


def parse_marker(output, nonce):
    """Find the '@@RESULT:<nonce>@@ {json}' line this call printed. None if absent."""
    tag = "@@RESULT:%s@@ " % nonce
    for line in reversed((output or "").splitlines()):
        if line.startswith(tag):
            try:
                return json.loads(line[len(tag):])
            except Exception as exc:
                return {"ok": False, "error": "result line was not JSON: %s" % exc}
    return None


def list_documents(post):
    nonce = uuid.uuid4().hex[:8]
    out, err = post(DISCOVER_CODE % {"nonce": nonce}, "Revit MCP: list open models", 60.0)
    docs = parse_marker(out, nonce)
    if docs is None:
        raise MultiModelError(err or "could not read the document list from Revit: %s" % (out or "")[-600:])
    return docs


def resolve_targets(targets, docs):
    """Map each requested title/substring to exactly one open, non-linked, non-family model."""
    pool = [d for d in docs if not d.get("linked") and not d.get("family") and d.get("title") not in (None, "?")]
    if not targets:
        act = [d for d in pool if d.get("active")]
        if not act:
            raise MultiModelError("no titles given and no active project document found")
        return act
    chosen, problems = [], []
    for want in targets:
        exact = [d for d in pool if d["title"].lower() == want.lower()]
        hits = exact or [d for d in pool if want.lower() in d["title"].lower()]
        if len(hits) == 1:
            if hits[0] not in chosen:
                chosen.append(hits[0])
        elif not hits:
            problems.append("%r matches no open model (open: %s)" % (want, ", ".join(d["title"] for d in pool) or "none"))
        else:
            problems.append("%r is ambiguous: %s" % (want, ", ".join(d["title"] for d in hits)))
    if problems:
        raise MultiModelError("cannot resolve models - nothing was run:\n  " + "\n  ".join(problems))
    return chosen


def load_task(code, task_file):
    if code and task_file:
        raise MultiModelError("give either code or task_file, not both")
    if code:
        return code
    if not task_file:
        raise MultiModelError("give the task as code or as task_file")
    if not os.path.isfile(task_file):
        raise MultiModelError("task file not found: %s" % task_file)
    with open(task_file, encoding="utf-8") as fh:
        return fh.read()


def run(post, titles, code=None, task_file=None, apply=False, swallow_warnings=False, stop_on_fail=False,
        output_chars=3000):
    """Resolve titles, then run the task on each model, one call per model. Never raises."""
    try:
        task = load_task(code, task_file)
        chosen = resolve_targets(titles or [], list_documents(post))
        if apply:
            ro = [d["title"] for d in chosen if not d.get("modifiable")]
            if ro:
                raise MultiModelError("refusing to APPLY - opened read-only: " + ", ".join(ro))
    except MultiModelError as e:
        return {"ok": False, "error": str(e)}

    results = []
    for d in chosen:
        title = d["title"]
        nonce = uuid.uuid4().hex[:8]
        t0 = time.time()
        out, err = post(RUNNER_CODE % {"nonce": nonce, "title": title, "apply": bool(apply),
                                       "swallow": bool(swallow_warnings), "task": task},
                        "Revit MCP multi-model: %s" % title, CALL_TIMEOUT_S)
        res = parse_marker(out, nonce)
        if res is None:
            res = {"ok": False, "title": title,
                   "error": err or "no tagged result came back (timeout or listener error); Revit rolled the model back"}
        res.pop("nonce", None)
        res.setdefault("elapsed_s", round(time.time() - t0, 2))
        printed = "\n".join(l for l in (out or "").splitlines() if not l.startswith("@@RESULT:")).strip()
        if printed:
            res["output"] = printed[-output_chars:]
        res.pop("log", None)   # already inside output
        results.append(res)
        if stop_on_fail and not res.get("ok"):
            break

    ok_n = sum(1 for r in results if r.get("ok"))
    summary = {"ok": ok_n == len(results) and len(results) == len(chosen),
               "mode": "APPLY (committed)" if apply else "DRY RUN (rolled back - nothing kept)",
               "models_ok": "%d/%d" % (ok_n, len(chosen)), "results": results}
    if apply:
        summary["unsynced_models"] = [r["title"] for r in results if r.get("committed")]
        summary["next"] = "Sync or save each model in unsynced_models yourself; nothing was synced."
    else:
        summary["next"] = "Review, then re-run with apply=true to commit. Workshared: a dry run can leave elements borrowed - relinquish if you will not apply."
    return summary

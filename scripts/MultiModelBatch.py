r"""
MultiModelBatch.py -- run ONE IronPython task against SEVERAL Revit models that
are open in the SAME Revit session, one model per call, binding each model by
its document title instead of trusting whichever window happens to be active.

Why this exists (the rules it encodes, see the prompt template for the story):
  * pyRevit Routes hands every call the ACTIVE document. With two or more
    models open, whatever you last clicked into is what a script edits. This
    runner never uses that: it resolves `doc.Application.Documents` by title.
  * One model per HTTP call. The MCP bridge times a call out at ~60 s and then
    loses the result; this driver talks to the listener directly with a long
    timeout, and each model's result comes back tagged with a nonce so a stale
    or lagged response can never be mistaken for the current model's.
  * Own TransactionGroup per model. Dry run = the task REALLY runs (so counts are
    real) and the group is rolled back; APPLY = the group is assimilated into
    one undo step. A task's transactions must end Committed or the model is
    reported as failed (a silent RollBack is not an error message in Revit).
  * UI operations (selection, zoom, active view) only exist for the active
    document: the task gets `uidoc` only when its model IS the active one.
  * Elements inside multi-placement model groups still roll back through the
    API -- tasks should bucket and list them (see tasks\template_modify_parameter.py).
  * Sync is per model. After APPLY the summary lists which models now hold
    unsynced changes; the runner never syncs for you.

Task contract (an IronPython 2.7 snippet, file or string). Names available:
    doc     the TARGET model (not necessarily the active window)
    uidoc   the active UIDocument if the target is the active model, else None
    DB      Autodesk.Revit.DB          revit   the pyRevit module
    ctx     ctx.title, ctx.dry_run, ctx.is_active, ctx.log(msg),
            `with ctx.transaction("name") as t:` -> a started DB.Transaction
            on the target model, committed on exit (raises unless Committed)
    result  assign a JSON-serialisable dict; it is printed in the summary table
Everything printed inside the task is captured and shown per model.

Usage (edit CONFIG or use the switches; dry run is the default per the standing rule):
    python MultiModelBatch.py --list                       # open models, which is active
    python MultiModelBatch.py --titles B001 B002           # dry run TASK_FILE on both
    python MultiModelBatch.py --titles B001 B002 --apply   # commit, one model per call
    python MultiModelBatch.py --task tasks\my_task.py --titles "3505-TA"

Revit access: POSTs to the pyRevit MCP listener's HTTP route
(http://127.0.0.1:48884/revit_mcp/execute_code/) -- the same call the
execute_revit_code MCP tool makes -- so it works whether or not the MCP tools
are loaded in the session, and on any PC where Revit + pyRevit + the
mcp-server-for-revit-python extension are installed. IronPython 2.7 rules
apply inside the task: no f-strings, `DB.Element.Name.__get__(e)` for .Name,
`str(e.Id)` for ids (Revit 2026 has no ElementId.IntegerValue).

First written 2026-09-21 (see the multi-model-batch-runner memory).
"""
from __future__ import print_function

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

# ============================== CONFIG ======================================
TARGET_DOC_TITLES = []      # [] = active document only. Else title substrings (case-insensitive),
                            # e.g. ["B001", "B002"]; an exact title always wins over a substring.
TASK_FILE = r"tasks\example_count_elements.py"   # IronPython task; relative to this script or absolute
TASK_CODE = None            # paste a task string here to bypass TASK_FILE
APPLY = False               # False = dry run (task runs, then rolled back per model); True = commit
SWALLOW_WARNINGS = False    # True = auto-dismiss Revit WARNINGS raised inside task transactions (never errors)
STOP_ON_FIRST_FAILURE = False
REVIT_URL = "http://127.0.0.1:48884/revit_mcp/execute_code/"
CALL_TIMEOUT_S = 600        # per model; direct HTTP, so no 60 s MCP-bridge cut-off
# ============================================================================

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------- HTTP ---
def revit(code, description="MultiModelBatch"):
    """POST IronPython to the listener. Returns (output_text, error_text)."""
    payload = {"code": code, "description": description, "use_transaction": False}
    req = urllib.request.Request(REVIT_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    http_status = 200
    try:
        body = urllib.request.urlopen(req, timeout=CALL_TIMEOUT_S).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:          # listener answered (e.g. 500 with a JSON error body)
        http_status = exc.code
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
    except Exception as exc:
        return "", "Revit unreachable (%s) -- is Revit open with the pyRevit MCP listener running?" % exc
    try:
        d = json.loads(body)
    except Exception:
        return body, ("" if http_status == 200 else "HTTP %s: %s" % (http_status, body[-800:]))
    if isinstance(d, dict):
        out = d.get("output") or d.get("partial_output") or ""   # the listener uses partial_output on error
        if d.get("status") == "success" and http_status == 200:
            return out, ""
        err = d.get("error") or "HTTP %s" % http_status
        tb = d.get("traceback") or ""
        return out, err + ("\n" + tb[-1500:] if tb else "")
    return body, ""


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


# ---------------------------------------------------- IronPython payloads ---
DISCOVER_CODE = r'''from __future__ import print_function
import json
NONCE = %(nonce)r
active = (doc.Title, doc.PathName)
docs = []
for d in doc.Application.Documents:
    try:
        # IsModifiable is only True while a transaction is open, so it is useless
        # here; IsReadOnly is the "opened read-only" flag we actually want.
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
    active_key = (doc.Title, doc.PathName)
    target = None
    for d in doc.Application.Documents:
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
    tg = DB.TransactionGroup(target, "MultiModelBatch " + ("apply" if APPLY else "dry run"))
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


# --------------------------------------------------------------- driver ---
def list_documents():
    nonce = uuid.uuid4().hex[:8]
    out, err = revit(DISCOVER_CODE % {"nonce": nonce}, "MultiModelBatch: list documents")
    if err:
        raise SystemExit(err)
    docs = parse_marker(out, nonce)
    if docs is None:
        raise SystemExit("could not read the document list from Revit; raw output:\n" + (out or "")[-800:])
    return docs


def resolve_targets(targets, docs):
    """Map each requested title/substring to exactly one open, non-linked, non-family document."""
    pool = [d for d in docs if not d.get("linked") and not d.get("family") and d.get("title") not in (None, "?")]
    if not targets:
        act = [d for d in pool if d.get("active")]
        if not act:
            raise SystemExit("no target titles given and no active project document found")
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
        raise SystemExit("cannot resolve targets:\n  " + "\n  ".join(problems))
    return chosen


def load_task(task_file, task_code):
    if task_code:
        return task_code, "<inline TASK_CODE>"
    path = task_file if os.path.isabs(task_file) else os.path.join(HERE, task_file)
    if not os.path.isfile(path):
        raise SystemExit("task file not found: %s" % path)
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read(), path


def run_model(title, task_src, apply, swallow):
    nonce = uuid.uuid4().hex[:8]
    code = RUNNER_CODE % {"nonce": nonce, "title": title, "apply": bool(apply),
                          "swallow": bool(swallow), "task": task_src}
    out, err = revit(code, "MultiModelBatch: %s" % title)
    res = parse_marker(out, nonce)
    if res is None:
        return {"ok": False, "title": title,
                "error": err or "no tagged result came back (timeout or listener error)",
                "raw": (out or "")[-1500:]}
    res["raw"] = out
    return res


def summarize_data(data):
    if not isinstance(data, dict) or not data:
        return "-"
    parts = []
    for k in sorted(data):
        v = data[k]
        if isinstance(v, (list, dict)):
            v = "%d items" % len(v)
        parts.append("%s=%s" % (k, v))
    return ", ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run one IronPython task on several open Revit models, one call per model.")
    ap.add_argument("--list", action="store_true", help="list open documents and exit")
    ap.add_argument("--titles", nargs="*", help="document titles or substrings (overrides CONFIG)")
    ap.add_argument("--task", help="task file path (overrides CONFIG)")
    ap.add_argument("--apply", action="store_true", help="commit instead of dry run")
    ap.add_argument("--swallow-warnings", action="store_true", help="auto-dismiss Revit warnings in task transactions")
    ap.add_argument("--stop-on-fail", action="store_true", help="stop at the first failed model")
    ap.add_argument("--quiet", action="store_true", help="hide the per-model captured output")
    a = ap.parse_args(argv)

    docs = list_documents()
    if a.list:
        print("Open documents (%d):" % len(docs))
        for d in docs:
            flags = []
            if d.get("active"): flags.append("ACTIVE")
            if d.get("linked"): flags.append("linked")
            if d.get("family"): flags.append("family")
            if d.get("workshared"): flags.append("workshared")
            if not d.get("modifiable"): flags.append("read-only")
            print("  %-45s %s" % (d.get("title"), " ".join(flags)))
        return 0

    targets = a.titles if a.titles is not None else TARGET_DOC_TITLES
    apply = bool(a.apply or APPLY)
    swallow = bool(a.swallow_warnings or SWALLOW_WARNINGS)
    stop_on_fail = bool(a.stop_on_fail or STOP_ON_FIRST_FAILURE)
    task_src, task_label = load_task(a.task or TASK_FILE, None if a.task else TASK_CODE)
    chosen = resolve_targets(targets, docs)

    print("MultiModelBatch  mode=%s  task=%s" % ("APPLY (commit)" if apply else "DRY RUN (rolled back)", task_label))
    print("Models (%d): %s" % (len(chosen), ", ".join(d["title"] + (" [active]" if d.get("active") else "") for d in chosen)))
    if apply:
        ro = [d["title"] for d in chosen if not d.get("modifiable")]
        if ro:
            raise SystemExit("refusing to APPLY: not modifiable -> " + ", ".join(ro))
    print("")

    results = []
    for d in chosen:
        title = d["title"]
        print("=== %s ===" % title)
        t0 = time.time()
        res = run_model(title, task_src, apply, swallow)
        res.setdefault("elapsed_s", round(time.time() - t0, 2))
        results.append(res)
        if not a.quiet:
            body = "\n".join(l for l in (res.get("raw") or "").splitlines() if not l.startswith("@@RESULT:"))
            if body.strip():
                print(body.rstrip())
        if res.get("ok"):
            print("-> ok  %s  %.1fs  %s" % ("COMMITTED" if res.get("committed") else "rolled back (dry run)",
                                            res.get("elapsed_s", 0), summarize_data(res.get("data"))))
        else:
            print("-> FAILED: %s" % res.get("error"))
            if res.get("traceback"):
                print(res["traceback"].rstrip())
            if stop_on_fail:
                print("stopping at first failure (--stop-on-fail)")
                break
        print("")

    print("%-40s %-10s %-9s %-7s %s" % ("Model", "Result", "Committed", "Secs", "Data"))
    print("-" * 100)
    for r in results:
        print("%-40s %-10s %-9s %-7s %s" % (
            r.get("title", "?")[:40], "ok" if r.get("ok") else "FAILED",
            "yes" if r.get("committed") else "no", r.get("elapsed_s", "-"),
            summarize_data(r.get("data")) if r.get("ok") else (r.get("error") or "")[:60]))
    ok_n = sum(1 for r in results if r.get("ok"))
    print("\n%d/%d models ok, %d failed" % (ok_n, len(results), len(results) - ok_n))
    if apply:
        dirty = [r["title"] for r in results if r.get("committed")]
        if dirty:
            print("Now holding UNSYNCED/UNSAVED changes (sync or save each one): " + ", ".join(dirty))
    else:
        print("Dry run: nothing was kept. Re-run with --apply (or APPLY = True) to commit.")
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

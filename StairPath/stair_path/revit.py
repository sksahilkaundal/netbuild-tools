"""Talk to Revit through the pyRevit MCP listener's HTTP route (same as Level Shift, Element Remover and the Plot
Runner).

The POST is the one the ``execute_revit_code`` MCP tool makes, sent directly with a long timeout, so the ~60 s
MCP-bridge cut-off does not apply. Every call prints nonce-tagged JSON lines; a reply without this call's nonce
is a stale echo and is ignored.

What is sent is the pyRevit button's own engine (payload.py: rules.py + engine.py as text) plus DRIVER, which
picks the model, runs engine.Run and prints its checks, lines and annotation rows.
Everything sent to Revit is IronPython 2.7: no f-strings, print(<one expr>).
"""

import json
import socket
import urllib.error
import urllib.request
import uuid

from .payload import ENGINE, RULES

MARK = "@@SP-%s:%s@@"


def new_nonce():
    return uuid.uuid4().hex[:12]


def py_literal(value):
    """A literal both IronPython 2.7 and CPython 3 read back to the same value."""
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        text = repr(value)
        return ("u" + text) if any(ord(ch) > 127 for ch in value) else text
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(py_literal(v) for v in value)
    if isinstance(value, dict):
        return "{%s}" % ", ".join("%s: %s" % (py_literal(k), py_literal(v)) for k, v in value.items())
    raise TypeError("unsupported value type: %r" % (value,))


class Reply(object):
    def __init__(self, output="", error="", unreachable=False, paused=False, timed_out=False):
        self.output, self.error = output or "", error or ""
        self.unreachable, self.paused, self.timed_out = unreachable, paused, timed_out

    def marker(self, tag, nonce):
        """The JSON printed after ``@@SP-<tag>:<nonce>@@`` (last one wins), or None."""
        prefix = MARK % (tag, nonce) + " "
        for line in reversed(self.output.splitlines()):
            if line.startswith(prefix):
                try:
                    return json.loads(line[len(prefix):])
                except ValueError:
                    return None
        return None

    def has(self, tag, nonce):
        prefix = MARK % (tag, nonce)
        return any(line.startswith(prefix) for line in self.output.splitlines())


def post(url, code, timeout, description="Stair Path by Netbuild"):
    payload = {"code": code, "description": description, "use_transaction": False}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    status = 200
    try:
        body = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
    except Exception as exc:
        if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in str(exc).lower():
            return Reply(error="no answer from Revit within %ss -- Revit may still be working; check the "
                               "model before running again" % timeout, timed_out=True)
        return Reply(error="Revit not reachable at %s (%s) -- is Revit open with the pyRevit MCP "
                           "listener running?" % (url, exc), unreachable=True)
    try:
        d = json.loads(body)
    except ValueError:
        return Reply(body, "" if status == 200 else "HTTP %s: %s" % (status, body[-800:]))
    if not isinstance(d, dict):
        return Reply(body)
    if d.get("status") == "paused":
        return Reply(error=d.get("error") or "Revit MCP is paused (MCP Status button)", paused=True)
    out = d.get("output") or d.get("partial_output") or ""
    if d.get("status") == "success" and status == 200:
        return Reply(out)
    err = d.get("error") or ("HTTP %s" % status)
    tb = d.get("traceback") or ""
    return Reply(out, err + ("\n" + tb[-1500:] if tb else ""))


LIST_DOCS = r'''import json as _sp_json
_out = []
for d in doc.Application.Documents:
    try:
        _out.append({"title": d.Title, "path": d.PathName, "linked": bool(d.IsLinked),
                     "family": bool(d.IsFamilyDocument), "readonly": bool(d.IsReadOnly),
                     "active": d.Title == doc.Title and d.PathName == doc.PathName})
    except Exception as e:
        _out.append({"title": "?", "error": str(e)})
print("@@SP-DOCS:%(nonce)s@@ " + _sp_json.dumps(_out))
'''

# Runs after ENGINE in the listener's namespace (doc / uidoc = the active model and its UIDocument).
DRIVER = r'''
import json as _sp_json


def _sp_emit(tag, data):
    print("@@SP-%s:%s@@ %s" % (tag, _SP["nonce"], _sp_json.dumps(data)))


def _sp_pick():
    want = [m.lower() for m in (_SP.get("match") or []) if m]
    if not want:
        return doc
    docs = [x for x in doc.Application.Documents if not x.IsLinked and not x.IsFamilyDocument]
    hits = [x for x in docs if [w for w in want if w in x.Title.lower()]]
    if len(hits) != 1:
        raise Exception("SP: %d open model(s) match %s -- open models: %s"
                        % (len(hits), _SP.get("match"), [x.Title for x in docs]))
    return hits[0]


def _sp_main():
    d = _sp_pick()
    active = d.Title == doc.Title and d.PathName == doc.PathName
    _sp_emit("DOC", {"title": d.Title, "path": d.PathName, "active": active, "readonly": bool(d.IsReadOnly),
                     "family": bool(d.IsFamilyDocument)})
    r = Run(d, uidoc if active else None, _SP["settings"])
    if d.IsFamilyDocument:
        r.checks.append(Check("Model", False, "%s is a family -- open a project model" % d.Title))
    elif d.IsReadOnly and _SP["action"] != "plan":
        r.checks.append(Check("Model is read-only", False, "open it editable to place stair paths"))
    if not active and r.s["views"] == "open":
        r.checks.append(Check("Open views", False, "%s is not the active window in Revit -- make it active, or "
                              "pick the views by name" % d.Title))
    try:
        r.run(_SP["action"])
    except Exception as e:
        r.checks.append(Check("Stopped", False, "%s: %s -- nothing was changed" % (type(e).__name__, e)))
    _sp_emit("RESULT", {"ok": r.ok(), "checks": [[c.ok, c.label, c.detail] for c in r.checks],
                        "lines": list(r.lines), "rows": r.rows[:_SP["max_rows"]], "rows_total": len(r.rows),
                        "settings": dict((k, r.s[k]) for k in rules.DEFAULTS)})


_sp_emit("BEGIN", {})
_sp_main()
_sp_emit("END", {})
'''


def list_docs_code(nonce):
    return LIST_DOCS % {"nonce": nonce}


def action_code(nonce, action, match, values, max_rows=20000):
    """The engine + driver for one call: ``action`` plan | trial | apply on the model whose title contains one of
    ``match`` (blank = the active model), with the Stair Path settings ``values`` (rules.DEFAULTS keys)."""
    if action not in ("plan", "trial", "apply"):
        raise ValueError("action must be plan, trial or apply")
    head = "# ---- Stair Path by Netbuild (one call)\n_SP = %s\n" % py_literal({
        "nonce": nonce, "action": action, "match": list(match or []), "settings": dict(values or {}),
        "max_rows": int(max_rows)})
    boot = ("import types as _sp_types\nrules = _sp_types.ModuleType('stair_path_rules')\n"
            "exec(%s, rules.__dict__)\nCheck = rules.Check\n" % py_literal(RULES))
    return head + boot + ENGINE + DRIVER

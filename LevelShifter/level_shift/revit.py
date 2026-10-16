"""Talk to Revit through the pyRevit MCP listener's HTTP route (same as the ProjectA Plot Runner).

The POST is the one the ``execute_revit_code`` MCP tool makes, sent directly with a long
timeout, so the ~60 s MCP-bridge cut-off does not apply. Every payload prints nonce-tagged
JSON lines; a reply without this call's nonce is a stale echo and is ignored.

Everything sent to Revit is IronPython 2.7: no f-strings, print(<one expr>).
"""

import json
import socket
import urllib.error
import urllib.request
import uuid

from .payload import CODE

MARK = "@@LS-%s:%s@@"


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
        """The JSON printed after ``@@LS-<tag>:<nonce>@@`` (last one wins), or None."""
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

    def text_lines(self):
        return [l for l in self.output.splitlines() if not l.startswith("@@LS-")]


def post(url, code, timeout, description="Netbuild Level Shift"):
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


LIST_DOCS = r'''import json as _ls_json
_out = []
for d in doc.Application.Documents:
    try:
        _out.append({"title": d.Title, "path": d.PathName, "linked": bool(d.IsLinked),
                     "family": bool(d.IsFamilyDocument), "readonly": bool(d.IsReadOnly),
                     "active": d.Title == doc.Title and d.PathName == doc.PathName})
    except Exception as e:
        _out.append({"title": "?", "error": str(e)})
print("@@LS-DOCS:%(nonce)s@@ " + _ls_json.dumps(_out))
'''


def list_docs_code(nonce):
    return LIST_DOCS % {"nonce": nonce}


def action_code(nonce, action, match, moves=(), tol_ft=0.0, rounds=4, move_fallback=True,
                rollback_on_drift=True, max_rows=20000):
    """The payload with its per-call config. ``moves``: [{"id", "name", "delta" (feet)}]."""
    cfg = {"nonce": nonce, "action": action, "match": list(match or []),
           "moves": [{"id": int(m["id"]), "name": m["name"], "delta": float(m["delta"])} for m in moves],
           "tol": float(tol_ft), "rounds": int(rounds), "move_fallback": bool(move_fallback),
           "rollback_on_drift": bool(rollback_on_drift), "max_rows": int(max_rows)}
    return "# ---- Netbuild Level Shift (one call)\n_LS = %s\n%s" % (py_literal(cfg), CODE)

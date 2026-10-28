"""Talk to Revit through the pyRevit MCP listener's HTTP route.

This is the same POST the ``execute_revit_code`` MCP tool makes, sent
directly with a long timeout, so the ~60 s MCP-bridge cut-off (and its
misleading "timed out" / stale-echo results) does not apply. Every payload
prints nonce-tagged JSON lines; a response without this call's nonce is a
stale echo and is ignored.

Everything sent to Revit is IronPython 2.7: no f-strings, no keyword-only
arguments, print as a statement-compatible ``print(<one expr>)``.
"""

import json
import socket
import urllib.error
import urllib.request
import uuid

from .patch import py_literal

MARK = "@@ProjectA-%s:%s@@"


def new_nonce():
    return uuid.uuid4().hex[:12]


class Reply(object):
    def __init__(self, output="", error="", unreachable=False, paused=False, timed_out=False):
        self.output, self.error = output or "", error or ""
        self.unreachable, self.paused, self.timed_out = unreachable, paused, timed_out

    def marker(self, tag, nonce):
        """The JSON printed after ``@@ProjectA-<tag>:<nonce>@@`` (last one wins), or None."""
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
        """Output lines without the runner's marker lines."""
        return [l for l in self.output.splitlines() if not l.startswith("@@ProjectA-")]


def post(url, code, timeout, description="ProjectA Plot GA export"):
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
            # Revit keeps working after the client gives up -- the disk decides.
            return Reply(error="no answer from Revit within %ss (it may still be exporting)" % timeout,
                         timed_out=True)
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


# ------------------------------------------------------------ payloads

PREAMBLE = r'''# ---- ProjectA Plot Runner preamble (added for this call only; the script file is unchanged)
import json as _projecta_json
_ProjectA_NONCE = %(nonce)s
_ProjectA_MATCH = %(match)s
_ProjectA_ONLY_SUBFOLDER = %(subfolder)s
_ProjectA_ONLY_SHEETS = %(sheets)s


def _projecta_emit(tag, data):
    print("@@ProjectA-%%s:%%s@@ %%s" %% (tag, _ProjectA_NONCE, _projecta_json.dumps(data)))


def _projecta_pick_doc(match):
    try:
        active = doc
    except NameError:
        active = __revit__.ActiveUIDocument.Document
    docs = []
    for d in active.Application.Documents:
        if d.IsLinked or d.IsFamilyDocument:
            continue
        docs.append(d)
    want = [m.lower() for m in match]
    hits = [d for d in docs if [w for w in want if w in d.Title.lower()]]
    if len(hits) != 1:
        raise Exception("ProjectA: %%d open model(s) match %%s -- open models: %%s"
                        %% (len(hits), match, [d.Title for d in docs]))
    d = hits[0]
    _projecta_emit("DOC", {"title": d.Title, "path": d.PathName,
                      "active": d.Title == active.Title and d.PathName == active.PathName,
                      "readonly": bool(d.IsReadOnly)})
    return d


def _projecta_filter(cands):
    out = []
    for c in cands:
        if _ProjectA_ONLY_SUBFOLDER is not None and c[1] != _ProjectA_ONLY_SUBFOLDER:
            continue
        if _ProjectA_ONLY_SHEETS is not None and c[0].SheetNumber not in _ProjectA_ONLY_SHEETS:
            continue
        out.append(c)
    _projecta_emit("CANDIDATES", [{"sheet": c[0].SheetNumber, "name": c[0].Name, "subfolder": c[1],
                              "fname": c[2]} for c in out])
    return out

_projecta_emit("BEGIN", {})
# ---- end of preamble
'''

FILTER_LINE = "candidates = _projecta_filter(candidates)   # ProjectA Plot Runner: narrow + report this call's sheets"
END_LINE = "_projecta_emit(\"END\", {})   # ProjectA Plot Runner: the script ran to the end"


def preamble(nonce, match, subfolder=None, sheets=None):
    return PREAMBLE % {"nonce": py_literal(nonce), "match": py_literal(list(match)),
                       "subfolder": py_literal(subfolder),
                       "sheets": py_literal(list(sheets) if sheets is not None else None)}


LIST_DOCS = r'''import json as _projecta_json
_out = []
for d in doc.Application.Documents:
    try:
        _out.append({"title": d.Title, "path": d.PathName, "linked": bool(d.IsLinked),
                     "family": bool(d.IsFamilyDocument), "readonly": bool(d.IsReadOnly),
                     "active": d.Title == doc.Title and d.PathName == doc.PathName})
    except Exception as e:
        _out.append({"title": "?", "error": str(e)})
print("@@ProjectA-DOCS:%(nonce)s@@ " + _projecta_json.dumps(_out))
'''

PROBE = r'''
from Autodesk.Revit.DB import FilteredElementCollector, ViewSheet
_d = _projecta_pick_doc(_ProjectA_MATCH)
_PARAMS = %(params)s
_GROUP_PARAM = %(group_param)s
_dates = {}
_groups = {}
_missing = {}
_n = 0
_example = None
for _s in FilteredElementCollector(_d).OfClass(ViewSheet).ToElements():
    if _s.IsPlaceholder:
        continue
    _n += 1
    _p = _s.LookupParameter("Current Revision Date")
    _v = (_p.AsString() if _p else None) or ""
    _dates[_v] = _dates.get(_v, 0) + 1
    if _GROUP_PARAM:
        _g = _s.LookupParameter(_GROUP_PARAM)
        _gv = (_g.AsString() if _g else None) or ""
        _groups[_gv] = _groups.get(_gv, 0) + 1
    for _name in _PARAMS:
        if _s.LookupParameter(_name) is None:
            _missing[_name] = _missing.get(_name, 0) + 1
    if _example is None and _v:
        _example = {"sheet": _s.SheetNumber, "name": _s.Name, "date": _v}
_projecta_emit("PROBE", {"sheets": _n, "dates": _dates, "groups": _groups, "missing": _missing,
                    "example": _example})
'''


def list_docs_code(nonce):
    return LIST_DOCS % {"nonce": nonce}


def probe_code(nonce, match, params, group_param=None):
    return preamble(nonce, match) + PROBE % {"params": py_literal(list(params)),
                                             "group_param": py_literal(group_param)}

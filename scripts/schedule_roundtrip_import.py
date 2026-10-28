# -*- coding: utf-8 -*-
r"""
Schedule round-trip, step 3b of 3: write the edited parameter values back into Revit.

Run inside Revit through execute_revit_code (IronPython; needs `doc`, `DB`), after step 3a
(py -3.14 scripts\schedule_roundtrip_import_diff.py <edited.xlsx>) wrote the changes JSON:

    CHANGES_JSON = r"C:\SK\Projects\ProjectA\Exports\2026-10-02\_import_changes_<model>.json"
    DRY_RUN = True          # True = report only, no transaction. False ONLY when the user says "apply".
    exec(compile(open(r"C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_import.py").read(),
                 "schedule_roundtrip_import.py", "exec"))

Per change it checks, before anything is written:
  - the active document is one of the workbook's models. A workbook exported WITH linked models
    carries a model per row: only the active model's rows are written; the rest are listed
    ("open that model and import again") - a linked model can't be edited from its host;
  - the element still exists and has the parameter, writable; text, whole numbers, Yes/No and
    unitless numbers are written (numbers with units - lengths, areas - are skipped and listed);
  - the model value still equals the exported (_Original) value - if someone changed it
    since the export it is a CONFLICT and is skipped, never overwritten;
    already equal to the new value = skipped as "already set";
  - workshared: not owned by another user and up to date with central (else Revit cannot
    borrow it) - those are skipped and listed.
Apply mode writes everything that passed in ONE transaction, warnings swallowed and listed,
then re-reads every written value in the same call (never trust a printed "commit" alone).
It does not save or sync - the user does that.
"""
import json
import System
from collections import Counter

try:
    CHANGES_JSON
except NameError:
    raise Exception("Set CHANGES_JSON to the step-3a output first")
try:
    DRY_RUN
except NameError:
    DRY_RUN = True

with open(CHANGES_JSON) as _fh:          # close at once: IronPython would keep the file locked
    data = json.load(_fh)
model_of = lambda c: c.get("model") or data["model"]
models = set(data.get("models") or []) | set(model_of(c) for c in data["changes"]) | set([data["model"]])
if doc.Title not in models:
    raise Exception("Active document is %s but the workbook holds rows for: %s - open one of those models first"
                    % (doc.Title, ", ".join(sorted(models))))
# rows of a linked model are written when THAT model is the active document, never from the host
other_models = Counter(model_of(c) for c in data["changes"] if model_of(c) != doc.Title)
mine = [c for c in data["changes"] if model_of(c) == doc.Title]

me = doc.Application.Username
ws_on = doc.IsWorkshared


def find_param(e, pid, name):
    # a parameter id only means something in the model it came from - linked rows go by name
    if model_of_param_ok:
        for p in e.Parameters:
            if int(p.Id.Value) == int(pid):
                return p
    return e.LookupParameter(name)


model_of_param_ok = doc.Title == data["model"]


def _num(t):
    try:
        return float(str(t).replace(",", "").strip())
    except ValueError:
        return None


def _yesno(p):
    try:
        return p.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo
    except Exception:
        return False


def _plain_double(p):
    """Double with no unit conversion (Number spec); lengths / areas are not supported here."""
    try:
        return abs(DB.UnitUtils.ConvertToInternalUnits(1.0, p.GetUnitTypeId()) - 1.0) < 1e-9
    except Exception:
        return True


def to_value(p, text):
    """Excel text -> value for p.Set(); raises ValueError with the reason when it can't."""
    st = p.StorageType
    if st == DB.StorageType.String:
        return text
    if text == "":
        raise ValueError("blank cell for a number parameter")
    if st == DB.StorageType.Integer and _yesno(p):
        t = text.strip().lower()
        if t in ("yes", "1", "true"):
            return 1
        if t in ("no", "0", "false"):
            return 0
        raise ValueError("Yes/No parameter needs Yes or No")
    n = _num(text)
    if n is None:
        raise ValueError("not a number")
    if st == DB.StorageType.Integer:
        if n != int(n):
            raise ValueError("whole number expected")
        return int(n)
    if st == DB.StorageType.Double:
        if not _plain_double(p):
            raise ValueError("number with units (length/area) - not supported, edit in Revit")
        return n
    raise ValueError("unsupported parameter type %s" % st)


def current(p):
    st = p.StorageType
    if st == DB.StorageType.String:
        return (p.AsString() or "").strip()
    if st == DB.StorageType.Integer:
        return p.AsInteger()
    if st == DB.StorageType.Double:
        return p.AsDouble()
    return None


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    return a == b


todo, already, problems = [], Counter(), {}


def problem(kind, c, extra=""):
    problems.setdefault(kind, []).append((c["id"], c["param"], extra))


owner_cache = {}
for c in mine:
    eid = DB.ElementId(System.Int64(c["id"]))
    e = doc.GetElement(eid)
    if e is None:
        problem("element not found", c)
        continue
    p = find_param(e, c["pid"], c["param"])
    if p is None:
        problem("parameter missing", c)
        continue
    if p.IsReadOnly:
        problem("parameter read-only", c)
        continue
    try:
        new_v = to_value(p, c["new"])
        old_v = to_value(p, c["old"]) if (c["old"] != "" or p.StorageType == DB.StorageType.String) else None
    except ValueError as ex:
        problem("value not accepted", c, "%s: %r" % (ex, c["new"]))
        continue
    cur = current(p)
    if same(cur, new_v):
        already[c["param"]] += 1
        continue
    if not (same(cur, old_v) or (old_v is None and not p.HasValue)):
        problem("CONFLICT - changed in Revit since export", c, "export %r, now %r, Excel %r" % (c["old"], cur, c["new"]))
        continue
    c["_value"] = new_v
    if ws_on:
        if c["id"] not in owner_cache:
            st = DB.WorksharingUtils.GetCheckoutStatus(doc, eid)
            upd = DB.WorksharingUtils.GetModelUpdatesStatus(doc, eid)
            owner = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, eid).Owner
            owner_cache[c["id"]] = (st, upd, owner)
        st, upd, owner = owner_cache[c["id"]]
        if st == DB.CheckoutStatus.OwnedByOtherUser:
            problem("owned by another user", c, owner)
            continue
        if upd in (DB.ModelUpdatesStatus.UpdatedInCentral, DB.ModelUpdatesStatus.DeletedInCentral):
            problem("not up to date with central (Reload Latest)", c, str(upd))
            continue
    todo.append((e, p, c))

print("Model    : %s | user %s | workshared %s" % (doc.Title, me, ws_on))
print("Workbook : %s" % data["workbook"].split("\\")[-1])
print("Mode     : %s" % ("DRY RUN - nothing written" if DRY_RUN else "APPLY"))
print("Changes in Excel: %d | to write: %d | already set: %d | skipped: %d"
      % (len(mine), len(todo), sum(already.values()), sum(len(v) for v in problems.values())))
for mdl, k in sorted(other_models.items()):
    print("  NOT HERE: %d change(s) belong to %s - open that model and run the import again" % (k, mdl))
for prm in data["params"]:
    cc = Counter((c["old"], c["new"]) for _, _, c in todo if c["param"] == prm)
    print("  %s: %d to write" % (prm, sum(cc.values())))
    for (o, n), cnt in cc.most_common(12):
        print("    %5d  %r -> %r" % (cnt, o, n))
for kind, rows in sorted(problems.items()):
    print("SKIPPED - %s: %d" % (kind, len(rows)))
    for r in rows[:10]:
        print("    id %s  %s  %s" % r)
    if len(rows) > 10:
        print("    ... %d more" % (len(rows) - 10))

if not DRY_RUN and todo:
    warns, errs = [], []

    class _Swallow(DB.IFailuresPreprocessor):
        def PreprocessFailures(self, fa):
            for f in fa.GetFailureMessages():
                if f.GetSeverity() == DB.FailureSeverity.Warning:
                    warns.append(f.GetDescriptionText())
                    fa.DeleteWarning(f)
                else:
                    errs.append("%s: %s (%d elements)" % (f.GetSeverity(), f.GetDescriptionText(),
                                                          f.GetFailingElementIds().Count))
            return DB.FailureProcessingResult.Continue

    t = DB.Transaction(doc, "Import from Excel: " + ", ".join(list(data["params"])))
    t.Start()
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(_Swallow())
    t.SetFailureHandlingOptions(opts)
    failed = []
    for e, p, c in todo:
        try:
            if not p.Set(c["_value"]):
                failed.append((c["id"], c["param"], "Set returned False"))
        except Exception as ex:
            failed.append((c["id"], c["param"], str(ex)))
    status = t.Commit()
    print("COMMIT STATUS: %s | set failures: %d | warnings swallowed: %d" % (status, len(failed), len(warns)))
    for f in failed[:10]:
        print("    failed id %s  %s  %s" % f)
    for w in sorted(set(warns))[:5]:
        print("    warning: %s" % w)
    for x in sorted(set(errs))[:5]:
        print("    ERROR: %s" % x)
    if status != DB.TransactionStatus.Committed and not errs:
        # 2026-10-02, 970002: the first apply of 3,584 Areas (none borrowed yet) rolled back with no
        # failure message at all; the identical transaction committed on the next call. Retry once.
        print("    Rolled back with no failure recorded - likely the element borrow from central; run again.")
    ok = bad = 0                                            # verify from the model, same call
    for e, p, c in todo:
        e2 = doc.GetElement(DB.ElementId(System.Int64(c["id"])))
        p2 = find_param(e2, c["pid"], c["param"]) if e2 is not None else None
        if p2 is not None and same(current(p2), c["_value"]):
            ok += 1
        else:
            bad += 1
    print("VERIFIED IN MODEL: %d of %d now hold the Excel value | %d do not" % (ok, len(todo), bad))
    print("Not saved / synced - Synchronize with Central when ready.")

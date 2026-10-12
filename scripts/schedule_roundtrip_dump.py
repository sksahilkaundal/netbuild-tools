# -*- coding: utf-8 -*-
r"""
Schedule round-trip, step 1 of 3: dump a Revit schedule's HOST-MODEL elements to JSON.

Run inside Revit through execute_revit_code (IronPython; needs `doc`, `DB`):

    SCHEDULE_NAME = "Excel - Area - Overall With Assets-Cross Check"
    OUT_JSON = r"C:\SK\Projects\ProjectA\Exports\2026-09-30\_schedule_dump.json"
    exec(compile(open(r"C:\SK\OneDrive\Netbuild\scripts\schedule_roundtrip_dump.py").read(),
                 "schedule_roundtrip_dump.py", "exec"))

Step 2 builds the workbook: py -3.14 scripts\schedule_roundtrip_build_xlsx.py <dump.json> <out.xlsx>
Step 3 (import back, with the parameter logic) is written separately.

Read-only - opens no transaction, changes nothing in the model.

Scope: ONLY elements of the current (host) model. The element list comes from
FilteredElementCollector(doc, schedule.Id) filtered to the schedule's category, which
never returns linked-model elements; rendered schedule rows that match no host element
(i.e. rows coming from loaded links when "Include elements in links" is on) are counted
and excluded.

Per element it records every schedule field that is a real parameter (instance / type /
the parts of combined parameters), with storage type, spec, read-only flag and shared GUID.
Values that only exist in the schedule (Formula, Count, ...) are taken from the rendered
rows: each row is matched to its element by the visible parameter columns, ties broken by
numeric values (e.g. an area shown in a formula column), so identical rows only swap
between elements whose values are identical anyway.
Also dumps the key schedules behind any key parameter (valid key names + what each key
drives) and the user worksets, for dropdowns in the workbook.
"""
import os
import json
import datetime
import re
import System

try:
    SCHEDULE_NAME
except NameError:
    SCHEDULE_NAME = "Excel - Area - Overall With Assets-Cross Check"
try:
    OUT_JSON
except NameError:
    OUT_JSON = os.path.join(r"C:\SK\Projects\ProjectA\Exports", datetime.date.today().strftime("%Y-%m-%d"),
                            "_schedule_dump.json")
try:
    INCLUDE_LINKS            # True = also the schedule's rows from loaded links (each tagged with its model)
except NameError:
    INCLUDE_LINKS = False


def u(x):
    """Escape non-ASCII as \\uXXXX so IronPython's json never trips on code-page bytes."""
    if x is None:
        return None
    try:
        x = unicode(x)
    except UnicodeDecodeError:
        x = x.decode("latin-1")
    return "".join([ch if ord(ch) < 128 else "\\u%04x" % ord(ch) for ch in x])


def num(txt):
    """'1,204.59 m2' -> 1204.59 ; non-numeric -> None."""
    if txt is None:
        return None
    m = re.match(r"^\s*(-?[\d,]*\.?\d+)", txt)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def norm(txt):
    n = num(txt)
    if n is not None and re.match(r"^\s*-?[\d,]*\.?\d+\s*(m\S*|mm|sqm|%)?\s*$", txt or ""):
        return "#%.2f" % n
    return (txt or "").strip().lower()


def spec_of(p):
    try:
        return p.Definition.GetDataType().TypeId
    except Exception:
        return ""


def param_rec(p):
    st = p.StorageType
    r = {"n": u(p.Definition.Name), "st": str(st), "ro": bool(p.IsReadOnly), "has": bool(p.HasValue),
         "spec": spec_of(p), "disp": u(p.AsValueString()), "raw": None}
    if st == DB.StorageType.String:
        r["raw"] = u(p.AsString())
    elif st == DB.StorageType.Integer:
        r["raw"] = p.AsInteger()
    elif st == DB.StorageType.Double:
        r["raw"] = p.AsDouble()
        sp = r["spec"]
        if "area" in sp:
            r["si"] = DB.UnitUtils.ConvertFromInternalUnits(p.AsDouble(), DB.UnitTypeId.SquareMeters)
        elif "length" in sp:
            r["si"] = DB.UnitUtils.ConvertFromInternalUnits(p.AsDouble(), DB.UnitTypeId.Millimeters)
        elif "volume" in sp:
            r["si"] = DB.UnitUtils.ConvertFromInternalUnits(p.AsDouble(), DB.UnitTypeId.CubicMeters)
        else:
            r["si"] = p.AsDouble()
    elif st == DB.StorageType.ElementId:
        r["raw"] = int(p.AsElementId().Value)
    try:
        r["guid"] = str(p.GUID) if p.IsShared else None
    except Exception:
        r["guid"] = None
    return r


sched = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule).ToElements()
         if not v.IsTemplate and v.Name == SCHEDULE_NAME]
if not sched:
    raise Exception("Schedule not found: %s" % SCHEDULE_NAME)
sched = sched[0]
sdef = sched.Definition
cat_id = sdef.CategoryId

# ---- fields --------------------------------------------------------------------------
fields = []
for i in range(sdef.GetFieldCount()):
    f = sdef.GetField(i)
    ft = str(f.FieldType)
    rec = {"idx": i, "name": u(f.GetName()), "heading": u(f.ColumnHeading), "hidden": bool(f.IsHidden),
           "ftype": ft, "pid": int(f.ParameterId.Value)}
    if ft == "CombinedParameter":
        rec["combined"] = [{"pid": int(cp.ParamId.Value), "prefix": u(cp.Prefix), "suffix": u(cp.Suffix),
                            "sep": u(cp.Separator)} for cp in f.GetCombinedParameters()]
    fields.append(rec)
visible = [f for f in fields if not f["hidden"]]

# ---- host elements only --------------------------------------------------------------
host = [e for e in DB.FilteredElementCollector(doc, sched.Id).ToElements()
        if e.Category is not None and e.Category.Id == cat_id and not isinstance(e, DB.RevitLinkInstance)]


def pids_of(fr):
    if fr["ftype"] in ("Instance", "ElementType"):
        return [fr["pid"]]
    return [c["pid"] for c in fr.get("combined", [])]


elem_recs = []
for e in host:
    inst = dict((int(p.Id.Value), p) for p in e.Parameters)
    typ = doc.GetElement(e.GetTypeId()) if e.GetTypeId() != DB.ElementId.InvalidElementId else None
    tparams = dict((int(p.Id.Value), p) for p in typ.Parameters) if typ else {}
    vals = {}
    for fr in fields:
        for pid in pids_of(fr):
            key = str(pid)
            if key in vals:
                continue
            p = tparams.get(pid) if fr["ftype"] == "ElementType" else inst.get(pid)
            vals[key] = param_rec(p) if p is not None else None
    owner = ""
    if doc.IsWorkshared:
        try:
            owner = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, e.Id).Owner
        except Exception:
            pass
    rec = {"id": int(e.Id.Value), "uid": u(e.UniqueId), "owner": u(owner), "vals": vals, "model": u(doc.Title)}
    if isinstance(e, DB.SpatialElement):
        rec["area_m2"] = DB.UnitUtils.ConvertFromInternalUnits(e.Area, DB.UnitTypeId.SquareMeters)
    if hasattr(e, "AreaScheme") and e.AreaScheme is not None:
        rec["scheme"] = u(e.AreaScheme.Name)
    elem_recs.append(rec)

# ---- linked elements (optional) -------------------------------------------------------
# A link's parameters have their own ids: map each host field to built-in id / shared GUID / name.
link_recs, link_titles = [], []
if INCLUDE_LINKS:
    def _getter(pid):
        if pid < 0:
            try:
                bip = System.Enum.ToObject(DB.BuiltInParameter, pid)
            except Exception:
                return None
            return lambda e, b=bip: e.get_Parameter(b)
        pe = doc.GetElement(DB.ElementId(System.Int64(pid)))
        if isinstance(pe, DB.SharedParameterElement):
            return lambda e, g=pe.GuidValue: e.get_Parameter(g)
        try:
            name = pe.GetDefinition().Name
        except Exception:
            name = getattr(pe, "Name", None)
        return (lambda e, n=name: e.LookupParameter(n)) if name else None

    getters = {}
    for fr in fields:
        for pid in pids_of(fr):
            getters[pid] = (_getter(pid), fr["ftype"] == "ElementType")
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ldoc = li.GetLinkDocument()
        if ldoc is None:
            continue                                                  # unloaded link
        if ldoc.Title not in link_titles:
            link_titles.append(ldoc.Title)
        for e in DB.FilteredElementCollector(ldoc).OfCategoryId(cat_id).WhereElementIsNotElementType():
            typ = ldoc.GetElement(e.GetTypeId()) if e.GetTypeId() != DB.ElementId.InvalidElementId else None
            vals = {}
            for pid, (get, is_type) in getters.items():
                src = typ if is_type else e
                p = get(src) if (get and src is not None) else None
                vals[str(pid)] = param_rec(p) if p is not None else None
            rec = {"id": int(e.Id.Value), "uid": u(e.UniqueId), "owner": "", "vals": vals,
                   "model": u(ldoc.Title), "link": u(li.Name)}
            if isinstance(e, DB.SpatialElement):
                rec["area_m2"] = DB.UnitUtils.ConvertFromInternalUnits(e.Area, DB.UnitTypeId.SquareMeters)
            if hasattr(e, "AreaScheme") and e.AreaScheme is not None:
                rec["scheme"] = u(e.AreaScheme.Name)
            link_recs.append(rec)


def cell_text_for(rec, fr):
    """What the schedule would show for this element in a visible parameter column."""
    if fr["ftype"] in ("Instance", "ElementType"):
        v = rec["vals"].get(str(fr["pid"]))
        if not v:
            return ""
        return (v["raw"] if v["st"] == "String" else v["disp"]) or ""
    if fr["ftype"] == "CombinedParameter":
        parts = []
        for c in fr["combined"]:
            v = rec["vals"].get(str(c["pid"]))
            t = ((v["raw"] if v["st"] == "String" else v["disp"]) or "") if v else ""
            parts.append((c["prefix"] or "") + t + (c["suffix"] or ""))
        out = ""
        for k, c in enumerate(fr["combined"]):
            out += parts[k]
            if k < len(parts) - 1:
                out += (c["sep"] or "")
        return out if any(parts) else ""
    return None


# ---- rendered rows -> elements -------------------------------------------------------
body = sched.GetTableData().GetSectionData(DB.SectionType.Body)
nrows, ncols = body.NumberOfRows, body.NumberOfColumns
rows = [[u(sched.GetCellText(DB.SectionType.Body, r, c)) for c in range(ncols)] for r in range(nrows)]
col_of = dict((f["idx"], k) for k, f in enumerate(visible))           # field idx -> body column
key_fields = [f for f in visible if f["ftype"] in ("Instance", "ElementType", "CombinedParameter")]
calc_fields = [f for f in visible if f["ftype"] not in ("Instance", "ElementType", "CombinedParameter")]

def make_pool(recs):
    pool = {}
    for rec in recs:
        k = tuple(norm(cell_text_for(rec, f)) for f in key_fields)
        rec["_numbers"] = set(["%.2f" % v["si"] for v in rec["vals"].values() if v and v.get("si") is not None] +
                              (["%.2f" % rec["area_m2"]] if "area_m2" in rec else []))
        pool.setdefault(k, []).append(rec)
    return pool


def take(pool, r, row):
    """Match one rendered row to an element of the pool; True when matched."""
    cands = pool.get(tuple(norm(row[col_of[f["idx"]]]) for f in key_fields))
    if not cands:
        return False
    rownums = set("%.2f" % num(row[col_of[f["idx"]]]) for f in calc_fields
                  if num(row[col_of[f["idx"]]]) not in (None, 0.0))
    best = max(cands, key=lambda c: len(rownums & c["_numbers"]))
    cands.remove(best)
    best["row"] = r
    best["calc"] = dict((str(f["idx"]), row[col_of[f["idx"]]]) for f in calc_fields)
    return True


host_pool = make_pool(elem_recs)
matched, foreign, summary_rows = 0, [], []
for r, row in enumerate(rows):
    if r == 0 and all(row[col_of[f["idx"]]] == f["heading"] for f in key_fields):
        continue                                                      # heading row
    if not any(x.strip() for x in row):
        continue                                                      # blank spacer row
    if take(host_pool, r, row):
        matched += 1
    elif not any(row[col_of[f["idx"]]].strip() for f in key_fields):
        summary_rows.append({"row": r, "cells": row})                 # grand total / footer
    else:
        foreign.append({"row": r, "cells": row})                      # link row or group header

linked_matched = 0
if INCLUDE_LINKS and link_recs:
    link_pool = make_pool(link_recs)
    rest = []
    for fr_ in foreign:
        if take(link_pool, fr_["row"], fr_["cells"]):
            linked_matched += 1
        else:
            rest.append(fr_)
    foreign = rest
    elem_recs += [rec for rec in link_recs if "row" in rec]          # only what the schedule shows
for rec in elem_recs + link_recs:
    rec.pop("_numbers", None)

# ---- lookup lists --------------------------------------------------------------------
keys = {}
for ks in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule).ToElements():
    if ks.IsTemplate or not ks.Definition.IsKeySchedule or ks.Definition.CategoryId != cat_id:
        continue
    kdef = ks.Definition
    kfields = [kdef.GetField(i) for i in range(kdef.GetFieldCount())]
    kpids = [int(f.ParameterId.Value) for f in kfields]
    items = []
    for ke in DB.FilteredElementCollector(doc, ks.Id).ToElements():
        pv = dict((int(p.Id.Value), p) for p in ke.Parameters)
        items.append({"id": int(ke.Id.Value), "name": u(ke.Name),
                      "vals": [u((pv[pid].AsString() if pv[pid].StorageType == DB.StorageType.String
                                  else pv[pid].AsValueString()) if pid in pv else None) for pid in kpids]})
    keys[u(ks.KeyScheduleParameterName)] = {"schedule": u(ks.Name), "fields": [u(f.GetName()) for f in kfields],
                                            "items": sorted(items, key=lambda x: x["name"].lower())}

worksets = []
if doc.IsWorkshared:
    worksets = sorted([{"id": int(w.Id.IntegerValue) if hasattr(w.Id, "IntegerValue") else int(w.Id), "name": u(w.Name)}
                       for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset).ToWorksets()],
                      key=lambda w: w["name"].lower())

payload = {
    "schedule": u(sched.Name), "schedule_id": int(sched.Id.Value), "category_id": int(cat_id.Value),
    "doc": u(doc.Title), "doc_path": u(doc.PathName), "exported": datetime.datetime.now().isoformat(),
    "include_links_setting": bool(sdef.IncludeLinkedFiles),
    "scope": "host + linked models" if INCLUDE_LINKS else "host model only",
    "include_links": bool(INCLUDE_LINKS), "link_models": [u(t) for t in link_titles],
    "fields": fields, "elements": elem_recs, "rows": rows,
    "foreign_rows": foreign, "summary_rows": summary_rows,
    "key_schedules": keys, "worksets": worksets,
}
out_dir = os.path.dirname(OUT_JSON)
if out_dir and not os.path.isdir(out_dir):
    os.makedirs(out_dir)
with open(OUT_JSON, "w") as fh:
    fh.write(json.dumps(payload).replace("\\\\u", "\\u"))

print("Schedule   : %s (id %d)" % (sched.Name, sched.Id.Value))
n_host = len([e for e in elem_recs if e["model"] == u(doc.Title)])
print("Host elems : %d  | matched to schedule rows: %d  | unmatched: %d"
      % (n_host, matched, len([e for e in elem_recs if "row" not in e])))
if INCLUDE_LINKS:
    print("Linked     : %d rows matched to elements of %d loaded link(s): %s"
          % (linked_matched, len(link_titles), ", ".join(link_titles) or "-"))
print("Excluded   : %d rendered rows not exported (%s)"
      % (len(foreign), "group headers / unmatched" if INCLUDE_LINKS else "links + group headers"))
print("Owned by others: %d | borrowed by you: %d" % (
    len([e for e in elem_recs if e["owner"] and e["owner"] != u(doc.Application.Username)]),
    len([e for e in elem_recs if e["owner"] and e["owner"] == u(doc.Application.Username)])))
print("Key schedules: %s | worksets: %d" % (", ".join(keys.keys()) or "-", len(worksets)))
print("Wrote %s (%d bytes)" % (OUT_JSON, os.path.getsize(OUT_JSON)))

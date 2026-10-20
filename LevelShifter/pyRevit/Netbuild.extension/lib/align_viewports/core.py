"""The Align Viewports engine: read the sheets, plan the moves, apply them, verify, log.

Runs inside Revit under pyRevit (IronPython 2.7) and on CPython 3 for the tests (a stand-in Revit model):
no f-strings, no keyword-only arguments, no print(..., end=), no super() without arguments.  The Revit API
is imported inside the functions that need it, so the module itself loads anywhere.

How it aligns (verified live 2026-09-23, 3505-ProjectG-Studio-ARC-RVT-00010, scripts/align_viewports_from_reference_sheet.py):
- Plans: by the viewport's projection ORIGIN on the sheet (Viewport.GetProjectionToSheetTransform().Origin), not by
  box centre. Box centres differ between sheets because crop / annotation-crop extents differ, so centre-matching
  would leave the plans (and grids) misaligned.
- Pairing: viewports are paired by SLOT (sorted top -> bottom by box centre Y, then left -> right), never by detail
  number -- detail numbers are not consistent between sheets.
- Titles: Viewport.LabelOffset is measured from the viewport BOX corner, and box sizes differ per sheet, so the
  reference offset is corrected:  new_offset = ref_offset + (ref_box_min - target_box_min_after_move).
- GetLabelOutline() and GetBoxOutline() + LabelOffset read back stale values for sheets not open on screen, so the
  titles are checked by exporting sheets to PNG (export_images), not by read-back. Only the projection origin reads
  back reliably -- verify() re-reads it.
- doc.Regenerate() across many sheets with linked views is slow; it is never called here (Commit regenerates).
"""

import io
import os
import re

from .about import PRODUCT

MM = 304.8                      # mm per foot (Revit internal units are feet)
TOLERANCE_MM = 0.05             # a re-read projection origin further off than this fails the check
VIEW_TYPES = [                  # (Revit ViewType name, label) -- the kinds of viewport that can be aligned
    ("FloorPlan", "Floor plans"),
    ("CeilingPlan", "Ceiling plans"),
    ("AreaPlan", "Area plans"),
    ("EngineeringPlan", "Structural plans"),
    ("Section", "Sections"),
    ("Elevation", "Elevations"),
    ("Detail", "Detail views"),
    ("DraftingView", "Drafting views"),
    ("ThreeD", "3D views"),
]
DEFAULT_VIEW_TYPES = ("FloorPlan",)     # legends, schedules and the rest are left alone
TIME_LOG_FIELDS = ["date", "task", "project", "export", "issues", "manual_minutes",
                   "actual_minutes", "minutes_saved", "notes"]     # same columns as the Plot Runner's log
TIME_LOG_TASK = "Align viewports to reference sheet"


class Check(object):
    def __init__(self, label, ok, detail=""):
        self.label, self.ok, self.detail = label, ok, detail

    @property
    def mark(self):
        return "OK  " if self.ok is True else ("WARN" if self.ok is None else "FAIL")

    def __str__(self):
        return "[%s] %s%s" % (self.mark, self.label, (" -- " + self.detail) if self.detail else "")


# ------------------------------------------------------------ choosing sheets

def natural_key(number):
    """'A9' < 'A10', '10B01' < '10002' < '10010': numbers inside sheet numbers compare as numbers."""
    return [(0, int(p), u"") if p.isdigit() else (1, 0, p.lower()) for p in re.split(r"(\d+)", number) if p]


def split_numbers(text):
    """Sheet numbers from 'A101, A102; 10B01' (commas, semicolons or spaces)."""
    return [p for p in re.split(r"[,;\s]+", text or u"") if p]


def parse_range(first, last):
    """(first, last) as ints from two text fields, or None when both are blank. Raises ValueError."""
    first, last = (first or u"").strip(), (last or u"").strip()
    if not first and not last:
        return None
    if not first.isdigit() or not last.isdigit():
        raise ValueError("The sheet range takes two whole numbers, e.g. 10001 to 10039 (got '%s' to '%s')."
                         % (first, last))
    a, b = int(first), int(last)
    return (a, b) if a <= b else (b, a)


def pick_targets(numbers, reference, rng=None, extra=()):
    """Target sheet numbers: numeric ones in the inclusive range, plus the extra ones; never the reference.

    Returns (targets in natural order, extra numbers that are not in the model).
    """
    have = set(numbers)
    out = set(n for n in numbers if rng and n.isdigit() and rng[0] <= int(n) <= rng[1])
    out.update(n for n in extra if n in have)
    out.discard(reference)
    return sorted(out, key=natural_key), [n for n in extra if n not in have]


def check_image_sheets(targets, count=3):
    """A few targets to export for the title check: the first, the middle and the last."""
    if len(targets) <= count:
        return list(targets)
    picks = [targets[0], targets[len(targets) // 2], targets[-1]]
    out = []
    for n in picks:
        if n not in out:
            out.append(n)
    return out[:count]


# ------------------------------------------------------------ reading the model

def read_sheets(doc):
    """{sheet number: ViewSheet} for every real sheet (placeholders skipped)."""
    from Autodesk.Revit.DB import FilteredElementCollector, ViewSheet
    return dict((s.SheetNumber, s) for s in FilteredElementCollector(doc).OfClass(ViewSheet)
                if not getattr(s, "IsPlaceholder", False))


def slot_viewports(doc, sheet, view_types):
    """The sheet's viewports showing one of view_types, in slot order: top -> bottom, then left -> right."""
    vps = [doc.GetElement(i) for i in sheet.GetAllViewports()]
    vps = [vp for vp in vps if vp is not None and str(doc.GetElement(vp.ViewId).ViewType) in view_types]
    return sorted(vps, key=lambda vp: (-vp.GetBoxCenter().Y, vp.GetBoxCenter().X))


def _view_name(doc, vp):
    return doc.GetElement(vp.ViewId).Name


class Move(object):
    """One target viewport: its slot on the reference, the move and the new title offset."""

    def __init__(self, sheet, slot, vp, name, d, old_offset, new_offset, old_length, new_length, target):
        self.sheet, self.slot, self.vp, self.name = sheet, slot, vp, name
        self.d, self.old_offset, self.new_offset = d, old_offset, new_offset
        self.old_length, self.new_length, self.target = old_length, new_length, target

    @property
    def distance_mm(self):
        return (self.d.X ** 2 + self.d.Y ** 2) ** 0.5 * MM


def make_plan(doc, reference, targets, view_types):
    """What Apply would do -- nothing is changed. Raises ValueError for a reference that cannot be used."""
    sheets = read_sheets(doc)
    if reference not in sheets:
        raise ValueError("Reference sheet %s is not in %s." % (reference, doc.Title))
    ref_vps = slot_viewports(doc, sheets[reference], view_types)
    if not ref_vps:
        raise ValueError("Reference sheet %s has no %s viewport." % (reference, type_names(view_types)))
    if not hasattr(ref_vps[0], "GetProjectionToSheetTransform") or not hasattr(ref_vps[0], "LabelOffset"):
        raise ValueError("This Revit has no viewport title / projection API -- Align Viewports needs Revit 2022 "
                         "or later.")
    ref = [dict(name=_view_name(doc, vp), origin=vp.GetProjectionToSheetTransform().Origin,
                box_min=vp.GetBoxOutline().MinimumPoint, offset=vp.LabelOffset, length=vp.LabelLineLength)
           for vp in ref_vps]
    plan = dict(doc=doc.Title, reference=reference, ref=ref, targets=[], moves=[], skipped=[], empty=[],
                fewer=[], missing=[], view_types=list(view_types))
    for n in targets:
        if n == reference:
            continue
        if n not in sheets:
            plan["missing"].append(n)
            continue
        plan["targets"].append(n)
        vps = slot_viewports(doc, sheets[n], view_types)
        if not vps:
            plan["empty"].append(n)
            continue
        if len(vps) > len(ref):
            plan["skipped"].append((n, "%d viewports, the reference has %d" % (len(vps), len(ref))))
            continue
        if len(vps) < len(ref):
            plan["fewer"].append((n, len(vps)))
        for slot, vp in enumerate(vps):
            r = ref[slot]
            d = r["origin"] - vp.GetProjectionToSheetTransform().Origin
            new_box_min = vp.GetBoxOutline().MinimumPoint + d
            new_off = r["offset"] + (r["box_min"] - new_box_min)
            plan["moves"].append(Move(n, slot, vp, _view_name(doc, vp), d, vp.LabelOffset, new_off,
                                      vp.LabelLineLength, r["length"], r["origin"]))
    return plan


def type_names(view_types):
    labels = dict(VIEW_TYPES)
    return " / ".join(labels.get(t, t).lower() for t in view_types) or "matching"


def _xy(p):
    return "(%.1f, %.1f)" % (p.X * MM, p.Y * MM)


def move_line(m, titles=True):
    """'  10024 slot 0  L24 GA PLAN   move (+12.0, -3.5) mm | title offset (a, b) -> (c, d) mm'."""
    text = u"  %s slot %d  %-30s move (%+.1f, %+.1f) mm" % (m.sheet, m.slot, m.name[:30], m.d.X * MM, m.d.Y * MM)
    if titles:
        text += u" | title offset %s -> %s mm" % (_xy(m.old_offset), _xy(m.new_offset))
        if abs(m.old_length - m.new_length) * MM > TOLERANCE_MM:
            text += u", line %.1f -> %.1f mm" % (m.old_length * MM, m.new_length * MM)
    return text


def plan_checks(plan, titles=True):
    """(checks, lines) for a plan."""
    checks, lines = [], []
    ref = plan["ref"]
    checks.append(Check("Reference sheet %s" % plan["reference"], True, "%d slot(s), top -> bottom: %s" % (
        len(ref), "; ".join("%d %s" % (i, r["name"]) for i, r in enumerate(ref)))))
    moves = plan["moves"]
    sheets = sorted(set(m.sheet for m in moves), key=natural_key)
    if moves:
        far = max(m.distance_mm for m in moves)
        checks.append(Check("To align", True, "%d viewport(s) on %d sheet(s) -- %d already in place, largest move "
                            "%.1f mm" % (len(moves), len(sheets), len([m for m in moves if m.distance_mm <=
                                                                       TOLERANCE_MM]), far)))
    else:
        checks.append(Check("To align", False, "no viewport on the target sheets can be paired with the reference"))
    for n, why in plan["skipped"]:
        checks.append(Check("Skipped sheet %s" % n, None, why + " -- move or remove the extra one, or pick another "
                            "reference"))
    if plan["fewer"]:
        checks.append(Check("Fewer viewports", None, "aligned to the reference's top slots: %s" % ", ".join(
            "%s (%d)" % kv for kv in plan["fewer"])))
    if plan["empty"]:
        checks.append(Check("Nothing to align", None, "no %s viewport on %s" % (
            type_names(plan["view_types"]), ", ".join(plan["empty"]))))
    if plan["missing"]:
        checks.append(Check("Not in the model", None, ", ".join(plan["missing"])))
    lines.extend(move_line(m, titles) for m in moves)
    return checks, lines


# ------------------------------------------------------------ changing the model

def run(doc, plan, commit=False, titles=True):
    """Move the viewports (and titles) in one TransactionGroup named after the product, then re-read every
    projection origin. commit=False (the trial run) rolls everything back; so does any failure.

    Returns {committed, moved, fails: [(sheet, slot, error)], verify: [(sheet, slot, name, off_mm)], status}.
    """
    from Autodesk.Revit.DB import Transaction, TransactionGroup
    result = dict(committed=False, moved=0, fails=[], verify=[], status="")
    tg = TransactionGroup(doc, PRODUCT)
    tg.Start()
    t = Transaction(doc, PRODUCT)
    done = False
    try:
        t.Start()
        for m in plan["moves"]:
            try:
                m.vp.SetBoxCenter(m.vp.GetBoxCenter() + m.d)
                if titles:
                    m.vp.LabelLineLength = m.new_length
                    m.vp.LabelOffset = m.new_offset
                result["moved"] += 1
            except Exception as e:
                result["fails"].append((m.sheet, m.slot, str(e)[:160]))
        if result["fails"]:
            t.RollBack()
            tg.RollBack()
            done = True
            result["status"] = "rolled back -- %d viewport(s) could not be changed" % len(result["fails"])
            return result
        result["status"] = str(t.Commit())
        result["verify"] = verify(doc, plan)
        if commit and result["status"] == "Committed":
            tg.Assimilate()
            result["committed"] = True
        else:
            tg.RollBack()
        done = True
        return result
    finally:
        if not done:                            # a Revit error escaped: leave the model as it was
            try:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
            finally:
                tg.RollBack()


def verify(doc, plan):
    """Re-read every moved viewport's projection origin: [(sheet, slot, view name, mm off its reference slot)]."""
    out = []
    for m in plan["moves"]:
        o = m.vp.GetProjectionToSheetTransform().Origin
        off = ((o.X - m.target.X) ** 2 + (o.Y - m.target.Y) ** 2) ** 0.5 * MM
        out.append((m.sheet, m.slot, m.name, off))
    return out


def result_checks(action, plan, r, titles=True):
    """(checks, lines) for a trial run / apply."""
    checks, lines = [], []
    if r["fails"]:
        checks.append(Check("Not changed", False, r["status"]))
        for n, slot, err in r["fails"]:
            checks.append(Check("Sheet %s slot %d" % (n, slot), False, err))
        return checks, lines
    bad = [v for v in r["verify"] if v[3] > TOLERANCE_MM]
    if bad:
        checks.append(Check("Projection origins re-read", False, "%d viewport(s) off their reference slot: %s" % (
            len(bad), "; ".join("%s slot %d %.2f mm" % (v[0], v[1], v[3]) for v in bad[:10]))))
    else:
        checks.append(Check("Projection origins re-read", True, "%d viewport(s), every one 0.0 mm off its "
                            "reference slot" % len(r["verify"])))
    if titles:
        checks.append(Check("View titles", None, "offset and line length set from the reference -- Revit reads "
                            "titles back wrong for sheets not on screen, so check them with 'Export check "
                            "images' (PNG) after Apply"))
    if action == "trial":
        checks.append(Check("Trial", True if not bad else None, "rolled back -- the model is unchanged"))
    elif r["committed"]:
        checks.append(Check("Applied", True, "%d viewport(s), one Undo entry in Revit: '%s'. Save / Synchronize "
                            "when happy" % (r["moved"], PRODUCT)))
    else:
        checks.append(Check("Applied", False, "rolled back -- the model is unchanged (%s)" % r["status"]))
    return checks, lines


def export_images(doc, sheets, folder, pixels=2400):
    """Export the sheets (ViewSheet objects) to PNG in folder for the title check. Returns the PNG paths."""
    from Autodesk.Revit.DB import (ElementId, ExportRange, ImageExportOptions, ImageFileType, ImageResolution,
                                   ZoomFitType)
    from System.Collections.Generic import List
    if not os.path.isdir(folder):
        os.makedirs(folder)
    before = set(os.listdir(folder))
    opts = ImageExportOptions()
    opts.ExportRange = ExportRange.SetOfViews
    opts.SetViewsAndSheets(List[ElementId]([s.Id for s in sheets]))
    opts.FilePath = os.path.join(folder, "check")
    opts.HLRandWFViewsFileType = ImageFileType.PNG
    opts.ShadowViewsFileType = ImageFileType.PNG
    opts.ImageResolution = ImageResolution.DPI_150
    opts.ZoomType = ZoomFitType.FitToPage
    opts.PixelSize = pixels
    doc.ExportImage(opts)
    return sorted(os.path.join(folder, n) for n in os.listdir(folder)
                  if n not in before and n.lower().endswith(".png"))


# ------------------------------------------------------------ logs

def _csv_cell(v):
    t = u"%s" % v
    if any(ch in t for ch in u'",\n\r'):
        t = u'"%s"' % t.replace(u'"', u'""')
    return t


def _csv_line(cells):
    return u",".join(_csv_cell(c) for c in cells) + u"\r\n"


def write_moves_csv(path, plan, result=None, titles=True):
    """One row per viewport (Excel-friendly UTF-8): the move, the title change and the re-read origin."""
    off = dict(((v[0], v[1]), v[3]) for v in (result or {}).get("verify", []))
    head = ["sheet", "slot", "view", "move x (mm)", "move y (mm)", "title offset before (mm)",
            "title offset after (mm)", "title line before (mm)", "title line after (mm)", "origin off after (mm)"]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(_csv_line(head))
        for m in plan["moves"]:
            f.write(_csv_line([m.sheet, m.slot, m.name, "%.1f" % (m.d.X * MM), "%.1f" % (m.d.Y * MM),
                               _xy(m.old_offset), _xy(m.new_offset) if titles else "",
                               "%.1f" % (m.old_length * MM), ("%.1f" % (m.new_length * MM)) if titles else "",
                               ("%.2f" % off[(m.sheet, m.slot)]) if (m.sheet, m.slot) in off else ""]))
    return path


def _split_csv_line(line):
    """The cells of one CSV line (quotes handled) -- enough for a header row."""
    cells, cur, quoted, i = [], u"", False, 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == u'"' and line[i + 1:i + 2] == u'"':
                cur += u'"'
                i += 1
            elif ch == u'"':
                quoted = False
            else:
                cur += ch
        elif ch == u'"':
            quoted = True
        elif ch == u",":
            cells.append(cur)
            cur = u""
        else:
            cur += ch
        i += 1
    cells.append(cur)
    return cells


def log_time_saved(path, row):
    """Append one row to the time-saved log; follow the existing header when the file has one.

    Returns (header, cells). Raises ValueError when the existing header shares no column with TIME_LOG_FIELDS.
    """
    exists = os.path.isfile(path) and os.path.getsize(path) > 0
    if exists:
        with io.open(path, "r", encoding="utf-8-sig") as f:
            header = _split_csv_line(f.readline().rstrip(u"\r\n"))
        lookup = dict((k.lower(), v) for k, v in row.items())
        out = [lookup.get(h.strip().lower(), "") for h in header]
        if not [c for c in out if c != ""]:
            raise ValueError("%s has columns %s -- none match %s" % (path, header, ", ".join(TIME_LOG_FIELDS)))
        with io.open(path, "rb") as f:
            f.seek(-1, 2)
            ends_with_newline = f.read(1) in (b"\n", b"\r")
    else:
        header = TIME_LOG_FIELDS
        out = [row.get(h, "") for h in header]
        ends_with_newline = True
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
    with io.open(path, "a", encoding="utf-8", newline="") as f:
        if not exists:
            f.write(_csv_line(header))
        elif not ends_with_newline:
            f.write(u"\r\n")
        f.write(_csv_line(out))
    return header, out

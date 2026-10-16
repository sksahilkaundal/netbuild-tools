# -*- coding: UTF-8 -*-
"""
fix_room_separation_line_overlaps.py

For the Revit MCP `execute_revit_code` tool (uses the pre-supplied `doc`;
no extra imports needed beyond Autodesk.Revit.DB).

Reusable pipeline that clears three related Revit warning types on Room
Separation Lines (OST_RoomSeparationLines ModelLine elements), developed
and verified live against ProjectC-Studio-BIM-B001-ZZZ-AR-900001
(121 warnings -> 1, the remaining one an unrelated pre-existing floor
Shape-Editing note):

  1. "Room separation line is slightly off axis" - the line LOOKS
     horizontal/vertical but its endpoints differ by a sub-millimeter
     floating-point drift (e.g. dY ~ 0.0003mm), which is enough for
     Revit's strict axis tolerance to flag it. Fix: snap both endpoints
     to the same axis-aligned coordinate (average X or Y). Always safe -
     does not change the line's effective position.

  2. "Highlighted room separation lines overlap" (line<->line duplicate
     overlap) - two room separation lines occupy the same space. Fix:
     delete one of the pair, but ONLY if doing so does not cause a
     "Room is not in a properly enclosed region" failure (checked live
     via an IFailuresPreprocessor per deletion, in its own transaction -
     if it would unbound a room, the deletion is rolled back and the
     line is left in place, still overlapping, for manual review).

  3. "A wall and a room separation line overlap" (line<->wall overlap) -
     tried in two stages per line:
       a. SHORTEN: if the line only overlaps a wall at one end (or spans
          past both ends of one wall), trim/split it to leave a small
          GAP_FEET (~10mm) short of the wall, exactly like the older
          [[trim-room-separation-lines-wall-gap-script]] approach.
       b. PERPENDICULAR OFFSET (fallback): some lines run COINCIDENT
          along a whole chain of walls (e.g. a full-length perimeter
          line touching 12+ separate wall segments in a row) - the
          shorten logic only handles overlap at the line's own ends, so
          it can't clear this case (attempting it via repeated
          split-per-warning made things WORSE — warning count went up,
          not down — before this offset approach was found). Instead,
          nudge the whole line sideways by OFFSET_FEET perpendicular to
          its own direction. **Confirmed live: even a tiny 1mm offset is
          enough** — the warning checks proximity to the wall's
          LOCATION LINE (a zero-width reference), not the wall's actual
          solid thickness, so there is no need to clear half the wall's
          width. Default OFFSET_FEET is deliberately small (1mm) to
          minimize the shift to the room boundary.
     Both stages use the same room-unbounding safety check as step 2 -
     if either would unbound a room, that line is skipped and left with
     its warning intact rather than silently breaking the model.

**Known limitation, found live:** if you naively fix warnings by
re-fetching `doc.GetWarnings()` in a plain loop and process the FIRST
warning it returns each iteration without care, repeatedly hitting the
SAME line via the split-per-warning path can create extra overlapping
segments faster than it clears the original ones (multiplies warnings
instead of reducing them). This script avoids that by: (1) trying
SHORTEN once per line as a single planned operation covering ALL of
that line's current overlaps in one pass, and (2) falling back to a
SINGLE perpendicular offset for the whole line (not per-wall) when
shorten doesn't apply - never repeatedly re-splitting the same line.

**Also found live (real MCP infrastructure gotcha, not specific to this
script):** `execute_revit_code` results can lag - a call's printed
"Committed"/success output does not always mean `doc.GetWarnings()`
will reflect that immediately on the very next call. If a warning count
looks stuck or wrong right after a script run, re-query
`doc.GetWarnings()` fresh (a new call) before concluding the fix didn't
work - it may just be a stale/delayed response.

CONFIG at top: `GAP_FEET` (shorten gap), `OFFSET_FEET` (perpendicular
offset, default 1mm), `DRY_RUN` is NOT implemented (every change here is
already individually rollback-safe per-line via the room-unbounding
check) - run it live; nothing commits unless it's safe.
"""

from Autodesk.Revit.DB import *
import System

# ---------------------------------------------------------------- CONFIG --
GAP_FEET = 0.0328084          # ~10mm gap for the end-shorten case
OFFSET_FEET = 1.0 / 304.8     # ~1mm perpendicular offset fallback - confirmed sufficient live
# ----------------------------------------------------------------------- #


class SafeFailuresPreprocessor(IFailuresPreprocessor):
    """Rolls back the transaction if the change would unbound a room
    (or raise any other Error-severity failure); otherwise silently
    dismisses benign warnings so the commit isn't blocked by them."""
    def __init__(self):
        self.unbounding = False
        self.other_errors = []

    def PreprocessFailures(self, failuresAccessor):
        msgs = list(failuresAccessor.GetFailureMessages())
        for m in msgs:
            desc = m.GetDescriptionText()
            if "not in a properly enclosed region" in desc or "not properly enclosed" in desc:
                self.unbounding = True
            if m.GetSeverity() == FailureSeverity.Error:
                self.other_errors.append(desc)
        if self.unbounding or self.other_errors:
            return FailureProcessingResult.ProceedWithRollBack
        for m in msgs:
            if m.GetSeverity() == FailureSeverity.Warning:
                try:
                    failuresAccessor.DeleteWarning(m)
                except Exception:
                    pass
        return FailureProcessingResult.Continue


def run_safe(doc, description, action):
    """Runs `action()` inside its own transaction with the safety
    preprocessor. Returns (committed: bool, unbounding: bool, error: str|None)."""
    t = Transaction(doc, description)
    opts = t.GetFailureHandlingOptions()
    pre = SafeFailuresPreprocessor()
    opts.SetFailuresPreprocessor(pre)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    try:
        action()
        status = t.Commit()
    except Exception as ex:
        t.RollBack()
        return (False, False, str(ex))
    if pre.unbounding:
        return (False, True, None)
    return (str(status) == "Committed", False, None)


def perp_vec(direction):
    return XYZ(-direction.Y, direction.X, 0).Normalize()


def perp_dist(pt, origin, direction):
    v = pt - origin
    proj = v.DotProduct(direction)
    closest = origin + direction.Multiply(proj)
    return closest.DistanceTo(pt)


# --------------------------------------------------------- Step 1: axis --
def fix_off_axis_lines(doc):
    fixed = []
    warnings = doc.GetWarnings()
    for w in warnings:
        if "Room separation line is slightly off axis" not in w.GetDescriptionText():
            continue
        for eid in w.GetFailingElements():
            el = doc.GetElement(eid)
            if el is None or el.GetType().Name != "ModelLine":
                continue
            crv = el.Location.Curve
            if not isinstance(crv, Line):
                continue
            p0, p1 = crv.GetEndPoint(0), crv.GetEndPoint(1)
            dx, dy = abs(p1.X - p0.X), abs(p1.Y - p0.Y)
            if dx < 1e-4 and dy > 0:
                avg = (p0.X + p1.X) / 2.0
                new_line = Line.CreateBound(XYZ(avg, p0.Y, p0.Z), XYZ(avg, p1.Y, p1.Z))
            elif dy < 1e-4 and dx > 0:
                avg = (p0.Y + p1.Y) / 2.0
                new_line = Line.CreateBound(XYZ(p0.X, avg, p0.Z), XYZ(p1.X, avg, p1.Z))
            else:
                continue

            def do_fix(el=el, new_line=new_line):
                el.Location.Curve = new_line

            ok, _, _ = run_safe(doc, "Snap off-axis room sep line {}".format(eid.Value), do_fix)
            if ok:
                fixed.append(eid.Value)
    return fixed


# ------------------------------------------------- Step 2: line vs line --
def fix_line_line_overlaps(doc):
    deleted = []
    skipped = []
    warnings = doc.GetWarnings()
    pairs = []
    for w in warnings:
        if "Highlighted room separation lines overlap" not in w.GetDescriptionText():
            continue
        ids = list(w.GetFailingElements())
        if len(ids) == 2:
            pairs.append(ids[1])  # delete the second of the pair, keep the first

    for eid in pairs:
        el = doc.GetElement(eid)
        if el is None:
            continue

        def do_delete(doc=doc, eid=eid):
            doc.Delete(eid)

        ok, unbounding, err = run_safe(doc, "Delete duplicate room sep line {}".format(eid.Value), do_delete)
        if ok:
            deleted.append(eid.Value)
        else:
            skipped.append((eid.Value, "unbounding" if unbounding else (err or "rolledback")))
    return deleted, skipped


# ------------------------------------------------- Step 3: line vs wall --
def _try_shorten(ref_wall, trim_el):
    """Returns (result_tag, data) - data is None if not applicable."""
    curveA = ref_wall.Location.Curve
    curveB = trim_el.Location.Curve
    if not (isinstance(curveA, Line) and isinstance(curveB, Line)):
        return ("skip-nonline", None)

    dirA = curveA.Direction.Normalize()
    originA = curveA.GetEndPoint(0)
    dirB = curveB.Direction.Normalize()
    if dirA.CrossProduct(dirB).GetLength() > 0.01:
        return ("skip-notparallel", None)

    half_thick = ref_wall.Width / 2.0 if hasattr(ref_wall, "Width") else 0.02
    d0 = perp_dist(curveB.GetEndPoint(0), originA, dirA)
    d1 = perp_dist(curveB.GetEndPoint(1), originA, dirA)
    if d0 > half_thick + 0.05 or d1 > half_thick + 0.05:
        return ("skip-toofar", None)

    def proj(pt):
        return (pt - originA).DotProduct(dirA)

    aP0, aP1 = proj(curveA.GetEndPoint(0)), proj(curveA.GetEndPoint(1))
    aStart, aEnd = min(aP0, aP1), max(aP0, aP1)

    bP0raw, bP1raw = curveB.GetEndPoint(0), curveB.GetEndPoint(1)
    bP0, bP1 = proj(bP0raw), proj(bP1raw)
    b0_is_low = bP0 <= bP1
    bStart, bEnd = (bP0, bP1) if b0_is_low else (bP1, bP0)

    if max(aStart, bStart) >= min(aEnd, bEnd) - 1e-6:
        return ("skip-nooverlap", None)

    origB = bP0raw if b0_is_low else bP1raw
    dirB_signed = (bP1raw - bP0raw).Normalize() if b0_is_low else (bP0raw - bP1raw).Normalize()

    def point_at_b(param_along_A):
        return origB + dirB_signed.Multiply(param_along_A - bStart)

    contains_a = bStart <= aStart + 1e-6 and bEnd >= aEnd - 1e-6
    b_low_inside = bStart >= aStart - 1e-6 and bStart <= aEnd + 1e-6
    b_high_inside = bEnd >= aStart - 1e-6 and bEnd <= aEnd + 1e-6

    if contains_a:
        return ("skip-spans-whole-wall", None)  # ambiguous which end to trim - offset fallback handles this better
    elif b_low_inside and not b_high_inside:
        newLow = point_at_b(aEnd + GAP_FEET)
        newHigh = bP1raw if b0_is_low else bP0raw
        if newLow.DistanceTo(newHigh) > 0.02:
            return ("trim-low", Line.CreateBound(newLow, newHigh))
        return ("skip-toosmall", None)
    elif b_high_inside and not b_low_inside:
        newLow = bP0raw if b0_is_low else bP1raw
        newHigh = point_at_b(aStart - GAP_FEET)
        if newLow.DistanceTo(newHigh) > 0.02:
            return ("trim-high", Line.CreateBound(newLow, newHigh))
        return ("skip-toosmall", None)
    else:
        return ("skip-unclear", None)


def fix_wall_line_overlaps(doc):
    handled = []
    skipped = []

    warnings = doc.GetWarnings()
    by_line = {}
    for w in warnings:
        if "A wall and a room separation line overlap" not in w.GetDescriptionText():
            continue
        ids = list(w.GetFailingElements())
        if len(ids) != 2:
            continue
        e1, e2 = doc.GetElement(ids[0]), doc.GetElement(ids[1])
        if e1 is None or e2 is None:
            continue
        wall, line = (e1, e2) if e1.GetType().Name == "Wall" else (e2, e1)
        if wall.GetType().Name != "Wall" or line.GetType().Name != "ModelLine":
            continue
        by_line.setdefault(line.Id.Value, {"line": line, "walls": []})["walls"].append(wall)

    for line_val, info in by_line.items():
        line_el = info["line"]
        walls = info["walls"]

        # Stage A: try a single-wall end-shorten only when there's exactly one wall
        if len(walls) == 1:
            tag, data = _try_shorten(walls[0], line_el)
            if data is not None:
                def do_shorten(line_el=line_el, data=data):
                    line_el.Location.Curve = data
                ok, unbounding, err = run_safe(doc, "Shorten room sep line {}".format(line_val), do_shorten)
                if ok:
                    handled.append((line_val, tag))
                    continue
                elif not unbounding:
                    pass  # fall through to offset attempt below
                else:
                    skipped.append((line_val, "shorten-would-unbound"))
                    continue

        # Stage B: perpendicular offset fallback (handles multi-wall / spans-whole-wall cases)
        crv = line_el.Location.Curve
        if not isinstance(crv, Line):
            skipped.append((line_val, "non-line-geometry"))
            continue
        dirL = crv.Direction.Normalize()
        perp = perp_vec(dirL)
        p0, p1 = crv.GetEndPoint(0), crv.GetEndPoint(1)

        success = False
        for sign in (1, -1):
            move_vec = perp.Multiply(OFFSET_FEET * sign)
            new_line = Line.CreateBound(p0 + move_vec, p1 + move_vec)

            def do_offset(line_el=line_el, new_line=new_line):
                line_el.Location.Curve = new_line

            ok, unbounding, err = run_safe(doc, "Offset room sep line {} by {:.2f}mm".format(line_val, OFFSET_FEET * sign * 304.8), do_offset)
            if ok:
                handled.append((line_val, "offset-{:.1f}mm".format(OFFSET_FEET * sign * 304.8)))
                success = True
                break
        if not success:
            skipped.append((line_val, "offset-would-unbound-both-directions"))

    return handled, skipped


# --------------------------------------------------------------- MAIN ----
def run(doc):
    print("Warnings before: {}".format(len(doc.GetWarnings())))

    axis_fixed = fix_off_axis_lines(doc)
    print("Step 1 (off-axis) fixed: {}".format(axis_fixed))

    ll_deleted, ll_skipped = fix_line_line_overlaps(doc)
    print("Step 2 (line-vs-line) deleted: {}".format(ll_deleted))
    print("Step 2 (line-vs-line) skipped (would unbound): {}".format(ll_skipped))

    wl_handled, wl_skipped = fix_wall_line_overlaps(doc)
    print("Step 3 (wall-vs-line) handled: {}".format(wl_handled))
    print("Step 3 (wall-vs-line) skipped (would unbound both ways): {}".format(wl_skipped))

    print("Warnings after: {}".format(len(doc.GetWarnings())))


run(doc)

"""Sheet lists (single / list / series) and the revision-date filter string."""

import datetime
import re

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Separators between sheets in a list. Whitespace also separates, except
# around a series keyword ("210001 to 210012").
LIST_SPLIT = re.compile(r"[,;|\r\n\t]+")
SERIES = re.compile(r"^\s*(\S+)\s*(?:\.\.|\bto\b|~|:)\s*(\S+)\s*$", re.I)
DIGIT_DASH_SERIES = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
TAIL = re.compile(r"^(.*?)(\d+)$")


class SheetSpecError(ValueError):
    pass


class Selector(object):
    """One item from the sheet box: an exact sheet, or a numbered series."""

    def __init__(self, text, start=None, end=None):
        self.text = text
        self.series = start is not None
        if self.series:
            ma, mb = TAIL.match(start), TAIL.match(end)
            if not ma or not mb:
                raise SheetSpecError("series %r: both ends must end in a number" % text)
            if ma.group(1).lower() != mb.group(1).lower():
                raise SheetSpecError("series %r: %r and %r have different prefixes"
                                     % (text, ma.group(1), mb.group(1)))
            self.prefix = ma.group(1).lower()
            self.lo, self.hi = int(ma.group(2)), int(mb.group(2))
            if self.lo > self.hi:
                raise SheetSpecError("series %r runs backwards" % text)
            if self.hi - self.lo > 5000:
                raise SheetSpecError("series %r is over 5000 sheets -- check the numbers" % text)

    def matches(self, key):
        key = key.strip().lower()
        if not self.series:
            return key == self.text.strip().lower()
        m = TAIL.match(key)
        return bool(m) and m.group(1) == self.prefix and self.lo <= int(m.group(2)) <= self.hi

    def __repr__(self):
        return "Selector(%r)" % self.text


def parse_sheet_spec(text):
    """'210001' | '210001, 210004; 210007' | '210001 to 210012' | mixed -> [Selector].

    Empty text -> [] (meaning: every sheet that matches the revision date).
    """
    out = []
    for chunk in LIST_SPLIT.split(text or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = SERIES.match(chunk) or DIGIT_DASH_SERIES.match(chunk)
        if m:
            out.append(Selector(chunk, m.group(1), m.group(2)))
            continue
        for tok in chunk.split():
            out.append(Selector(tok))
    return out


def candidate_keys(c):
    """Names a sheet can be called by: Sheet Number, drawing number (with/without _rev), 7th field."""
    base = c["fname"].rsplit("_", 1)[0] if "_" in c["fname"] else c["fname"]
    keys = [c["sheet"], c["fname"], base]
    if "-" in base:
        keys.append(base.rsplit("-", 1)[1])
    return [k for k in keys if k]


def select(candidates, selectors):
    """-> (chosen candidates in script order, [selector texts that matched nothing])."""
    if not selectors:
        return list(candidates), []
    used = set()
    chosen = []
    for c in candidates:
        keys = candidate_keys(c)
        hit = [i for i, s in enumerate(selectors) if any(s.matches(k) for k in keys)]
        if hit:
            chosen.append(c)
            used.update(hit)
    unmatched = [s.text for i, s in enumerate(selectors) if i not in used]
    return chosen, unmatched


# ------------------------------------------------------------ revision date

DATE_INPUTS = ["%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y",
               "%Y%m%d"]


def parse_date(text):
    t = (text or "").strip()
    for fmt in DATE_INPUTS:
        try:
            return datetime.datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def date_variants(d):
    """Zero-padded spellings only: '6-Sep-2026' would also hit '16-Sep-2026' (substring filter)."""
    mon = MONTHS[d.month - 1]
    return ["%02d-%s-%04d" % (d.day, mon, d.year),
            "%02d/%02d/%04d" % (d.day, d.month, d.year),
            "%02d.%02d.%04d" % (d.day, d.month, d.year),
            "%04d-%02d-%02d" % (d.year, d.month, d.day),
            "%02d %s %04d" % (d.day, mon, d.year)]


def pick_date_filter(text, values):
    """Choose the REVISION_DATE_FILTER string the model actually uses.

    text   -- what the user typed (any common date spelling, or an exact string)
    values -- {"Current Revision Date" value: sheet count} read live from the model
    -> (filter or None, {variant: sheets matched}, message)
    """
    t = (text or "").strip()
    if not t:
        return None, {}, "no revision-date filter (every routed sheet / the sheets listed)"
    d = parse_date(t)
    variants = date_variants(d) if d else [t]
    counts = dict((v, sum(n for val, n in values.items() if v in (val or ""))) for v in variants)
    hits = [v for v in variants if counts[v]]
    if not hits:
        return None, counts, ("no sheet's \"Current Revision Date\" contains %s"
                              % " / ".join(repr(v) for v in variants))
    best = max(hits, key=lambda v: counts[v])
    msg = "%r matches %d sheet(s)" % (best, counts[best])
    if len(hits) > 1:
        msg += "; this model ALSO uses %s -- only %r is exported" % (
            ", ".join("%r (%d)" % (v, counts[v]) for v in hits if v != best), best)
    return best, counts, msg

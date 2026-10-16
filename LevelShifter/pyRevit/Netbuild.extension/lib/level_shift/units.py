"""Lengths: what you type (mm or m) <-> Revit internal feet."""

import re

FEET = {"mm": 304.8, "m": 0.3048, "ft": 1.0}   # units per foot
_NUM = re.compile(r"^([+-]?)(\d*\.?\d+|\d+\.)(mm|m|ft)?$", re.I)


def to_ft(value, units):
    return float(value) / FEET[units]


def from_ft(feet, units):
    return float(feet) * FEET[units]


def parse_length(text, units):
    """'3500', '3,500', '+300', '-1200 mm', '3.5m', '3,5 m' -> value in ``units`` (a unit suffix wins).

    Raises ValueError for anything else.
    """
    raw = (text or "").strip().replace(" ", "").replace("_", "")
    if "," in raw:
        if "." in raw or re.match(r"^[+-]?\d{1,3}(,\d{3})+([a-zA-Z]*)$", raw):
            raw = raw.replace(",", "")          # thousands separators
        else:
            raw = raw.replace(",", ".")         # decimal comma
    m = _NUM.match(raw)
    if not m:
        raise ValueError("not a length: %r (e.g. 3500, +300, -1200, 3.5m)" % text)
    value = float(m.group(1) + m.group(2))
    unit = (m.group(3) or units).lower()
    return value * FEET[units] / FEET[unit]


def fmt(value, units, signed=False):
    """A value already in ``units`` -> '+3,500.0 mm' style text."""
    digits = {"mm": 1, "m": 4, "ft": 4}[units]
    text = ("{:+,.%df}" if signed else "{:,.%df}") % digits
    return "%s %s" % (text.format(value), units)


def fmt_ft(feet, units, signed=False):
    return fmt(from_ft(feet, units), units, signed)

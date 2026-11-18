"""Read one column of an .xlsx workbook without Excel or openpyxl (IronPython 2.7 under pyRevit + CPython 3).

An .xlsx is a zip of XML parts: xl/workbook.xml names the tabs, xl/_rels/workbook.xml.rels points each tab at its
worksheet part, xl/sharedStrings.xml holds the text. Cell text is kept exactly -- trailing spaces included, as some
workset names end with one.

A register that is open in Excel is locked for normal reads; inside Revit it is read through a .NET stream that
shares the lock (the way Explorer copies an open file), into a temporary copy.
"""

import io
import os
import re
import tempfile
import zipfile

# Parsed with re rather than xml.etree: IronPython 2.7 may lack pyexpat, and one code path runs in Revit and tests.
_P = r"(?:[A-Za-z_][\w.-]*:)?"                     # an optional namespace prefix (x:sheet, ...)
_ATTR = re.compile(r'([\w:.-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
_ENT = re.compile(r"&(#x[0-9A-Fa-f]+|#\d+|amp|lt|gt|quot|apos);")
_NAMED = {"amp": u"&", "lt": u"<", "gt": u">", "quot": u'"', "apos": u"'"}


class RegisterError(Exception):
    pass


def _unescape(text):
    def one(m):
        e = m.group(1)
        if e.startswith("#x"):
            return _chr(int(e[2:], 16))
        if e.startswith("#"):
            return _chr(int(e[1:]))
        return _NAMED[e]
    return _ENT.sub(one, text)


def _chr(n):
    try:
        return unichr(n)                               # noqa: F821 -- IronPython 2.7
    except NameError:
        return chr(n)


def _attrs(tag):
    """{local name: value} of one start tag's attributes."""
    return dict((k.split(":")[-1] if not k.startswith("xmlns") else k, _unescape(a if a or not b else b))
                for k, a, b in _ATTR.findall(tag))


def _tags(xml, name):
    """[(attributes, inner xml)] of every <name ...>...</name> or <name .../> element (any namespace prefix)."""
    pat = re.compile(r"<%s%s\b([^>]*?)(?:/>|>(.*?)</%s%s\s*>)" % (_P, name, _P, name), re.S)
    return [(_attrs(a), inner or u"") for a, inner in pat.findall(xml)]


def _read(z, part):
    data = z.read(part)
    return data.decode("utf-8") if not isinstance(data, type(u"")) else data


def _shared_copy(path):
    """A temporary copy of a file another program holds open (.NET, inside Revit); None outside .NET."""
    try:
        from System.IO import File, FileAccess, FileMode, FileShare, FileStream, MemoryStream
    except Exception:
        return None
    tmp = os.path.join(tempfile.gettempdir(), "netbuild_modelprep_register.xlsx")
    fs = FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)
    try:
        ms = MemoryStream()
        fs.CopyTo(ms)
        File.WriteAllBytes(tmp, ms.ToArray())
    finally:
        fs.Close()
    return tmp


def _open(path):
    if not os.path.isfile(path):
        raise RegisterError("not found: %s" % path)
    try:
        with io.open(path, "rb") as f:
            f.read(1)
        return zipfile.ZipFile(path)
    except (IOError, OSError):
        copy = _shared_copy(path)
        if copy is None:
            raise
        return zipfile.ZipFile(copy)


def _text(inner):
    """All <t> text of a shared / inline string (rich text runs joined)."""
    return u"".join(_unescape(t) for _, t in _tags(inner, "t"))


def _col_index(ref):
    """'C12' -> 2 (zero-based); None when ref has no letters."""
    m = re.match(r"([A-Za-z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1).upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _sheet_parts(z):
    """[(tab name, part path)] in workbook order."""
    rels = dict((a.get("Id"), a.get("Target") or "") for a, _ in _tags(_read(z, "xl/_rels/workbook.xml.rels"),
                                                                        "Relationship"))
    out = []
    for a, _ in _tags(_read(z, "xl/workbook.xml"), "sheet"):
        t = rels.get(a.get("id")) or ""
        out.append((a.get("name"), t.lstrip("/") if t.startswith("/") else "xl/" + t))
    return out


def _shared_strings(z):
    try:
        xml = _read(z, "xl/sharedStrings.xml")
    except KeyError:
        return []
    return [_text(inner) for _, inner in _tags(xml, "si")]


def _column(z, part, col, strings, skip_rows):
    out = []
    for i, (_, row) in enumerate(_tags(_read(z, part), "row")):
        if i < skip_rows:
            continue
        for pos, (a, inner) in enumerate(_tags(row, "c")):
            idx = _col_index(a.get("r"))
            if (pos if idx is None else idx) != col:
                continue
            kind = a.get("t")
            if kind == "inlineStr":
                value = _text(inner)
            else:
                v = _tags(inner, "v")
                value = _unescape(v[0][1]) if v else u""
                if kind == "s":
                    value = strings[int(value)] if value.strip().isdigit() and int(value) < len(strings) else u""
            if value.strip():
                out.append(value)
    return out


def read_register(path, column="A", skip_rows=0):
    """{tab name: [non-blank cell texts of that column, top to bottom]} for every tab, in workbook order (as a list
    of (tab, names) pairs). Raises RegisterError when the file is missing or not an .xlsx."""
    col = _col_index(column)
    if col is None:
        raise RegisterError("not a column: %r" % column)
    try:
        z = _open(path)
    except zipfile.BadZipfile:
        raise RegisterError("not an .xlsx file: %s" % path)
    try:
        strings = _shared_strings(z)
        return [(name, _column(z, part, col, strings, skip_rows)) for name, part in _sheet_parts(z)]
    except (KeyError, ValueError) as e:
        raise RegisterError("could not read %s: %s" % (os.path.basename(path), e))
    finally:
        z.close()

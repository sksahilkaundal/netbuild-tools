"""Set an export script's CONFIG globals for one Revit call, without editing the file.

The script is read, never written. Only the right-hand side of each overridden
top-level ``NAME = ...`` is swapped (byte-exact splice), so every other line --
comments, the coding header, IronPython-2.7-only idioms -- reaches Revit
unchanged. Values are written as Python-2.7-compatible literals.

Two small blocks are added around the script:

* a preamble (prepended) with the per-call nonce, the model to bind to and
  the optional sheet / category filter, and
* one filter line inserted right after the top-level loop that builds
  ``candidates``, which narrows the list and prints it as a nonce-tagged JSON
  line, so the runner knows exactly which files this call should write.
"""

import ast
import warnings


class PatchError(Exception):
    pass


class Expr(str):
    """A raw expression, written into the script as-is (e.g. the doc binding)."""


def py_literal(value):
    """A literal both IronPython 2.7 and CPython 3 read back to the same value."""
    if isinstance(value, Expr):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        text = repr(value)
        return ("u" + text) if any(ord(ch) > 127 for ch in value) else text
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(py_literal(v) for v in value)
    if isinstance(value, dict):
        return "{%s}" % ", ".join("%s: %s" % (py_literal(k), py_literal(v)) for k, v in value.items())
    raise PatchError("unsupported value type: %r" % (value,))


def _line_starts(data):
    starts, pos = [0], 0
    for line in data.splitlines(True):
        pos += len(line)
        starts.append(pos)
    return starts


def _decode(source):
    if isinstance(source, bytes):
        source = source.decode("utf-8-sig")
    return source.lstrip("﻿")


def parse(source, filename="<script>"):
    try:
        with warnings.catch_warnings():  # e.g. '\<' in an IronPython docstring
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(_decode(source), filename=filename)
    except SyntaxError as e:
        raise PatchError("%s does not parse: %s" % (filename, e))


def top_level_values(source, names, filename="<script>"):
    """{name: value} for top-level ``NAME = <literal>``; a non-literal comes back as Expr(source text)."""
    text = _decode(source)
    out = {}
    for stmt in parse(text, filename).body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            n = stmt.targets[0].id
            if n in names:
                try:
                    out[n] = ast.literal_eval(stmt.value)
                except ValueError:
                    out[n] = Expr(ast.get_source_segment(text, stmt.value) or "")
    return out


def find_candidates_loop(tree, list_name="candidates"):
    """The top-level `for` loop whose body calls ``<list_name>.append``."""
    for stmt in tree.body:
        if not isinstance(stmt, ast.For):
            continue
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == list_name):
                return stmt
    return None


def patch_source(source, overrides, insert_after_loop=None, prepend="", append="",
                 filename="<script>"):
    """Return the patched script text (str) and {name: assignments replaced}."""
    text = _decode(source)
    tree = parse(text, filename)
    data = text.encode("utf-8")
    starts = _line_starts(data)

    def off(lineno, col):
        return starts[lineno - 1] + col

    edits = []
    hits = dict((n, 0) for n in overrides)
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            todo = [n for n in names if n in overrides]
            if not todo or stmt.value is None:
                continue
            if len(targets) > 1:
                raise PatchError("%s line %d assigns several names together; cannot override %s"
                                 % (filename, stmt.lineno, todo[0]))
            v = stmt.value
            edits.append((off(v.lineno, v.col_offset), off(v.end_lineno, v.end_col_offset),
                          py_literal(overrides[todo[0]]).encode("utf-8")))
            hits[todo[0]] += 1

    missing = sorted(n for n, c in hits.items() if c == 0)
    if missing:
        raise PatchError("not assigned at the top level of %s: %s" % (filename, ", ".join(missing)))

    if insert_after_loop is not None:
        loop = find_candidates_loop(tree)
        if loop is None:
            raise PatchError("%s has no top-level loop that builds `candidates`" % filename)
        at = starts[loop.end_lineno] if loop.end_lineno < len(starts) else len(data)
        block = insert_after_loop.rstrip("\n") + "\n"
        if at == len(data) and not data.endswith(b"\n"):
            block = "\n" + block
        edits.append((at, at, block.encode("utf-8")))

    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        data = data[:start] + new + data[end:]
    out = data.decode("utf-8")
    if prepend:
        out = prepend.rstrip("\n") + "\n" + out
    if append:
        out = out.rstrip("\n") + "\n" + append.rstrip("\n") + "\n"
    return out, hits

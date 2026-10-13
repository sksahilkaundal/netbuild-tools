"""Run a Python script with some of its module-level CONFIG globals replaced.

The script file is only read, never written. Its source is parsed, every
top-level assignment to an overridden name has its right-hand side swapped
for the new value, and the patched tree is executed as ``__main__`` -- the
same as ``python <script>``.

The new value keeps the *form* of the original assignment, so the script
sees the type it expects:

    BASE = Path(r"C:\\old")        ->  BASE = Path('C:\\new')
    BCF_FILE = "a.bcf"            ->  BCF_FILE = 'b.bcf'
    BCF_FILE = ["a.bcf"]          ->  BCF_FILE = ['b.bcf', 'c.bcf']
    MAX_ISSUE_ID = None           ->  MAX_ISSUE_ID = 1450

Also runnable on its own (this is how the runner calls it, with the user's
Python):

    python overrides.py <script.py> --set NAME=<json> [--set NAME=<json> ...]
"""

import argparse
import ast
import builtins
import copy
import json
import os
import sys


class OverrideError(Exception):
    pass


def _is_path_call(node):
    """Path("x") / pathlib.Path("x") / PureWindowsPath("x") with one str arg."""
    if not isinstance(node, ast.Call) or len(node.args) != 1 or node.keywords:
        return False
    func = node.func
    name = func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) else None)
    return bool(name) and name.endswith("Path")


def _const(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return ast.Constant(value=value)
    if isinstance(value, (list, tuple)):
        return ast.List(elts=[_const(v) for v in value], ctx=ast.Load())
    if isinstance(value, dict):
        return ast.Dict(keys=[_const(k) for k in value],
                        values=[_const(v) for v in value.values()])
    raise OverrideError("unsupported value type: %r" % (value,))


def _shaped(name, original, value):
    """Build an AST node for ``value`` shaped like the ``original`` node."""
    if isinstance(original, (ast.List, ast.Tuple)) and isinstance(value, (str, list, tuple)):
        items = [value] if isinstance(value, str) else list(value)
        template = original.elts[0] if original.elts else None
        elts = [_shaped(name, template, v) if template is not None else _const(v)
                for v in items]
        cls = ast.Tuple if isinstance(original, ast.Tuple) else ast.List
        return cls(elts=elts, ctx=ast.Load())

    if isinstance(value, (list, tuple)):
        if len(value) == 1:
            value = value[0]
        else:
            raise OverrideError(
                "%s holds a single value in the script, but %d values were given: %r"
                % (name, len(value), list(value)))

    if _is_path_call(original) and isinstance(value, str):
        node = copy.deepcopy(original)
        node.args = [ast.Constant(value=value)]
        return node

    return _const(value)


def patch_source(source, overrides, filename="<script>"):
    """Return (code object, {name: number of assignments replaced})."""
    tree = ast.parse(source, filename=filename)
    hits = dict((name, 0) for name in overrides)

    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            # Only a plain `NAME = value` (or `A = B = value`) is rewritten;
            # tuple unpacking is left alone.
            if len(names) != len(stmt.targets):
                continue
            todo = [n for n in names if n in overrides]
            if not todo:
                continue
            if len(names) > 1:
                raise OverrideError(
                    "line %d assigns %s together; cannot override one of them"
                    % (stmt.lineno, " = ".join(names)))
            name = todo[0]
            stmt.value = _shaped(name, stmt.value, overrides[name])
            hits[name] += 1
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            if name in overrides:
                stmt.value = _shaped(name, stmt.value, overrides[name])
                hits[name] += 1

    missing = [n for n, c in hits.items() if c == 0]
    if missing:
        raise OverrideError(
            "not assigned at the top level of %s: %s" % (filename, ", ".join(missing)))

    ast.fix_missing_locations(tree)
    return compile(tree, filename, "exec"), hits


def run_script(path, overrides, argv=None):
    """Execute ``path`` as __main__ with ``overrides`` applied."""
    path = os.path.abspath(path)
    with open(path, "rb") as f:
        source = f.read()
    code, hits = patch_source(source, overrides, filename=path)

    for name in sorted(overrides):
        print("[runner] %s = %r" % (name, overrides[name]), flush=True)

    sys.argv = [path] + list(argv or [])
    # Swap this file's folder for the script's on sys.path, so the runner's
    # modules (settings.py, gui.py ...) never shadow the script's own imports.
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
    sys.path.insert(0, os.path.dirname(path))
    globs = {"__name__": "__main__", "__file__": path,
             "__builtins__": builtins, "__package__": None}
    exec(code, globs)
    return hits


def _parse_set(item):
    if "=" not in item:
        raise argparse.ArgumentTypeError("expected NAME=<json>, got %r" % item)
    name, raw = item.split("=", 1)
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw  # bare string
    return name.strip(), value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("script")
    ap.add_argument("--set", dest="sets", action="append", type=_parse_set, default=[],
                    metavar="NAME=JSON")
    ap.add_argument("script_args", nargs="*")
    args = ap.parse_args(argv)
    try:
        run_script(args.script, dict(args.sets), args.script_args)
    except OverrideError as e:
        print("[runner] ERROR: %s" % e, file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

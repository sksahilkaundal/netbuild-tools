"""Command-line front end. `LevelShift <command> -h` for each command."""

import argparse
import sys

from .core import MAX_LEVELS, MoveSpec
from .runner import Aborted, Runner
from .settings import DEFAULTS, Settings


def _report(res):
    print()
    for c in res.checks:
        print(c)
    if res.log_path:
        print("log: %s" % res.log_path)
    if res.info.get("rows_csv"):
        print("element list: %s" % res.info["rows_csv"])
    return 0 if res.ok else 1


def _specs(a, units):
    specs = [MoveSpec.parse(t, "to", units) for t in a.to or []]
    specs += [MoveSpec.parse(t, "by", units) for t in a.by or []]
    return specs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="LevelShift", description=(
        "Move up to %d levels to a new elevation while every element on them keeps its X, Y, Z "
        "(talks to Revit through the pyRevit MCP listener)" % MAX_LEVELS))
    ap.add_argument("--model", help="Revit title must contain this (default from settings; blank = active model)")
    ap.add_argument("--units", choices=["mm", "m"], help="units for values without a suffix (default from settings)")
    sub = ap.add_subparsers(dest="cmd")

    st = sub.add_parser("setup", help="show / change settings")
    st.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="e.g. --set tolerance_mm=0.5  (keys: %s)" % ", ".join(DEFAULTS))
    sub.add_parser("models", help="list the models open in Revit (and the active one)")
    sub.add_parser("levels", help="list the levels of the model with their current elevation")
    for name, text in (("plan", "what would be compensated, and what blocks it -- nothing is changed"),
                       ("trial", "do the whole move in Revit, measure every element, then roll back"),
                       ("apply", "do the move; kept only if every element kept its position")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--to", action="append", metavar="LEVEL=ELEVATION",
                       help="new elevation, e.g. --to \"Level 03=10500\" or --to \"L03=10.5m\"")
        p.add_argument("--by", action="append", metavar="LEVEL=MOVE",
                       help="move up (+) or down (-), e.g. --by \"Level 03=+300\" --by \"L04=-150\"")
        if name == "apply":
            p.add_argument("--keep-drift", action="store_true",
                           help="keep the result even if some element still moved (they are listed)")
    sub.add_parser("gui", help="open the window (default)")

    a = ap.parse_args(argv)
    s = Settings()
    if a.model is not None:
        s["model_match"] = a.model
    if a.units:
        s["units"] = a.units

    if a.cmd in (None, "gui"):
        from .gui import main as gui_main
        return gui_main(["--model", a.model] if a.model else [])

    if a.cmd == "setup":
        for item in a.set:
            key, _, val = item.partition("=")
            if key not in DEFAULTS:
                ap.error("unknown setting %r" % key)
            kind = type(DEFAULTS[key])
            s[key] = (val.lower() in ("1", "true", "yes", "on")) if kind is bool else kind(val)
        if a.set:
            s.save()
            print("saved %s" % s.path)
        for k in DEFAULTS:
            print("  %-24s %s" % (k, s[k]))
        return 0

    runner = Runner(s)
    if a.cmd == "models":
        try:
            docs = runner.list_docs()
        except Aborted as e:
            print("[FAIL] %s" % e)
            return 2
        for d in docs:
            flags = [f for f in ("active", "linked", "family", "readonly") if d.get(f)]
            print("  %s%s" % (d.get("title"), ("   [" + ", ".join(flags) + "]") if flags else ""))
        return 0

    if a.cmd == "levels":
        return _report(runner.read_levels())

    try:
        specs = _specs(a, runner.units)
    except ValueError as e:
        print("[FAIL] %s" % e)
        return 2
    if not specs:
        ap.error("give at least one --to or --by")
    if a.cmd == "apply" and a.keep_drift:
        s["rollback_on_drift"] = False
    s.save_last({"model_match": s["model_match"], "specs": [sp.as_dict() for sp in specs]})
    return _report(runner.run(a.cmd, None, specs))


if __name__ == "__main__":
    sys.exit(main())

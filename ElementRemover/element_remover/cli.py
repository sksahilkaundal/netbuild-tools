"""Command-line front end. `ElementRemover <command> -h` for each command."""

import argparse
import sys

from . import about
from .core import Targets, split_names
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ElementRemover", description=(
        "%s %s -- remove the elements on chosen worksets and / or passing chosen view filters, standalone or "
        "inside model groups (talks to Revit through the pyRevit MCP listener)" % (about.PRODUCT, about.VERSION)),
        epilog="%s  |  %s  |  %s (ElementRemover license)" % (about.COPYRIGHT, about.WEBSITE, about.LICENSE_NAME))
    ap.add_argument("--version", action="version", version="%s %s" % (about.PRODUCT, about.VERSION))
    ap.add_argument("--model", help="Revit title must contain this (default from settings; blank = active model)")
    sub = ap.add_subparsers(dest="cmd")

    st = sub.add_parser("setup", help="show / change settings")
    st.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="e.g. --set skip_pinned=false  (keys: %s)" % ", ".join(DEFAULTS))
    sub.add_parser("models", help="list the models open in Revit (and the active one)")
    sub.add_parser("sources", help="list the worksets, view filters and categories of the model")
    for name, text in (("plan", "what would be removed, what is skipped, what blocks it -- nothing is changed"),
                       ("trial", "do the whole removal in Revit, check it, then roll back"),
                       ("apply", "do the removal; one Undo entry in Revit")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--workset", action="append", default=[], metavar="NAME",
                       help="remove the elements on this workset (repeat for more)")
        p.add_argument("--filter", action="append", default=[], metavar="NAME",
                       help="remove the elements passing this view filter or saved selection (repeat for more)")
        p.add_argument("--category", action="append", default=[], metavar="NAME",
                       help="only these categories, e.g. --category Walls (repeat, or 'Walls, Doors')")
        p.add_argument("--both", action="store_true",
                       help="an element must be on a --workset AND pass a --filter (default: either)")
        p.add_argument("--include-pinned", action="store_true", help="remove pinned elements too (unpins them)")
        p.add_argument("--no-groups", action="store_true",
                       help="leave elements inside model groups alone (default: ungroup, remove, regroup)")
    sub.add_parser("about", help="product info, requirements and licence")
    sub.add_parser("license", aliases=["licence"], help="the licence: ownership, website and the full agreement")

    a = ap.parse_args(argv)
    if a.cmd is None:
        ap.print_help()
        return 0
    if a.cmd in ("about", "license", "licence"):
        text = about.about_text() if a.cmd == "about" else about.licence_text()
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, "replace").decode(enc))     # a console without the (c) sign
        return 0

    s = Settings()
    if a.model is not None:
        s["model_match"] = a.model

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

    if a.cmd == "sources":
        return _report(runner.read_sources())

    cats = []
    for c in a.category:
        cats.extend(n for n in split_names(c) if n not in cats)
    targets = Targets(a.workset, a.filter, cats, "all" if a.both else "any")
    if not targets.worksets and not targets.filters:
        ap.error("give at least one --workset or --filter")
    if a.include_pinned:
        s["skip_pinned"] = False
    if a.no_groups:
        s["fix_groups"] = False
    s.save_last({"model_match": s["model_match"], "targets": targets.as_dict()})
    return _report(runner.run(a.cmd, targets))


if __name__ == "__main__":
    sys.exit(main())

"""Command-line front end. `StairPath <command> -h` for each command."""

import argparse
import sys

from . import about, rules
from .runner import Aborted, Runner
from .settings import DEFAULTS, Settings


def _report(res):
    print()
    for c in res.checks:
        print(c)
    if res.log_path:
        print("log: %s" % res.log_path)
    if res.info.get("rows_csv"):
        print("annotation list: %s" % res.info["rows_csv"])
    return 0 if res.ok else 1


def _bool(text):
    t = text.strip().lower()
    if t in ("1", "true", "yes", "on"):
        return True
    if t in ("0", "false", "no", "off"):
        return False
    raise ValueError("not true / false")


def parse_sets(items, known):
    """['dir_x_mm=300', ...] -> {key: value}, typed like ``known``; ValueError naming the bad item."""
    out = {}
    for item in items:
        key, eq, val = item.partition("=")
        key = key.strip()
        if not eq or key not in known:
            raise ValueError("unknown setting %r (keys: %s)" % (item, ", ".join(sorted(known))))
        kind = type(known[key])
        try:
            out[key] = _bool(val) if kind is bool else kind(val.strip())
        except ValueError:
            raise ValueError("%s: %r is not a %s" % (key, val, "true / false" if kind is bool else kind.__name__))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="StairPath", description=(
        "%s %s -- Up / Down stair path annotations in plan views by the office standard (talks to Revit through "
        "the pyRevit MCP listener)" % (about.PRODUCT, about.VERSION)),
        epilog="%s  |  %s  |  %s (StairPath license)" % (about.COPYRIGHT, about.WEBSITE, about.LICENSE_NAME))
    ap.add_argument("--version", action="version", version="%s %s" % (about.PRODUCT, about.VERSION))
    ap.add_argument("--model", help="Revit title must contain this (default from settings; blank = active model)")
    sub = ap.add_subparsers(dest="cmd")

    st = sub.add_parser("setup", help="show / change the connection settings and the settings kept per model")
    st.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="e.g. --set apply_timeout_seconds=7200  (keys: %s)" % ", ".join(DEFAULTS))
    sub.add_parser("models", help="list the models open in Revit (and the active one)")
    for name, text in (("plan", "the stair cores and what each view gets -- nothing is changed"),
                       ("trial", "place everything in Revit, report it, then roll back"),
                       ("apply", "place everything; one Undo entry in Revit ('Stair Path by Netbuild')")):
        p = sub.add_parser(name, help=text, description=text + ". Settings given here are kept for the model.")
        views = p.add_mutually_exclusive_group()
        views.add_argument("--open-views", action="store_true", help="the plan views open in Revit")
        views.add_argument("--views-named", metavar="TEXT", help="every plan view whose name contains TEXT")
        clear = p.add_mutually_exclusive_group()
        clear.add_argument("--clear-views", action="store_true", help="clear existing stair paths in the target "
                                                                      "views only (default)")
        clear.add_argument("--clear-model", action="store_true", help="clear existing stair paths in the whole model")
        p.add_argument("--create-types", action="store_true",
                       help="create missing 'Standard 1-500 / 1-200 / 1-100' types (duplicates of 'Standard')")
        p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                       help="any Stair Path setting, e.g. --set dir_x_mm=300 --set sweep=false (keys: %s)"
                            % ", ".join(rules.DEFAULTS))
        p.add_argument("--reset", action="store_true", help="start from the default settings for this model")
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
        try:
            changes = parse_sets(a.set, DEFAULTS)
        except ValueError as e:
            ap.error(str(e))
        if changes:
            s.update(changes)
            s.save()
            print("saved %s" % s.path)
        for k in DEFAULTS:
            print("  %-24s %s" % (k, s[k]))
        print("Stair Path settings kept per model%s" % ("" if s.models else ": none yet (each run keeps its own)"))
        for title in sorted(s.models):
            values = rules.settings(s.models[title])
            changed = ["%s=%s" % (k, values[k]) for k in sorted(rules.DEFAULTS) if values[k] != rules.DEFAULTS[k]]
            print("  %s: %s" % (title, ", ".join(changed) or "defaults"))
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

    try:
        overrides = parse_sets(a.set, rules.DEFAULTS)
    except ValueError as e:
        ap.error(str(e))
    if a.open_views:
        overrides["views"] = "open"
    if a.views_named is not None:
        overrides.update(views="name", name_filter=a.views_named)
    if a.clear_views or a.clear_model:
        overrides["clear"] = "model" if a.clear_model else "views"
    if a.create_types:
        overrides["create_types"] = True
    return _report(runner.run(a.cmd, overrides, a.reset))


if __name__ == "__main__":
    sys.exit(main())

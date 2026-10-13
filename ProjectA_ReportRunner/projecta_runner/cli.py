"""Command-line front end. `python -m projecta_runner <command> -h` for each command."""

import argparse
import os
import sys

from .runner import (Runner, RunInputs, export_files, guess_previous, log_time_saved,
                     today)
from .settings import DEFAULTS, Settings


def _inputs(a, s):
    base = a.base or s["base_dir"]
    pdfs, bcfs = export_files(os.path.join(base, a.export))
    prev = a.previous if a.previous is not None else (guess_previous(base, a.export) or "none")
    return RunInputs(base, a.export, a.acc_pdf or (pdfs[0] if pdfs else ""),
                     a.bcf or bcfs, None if a.issues == "all" else a.issues, prev)


def _report(res):
    print()
    for c in res.checks:
        print(c)
    if res.log_path:
        print("log: %s" % res.log_path)
    return 0 if res.ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="projecta_runner", description="ProjectA ACC issue-report runner")
    sub = ap.add_subparsers(dest="cmd")

    st = sub.add_parser("setup", help="show / link the local paths")
    st.add_argument("--set", action="append", default=[], metavar="KEY=PATH",
                    help="e.g. --set netbuild_root=D:\\Netbuild  (keys: %s)"
                    % ", ".join(k for k, v in DEFAULTS.items() if isinstance(v, str)))

    def run_args(p):
        p.add_argument("--base", help="BASE folder (default from settings)")
        p.add_argument("--export", required=True, help="new export folder, YYYYMMDD")
        p.add_argument("--acc-pdf", help="ACC 'Issue detail-...pdf' (default: found in the folder)")
        p.add_argument("--bcf", action="append", help="BCF file; repeat for each (default: all in the folder)")
        p.add_argument("--issues", default="all", help="'all' or the highest ACC id to include")
        p.add_argument("--previous", help="previous EXPORT folder (YYYYMMDD) or 'none' "
                                          "(default: the newest older dated folder)")

    run_args(sub.add_parser("extract", help="step 1: extract only (RUN_BUILD=False)"))
    sub.add_parser("pending", help="issues with no Studio note (walkthrough pending)")
    w = sub.add_parser("walk", help="any walkthrough command, e.g. walk -- note 1234 \"text\"")
    w.add_argument("args", nargs=argparse.REMAINDER)
    run_args(sub.add_parser("build", help="step 2: build only (RUN_EXTRACT=False)"))
    v = sub.add_parser("verify", help="step 4: verify the output folder")
    v.add_argument("folder", nargs="?", help="default: today's report folder in BASE")
    v.add_argument("--base")
    t = sub.add_parser("log-time", help="append the session to the time-saved log")
    t.add_argument("--export", default="")
    t.add_argument("--issues", default="")
    t.add_argument("--actual", type=float, required=True, help="minutes this session took")
    t.add_argument("--manual", type=float, help="minutes the manual process takes")
    t.add_argument("--notes", default="")
    sub.add_parser("gui", help="open the window (default)")

    a = ap.parse_args(argv)
    s = Settings()

    if a.cmd in (None, "gui"):
        from .gui import main as gui_main
        return gui_main()

    if a.cmd == "setup":
        for item in a.set:
            key, _, val = item.partition("=")
            if key not in DEFAULTS:
                ap.error("unknown setting %r" % key)
            s[key] = val
        if a.set:
            s.save()
            print("saved %s" % s.path)
        bad = 0
        for label, path, ok in s.check_paths():
            print("[%s] %-24s %s" % ("OK  " if ok else "MISS", label, path))
            bad += not ok
        return 1 if bad else 0

    r = Runner(s)

    if a.cmd in ("extract", "build"):
        inp = _inputs(a, s)
        problems = inp.problems()
        if problems:
            print("\n".join("[FAIL] " + p for p in problems))
            return 2
        if a.cmd == "build":
            locked = r.locked_pdfs(inp.base)
            if locked:
                print("These PDFs are open in a viewer -- close them, then run build again:")
                print("\n".join("  " + p for p in locked))
                return 3
        res = r.extract(inp) if a.cmd == "extract" else r.build(inp)
        code = _report(res)
        if a.cmd == "extract" and code == 0:
            print("\nNext: `pending` to list issues with no Studio note, then `build`.")
        return code

    if a.cmd == "pending":
        return _report(r.pending())

    if a.cmd == "walk":
        args = a.args[1:] if a.args[:1] == ["--"] else a.args
        return _report(r.walkthrough(args))

    if a.cmd == "verify":
        folder = a.folder or r.output_folder(a.base or s["base_dir"])
        if not folder:
            print("[FAIL] no %s report folder in BASE; pass the folder path" % today())
            return 2
        return _report(r.verify(folder))

    if a.cmd == "log-time":
        manual = a.manual if a.manual is not None else float(s["time_saved_manual_minutes"])
        row = {"date": today(), "task": s["time_saved_task"], "project": s["project_title"],
               "export": a.export, "issues": a.issues, "manual_minutes": manual,
               "actual_minutes": a.actual, "minutes_saved": manual - a.actual, "notes": a.notes}
        log_time_saved(s["time_saved_log"], row)
        print("logged to %s" % s["time_saved_log"])
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

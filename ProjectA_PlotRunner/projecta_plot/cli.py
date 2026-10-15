"""Command-line front end. `python -m projecta_plot <command> -h` for each command."""

import argparse
import os
import sys

from .runner import MODES, Job, Runner, Aborted, log_time_saved, static_checks, today
from .settings import DEFAULTS, SCRIPT_KEYS, Settings
from .sheets import SheetSpecError


def _report(res):
    print()
    for c in res.checks:
        print(c)
    if res.log_path:
        print("log: %s" % res.log_path)
    if res.info.get("summary_csv"):
        print("file list: %s" % res.info["summary_csv"])
    return 0 if res.ok else 1


def _sheet_spec(a):
    spec = a.sheets or ""
    if a.sheets_file:
        with open(a.sheets_file, "r", encoding="utf-8-sig") as f:
            spec = (spec + "\n" + f.read()).strip()
    return spec


def _job(a, s):
    job = Job(a.plot_root or s["plot_root"], a.out or today(), a.date or "", a.mode, _sheet_spec(a))
    problems = job.problems()
    if problems:
        raise SheetSpecError("\n".join(problems))
    return job


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ProjectAPlot", description="ProjectA Plot GA export runner (talks to Revit "
                                 "through the pyRevit MCP listener; your export scripts are never edited)")
    sub = ap.add_subparsers(dest="cmd")

    st = sub.add_parser("setup", help="show / link the local paths and check both export scripts")
    st.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="e.g. --set netbuild_root=D:\\Netbuild  (keys: %s)"
                    % ", ".join(k for k, v in DEFAULTS.items() if isinstance(v, str)))
    sub.add_parser("models", help="list the models open in Revit (and the active one)")
    c = sub.add_parser("check", help="is this model open in Revit?  e.g. check B001")
    c.add_argument("model")

    def job_args(p, model=True):
        if model:
            p.add_argument("model", help="SW00 | B001 ... B005 (names from settings)")
        p.add_argument("--date", help="revision date to match in \"Current Revision Date\"; any spelling "
                                      "(06-Sep-2026, 06/09/2026, 2026-09-06) -- the model's own format is "
                                      "found live")
        p.add_argument("--out", help="output folder name YYYYMMDD (default today)")
        p.add_argument("--plot-root", help="default from settings")
        p.add_argument("--mode", choices=sorted(MODES), default="pdf", help="pdf | cad | pdf+cad (default pdf)")
        p.add_argument("--sheets", help="single '210001', list '210001,210004;210007', or series "
                                        "'210001 to 210012' (Sheet Number, drawing number or its last field)")
        p.add_argument("--sheets-file", help="text file with the sheet list (one per line, or separated)")
        p.add_argument("--allow-missing", action="store_true",
                       help="export the listed sheets that were found even if some were not")

    job_args(sub.add_parser("dry", help="dry run: the exact sheets + filenames for one model"))
    job_args(sub.add_parser("export", help="export one model: PDFs first, then DWGs; verified on disk"))
    r = sub.add_parser("run", help="the full pass: each model in turn, waiting for you to open it")
    job_args(r, model=False)
    r.add_argument("--models", nargs="+", help="default: every model in settings, in order")
    v = sub.add_parser("verify", help="check the whole output folder on disk")
    v.add_argument("--out", help="YYYYMMDD (default today)")
    v.add_argument("--plot-root")
    v.add_argument("--mode", choices=sorted(MODES), default="pdf+cad")
    t = sub.add_parser("log-time", help="append the session to the time-saved log")
    t.add_argument("--out", default="")
    t.add_argument("--sheets", default="", help="number of sheets exported")
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
            if key not in DEFAULTS or not isinstance(DEFAULTS[key], str):
                ap.error("unknown setting %r" % key)
            s[key] = val
        if a.set:
            s.save()
            print("saved %s" % s.path)
        bad = 0
        for label, path, ok in s.check_paths():
            print("[%s] %-34s %s" % ("OK  " if ok else "MISS", label, path))
            bad += not ok
        for key, _ in SCRIPT_KEYS:
            if os.path.isfile(s.script(key)):
                for chk in static_checks(s.script(key), "master" if key == "master_script" else "podium"):
                    print(chk)
                    bad += chk.ok is False
        print("Revit listener: %s" % s["revit_url"])
        return 1 if bad else 0

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

    if a.cmd == "check":
        return _report(runner.check_model(s.model(a.model)))

    if a.cmd in ("dry", "export", "run"):
        try:
            job = _job(a, s)
            models = [s.model(m) for m in (a.models or [m["name"] for m in s["models"]])] \
                if a.cmd == "run" else [s.model(a.model)]
        except (SheetSpecError, KeyError, OSError) as e:
            print("[FAIL] %s" % e)
            return 2
        s.save_last(job.as_dict())
        print("BASE_OUTPUT_FOLDER = %s   |   %s   |   date %r   |   sheets: %s"
              % (job.out_dir, a.mode, job.date_text or None, job.sheet_spec or "all matching"))
        if a.cmd == "dry":
            return _report(runner.dry_run(models[0], job))
        if a.cmd == "export":
            return _report(runner.export(models[0], job, allow_unmatched=a.allow_missing))

        rows, failed = [], []
        for m in models:
            while True:
                ans = input("\nOpen %s in Revit. Press Enter when it is open  [s = skip, q = quit]: "
                            % m["name"]).strip().lower()
                if ans in ("s", "q"):
                    break
                chk = runner.check_model(m)
                _report(chk)
                if chk.ok:
                    break
            if ans == "q":
                break
            if ans == "s":
                print("skipped %s" % m["name"])
                continue
            res = runner.export(m, job, allow_unmatched=a.allow_missing)
            _report(res)
            rows.extend(res.info.get("files") or [])
            if not res.ok:
                failed.append(m["name"])
        code = _report(runner.verify_output(job.out_dir, a.mode, rows))
        print("\n%d file(s) verified this run; models needing attention: %s"
              % (sum(1 for r in rows if r["status"] == "OK"), ", ".join(failed) or "none"))
        return 1 if failed or code else 0

    if a.cmd == "verify":
        out = os.path.join(a.plot_root or s["plot_root"], a.out or today())
        return _report(runner.verify_output(out, a.mode))

    if a.cmd == "log-time":
        manual = a.manual if a.manual is not None else float(s["time_saved_manual_minutes"])
        log_time_saved(s["time_saved_log"], {
            "date": today(), "task": s["time_saved_task"], "project": s["project_title"], "export": a.out,
            "issues": a.sheets, "manual_minutes": manual, "actual_minutes": a.actual,
            "minutes_saved": manual - a.actual, "notes": a.notes})
        print("logged to %s" % s["time_saved_log"])
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

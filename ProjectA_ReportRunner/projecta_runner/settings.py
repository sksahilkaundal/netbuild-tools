"""Portable settings: settings.json next to the app, last inputs in last_run.json."""

import json
import os
import shutil
import sys

DEFAULTS = {
    # Python that runs the Netbuild scripts (needs their packages installed).
    # Empty = the Python running this app, or `py -3` / `python` when frozen.
    "python_exe": "",
    "netbuild_root": r"C:\SK\OneDrive\Netbuild",
    "pipeline_script": r"scripts\ProjectA_IssueReport_Pipeline.py",
    # Run by the pipeline itself; linked here only so Setup can check them.
    "extract_script": r"ProjectA_IssueExport_Extract.py",
    "build_script": r"ProjectA_IssueDetailReport_Build.py",
    "walkthrough_script": r"scripts\ProjectA_IssueWalkthrough.py",
    "verify_script": r"scripts\ProjectA_IssueReport_Verify.py",
    "base_dir": r"C:\SK\Projects\ProjectA\Issues\260914",
    "project_title": "ProjectF - Sports Boulevard ProjectA TOWER",
    # Arguments for "list issues with no Studio note" (no level range).
    "walkthrough_pending_args": ["pending"],
    # Extra pipeline globals set on every run (both steps).
    "extra_globals": {"BY_MODEL": True},
    # Report folder written by the build: <YYYYMMDD>_ProjectA_ACC Issue detail (Issues a-b)
    "report_folder_glob": "*_ProjectA_ACC Issue detail (Issues *)",
    "superseded_dir": "_superseded",
    # Time-saved log (CSV). Appended to; an existing header is respected.
    "time_saved_log": r"C:\SK\OneDrive\Netbuild\time_saved_log.csv",
    "time_saved_task": "ProjectA ACC Issue detail report",
    "time_saved_manual_minutes": 240,
}


PATH_KEYS = [
    ("pipeline_script", "Pipeline script"),
    ("extract_script", "Extract script"),
    ("build_script", "Build script"),
    ("walkthrough_script", "Walkthrough script"),
    ("verify_script", "Verify script"),
]


def app_dir():
    """Folder that holds the app (the .exe when frozen, else ProjectA_ReportRunner/)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts):
    """A file shipped with the app (inside the bundle when frozen)."""
    root = getattr(sys, "_MEIPASS", None) or app_dir()
    return os.path.join(root, *parts)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


class Settings(dict):
    def __init__(self, folder=None):
        self.folder = folder or app_dir()
        self.path = os.path.join(self.folder, "settings.json")
        merged = dict(DEFAULTS)
        merged.update(_read_json(self.path))
        super().__init__(merged)

    def save(self):
        _write_json(self.path, dict(self))

    def script(self, key):
        p = self[key]
        return p if os.path.isabs(p) else os.path.join(self["netbuild_root"], p)

    def check_paths(self):
        """[(label, path, ok)] for every local path the runner relies on."""
        rows = [("Netbuild folder", self["netbuild_root"], os.path.isdir(self["netbuild_root"]))]
        for key, label in PATH_KEYS:
            p = self.script(key)
            rows.append((label, p, os.path.isfile(p)))
        rows.append(("Issues BASE folder", self["base_dir"], os.path.isdir(self["base_dir"])))
        py = self.python_cmd()[0]
        rows.append(("Python", " ".join(self.python_cmd()),
                     os.path.isfile(py) or bool(shutil.which(py))))
        log = self["time_saved_log"]
        rows.append(("Time-saved log (folder)", log, os.path.isdir(os.path.dirname(log) or ".")))
        return rows

    def python_cmd(self):
        if self["python_exe"]:
            return [self["python_exe"]]
        if not getattr(sys, "frozen", False):
            exe = sys.executable
            console = os.path.join(os.path.dirname(exe), "python.exe")
            if os.path.basename(exe).lower() == "pythonw.exe" and os.path.isfile(console):
                exe = console
            return [exe]
        if os.name == "nt" and shutil.which("py"):
            return ["py", "-3"]
        return [shutil.which("python") or "python"]

    # last inputs, so the form reopens where it was left
    def load_last(self):
        return _read_json(os.path.join(self.folder, "last_run.json"))

    def save_last(self, data):
        try:
            _write_json(os.path.join(self.folder, "last_run.json"), data)
        except OSError:
            pass

    def logs_dir(self):
        d = os.path.join(self.folder, "logs")
        os.makedirs(d, exist_ok=True)
        return d

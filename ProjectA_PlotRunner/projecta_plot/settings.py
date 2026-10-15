"""Portable settings: settings.json next to the app, last inputs in last_run.json."""

import json
import os
import sys

DEFAULTS = {
    "netbuild_root": r"C:\Users\user\OneDrive - Studio\Documents\Claude",
    "master_script": r"scripts\export_master_ga_sheets_by_browser_filter.py",
    "podium_script": r"scripts\export_podium_sheets_by_revision.py",
    # BASE_OUTPUT_FOLDER = <plot_root>\<YYYYMMDD>
    "plot_root": r"C:\Users\user\OneDrive - Studio\Projects\ProjectA\Plot",
    # pyRevit MCP listener (same route the execute_revit_code MCP tool uses)
    "revit_url": "http://127.0.0.1:48884/revit_mcp/execute_code/",
    # Models in run order. `match`: any of these substrings in the Revit document
    # title binds the call to that model (a local file's title carries a _username suffix).
    "models": [
        {"name": "SW00", "kind": "master", "match": ["-SW0O-", "-SW00-"],
         "doc": "ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001"},
        {"name": "B001", "kind": "podium", "match": ["-B001-"],
         "doc": "ProjectC-Studio-BIM-B001-ZZZ-BM-950001"},
        {"name": "B002", "kind": "podium", "match": ["-B002-"],
         "doc": "ProjectC-Studio-BIM-B002-ZZZ-BM-950001"},
        {"name": "B003", "kind": "podium", "match": ["-B003-"],
         "doc": "ProjectC-Studio-BIM-B003-ZZZ-BM-950001"},
        {"name": "B004", "kind": "podium", "match": ["-B004-"],
         "doc": "ProjectC-Studio-BIM-B004-ZZZ-BM-950001"},
        {"name": "B005", "kind": "podium", "match": ["-B005-"],
         "doc": "ProjectC-Studio-BIM-B005-ZZZ-BM-950001"},
    ],
    # Watching the disk while Revit exports
    "poll_seconds": 3,
    "stall_seconds": 90,        # batch: no new/growing file for this long = stalled -> one sheet per call
    "settle_seconds": 15,       # after Revit answers, wait this long for the last file to land
    "sheet_timeout_seconds": 600,
    "batch_timeout_seconds": 7200,
    "probe_timeout_seconds": 300,
    # DWG export drops these next to the drawings; swept after each CAD batch
    # (only files written during that batch).
    "sweep_byproducts": True,
    "byproduct_patterns": ["FP_*.pat", "*.pcp", "*.jpg", "*.png"],
    # Time-saved log (CSV). Appended to; an existing header is respected.
    "time_saved_log": r"C:\Users\user\OneDrive - Studio\Documents\Claude\time_saved_log.csv",
    "time_saved_task": "ProjectA Plot GA export",
    "project_title": "ProjectF - Sports Boulevard ProjectA TOWER",
    "time_saved_manual_minutes": 240,
}

SCRIPT_KEYS = [("master_script", "Master (SW00) export script"),
               ("podium_script", "Podium (B001-B005) export script")]


def app_dir():
    """Folder that holds the app (the .exe when frozen, else ProjectA_PlotRunner/)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        merged = json.loads(json.dumps(DEFAULTS))
        merged.update(_read_json(self.path))
        super().__init__(merged)

    def save(self):
        _write_json(self.path, dict(self))

    def script(self, key):
        p = self[key]
        return p if os.path.isabs(p) else os.path.join(self["netbuild_root"], p)

    def model(self, name):
        for m in self["models"]:
            if m["name"].lower() == (name or "").lower():
                return m
        raise KeyError("unknown model %r (known: %s)" % (name, ", ".join(m["name"] for m in self["models"])))

    def model_script(self, model):
        return self.script("master_script" if model["kind"] == "master" else "podium_script")

    def check_paths(self):
        """[(label, path, ok)] for every local path the runner relies on."""
        rows = [("Netbuild folder", self["netbuild_root"], os.path.isdir(self["netbuild_root"]))]
        for key, label in SCRIPT_KEYS:
            p = self.script(key)
            rows.append((label, p, os.path.isfile(p)))
        rows.append(("Plot root folder", self["plot_root"], os.path.isdir(self["plot_root"])))
        log = self["time_saved_log"]
        rows.append(("Time-saved log (folder)", log, os.path.isdir(os.path.dirname(log) or ".")))
        return rows

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

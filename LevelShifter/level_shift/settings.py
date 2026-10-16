"""Portable settings: settings.json next to the app, last inputs in last_run.json."""

import json
import os
import sys

MAX_LEVELS = 10

DEFAULTS = {
    # pyRevit MCP listener (same route the execute_revit_code MCP tool and the ProjectA Plot Runner use)
    "revit_url": "http://127.0.0.1:48884/revit_mcp/execute_code/",
    # Revit document title must contain this text (comma-separated alternatives); blank = active model
    "model_match": "",
    "units": "mm",                  # mm | m -- what you type and what is shown
    # An element counts as "kept its position" when its bounding box min Z and max Z each moved
    # less than this.
    "tolerance_mm": 1.0,
    "correction_rounds": 4,         # measure -> correct rounds after the level move
    "move_fallback": True,          # an element with no offset parameter is moved back by (0, 0, -dz)
    "rollback_on_drift": True,      # Apply: if any element still moved, undo everything
    "probe_timeout_seconds": 300,
    "apply_timeout_seconds": 3600,
    "max_rows": 20000,              # element rows written to the CSV per run
}


def app_dir():
    """Folder that holds the app (the .exe when frozen, else LevelShifter/)."""
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

    def match(self):
        return [m.strip() for m in (self["model_match"] or "").split(",") if m.strip()]

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

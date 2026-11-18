"""Portable settings: settings.json next to the app.

The connection keys (DEFAULTS) apply to every run. The Stair Path settings (rules.DEFAULTS: text offsets,
tolerances, which views ...) are tuned per building, so they are kept per model title under "models" --
the same idea as the ribbon button, which keeps them per model in its pyRevit config.
"""

import json
import os
import sys

from . import rules

DEFAULTS = {
    # pyRevit MCP listener (same route the execute_revit_code MCP tool, Level Shift and the Plot Runner use)
    "revit_url": "http://127.0.0.1:48884/revit_mcp/execute_code/",
    # Revit document title must contain this text (comma-separated alternatives); blank = active model
    "model_match": "",
    "probe_timeout_seconds": 300,
    "apply_timeout_seconds": 3600,
    "max_rows": 20000,              # annotation rows returned / written to the CSV
}


def app_dir():
    """Folder that holds the app (the .exe when frozen, else StairPath/)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


class Settings(dict):
    def __init__(self, folder=None):
        self.folder = folder or app_dir()
        self.path = os.path.join(self.folder, "settings.json")
        data = _read_json(self.path)
        models = data.pop("models", {})
        merged = dict(DEFAULTS)
        merged.update((k, v) for k, v in data.items() if k in DEFAULTS)
        super().__init__(merged)
        self.models = models if isinstance(models, dict) else {}

    def save(self):
        data = dict(self)
        data["models"] = self.models
        _write_json(self.path, data)

    def match(self):
        return [m.strip() for m in (self["model_match"] or "").split(",") if m.strip()]

    def model_values(self, title, reset=False):
        """The Stair Path settings kept for this model (rules.DEFAULTS when none, or ``reset``)."""
        return rules.settings(None if reset else self.models.get(title))

    def keep_model_values(self, title, values):
        self.models[title] = dict((k, values[k]) for k in rules.DEFAULTS)

    def logs_dir(self):
        d = os.path.join(self.folder, "logs")
        os.makedirs(d, exist_ok=True)
        return d

"""Portable settings: settings.json next to the app (the .exe, or BuaUpdate/ when run from source)."""

import json
import os
import sys

from .engine import AUTO, RAW_NAME

# The project folder, first one that exists (the work PC's OneDrive, then the C:\SK copy).
DEFAULT_FOLDERS = [
    r"C:\Users\user\OneDrive - Studio\Projects\ProjectA\Excel\BUA - Overall With Assets For MEP Team",
    r"C:\SK\Projects\ProjectA\Excel\BUA - Overall With Assets For MEP Team",
]

DEFAULTS = {
    "folder": "",            # blank = the first DEFAULT_FOLDERS entry that exists
    "raw": "",               # blank = <folder>\Excel - Raw Area from RVT- Overall With Assets For MEP Team.xlsx
    "option1": "",           # blank = the one '*_with All Levels_Option 1.xlsx' in the folder
    "option2": "",           # blank = the one '*_Raw Levels Only_Option 2.xlsx' in the folder
    "typical": AUTO,         # auto | 2026-09 | 2026-07 -- the typical-floor set
    "backup": True,          # copy both workbooks to <folder>\Backup\<date_time>\ before writing
}


def app_dir():
    """Folder that holds the app (the .exe when frozen, else BuaUpdate/)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_folder(cwd=None, candidates=None):
    """The current folder when it holds the raw export, else the first existing DEFAULT_FOLDERS entry."""
    cwd = os.getcwd() if cwd is None else cwd
    if os.path.isfile(os.path.join(cwd, RAW_NAME)):
        return cwd
    for f in DEFAULT_FOLDERS if candidates is None else candidates:
        if os.path.isdir(f):
            return f
    return ""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class Settings(dict):
    def __init__(self, folder=None):
        self.dir = folder or app_dir()
        self.path = os.path.join(self.dir, "settings.json")
        merged = dict(DEFAULTS)
        merged.update(_read_json(self.path))
        super().__init__(merged)

    def project_folder(self):
        return self["folder"] or default_folder()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(self), f, indent=2)
        os.replace(tmp, self.path)

"""Find and start the Level Shift by Netbuild app for the "Level Shift App" button.  IronPython 2.7 + CPython 3."""

import os

from level_shift.about import PRODUCT

EXE = PRODUCT + ".exe"                  # "Level Shift by Netbuild.exe"
OLD_EXE = "LevelShifter.exe"            # 1.0 - 1.2 builds
EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # .../Netbuild.extension


def candidates(configured="", env=None):
    """Where LevelShifter.exe is looked for, in order."""
    env = os.environ if env is None else env
    out = []
    if configured:
        out.append(configured)
    local = env.get("LOCALAPPDATA")
    for name in (EXE, OLD_EXE):
        out.append(os.path.join(EXT_DIR, "bin", name))                    # shipped inside the extension
        if local:
            out.append(os.path.join(local, "Netbuild", "LevelShifter", name))
    return out


def find_exe(configured="", env=None):
    for p in candidates(configured, env):
        if p and os.path.isfile(p):
            return p
    return None


def args_line(model_title):
    """Command-line arguments: bind the window to the model the button was clicked from."""
    if not model_title:
        return ""
    return '--model "%s"' % model_title.replace('"', "")

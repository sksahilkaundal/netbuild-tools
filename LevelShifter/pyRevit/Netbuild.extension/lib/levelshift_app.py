"""Find and start LevelShifter.exe for the "Level Shifter App" button.  IronPython 2.7 + CPython 3."""

import os

EXE = "LevelShifter.exe"
EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # .../Netbuild.extension


def candidates(configured="", env=None):
    """Where LevelShifter.exe is looked for, in order."""
    env = os.environ if env is None else env
    out = []
    if configured:
        out.append(configured)
    out.append(os.path.join(EXT_DIR, "bin", EXE))                         # shipped inside the extension
    local = env.get("LOCALAPPDATA")
    if local:
        out.append(os.path.join(local, "Netbuild", "LevelShifter", EXE))
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

"""Find and start the BUA Update by Netbuild app for the "BUA Update" button.  IronPython 2.7 + CPython 3."""

import os

from bua_update.about import PRODUCT

EXE = PRODUCT + ".exe"                  # "BUA Update by Netbuild.exe"
EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # .../Netbuild.extension


def candidates(configured="", env=None):
    """Where the app is looked for, in order."""
    env = os.environ if env is None else env
    out = []
    if configured:
        out.append(configured)
    out.append(os.path.join(EXT_DIR, "bin", EXE))                        # shipped inside the extension
    local = env.get("LOCALAPPDATA")
    if local:
        out.append(os.path.join(local, "Netbuild", "BuaUpdate", EXE))
    return out


def find_exe(configured="", env=None):
    for p in candidates(configured, env):
        if p and os.path.isfile(p):
            return p
    return None

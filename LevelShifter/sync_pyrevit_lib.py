"""Copy the engine files the pyRevit buttons share with the exe into the extension's lib folder.

    python LevelShifter/sync_pyrevit_lib.py

Run it after changing any of SHARED; the tests fail while the copies differ.
"""

import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "level_shift")
DST = os.path.join(HERE, "pyRevit", "Netbuild.extension", "lib", "level_shift")
SHARED = ["__init__.py", "core.py", "payload.py", "units.py"]   # IronPython 2.7 + CPython 3

if __name__ == "__main__":
    os.makedirs(DST, exist_ok=True)
    for name in SHARED:
        shutil.copyfile(os.path.join(SRC, name), os.path.join(DST, name))
        print("copied %s" % name)

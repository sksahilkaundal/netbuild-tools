"""Copy the engine files the pyRevit button shares with the exe into the shared Netbuild.extension's lib folder.

    python ElementRemover/sync_pyrevit_lib.py

Run it after changing any of SHARED; the tests fail while the copies differ.
"""

import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "element_remover")
EXT = os.path.join(os.path.dirname(HERE), "LevelShifter", "pyRevit", "Netbuild.extension")   # the shared extension
DST = os.path.join(EXT, "lib", "element_remover")
SHARED = ["__init__.py", "about.py", "core.py", "payload.py"]   # IronPython 2.7 + CPython 3

if __name__ == "__main__":
    os.makedirs(DST, exist_ok=True)
    for name in SHARED:
        shutil.copyfile(os.path.join(SRC, name), os.path.join(DST, name))
        print("copied %s" % name)

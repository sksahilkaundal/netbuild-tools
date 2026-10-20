"""Smoke-test a frozen BuaUpdate.exe on a synthetic project folder (July raw, then a new item).

    python BuaUpdate/tests/smoke_exe.py BuaUpdate/dist/BuaUpdate.exe
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_bua_update as t  # noqa: E402

exe = os.path.abspath(sys.argv[1])
folder = t.project(t.JULY)
failed = False
try:
    for args, want_rc, want in ((["--version"], 0, "BUA Update by Netbuild " + t.__version__),
                                (["licence"], 0, "Netbuild Software Licence Agreement"),
                                (["check", "--folder", folder], 0, "Check only -- nothing written."),
                                (["update", "--folder", folder], 0, "ALL TOTALS TIE OUT - DONE")):
        p = subprocess.run([exe] + args, capture_output=True, text=True)
        print("$ BuaUpdate.exe %s  -> rc %d\n%s%s" % (" ".join(args), p.returncode, p.stdout[-3000:], p.stderr))
        failed |= p.returncode != want_rc or want not in p.stdout
    t.make_raw(os.path.join(folder, t.engine.RAW_NAME), t.JULY + [("Tower A", "37th Floor", "Residential-ser", 3, 3)])
    p = subprocess.run([exe, "update", "--folder", folder, "--no-backup"], capture_output=True, text=True)
    print("$ BuaUpdate.exe update (new item)  -> rc %d\n%s" % (p.returncode, p.stdout[-1500:]))
    failed |= p.returncode != 2 or "!!!  New Space/Room Cats: ser" not in p.stdout
finally:
    shutil.rmtree(folder, ignore_errors=True)
sys.exit(1 if failed else 0)

"""Smoke-test a frozen LevelShift.exe against the stand-in Revit from fake_revit.

    python LevelShifter/tests/smoke_exe.py LevelShifter/dist/LevelShift.exe
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_level_shift  # noqa: E402

exe = os.path.abspath(sys.argv[1])
fx = test_level_shift.Fixture("setUp")
fx.setUp()
settings = os.path.join(os.path.dirname(exe), "settings.json")
with open(settings, "w") as f:
    json.dump(dict(fx.s), f)

failed = False
try:
    for args in (["setup"], ["models"], ["levels"], ["plan", "--by", "L01=+300"],
                 ["trial", "--by", "L01=+300", "--to", "L02=6850"],
                 ["apply", "--by", "L01=+300", "--to", "L02=6850"]):
        p = subprocess.run([exe] + args, capture_output=True, text=True)
        print("$ LevelShift.exe %s  -> rc %d\n%s%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
        failed |= p.returncode != 0
    moved = fx.moved()
    print("L01 %s, L02 %s, elements that moved: %s" % (fx.elev("L01"), fx.elev("L02"), moved or "none"))
    failed |= (fx.elev("L01"), fx.elev("L02")) != (3800, 6850) or bool(moved)
finally:
    os.remove(settings)
    fx.tearDown()
sys.exit(1 if failed else 0)

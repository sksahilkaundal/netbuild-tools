"""Smoke-test a frozen ProjectA.exe against the stand-in scripts from test_runner.

    python ProjectA_ReportRunner/tests/smoke_exe.py ProjectA_ReportRunner/dist/ProjectA.exe
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_runner  # noqa: E402

exe = os.path.abspath(sys.argv[1])
fx = test_runner.Fixture("setUp")
fx.setUp()
settings = os.path.join(os.path.dirname(exe), "settings.json")
with open(settings, "w") as f:
    json.dump(dict(fx.s), f)

failed = False
try:
    for args in (["setup"], ["extract", "--export", "20261009"], ["pending"],
                 ["build", "--export", "20261009"], ["verify"]):
        p = subprocess.run([exe] + args, capture_output=True, text=True)
        print("$ ProjectA.exe %s  -> rc %d\n%s%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
        failed |= p.returncode != 0
finally:
    os.remove(settings)
    fx.tearDown()
sys.exit(1 if failed else 0)

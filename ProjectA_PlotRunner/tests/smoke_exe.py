"""Smoke-test a frozen ProjectAPlot.exe against the stand-in Revit from fake_revit.

    python ProjectA_PlotRunner/tests/smoke_exe.py ProjectA_PlotRunner/dist/ProjectAPlot.exe
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_plot  # noqa: E402

exe = os.path.abspath(sys.argv[1])
fx = test_plot.Fixture("setUp")
fx.setUp()
settings = os.path.join(os.path.dirname(exe), "settings.json")
with open(settings, "w") as f:
    json.dump(dict(fx.s), f)

failed = False
try:
    for args in (["setup"], ["models"], ["check", "SW00"],
                 ["export", "SW00", "--date", "06-Sep-2026", "--out", "20261015", "--mode", "pdf+cad"],
                 ["export", "B001", "--date", "06/09/2026", "--out", "20261015", "--mode", "pdf+cad",
                  "--sheets", "210001 to 210003, 230001"],
                 ["verify", "--out", "20261015", "--mode", "pdf+cad"]):
        p = subprocess.run([exe] + args, capture_output=True, text=True)
        print("$ ProjectAPlot.exe %s  -> rc %d\n%s%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
        failed |= p.returncode != 0
    files = sorted(test_plot.tree(fx.out))
    print("\n".join(files))
    failed |= len(files) != 16
finally:
    os.remove(settings)
    fx.tearDown()
sys.exit(1 if failed else 0)

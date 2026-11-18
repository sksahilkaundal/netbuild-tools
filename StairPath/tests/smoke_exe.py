"""Smoke-test a frozen StairPath.exe against the stand-in pyRevit MCP listener (fake_listener.py).

    python StairPath/tests/smoke_exe.py StairPath/dist/StairPath.exe
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_listener import FakeListener  # noqa: E402
from stair_path.settings import DEFAULTS  # noqa: E402

exe = os.path.abspath(sys.argv[1])
fake = FakeListener()
folder = os.path.dirname(exe)
settings = os.path.join(folder, "settings.json")
s = dict(DEFAULTS)
s["revit_url"] = fake.url
with open(settings, "w") as f:
    json.dump(s, f)

failed = False
try:
    for args in (["--version"], ["about"], ["license"], ["setup"], ["models"], ["plan"], ["trial"],
                 ["apply", "--set", "dir_y_mm=350"]):
        p = subprocess.run([exe] + args, capture_output=True, text=True)
        print("$ StairPath.exe %s  -> rc %d\n%s%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
        failed |= p.returncode != 0
    placed = len(fake.doc.paths())
    print("stair paths in the model after apply: %d (%s)" % (placed, fake.doc.group_result))
    failed |= fake.doc.group_result != "assimilated" or placed != 14
    with open(settings) as f:
        kept = json.load(f)["models"]["Tower_B001"]["dir_y_mm"]
    print("dir_y_mm kept for Tower_B001: %s" % kept)
    failed |= kept != 350.0
finally:
    os.remove(settings)
    fake.close()
sys.exit(1 if failed else 0)

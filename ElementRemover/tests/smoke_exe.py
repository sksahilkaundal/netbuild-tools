"""Smoke-test a frozen ElementRemover.exe against the stand-in Revit from fake_revit.

    python ElementRemover/tests/smoke_exe.py ElementRemover/dist/ElementRemover.exe
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_revit import FakeRevit  # noqa: E402
from element_remover.settings import DEFAULTS  # noqa: E402

exe = os.path.abspath(sys.argv[1])
fake = FakeRevit()
settings = os.path.join(os.path.dirname(exe), "settings.json")
s = dict(DEFAULTS)
s["revit_url"] = fake.url
with open(settings, "w") as f:
    json.dump(s, f)

failed = False
try:
    for args in (["--version"], ["about"], ["license"], ["setup"], ["models"], ["sources"],
                 ["plan", "--workset", "Demolition"], ["trial", "--workset", "Demolition"],
                 ["apply", "--workset", "Demolition", "--category", "Walls"]):
        p = subprocess.run([exe] + args, capture_output=True, text=True)
        print("$ ElementRemover.exe %s  -> rc %d\n%s%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
        failed |= p.returncode != 0
    left = [k for k in ("demo wall 1", "demo wall 2", "store wall 3") if fake.doc.alive(fake.el[k])]
    print("Demolition walls still in the model: %s" % (left or "none"))
    failed |= bool(left)
finally:
    os.remove(settings)
    fake.close()
sys.exit(1 if failed else 0)

"""Console entry point (ProjectA.exe): ProjectA setup | extract | pending | walk | build | verify | log-time."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from projecta_runner.cli import main  # noqa: E402

sys.exit(main())

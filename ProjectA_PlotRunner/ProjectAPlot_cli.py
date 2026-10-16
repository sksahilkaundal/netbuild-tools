"""Console entry point (ProjectAPlot.exe): setup | models | check | dry | export | run | verify | log-time | about | license."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from projecta_plot.cli import main  # noqa: E402

sys.exit(main())

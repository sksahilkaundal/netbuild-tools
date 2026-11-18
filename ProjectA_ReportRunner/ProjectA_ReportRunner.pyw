"""Window entry point (double-click, or ProjectA_ReportRunner.bat)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from projecta_runner.gui import main  # noqa: E402

main()

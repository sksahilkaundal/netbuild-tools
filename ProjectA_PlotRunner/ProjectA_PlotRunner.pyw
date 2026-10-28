"""Window entry point of Plot Runner by Netbuild (double-click, or ProjectA_PlotRunner.bat)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from projecta_plot.gui import main  # noqa: E402

main()

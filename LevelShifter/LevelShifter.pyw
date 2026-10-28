"""Window entry point (double-click, or LevelShifter.bat)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from level_shift.gui import main  # noqa: E402

main()

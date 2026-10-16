"""Console entry point (LevelShift.exe): setup | models | levels | plan | trial | apply | about | license."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from level_shift.cli import main  # noqa: E402

sys.exit(main())

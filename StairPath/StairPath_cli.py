"""Console entry point (StairPath.exe): setup | models | plan | trial | apply | about | license."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stair_path.cli import main  # noqa: E402

sys.exit(main())

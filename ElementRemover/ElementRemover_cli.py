"""Console entry point (ElementRemover.exe): setup | models | sources | plan | trial | apply | about | license."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from element_remover.cli import main  # noqa: E402

sys.exit(main())

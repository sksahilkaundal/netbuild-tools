# -*- coding: utf-8 -*-
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup_gui import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

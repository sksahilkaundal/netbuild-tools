# -*- coding: utf-8 -*-
"""Revit Status - entry stub. All logic lives in revitstatus_core (compiled to a .pyd for release)."""
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from revitstatus_core import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

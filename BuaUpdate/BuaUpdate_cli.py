"""Console entry point (BuaUpdate.exe): update | check | gui | about | license."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bua_update.cli import main  # noqa: E402

sys.exit(main())

"""Window entry point (double-click, or "BUA Update.bat")."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bua_update.gui import main  # noqa: E402

main()

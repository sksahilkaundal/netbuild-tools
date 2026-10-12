# -*- coding: utf-8 -*-
"""Entry stub for the Revit MCP Router bridge.

Source mode:  <extension venv python> revit_mcp_bridge.py   (imports bridge_core.py beside it)
Product mode: RevitMcpBridge.exe  (PyInstaller; bridge_core/nb_license/revit_mcp_router are compiled .pyd)
All logic lives in bridge_core.main().
"""
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bridge_core import main  # noqa: E402

sys.exit(main())

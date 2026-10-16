@echo off
rem Remote Router by Netbuild - serve Revit MCP Router by Netbuild to Claude on the web through a Cloudflare quick tunnel.
title Remote Router by Netbuild
cd /d "%~dp0"
set "PY=py -3.14"
if defined RMR_PYTHON set "PY=%RMR_PYTHON%"
if not exist "%LOCALAPPDATA%\RevitMcpRemote\remote.json" (
  echo First run: choose the passphrase you will type when Claude connects.
  %PY% revit_mcp_remote.py --setup || goto :end
)
%PY% revit_mcp_remote.py --tunnel quick %*
:end
pause

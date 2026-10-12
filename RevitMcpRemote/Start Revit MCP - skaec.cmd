@echo off
REM === Revit MCP Remote - one-click launcher for skaec.com ===
REM Double-click this to start the permanent tunnel + Revit slots.
REM Change SLOTS below for how many Revits you want to drive at once (1-10).

setlocal
set SLOTS=10
set DOMAIN=skaec.com
set TUNNEL=revit-mcp

cd /d "%~dp0"

title Revit MCP Remote (%SLOTS% slots - %DOMAIN%)
echo Starting Revit MCP Remote: %SLOTS% slots on %DOMAIN% ...
echo Leave this window OPEN while you work. Close it to stop.
echo.

py -3.14 revit_mcp_remote.py --tunnel named --tunnel-name %TUNNEL% --instances %SLOTS% --public-url "https://revit{n}.%DOMAIN%" --no-exec --no-log --state-dir "%USERPROFILE%\.rmr"

echo.
echo Revit MCP Remote has stopped.
pause

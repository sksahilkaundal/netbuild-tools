@echo off
rem Command line:  BuaUpdate update | check   [--folder DIR] [--typical auto, 2026-09 or 2026-07]   (-h for help)
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m bua_update %*
) else (
    python -m bua_update %*
)
exit /b %errorlevel%

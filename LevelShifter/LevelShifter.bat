@echo off
rem Double-click to open the Netbuild Level Shift window.
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 LevelShifter.pyw
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw LevelShifter.pyw
    exit /b 0
)
echo Python 3.9+ was not found on PATH.
echo Install it from python.org (tick "Add python.exe to PATH"), or use the .exe build.
pause

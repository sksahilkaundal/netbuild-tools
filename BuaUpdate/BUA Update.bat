@echo off
rem Double-click to open the BUA Update by Netbuild window.
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 BuaUpdate.pyw
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw BuaUpdate.pyw
    exit /b 0
)
echo Python 3.9+ was not found on PATH.
echo Install it from python.org (tick "Add python.exe to PATH") and run: py -3 -m pip install openpyxl
echo Or use the .exe build.
pause

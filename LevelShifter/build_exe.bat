@echo off
rem Optional: build LevelShifter.exe (window) and LevelShift.exe (command line).
rem Neither exe needs Python on the PC: they talk to Revit directly.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --windowed --name LevelShifter LevelShifter.pyw || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name LevelShift LevelShift_cli.py || goto :fail
echo.
echo Built dist\LevelShifter.exe and dist\LevelShift.exe -- copy them anywhere; settings.json and logs\ are created next to them.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

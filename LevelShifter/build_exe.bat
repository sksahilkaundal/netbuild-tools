@echo off
rem Optional: build "Level Shift by Netbuild.exe" (window) and LevelShift.exe (command line).
rem Neither exe needs Python on the PC: they talk to Revit directly.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 make_version_file.py version_window.txt "Level Shift by Netbuild.exe" || goto :fail
py -3 make_version_file.py version_cli.txt LevelShift.exe || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --windowed --name "Level Shift by Netbuild" --version-file version_window.txt LevelShifter.pyw || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name LevelShift --version-file version_cli.txt LevelShift_cli.py || goto :fail
echo.
echo Built "dist\Level Shift by Netbuild.exe" and dist\LevelShift.exe -- copy them anywhere; settings.json and logs\ are created next to them.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

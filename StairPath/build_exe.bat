@echo off
rem Optional: build StairPath.exe (command line). It needs no Python on the PC: it talks to Revit directly.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 make_version_file.py version_cli.txt StairPath.exe || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name StairPath --version-file version_cli.txt StairPath_cli.py || goto :fail
echo.
echo Built dist\StairPath.exe -- copy it anywhere; settings.json and logs\ are created next to it.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

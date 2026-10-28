@echo off
rem Optional: build ElementRemover.exe (command line). It needs no Python on the PC: it talks to Revit directly.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 make_version_file.py version_cli.txt ElementRemover.exe || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name ElementRemover --version-file version_cli.txt ElementRemover_cli.py || goto :fail
echo.
echo Built dist\ElementRemover.exe -- copy it anywhere; settings.json and logs\ are created next to it.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

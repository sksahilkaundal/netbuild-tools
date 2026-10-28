@echo off
rem Optional: build "BUA Update by Netbuild.exe" (window) and BuaUpdate.exe (command line).
rem Neither exe needs Python on the PC.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller openpyxl || goto :fail
py -3 make_version_file.py version_window.txt "BUA Update by Netbuild.exe" || goto :fail
py -3 make_version_file.py version_cli.txt BuaUpdate.exe || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --windowed --name "BUA Update by Netbuild" --version-file version_window.txt BuaUpdate.pyw || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name BuaUpdate --version-file version_cli.txt BuaUpdate_cli.py || goto :fail
echo.
echo Built "dist\BUA Update by Netbuild.exe" and dist\BuaUpdate.exe -- copy them anywhere; settings.json is created next to them.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

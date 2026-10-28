@echo off
rem Optional: build ProjectA_ReportRunner.exe (window) and ProjectA.exe (command line).
rem No Python is needed to OPEN the app.
rem The Netbuild scripts still run with your Python -- link it on the Setup tab.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --windowed --name ProjectA_ReportRunner ^
    --add-data "projecta_runner\overrides.py;projecta_runner" ProjectA_ReportRunner.pyw || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name ProjectA ^
    --add-data "projecta_runner\overrides.py;projecta_runner" ProjectA_cli.py || goto :fail
echo.
echo Built dist\ProjectA_ReportRunner.exe and dist\ProjectA.exe -- copy them anywhere; settings.json and logs\ are created next to it.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

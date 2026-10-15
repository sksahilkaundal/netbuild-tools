@echo off
rem Optional: build ProjectA_PlotRunner.exe (window) and ProjectAPlot.exe (command line).
rem Neither exe needs Python on the PC: they talk to Revit directly.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --windowed --name ProjectA_PlotRunner ProjectA_PlotRunner.pyw || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name ProjectAPlot ProjectAPlot_cli.py || goto :fail
echo.
echo Built dist\ProjectA_PlotRunner.exe and dist\ProjectAPlot.exe -- copy them anywhere; settings.json and logs\ are created next to them.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

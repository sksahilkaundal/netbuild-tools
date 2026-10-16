@echo off
rem Optional: build "Plot Runner by Netbuild.exe" (window) and ProjectAPlot.exe (command line),
rem both with the Windows version resource (Properties > Details) from projecta_plot\about.py.
rem Neither exe needs Python on the PC: they talk to Revit directly.
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 make_version_file.py version_window.txt "Plot Runner by Netbuild.exe" || goto :fail
py -3 make_version_file.py version_cli.txt ProjectAPlot.exe || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --windowed --name "Plot Runner by Netbuild" --version-file version_window.txt ProjectA_PlotRunner.pyw || goto :fail
py -3 -m PyInstaller --noconfirm --onefile --console --name ProjectAPlot --version-file version_cli.txt ProjectAPlot_cli.py || goto :fail
copy /y ..\LICENSE dist\LICENSE >nul || goto :fail
echo.
echo Built "dist\Plot Runner by Netbuild.exe" and dist\ProjectAPlot.exe (+ LICENSE) -- copy them anywhere; settings.json and logs\ are created next to them.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1

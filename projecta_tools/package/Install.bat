@echo off
rem Installs ProjectA Tools for the CURRENT USER only -- no admin rights needed.
rem Copies this package to %LOCALAPPDATA%\ProjectA_Tools, unblocks it, adds Start menu + Desktop
rem shortcuts and runs the environment check. Your settings, logs and newer Netbuild edits are kept.
setlocal
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\ProjectA_Tools"
if not exist "%SRC%runtime\python.exe" (
  echo !!! runtime\python.exe is missing next to Install.bat -- unzip the WHOLE package first.
  pause
  exit /b 1
)
"%SRC%runtime\python.exe" "%SRC%app\projecta_install.py" install
if errorlevel 1 (
  pause
  exit /b 1
)
echo.
"%DEST%\runtime\python.exe" "%DEST%\app\projecta_launcher.py" check
echo.
echo Start "ProjectA Issue Report" from the Start menu / Desktop, or run:
echo    "%DEST%\ProjectA Issue Report.bat"
pause
exit /b 0

@echo off
rem Removes ProjectA Tools for the current user. Your ProjectA project data (BASE, reports, notes CSVs) is never touched.
setlocal
set "DEST=%LOCALAPPDATA%\ProjectA_Tools"
echo This removes "%DEST%" (portable Python, launcher, bundled scripts) and the shortcuts.
echo Your ProjectA project folders (BASE, reports, notes CSVs) are NOT touched.
set "ANS="
set /p "ANS=Uninstall now? (Y/N): "
if /i not "%ANS%"=="Y" exit /b 0
set "WIPE="
set /p "WIPE=Also delete your launcher settings and logs (%DEST%\user)? (Y/N): "
if exist "%DEST%\runtime\python.exe" "%DEST%\runtime\python.exe" "%DEST%\app\projecta_install.py" remove-shortcuts
cd /d "%TEMP%"
for %%D in (runtime app Netbuild) do rd /s /q "%DEST%\%%D" 2>nul
for %%F in ("ProjectA Issue Report.bat" "README.md" "VERSION.txt") do del "%DEST%\%%~F" 2>nul
if /i "%WIPE%"=="Y" rd /s /q "%DEST%\user" 2>nul
echo Uninstalled.
(goto) 2>nul & del "%DEST%\Uninstall.bat" & rd "%DEST%" 2>nul

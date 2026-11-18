@echo off
rem ProjectA Issue Report -- portable launcher (no admin rights, no system Python needed).
rem   double-click            -> menu
rem   "ProjectA Issue Report.bat" check | extract | pending | build | verify | spotcheck | all | walk ...
setlocal
set "HERE=%~dp0"
set "PY=%HERE%runtime\python.exe"
if not exist "%PY%" (
  echo Portable Python not found: "%PY%"
  echo Unzip the whole ProjectA_Tools package, or run Install.bat again.
  pause
  exit /b 1
)
title ProjectA Issue Report
"%PY%" "%HERE%app\projecta_launcher.py" %*
set "RC=%ERRORLEVEL%"
if "%~1"=="" if not "%RC%"=="0" pause
exit /b %RC%

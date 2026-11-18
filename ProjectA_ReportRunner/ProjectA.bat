@echo off
rem Command line:  ProjectA setup | extract | pending | walk | build | verify | log-time   (-h for help)
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m projecta_runner %*
) else (
    python -m projecta_runner %*
)
exit /b %errorlevel%

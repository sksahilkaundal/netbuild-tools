@echo off
rem Command line:  ProjectAPlot setup | models | check | dry | export | run | verify | log-time   (-h for help)
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m projecta_plot %*
) else (
    python -m projecta_plot %*
)
exit /b %errorlevel%

@echo off
rem Command line:  LevelShift setup | models | levels | plan | trial | apply   (-h for help)
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m level_shift %*
) else (
    python -m level_shift %*
)
exit /b %errorlevel%

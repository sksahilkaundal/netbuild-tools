@echo off
rem Command line:  StairPath setup | models | plan | trial | apply | about | license   (-h for help)
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m stair_path %*
) else (
    python -m stair_path %*
)
exit /b %errorlevel%

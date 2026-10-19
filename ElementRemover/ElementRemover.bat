@echo off
rem Command line:  ElementRemover setup | models | sources | plan | trial | apply | about | license   (-h for help)
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m element_remover %*
) else (
    python -m element_remover %*
)
exit /b %errorlevel%

@echo off
rem Desktop Commander needs Node.js (the plugin starts "npx -y @wonderwhy-er/desktop-commander@latest").
rem No admin rights here, so this installs the official portable Node.js zip per user:
rem see install_node_portable.ps1 next to this file. Launch from Explorer:
rem   explorer.exe "C:\SK\OneDrive\Netbuild\scripts\install_desktop_commander.cmd"
title Install Node.js (per user) + Desktop Commander
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_node_portable.ps1"
echo.
echo Log: %~dp0install_desktop_commander.log
echo When it says OK, restart the Claude app so the Desktop Commander plugin connects.
pause

@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all-websites.ps1" %*
if errorlevel 1 pause
endlocal

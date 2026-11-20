@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-managed-services.ps1"
if errorlevel 1 pause

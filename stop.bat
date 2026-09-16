@echo off
REM Stop the AuricTerminal backend.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
pause

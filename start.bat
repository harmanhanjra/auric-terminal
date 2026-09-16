@echo off
REM AuricTerminal launcher — double-click to start. Add -KeepAlive to auto-restart on crash.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*

@echo off
setlocal
cd /d "%~dp0"
title Migrar datos a ASGARD v6.2
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0MIGRAR_DATOS_PORTABLES.ps1"
echo.
pause

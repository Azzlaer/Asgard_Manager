@echo off
cd /d "%~dp0"
if exist "%~dp0ASGARD_Service_Control.exe" (
    "%~dp0ASGARD_Service_Control.exe" stop
) else if exist "%~dp0python.exe" (
    "%~dp0python.exe" "%~dp0service_control.py" stop
) else (
    python "%~dp0service_control.py" stop
)
pause

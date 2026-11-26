@echo off
cd /d "%~dp0"
if exist "%~dp0ASGARD_Host_Manager.exe" (
    start "" "%~dp0ASGARD_Host_Manager.exe"
    exit /b 0
)
if exist "%~dp0pythonw.exe" (
    start "" "%~dp0pythonw.exe" "%~dp0manager_gui.py"
) else (
    start "" pythonw "%~dp0manager_gui.py"
)

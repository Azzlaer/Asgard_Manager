@echo off
cd /d "%~dp0"
if not exist "%~dp0Library\Mods" mkdir "%~dp0Library\Mods"
if not exist "%~dp0Library\Configs" mkdir "%~dp0Library\Configs"
start "" explorer.exe "%~dp0Library"

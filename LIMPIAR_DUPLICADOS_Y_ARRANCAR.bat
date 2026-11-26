@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ASGARD - Limpieza total de procesos Valheim

echo ============================================================
echo  ASGARD R10 - LIMPIEZA DE SERVIDORES DUPLICADOS
echo ============================================================
echo.
echo ADVERTENCIA: este proceso apagara TODOS los valheim_server.exe
echo de esta computadora. No borra mundos, configuraciones ni backups.
echo.
choice /C SN /N /M "Continuar [S/N]? "
if errorlevel 2 exit /b 0

echo.
echo [1/4] Deteniendo servicio ASGARD...
if exist "%~dp0ASGARD_Service_Control.exe" (
    "%~dp0ASGARD_Service_Control.exe" stop
) else if exist "%~dp0python.exe" (
    "%~dp0python.exe" "%~dp0service_control.py" stop
) else (
    python "%~dp0service_control.py" stop
)

echo [2/4] Cerrando todos los procesos valheim_server.exe...
taskkill /F /T /IM valheim_server.exe >nul 2>&1

echo [3/4] Esperando liberacion de procesos y puertos...
timeout /t 4 /nobreak >nul

echo [4/4] Iniciando servicio ASGARD R10...
if exist "%~dp0ASGARD_Service_Control.exe" (
    "%~dp0ASGARD_Service_Control.exe" start
) else if exist "%~dp0python.exe" (
    "%~dp0python.exe" "%~dp0service_control.py" start
) else (
    python "%~dp0service_control.py" start
)

echo.
echo Limpieza terminada. ASGARD reconstruira los PID desde los procesos reales.
echo Los servidores con Auto inicio activado arrancaran una sola vez.
pause

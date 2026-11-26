@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ASGARD - Detectar servidor Valheim
echo ============================================================
echo  ASGARD - CONFIGURACION AUTOMATICA DE RUTAS
echo ============================================================
echo.
echo Solo selecciona la carpeta que contiene valheim_server.exe.
echo ASGARD detectara Managed, modulos Unity, BepInEx\core y Jotunn.dll.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Tools\configurar_rutas_valheim.ps1"
if errorlevel 1 (
  echo.
  echo ERROR DE CONFIGURACION. Revisa el mensaje anterior.
  pause
  exit /b 1
)
echo.
if /i not "%~1"=="/nopause" pause
exit /b 0

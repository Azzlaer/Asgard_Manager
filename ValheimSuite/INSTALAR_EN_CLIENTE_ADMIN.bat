@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ASGARD - Instalar panel en cliente administrador
if not exist "Dist\AdminClient\AsgardCore.dll" (
  echo ERROR: No existen las DLL compiladas en Dist\AdminClient.
  echo Ejecuta CONFIGURAR_Y_COMPILAR.bat primero.
  pause
  exit /b 1
)
set "ENHANCED="
if exist "Dist\EnhancedShared\AsgardVoidAvatarClient.dll" (
  choice /m "Instalar tambien el Avatar Enhanced en este cliente"
  if errorlevel 2 goto install
  set "ENHANCED=-Enhanced"
)
:install
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Tools\instalar_mods_asgard.ps1" -Target client %ENHANCED%
if errorlevel 1 (
  echo.
  echo ERROR DE INSTALACION. Revisa el mensaje anterior.
  pause
  exit /b 1
)
echo.
pause

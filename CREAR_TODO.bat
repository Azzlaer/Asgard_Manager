@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ASGARD SERVER SUITE v7.0 R7 - COMPILACION COMPLETA
echo ============================================================
call CREAR_EXE_PORTABLE.bat
if errorlevel 1 exit /b 1
echo.
choice /m "Deseas compilar tambien las DLL de Valheim ahora"
if errorlevel 2 exit /b 0
pushd ValheimSuite
call CONFIGURAR_Y_COMPILAR.bat
popd

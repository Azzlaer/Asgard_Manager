@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call CONFIGURAR_RUTAS.bat /nopause
if errorlevel 1 exit /b 1
call BUILD_ALL.bat
if errorlevel 1 exit /b %errorlevel%
echo.
choice /m "Instalar ahora las DLL en el servidor seleccionado"
if errorlevel 2 exit /b 0
call INSTALAR_EN_SERVIDOR.bat
exit /b %errorlevel%

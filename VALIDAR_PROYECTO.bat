@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Validar ASGARD Server Suite v7.0 R7

where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY set "PY=python"

%PY% -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: No se encontro Python 3.10 o posterior.
  echo Instala Python y marca la opcion Add Python to PATH.
  pause
  exit /b 1
)

%PY% "%CD%\Tools\validar_proyecto.py"
if errorlevel 1 goto :error

pause
exit /b 0

:error
echo.
echo ERROR DE VALIDACION. Revisa el mensaje anterior.
pause
exit /b 1

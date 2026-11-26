@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Compilar ASGARD Host Manager v7.0.10.1 Logo Resource Fix

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: No se encontro Python 3.11 o posterior.
  pause
  exit /b 1
)

echo Validando proyecto antes de compilar...
%PY% "%CD%\Tools\validar_proyecto.py"
if errorlevel 1 goto :error

echo [1/6] Preparando entorno aislado...
if not exist "%CD%\_build_venv\Scripts\python.exe" %PY% -m venv "%CD%\_build_venv"
if errorlevel 1 goto :error
set "VPY=%CD%\_build_venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto :error
"%VPY%" -m pip install -r "requirements\requirements-build.txt"
if errorlevel 1 goto :error

set "BUILDROOT=%CD%\_exe_build"
set "BIN=%BUILDROOT%\bin"
set "RELEASE=%CD%\dist\AsgardHostManager_v7_0_Crimson_Void_R10_1_LogoResourceFix"
if exist "%BUILDROOT%" rmdir /s /q "%BUILDROOT%"
mkdir "%BIN%"
mkdir "%BUILDROOT%\spec_panel"
mkdir "%BUILDROOT%\spec_service"
mkdir "%BUILDROOT%\spec_control"
mkdir "%BUILDROOT%\spec_agent"

echo [2/6] Compilando panel grafico...
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name ASGARD_Host_Manager ^
 --add-data "%CD%\Assets\void_avatar_user.png;Assets" ^
 --distpath "%BIN%" --workpath "%BUILDROOT%\work_panel" --specpath "%BUILDROOT%\spec_panel" asgard_panel.py
if errorlevel 1 goto :error

echo [3/6] Compilando servicio local...
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name ASGARD_Service ^
 --distpath "%BIN%" --workpath "%BUILDROOT%\work_service" --specpath "%BUILDROOT%\spec_service" asgard_service.py
if errorlevel 1 goto :error

echo [4/6] Compilando controlador...
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --console --name ASGARD_Service_Control ^
 --distpath "%BIN%" --workpath "%BUILDROOT%\work_control" --specpath "%BUILDROOT%\spec_control" service_control.py
if errorlevel 1 goto :error

echo [5/6] Compilando agente remoto...
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name ASGARD_Remote_Agent ^
 --distpath "%BIN%" --workpath "%BUILDROOT%\work_agent" --specpath "%BUILDROOT%\spec_agent" asgard_remote_agent.py
if errorlevel 1 goto :error

echo [6/6] Creando carpeta portable sin xcopy...
"%VPY%" "%CD%\Tools\crear_portable.py" --root "%CD%" --bin "%BIN%" --release "%RELEASE%"
if errorlevel 1 goto :error

echo.
echo ============================================================
echo ASGARD v7.0.10.1 LOGO RESOURCE FIX COMPILADO
echo ============================================================
echo Carpeta: %RELEASE%
echo Abre ASGARD_Host_Manager.exe
explorer "%RELEASE%"
pause
exit /b 0

:error
echo.
echo ERROR: La compilacion no termino. No se modifico la version anterior.
pause
exit /b 1

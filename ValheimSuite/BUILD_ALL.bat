@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title ASGARD - Compilar DLL de Valheim R6
where dotnet >nul 2>&1 || (echo ERROR: instala .NET SDK 8 y vuelve a intentar.& pause & exit /b 1)

if not exist UserPaths.props (
  echo No existe UserPaths.props. Iniciando deteccion automatica...
  call CONFIGURAR_RUTAS.bat /nopause
  if errorlevel 1 exit /b 1
)

for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "([xml](Get-Content -Raw UserPaths.props)).Project.PropertyGroup.BuildEnhanced"`) do set "BUILD_ENHANCED=%%A"
if not defined BUILD_ENHANCED set "BUILD_ENHANCED=false"

if exist Dist rmdir /s /q Dist
mkdir Dist\ServerBase
mkdir Dist\EnhancedShared
mkdir Dist\AdminClient

for %%P in (AsgardCore AsgardAudit AsgardPunisherServer AsgardMasterUI) do (
  echo.
  echo Compilando %%P...
  dotnet build "%%P\%%P.csproj" -c Release
  if errorlevel 1 goto :error
)

rem Copiar inmediatamente los modulos base ya validados.
copy /y AsgardCore\bin\Release\net472\AsgardCore.dll Dist\ServerBase\ >nul
copy /y AsgardAudit\bin\Release\net472\AsgardAudit.dll Dist\ServerBase\ >nul
copy /y AsgardPunisherServer\bin\Release\net472\AsgardPunisherServer.dll Dist\ServerBase\ >nul
copy /y AsgardCore\bin\Release\net472\AsgardCore.dll Dist\AdminClient\ >nul
copy /y AsgardMasterUI\bin\Release\net472\AsgardMasterUI.dll Dist\AdminClient\ >nul

if /i "!BUILD_ENHANCED!"=="true" (
  echo.
  echo Compilando AsgardVoidAvatarClient...
  dotnet build "AsgardVoidAvatarClient\AsgardVoidAvatarClient.csproj" -c Release
  if errorlevel 1 goto :enhanced_error
  copy /y AsgardVoidAvatarClient\bin\Release\net472\AsgardVoidAvatarClient.dll Dist\EnhancedShared\ >nul
  ) else (
  echo.
  echo AVISO: Jotunn.dll no fue encontrado. Se omitira AsgardVoidAvatarClient.
  >"Dist\EnhancedShared\JOTUNN_NO_ENCONTRADO.txt" echo Instala Jotunn en BepInEx\plugins y vuelve a ejecutar CONFIGURAR_RUTAS.bat para compilar el Avatar Enhanced.
)

echo.
echo ============================================================
echo  COMPILACION COMPLETA R6
echo ============================================================
echo - Dist\ServerBase: servidor siempre.
echo - Dist\AdminClient: Core + panel F8; NO requiere Jotunn.
echo - Dist\EnhancedShared: Avatar Enhanced separado; requiere Jotunn.
if /i "!BUILD_ENHANCED!"=="true" echo - Dist\EnhancedShared: servidor y TODOS los clientes para modo Enhanced.
if /i not "!BUILD_ENHANCED!"=="true" echo - Enhanced omitido porque Jotunn.dll no fue encontrado.
echo.
pause
exit /b 0

:enhanced_error
echo.
echo ERROR al compilar el Avatar Enhanced.
echo ServerBase y AdminClient SI quedaron disponibles en Dist.
echo Revisa el primer error CS y vuelve a ejecutar despues de corregirlo.
>"Dist\EnhancedShared\ERROR_COMPILACION_ENHANCED.txt" echo El Avatar Enhanced no compilo. ServerBase y AdminClient fueron generados correctamente.
pause
exit /b 1

:error
echo.
echo Error de compilacion de una DLL base de ASGARD.
echo Las rutas ya fueron detectadas automaticamente. Revisa el primer error CS mostrado arriba.
echo Si el error menciona un ensamblado faltante, ejecuta CONFIGURAR_RUTAS.bat para verificar la instalacion del servidor.
pause
exit /b 1

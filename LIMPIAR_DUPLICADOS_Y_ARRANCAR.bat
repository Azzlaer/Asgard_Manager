@echo off
cd /d "%~dp0"
echo ASGARD - Diagnostico seguro de duplicados
echo No se cerraran procesos de Valheim automaticamente.
call "%~dp0DIAGNOSTICAR_SERVIDORES_DUPLICADOS.bat"
echo Abre ASGARD y selecciona el servidor afectado.
echo Usa Detener y luego Iniciar solo en esa instancia.
pause

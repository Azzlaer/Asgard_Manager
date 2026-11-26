$ErrorActionPreference = "SilentlyContinue"
$items = Get-CimInstance Win32_Process -Filter "Name='valheim_server.exe'" |
    Select-Object ProcessId, CreationDate, CommandLine
if (-not $items) {
    Write-Host "No hay procesos valheim_server.exe activos." -ForegroundColor Yellow
    exit 0
}
Write-Host "Procesos Valheim activos:" -ForegroundColor Cyan
$items | Sort-Object CreationDate | Format-Table -Wrap -AutoSize
Write-Host ""
Write-Host "No cierres un PID al azar si hay jugadores conectados." -ForegroundColor Yellow
Write-Host "Compara el PID con la columna PID del panel ASGARD." -ForegroundColor Yellow

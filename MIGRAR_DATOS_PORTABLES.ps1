$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

$newRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Selecciona la carpeta de ASGARD v5.4/v6.0/v6.1 que contiene Data y Library'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Host 'Migracion cancelada.'
    exit 0
}
$oldRoot = [System.IO.Path]::GetFullPath($dialog.SelectedPath)
$newRoot = [System.IO.Path]::GetFullPath($newRoot)
if ($oldRoot.TrimEnd('\') -ieq $newRoot.TrimEnd('\')) {
    throw 'La carpeta anterior y la nueva son la misma.'
}
if (-not (Test-Path -LiteralPath (Join-Path $oldRoot 'Data'))) {
    throw "La carpeta seleccionada no contiene Data: $oldRoot"
}

$controller = Join-Path $newRoot 'ASGARD_Service_Control.exe'
if (Test-Path -LiteralPath $controller) {
    try { & $controller stop | Out-Host } catch { Write-Warning $_ }
    Start-Sleep -Seconds 2
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$newData = Join-Path $newRoot 'Data'
if (Test-Path -LiteralPath (Join-Path $newData 'asgard_host.db')) {
    $safety = Join-Path $newRoot ("Data_before_migration_" + $stamp)
    Copy-Item -LiteralPath $newData -Destination $safety -Recurse -Force
    Write-Host "Respaldo de seguridad: $safety"
}

function Copy-Tree([string]$source, [string]$destination) {
    if (-not (Test-Path -LiteralPath $source)) { return }
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    & robocopy $source $destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /XJ /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Robocopy fallo con codigo $LASTEXITCODE copiando $source" }
}

Copy-Tree (Join-Path $oldRoot 'Data') (Join-Path $newRoot 'Data')
Copy-Tree (Join-Path $oldRoot 'Library') (Join-Path $newRoot 'Library')
Copy-Tree (Join-Path $oldRoot 'RemoteDownloads') (Join-Path $newRoot 'RemoteDownloads')

Write-Host ''
Write-Host 'MIGRACION COMPLETADA.' -ForegroundColor Green
Write-Host "Origen:  $oldRoot"
Write-Host "Destino: $newRoot"
Write-Host 'Ahora abre ASGARD_Host_Manager.exe.'

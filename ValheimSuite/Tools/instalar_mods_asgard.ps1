param(
    [ValidateSet("server", "client")]
    [string]$Target,
    [switch]$Enhanced,
    [string]$TargetRoot = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $scriptRoot "Dist"

function Select-Root([string]$Description) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $Description
    $dialog.ShowNewFolderButton = $false
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        return $dialog.SelectedPath
    }
    return ""
}

function Read-ConfiguredServerRoot {
    $propsPath = Join-Path $scriptRoot "UserPaths.props"
    if (-not (Test-Path -LiteralPath $propsPath -PathType Leaf)) { return "" }
    try {
        $xml = [xml](Get-Content -LiteralPath $propsPath -Raw)
        return [string]$xml.Project.PropertyGroup.ValheimServerRoot
    } catch { return "" }
}

function Resolve-TargetRoot {
    $candidate = $TargetRoot.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($candidate) -and $Target -eq "server") {
        $candidate = Read-ConfiguredServerRoot
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $description = if ($Target -eq "server") {
            "Selecciona la carpeta que contiene valheim_server.exe"
        } else {
            "Selecciona la carpeta que contiene valheim.exe"
        }
        $candidate = Select-Root $description
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) { throw "No se selecciono ninguna carpeta." }
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { throw "La carpeta no existe: $candidate" }
    $exe = if ($Target -eq "server") { "valheim_server.exe" } else { "valheim.exe" }
    if (-not (Test-Path -LiteralPath (Join-Path $candidate $exe) -PathType Leaf)) {
        throw "No se encontro $exe en: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Copy-DllSet([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "No existe la salida compilada: $Source. Ejecuta CONFIGURAR_Y_COMPILAR.bat primero."
    }
    $dlls = @(Get-ChildItem -LiteralPath $Source -Filter "*.dll" -File)
    if ($dlls.Count -eq 0) { throw "No hay DLL en: $Source" }
    foreach ($dll in $dlls) {
        Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $Destination $dll.Name) -Force
        Write-Host ("  + " + $dll.Name) -ForegroundColor Green
    }
}

$root = Resolve-TargetRoot
$pluginsRoot = Join-Path $root "BepInEx\plugins"
if (-not (Test-Path -LiteralPath $pluginsRoot -PathType Container)) {
    throw "No existe BepInEx\plugins en: $root. Instala BepInEx primero."
}

$destination = Join-Path $pluginsRoot "ASGARD"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (Test-Path -LiteralPath $destination -PathType Container) {
    $existing = @(Get-ChildItem -LiteralPath $destination -Filter "Asgard*.dll" -File -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        $backup = Join-Path $pluginsRoot ("ASGARD_Backup_" + $timestamp)
        New-Item -ItemType Directory -Path $backup -Force | Out-Null
        foreach ($dll in $existing) { Copy-Item -LiteralPath $dll.FullName -Destination $backup -Force }
        Write-Host "Backup creado: $backup" -ForegroundColor Yellow
    }
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Get-ChildItem -LiteralPath $destination -Filter "Asgard*.dll" -File -ErrorAction SilentlyContinue | Remove-Item -Force

$baseSource = if ($Target -eq "server") { Join-Path $distRoot "ServerBase" } else { Join-Path $distRoot "AdminClient" }
Write-Host "Instalando ASGARD en: $destination" -ForegroundColor Cyan
Copy-DllSet $baseSource $destination

$avatarPath = Join-Path $distRoot "EnhancedShared\AsgardVoidAvatarClient.dll"
if ($Enhanced) {
    if (-not (Test-Path -LiteralPath $avatarPath -PathType Leaf)) {
        throw "No existe AsgardVoidAvatarClient.dll. Instala Jotunn, vuelve a configurar rutas y recompila."
    }
    $jotunn = Get-ChildItem -LiteralPath $pluginsRoot -Filter "Jotunn.dll" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $jotunn) {
        throw "Modo Enhanced requiere Jotunn.dll instalado en este Valheim."
    }
    Copy-Item -LiteralPath $avatarPath -Destination (Join-Path $destination "AsgardVoidAvatarClient.dll") -Force
    Write-Host "  + AsgardVoidAvatarClient.dll" -ForegroundColor Magenta
    Write-Host "Jotunn detectado: $($jotunn.FullName)" -ForegroundColor Green
} else {
    $oldAvatar = Join-Path $destination "AsgardVoidAvatarClient.dll"
    if (Test-Path -LiteralPath $oldAvatar -PathType Leaf) { Remove-Item -LiteralPath $oldAvatar -Force }
}

Write-Host ""
Write-Host "INSTALACION ASGARD COMPLETA" -ForegroundColor Green
Write-Host "Destino: $destination"
Write-Host ("Tipo: " + $(if ($Target -eq "server") { "Servidor" } else { "Cliente administrador" }))
Write-Host ("Avatar Enhanced: " + $(if ($Enhanced) { "SI" } else { "NO" }))
Write-Host "Reinicia Valheim/BepInEx para cargar las DLL 7.0.6."
